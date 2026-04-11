# M3 自动卖出重写 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 `m3` 重写成“真实 M2 决策态 + M3 订单执行态 + 单轮共享预算收口”的自动卖出编排层，并在 CLI 同时展示决策状态和订单状态。

**Architecture:** `M2StateManager` 继续独占决策生命周期，`M3PositionStateManager` 独占订单执行生命周期，`M3ExecutionService` 只负责串联“持仓/行情 -> 决策回写 -> 提交/跟踪 -> 批次轮询收口 -> 双状态报告”。`--mode m3 --once` 仍然只跑一轮，但这一轮内部必须在 `0.5s` 间隔下用共享 `5s` 预算持续收口，而不是提交后只查一次。

**Tech Stack:** Python 3.10+, pytest, `Decimal`, stdlib `dataclasses/datetime/time/logging/zoneinfo`, 现有 `GMTradeGateway`, `GMCurrentQuoteGateway`, `M2DecisionEngine`, `M2StateManager`

---

## Planned File Structure

**Create:**
- `src/gmtrade_live/services/m3_state_manager.py`
- `tests/unit/test_m3_state_manager.py`
- `tests/integration/test_m3_execution_integration.py`

**Modify:**
- `src/gmtrade_live/models.py`
- `src/gmtrade_live/gateways/gmtrade_trade_gateway.py`
- `src/gmtrade_live/services/m3_execution_service.py`
- `src/gmtrade_live/bootstrap.py`
- `main.py`
- `tests/unit/test_m3_models.py`
- `tests/unit/test_m3_execution_service.py`
- `tests/unit/test_official_gateways.py`
- `tests/unit/test_main.py`
- `tests/unit/test_bootstrap.py`

**Delete:**
- `src/gmtrade_live/state.py`
- `tests/unit/test_state.py`

**Read-only references:**
- `src/gmtrade_live/services/m2_state_manager.py`
- `src/gmtrade_live/services/m2_decision_engine.py`
- `src/gmtrade_live/services/m2_dry_run.py`

## Scope Guard

- 固定自动卖单委托类型为 `price_type="market"`，本轮不扩展配置项。
- `--reconcile-timeout-seconds` 只服务 `m3`，默认值 `5`，不写回配置文件。
- 本轮收口预算按 round 共享，不按 symbol 单独计时。
- 不碰用户正在批注的 `m2_dry_run.py`，也不改 `M2DecisionEngine` / `M2StateManager` 的既有契约。
- `GMTradeGateway` 继续做空字符串归一化，避免把 `broker_order_id=""` 传进执行态。

### Task 1: 重命名并迁移 M3 执行状态管理器

**Files:**
- Create: `src/gmtrade_live/services/m3_state_manager.py`
- Create: `tests/unit/test_m3_state_manager.py`
- Delete: `src/gmtrade_live/state.py`
- Delete: `tests/unit/test_state.py`
- Modify: `src/gmtrade_live/bootstrap.py`
- Modify: `src/gmtrade_live/services/m3_execution_service.py`
- Modify: `tests/unit/test_m3_execution_service.py`

- [ ] **Step 1: 先写新的状态管理器失败测试**

```python
# tests/unit/test_m3_state_manager.py
from gmtrade_live.services.m3_state_manager import (
    M3ExecutionState,
    M3PositionStateManager,
)


def test_m3_state_manager_returns_idle_snapshot_for_new_symbol() -> None:
    manager = M3PositionStateManager(logger=None)

    snapshot = manager.get_state("SHSE.600036")

    assert snapshot.symbol == "SHSE.600036"
    assert snapshot.state is M3ExecutionState.idle
    assert snapshot.cl_ord_id is None


def test_m3_state_manager_treats_submitting_submitted_and_partial_as_open() -> None:
    manager = M3PositionStateManager(logger=None)

    manager.update_state(
        "SHSE.600036",
        M3ExecutionState.submitting,
        requested_volume=200,
        remaining_volume=200,
    )
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", M3ExecutionState.partially_filled)
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", M3ExecutionState.filled)
    assert manager.has_open_order("SHSE.600036") is False
```

- [ ] **Step 2: 运行新状态测试，确认因为文件还不存在而失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_m3_state_manager.py -q`

Expected: `ImportError: No module named 'gmtrade_live.services.m3_state_manager'`

- [ ] **Step 3: 实现新的 M3 状态文件，并把旧名字移除**

```python
# src/gmtrade_live/services/m3_state_manager.py
class M3ExecutionState(str, Enum):
    idle = "idle"
    submitting = "submitting"
    submitted = "submitted"
    partially_filled = "partially_filled"
    filled = "filled"
    cancelled = "cancelled"
    failed = "failed"


@dataclass(slots=True)
class M3ExecutionStateSnapshot:
    symbol: str
    state: M3ExecutionState
    cl_ord_id: str | None = None
    broker_order_id: str | None = None
    requested_volume: int = 0
    filled_volume: int = 0
    remaining_volume: int = 0
    submit_accepted: bool | None = None
    last_order_status: str | None = None
    rejection_reason: str | None = None
    avg_price: Decimal | None = None
    event_time: datetime | None = None
    last_update_time: datetime | None = None
    message: str = ""


class M3PositionStateManager:
    def __init__(self, logger: Logger | None) -> None:
        self._logger = logger
        self._cache: dict[str, M3ExecutionStateSnapshot] = {}

    def get_state(self, symbol: str) -> M3ExecutionStateSnapshot:
        if symbol not in self._cache:
            return M3ExecutionStateSnapshot(symbol=symbol, state=M3ExecutionState.idle)
        return self._cache[symbol]

    def active_states(self) -> tuple[M3ExecutionStateSnapshot, ...]:
        return tuple(sorted(self._cache.values(), key=lambda item: item.symbol))

    def has_open_order(self, symbol: str) -> bool:
        return self.get_state(symbol).state in {
            M3ExecutionState.submitting,
            M3ExecutionState.submitted,
            M3ExecutionState.partially_filled,
        }
```

```python
# 把旧导入全部改成新文件
from gmtrade_live.services.m3_state_manager import (
    M3ExecutionState,
    M3ExecutionStateSnapshot,
    M3PositionStateManager,
)
```

- [ ] **Step 4: 删除旧文件并修正引用**

Run: `git rm src/gmtrade_live/state.py tests/unit/test_state.py`

Expected: `git status` 里只出现新 `m3_state_manager.py` 和受影响导入文件。

- [ ] **Step 5: 跑状态层和 import 相关测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_m3_state_manager.py tests/unit/test_m3_execution_service.py -q`

Expected: 状态测试通过，`test_m3_execution_service.py` 里会继续因为服务还没改完而部分失败。

- [ ] **Step 6: 提交状态管理器重命名**

```bash
git add src/gmtrade_live/services/m3_state_manager.py src/gmtrade_live/bootstrap.py src/gmtrade_live/services/m3_execution_service.py tests/unit/test_m3_state_manager.py tests/unit/test_m3_execution_service.py
git rm src/gmtrade_live/state.py tests/unit/test_state.py
git commit -m "refactor(m3): rename execution state manager"
```

### Task 2: 扩展 M3 报告模型为双状态投影

**Files:**
- Modify: `src/gmtrade_live/models.py`
- Modify: `tests/unit/test_m3_models.py`

- [ ] **Step 1: 先把双状态字段写成失败测试**

```python
# tests/unit/test_m3_models.py
def test_m3_block_detail_exposes_decision_and_execution_fields() -> None:
    detail = M3BlockDetail(
        symbol="SHSE.600036",
        decision_lifecycle_state="watching",
        decision_should_sell=True,
        decision_can_submit_sell=True,
        decision_trigger_reason="take_profit_triggered",
        decision_block_reason=None,
        execution_state="failed",
        execution_cl_ord_id="CL_OLD",
        execution_broker_order_id="BK_OLD",
        execution_last_order_status="rejected",
        requested_ratio=Decimal("0.80"),
        total_volume=250,
        available_volume=0,
        raw_target_volume=200,
        promotion_type=None,
        normalized_target_volume=200,
        block_reason="sell_quantity_exceeds_available",
        evaluated_at=_now(),
    )

    assert detail.decision_lifecycle_state == "watching"
    assert detail.execution_state == "failed"


def test_m3_execution_detail_exposes_decision_projection() -> None:
    detail = M3ExecutionDetail(
        symbol="SHSE.600036",
        change_tags=("submit_accepted",),
        decision_lifecycle_state="watching",
        decision_should_sell=True,
        decision_can_submit_sell=True,
        decision_trigger_reason="take_profit_triggered",
        decision_block_reason=None,
        execution_state="submitted",
        cl_ord_id="CL_1",
        broker_order_id="BK_1",
        requested_volume=200,
        filled_volume=0,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="pending_new",
        rejection_reason=None,
        avg_price=None,
        event_time=_now(),
        message="accepted",
    )

    assert detail.decision_trigger_reason == "take_profit_triggered"
    assert detail.execution_state == "submitted"
```

- [ ] **Step 2: 运行模型测试，确认 dataclass 契约还没更新**

Run: `conda run -n stock_analysis pytest tests/unit/test_m3_models.py -q`

Expected: `TypeError`，提示 `M3BlockDetail` / `M3ExecutionDetail` 不接受新的双状态字段。

- [ ] **Step 3: 修改 `models.py`，把双状态字段加入稳定输出契约**

```python
# src/gmtrade_live/models.py
@dataclass(frozen=True, slots=True)
class M3BlockDetail:
    symbol: str
    decision_lifecycle_state: str | None
    decision_should_sell: bool
    decision_can_submit_sell: bool
    decision_trigger_reason: str | None
    decision_block_reason: str | None
    execution_state: str | None
    execution_cl_ord_id: str | None
    execution_broker_order_id: str | None
    execution_last_order_status: str | None
    requested_ratio: Decimal
    total_volume: int
    available_volume: int
    raw_target_volume: int
    promotion_type: str | None
    normalized_target_volume: int
    block_reason: str
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class M3ExecutionDetail:
    symbol: str
    change_tags: tuple[str, ...]
    decision_lifecycle_state: str | None
    decision_should_sell: bool
    decision_can_submit_sell: bool
    decision_trigger_reason: str | None
    decision_block_reason: str | None
    execution_state: str
    cl_ord_id: str | None
    broker_order_id: str | None
    requested_volume: int
    filled_volume: int
    remaining_volume: int
    submit_accepted: bool | None
    last_order_status: str | None
    rejection_reason: str | None
    avg_price: Decimal | None
    event_time: datetime
    message: str
```

- [ ] **Step 4: 运行模型测试，确认报告契约稳定**

Run: `conda run -n stock_analysis pytest tests/unit/test_m3_models.py -q`

Expected: `2 passed`

- [ ] **Step 5: 提交双状态模型**

```bash
git add src/gmtrade_live/models.py tests/unit/test_m3_models.py
git commit -m "feat(m3): add dual-state report fields"
```

### Task 3: 重写 `M3ExecutionService` 为双 manager 编排 + 本轮共享收口

**Files:**
- Modify: `src/gmtrade_live/services/m3_execution_service.py`
- Modify: `src/gmtrade_live/gateways/gmtrade_trade_gateway.py`
- Modify: `tests/unit/test_m3_execution_service.py`
- Modify: `tests/unit/test_official_gateways.py`

- [ ] **Step 1: 先写服务层失败测试**

```python
# tests/unit/test_m3_execution_service.py
def test_run_round_uses_real_m2_state_and_writes_decision_feedback() -> None:
    decision_manager = M2StateManager(logging.getLogger("test"))
    service = M3ExecutionService(
        trade_gateway=FakeTradeGateway(),
        market_gateway=FakeMarketGateway(),
        decision_state_manager=decision_manager,
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(
        config=_config(),
        round_no=1,
        reconcile_timeout_seconds=5,
    )

    state = decision_manager.get_state("SHSE.600036")
    assert state is not None
    assert state.last_trigger_reason == "take_profit_triggered"
    assert report.execution_details[0].decision_lifecycle_state == "watching"


def test_run_round_reconciles_new_submit_until_filled_within_shared_budget() -> None:
    trade_gateway = SequencedTradeGateway(
        order_statuses=[
            ("pending_new", 0, 0, None),
            ("partially_filled", 100, 100, "BK_1"),
            ("filled", 200, 0, "BK_1"),
        ],
        execution_reports=[(), (_execution(100),), (_execution(200),)],
    )
    sleep_calls: list[float] = []
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        decision_state_manager=M2StateManager(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.6, 1.1]),
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    report = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=5)

    assert sleep_calls == [0.5, 0.5]
    assert report.execution_details[-1].execution_state == "filled"
    assert report.execution_details[-1].filled_volume == 200


def test_run_round_preserves_submit_broker_order_id_and_remaining_volume_on_bad_snapshot() -> None:
    report = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=5)

    assert report.execution_details[0].broker_order_id == "BK_1"
    assert report.execution_details[0].remaining_volume == 200
```

- [ ] **Step 2: 运行服务测试，确认构造函数和收口逻辑都还不匹配**

Run: `conda run -n stock_analysis pytest tests/unit/test_m3_execution_service.py tests/unit/test_official_gateways.py -q`

Expected: 失败点至少包括构造函数参数不匹配、`run_round()` 缺少 `reconcile_timeout_seconds`、以及双状态字段未填充。

- [ ] **Step 3: 重写 `M3ExecutionService` 的依赖、分流和批次轮询**

```python
# src/gmtrade_live/services/m3_execution_service.py
_RECONCILE_INTERVAL_SECONDS = 0.5


class M3ExecutionService:
    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        market_gateway: MarketGateway,
        decision_state_manager: M2StateManager,
        execution_state_manager: M3PositionStateManager,
        decision_engine,
        logger: logging.Logger,
        clock=None,
        timer=None,
        sleep=None,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._decision_state_manager = decision_state_manager
        self._execution_state_manager = execution_state_manager
        self._decision_engine = decision_engine
        self._logger = logger
        self._clock = clock or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self._timer = timer or perf_counter
        self._sleep = sleep or time.sleep

    def run_round(
        self,
        *,
        config: AppConfig,
        round_no: int,
        reconcile_timeout_seconds: int,
    ) -> M3RoundReport:
        started_at = self._timer()
        now = self._clock()
        session_state = resolve_trading_session(
            now,
            timezone_name=config.timezone,
            market_session_mode=config.market_session_mode,
        )
        positions = tuple(
            position
            for position in self._trade_gateway.get_positions(config.account_id)
            if position.volume > 0
        )
        self._decision_state_manager.sync_positions(positions=positions, now=now)
        quote_map = self._load_quote_map(symbols=[position.symbol for position in positions])

        block_details: list[M3BlockDetail] = []
        tracking_symbols: set[str] = set()
        changed_symbols: set[str] = set()
        submitted_count = 0
        candidate_count = 0

        for position in positions:
            decision_state = self._decision_state_manager.get_state(position.symbol)
            assert decision_state is not None
            decision = self._decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=decision_state,
                config=config,
                now=now,
            )
            decision_state = self._decision_state_manager.update_decision_feedback(
                position.symbol,
                trigger_reason=decision.trigger_reason,
                block_reason=decision.block_reason,
                volume=decision.volume,
                available_volume=decision.available_volume,
                sellable_now=decision.sellable_now,
                decision_time=decision.evaluated_at,
            )
            if not decision.can_submit_sell:
                continue

            candidate_count += 1
            if self._execution_state_manager.has_open_order(position.symbol):
                tracking_symbols.add(position.symbol)
                continue
```

```python
def _reconcile_open_orders(
    self,
    *,
    request_map: dict[str, PositionSnapshot],
    deadline: float,
) -> list[M3ExecutionDetail]:
    details: list[M3ExecutionDetail] = []

    while request_map and self._timer() < deadline:
        round_changed: list[M3ExecutionDetail] = []
        next_request_map: dict[str, PositionSnapshot] = {}
        for symbol, position in request_map.items():
            changed = self._reconcile_trade_state(position=position)
            if changed is not None:
                round_changed.append(changed)
            if self._execution_state_manager.has_open_order(symbol):
                next_request_map[symbol] = position

        details.extend(round_changed)
        if not next_request_map:
            return details

        remaining = max(deadline - self._timer(), 0.0)
        self._sleep(min(_RECONCILE_INTERVAL_SECONDS, remaining))
        request_map = next_request_map

    return details
```

```python
def _build_query_events(
    self,
    *,
    cl_ord_id: str,
    symbol: str,
    last_order_status: str | None,
) -> tuple[_OrderStatusQueryEvent | _ExecutionReportsQueryEvent, ...]:
    events: list[_OrderStatusQueryEvent | _ExecutionReportsQueryEvent] = []
    order_snapshot = self._trade_gateway.query_order_status(cl_ord_id, symbol)
    current_status = last_order_status
    if order_snapshot is not None:
        current_status = order_snapshot.status
        events.append(self._to_order_status_event(order_snapshot))
    if current_status in {"filled", "partially_filled"}:
        execution_snapshots = self._trade_gateway.query_execution_reports(cl_ord_id)
        if execution_snapshots:
            events.append(self._to_execution_reports_event(execution_snapshots))
    return tuple(events)
```

- [ ] **Step 4: 保留 `broker_order_id` 归一化和坏快照保护**

```python
# src/gmtrade_live/gateways/gmtrade_trade_gateway.py
return OrderSubmitResult(
    accepted=_is_submit_accepted(order_id=cl_ord_id, raw_status=raw_status),
    cl_ord_id=str(cl_ord_id) if cl_ord_id is not None else None,
    broker_order_id=_as_optional_str(broker_order_id),
    symbol=str(_read_optional(row, "symbol", default=request.symbol)),
    message=message,
    raw_status=raw_status,
    event_time=event_time,
)


def _as_optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
```

```python
# src/gmtrade_live/services/m3_execution_service.py
def _resolve_remaining_volume(
    *,
    snapshot: M3ExecutionStateSnapshot,
    event: _OrderStatusQueryEvent,
) -> int:
    if event.remaining_volume > 0:
        return event.remaining_volume
    if event.status in {"filled", "cancelled", "expired", "done_for_day", "stopped", "rejected"}:
        return 0
    if snapshot.remaining_volume > 0 and event.filled_volume <= snapshot.filled_volume:
        return snapshot.remaining_volume
    if snapshot.requested_volume > event.filled_volume:
        return snapshot.requested_volume - event.filled_volume
    return 0
```

- [ ] **Step 5: 运行服务和 gateway 目标测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_m3_execution_service.py tests/unit/test_official_gateways.py -q`

Expected: 目标测试全部通过，且覆盖“真实决策态回写”“共享预算轮询”“空 broker id 归一化”“pending_new 零 remaining 防误写”。

- [ ] **Step 6: 提交 M3 服务重写**

```bash
git add src/gmtrade_live/services/m3_execution_service.py src/gmtrade_live/gateways/gmtrade_trade_gateway.py tests/unit/test_m3_execution_service.py tests/unit/test_official_gateways.py
git commit -m "feat(m3): rewrite service with dual states"
```

### Task 4: 接入 CLI / bootstrap 的 `m3` 收口参数和双状态输出

**Files:**
- Modify: `main.py`
- Modify: `src/gmtrade_live/bootstrap.py`
- Modify: `tests/unit/test_main.py`
- Modify: `tests/unit/test_bootstrap.py`

- [ ] **Step 1: 先写入口失败测试**

```python
# tests/unit/test_main.py
def test_parse_cli_args_accepts_m3_reconcile_timeout_seconds() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m3",
            "--once",
            "--reconcile-timeout-seconds",
            "7",
        ]
    )

    assert args.mode == "m3"
    assert args.reconcile_timeout_seconds == 7


def test_main_dispatches_reconcile_timeout_to_m3(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_m3_execution(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    bootstrap = SimpleNamespace(
        run_m0_connectivity_check=lambda config_path: 1,
        run_m1_manual_trade=lambda **kwargs: 1,
        run_m2_dry_run=lambda **kwargs: 1,
        run_m3_execution=_run_m3_execution,
    )

    monkeypatch.setitem(sys.modules, "gmtrade_live.bootstrap", bootstrap)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m3",
            "--once",
            "--reconcile-timeout-seconds",
            "7",
        ],
    )

    assert main.main() == 0
    assert captured["reconcile_timeout_seconds"] == 7
```

```python
# tests/unit/test_bootstrap.py
def test_run_m3_execution_prints_dual_state_detail_fields(monkeypatch, capsys) -> None:
    report = SimpleNamespace(
        summary=SimpleNamespace(
            round_no=1,
            session_state="trading",
            position_count=1,
            candidate_count=1,
            blocked_count=0,
            submitted_count=1,
            open_order_count=1,
            changed_symbol_count=1,
            duration_ms=12,
        ),
        block_details=(),
        execution_details=(
            SimpleNamespace(
                symbol="SHSE.600036",
                change_tags=("submit_accepted",),
                decision_lifecycle_state="watching",
                decision_should_sell=True,
                decision_can_submit_sell=True,
                decision_trigger_reason="take_profit_triggered",
                decision_block_reason=None,
                execution_state="submitted",
                cl_ord_id="CL_1",
                broker_order_id="BK_1",
                requested_volume=200,
                filled_volume=0,
                remaining_volume=200,
                submit_accepted=True,
                last_order_status="pending_new",
                rejection_reason=None,
                avg_price=None,
                event_time=datetime(2026, 4, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                message="accepted",
            ),
        ),
    )

    # 断言 bootstrap 会把 decision_* 字段也打到 JSON 中
```

- [ ] **Step 2: 运行入口测试，确认 parser 和 bootstrap 还没带上新字段**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py -q`

Expected: 至少出现 `AttributeError: 'Namespace' object has no attribute 'reconcile_timeout_seconds'`，以及 `m3_execution_detail` 缺少 `decision_*` 字段。

- [ ] **Step 3: 修改 `main.py` 与 `bootstrap.py`**

```python
# main.py
if mode == "m3":
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true")
    group.add_argument("--max-rounds", type=_parse_positive_int)
    parser.add_argument(
        "--reconcile-timeout-seconds",
        type=_parse_positive_int,
        default=5,
    )
    return parser
```

```python
# src/gmtrade_live/bootstrap.py
service = M3ExecutionService(
    trade_gateway=trade_gateway,
    market_gateway=market_gateway,
    decision_state_manager=M2StateManager(logger),
    execution_state_manager=M3PositionStateManager(logger),
    decision_engine=M2DecisionEngine(),
    logger=logger,
)

report = service.run_round(
    config=config,
    round_no=round_no,
    reconcile_timeout_seconds=reconcile_timeout_seconds,
)
```

```python
print(
    json.dumps(
        {
            "kind": "m3_execution_detail",
            "symbol": detail.symbol,
            "change_tags": list(detail.change_tags),
            "decision_lifecycle_state": detail.decision_lifecycle_state,
            "decision_should_sell": detail.decision_should_sell,
            "decision_can_submit_sell": detail.decision_can_submit_sell,
            "decision_trigger_reason": detail.decision_trigger_reason,
            "decision_block_reason": detail.decision_block_reason,
            "execution_state": detail.execution_state,
            "cl_ord_id": detail.cl_ord_id,
            "broker_order_id": detail.broker_order_id,
            "requested_volume": detail.requested_volume,
            "filled_volume": detail.filled_volume,
            "remaining_volume": detail.remaining_volume,
            "submit_accepted": detail.submit_accepted,
            "last_order_status": detail.last_order_status,
            "rejection_reason": detail.rejection_reason,
            "avg_price": str(detail.avg_price) if detail.avg_price is not None else None,
            "event_time": detail.event_time.isoformat(),
            "message": detail.message,
        },
        ensure_ascii=False,
    )
)
```

- [ ] **Step 4: 运行入口测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py -q`

Expected: 入口测试通过，且 `--mode m3 --once --reconcile-timeout-seconds 7` 能完整透传到 service。

- [ ] **Step 5: 提交 CLI / bootstrap 接口改动**

```bash
git add main.py src/gmtrade_live/bootstrap.py tests/unit/test_main.py tests/unit/test_bootstrap.py
git commit -m "feat(m3): expose reconcile timeout and dual-state cli output"
```

### Task 5: 补集成测试并做回归验证

**Files:**
- Create: `tests/integration/test_m3_execution_integration.py`
- Modify: `src/gmtrade_live/services/m3_execution_service.py`

- [ ] **Step 1: 先写 M3 集成失败测试**

```python
# tests/integration/test_m3_execution_integration.py
def test_m3_once_round_keeps_polling_until_budget_exhausted_or_order_finishes() -> None:
    trade_gateway = SequencedTradeGateway(
        positions=(
            _position("SZSE.002594", volume=200, available_volume=200),
        ),
        order_statuses=[
            ("pending_new", 0, 0, "BK_1"),
            ("partially_filled", 100, 100, "BK_1"),
            ("filled", 200, 0, "BK_1"),
        ],
        execution_reports=[(), (_execution(100),), (_execution(200),)],
    )
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        decision_state_manager=M2StateManager(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.6, 1.1]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=5)

    assert report.summary.submitted_count == 1
    assert report.execution_details[-1].execution_state == "filled"
    assert report.execution_details[-1].decision_trigger_reason == "take_profit_triggered"


def test_open_order_continues_in_next_round_after_timeout() -> None:
    decision_manager = M2StateManager(logging.getLogger("test"))
    execution_manager = M3PositionStateManager(logger=None)
    trade_gateway = SequencedTradeGateway(
        order_statuses=[
            ("pending_new", 0, 0, "BK_1"),
            ("filled", 200, 0, "BK_1"),
        ],
        execution_reports=[
            (),
            (_execution(200),),
        ],
    )
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        decision_state_manager=decision_manager,
        execution_state_manager=execution_manager,
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 1.2, 2.0, 2.1]),
        sleep=lambda seconds: None,
    )

    first_round = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=1)
    second_round = service.run_round(config=_config(), round_no=2, reconcile_timeout_seconds=5)

    assert first_round.summary.open_order_count == 1
    assert second_round.summary.submitted_count == 0
    assert second_round.execution_details[-1].execution_state == "filled"
    assert trade_gateway.submit_calls == 1
```

- [ ] **Step 2: 运行集成测试，确认跨轮跟踪或 round 内收口还有缺口时会失败**

Run: `conda run -n stock_analysis pytest tests/integration/test_m3_execution_integration.py -q`

Expected: 若 round 内轮询或下一轮续跟踪没完全打通，这里应先失败，再补实现。

- [ ] **Step 3: 补齐最后缺口并做针对性回归**

Run: `conda run -n stock_analysis pytest tests/unit/test_m3_state_manager.py tests/unit/test_m3_models.py tests/unit/test_m3_execution_service.py tests/unit/test_official_gateways.py tests/unit/test_main.py tests/unit/test_bootstrap.py tests/integration/test_m3_execution_integration.py -q`

Expected: 所有 M3 相关测试通过。

- [ ] **Step 4: 运行全量回归**

Run: `conda run -n stock_analysis pytest tests/unit tests/integration -q`

Expected: 全量单测和集成测试通过，没有回退 M0/M1/M2。

- [ ] **Step 5: 提交集成覆盖**

```bash
git add tests/integration/test_m3_execution_integration.py src/gmtrade_live/services/m3_execution_service.py
git commit -m "test(m3): add round reconciliation coverage"
```

## Self-Review Checklist

- [ ] 对照 `docs/superpowers/specs/2026-04-11-m3-auto-sell-rewrite-design.md` 检查：双状态、共享预算、`0.5s` 轮询、`--once` 单轮内收口、CLI 双状态投影、状态管理器改名，都有对应任务。
- [ ] 搜索计划文件，确认没有占位词、半截测试或“后面再补”的伪完成描述。
- [ ] 检查命名一致：`M3ExecutionState`、`M3ExecutionStateSnapshot`、`M3PositionStateManager`、`decision_state_manager`、`execution_state_manager`、`reconcile_timeout_seconds`。
- [ ] 检查计划没有要求改动 `m2_dry_run.py`、`m2_decision_engine.py`、`m2_state_manager.py` 的行为。
- [ ] 检查所有测试命令都使用 `conda run -n stock_analysis pytest tests/...` 这一类完整命令，而不是裸 `pytest`。

## Execution Notes

- 先做 Task 1，再做 Task 2；不要跳过状态命名收敛，否则后续 service 和 CLI 会一直背旧名字。
- Task 3 的关键不是把 `_poll_trade_state()` 机械搬来，而是把“单 symbol 事件构建”改成“round 级批次轮询”。
- `--once` 的语义必须保持为“只跑一轮，但这轮内部允许连续查询”，不能退回提交后只查一次。
- `M3BlockDetail` 和 `M3ExecutionDetail` 都要能看出决策态；`M3ExecutionDetail` 额外保留完整订单执行字段。
- 只有在 Task 5 的 targeted regression 和 full regression 都通过后，才能宣告 M3 重写完成。
