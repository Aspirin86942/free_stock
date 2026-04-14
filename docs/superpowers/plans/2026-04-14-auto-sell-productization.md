# Auto-Sell Productization Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前以 `M0~M4` 为主语义的仓库重构为“正式自动卖出入口 + 正式决策观测入口 + `tools/debug` 调试脚本 + 去阶段化日志/测试/文档/配置”的产品形态。

**Architecture:** 先把共享评估逻辑抽成 `SellCandidatePipeline`，再让 `DecisionObserverService` 与 `AutoSellService` 在同一份候选评估结果之上分叉。运行入口统一由 `gmtrade_live.app_runner` 负责，`main.py` 只启动正式自动卖出，`observe_decisions.py` 启动正式观测入口，`tools/debug` 承载连通性与手工下单脚本；结构化输出、smoke、文档和示例配置统一改成产品语义。

**Tech Stack:** Python 3.10+, pytest, `Decimal`, `dataclasses`, `argparse`, `logging`, `zoneinfo`, 现有 `GMTradeGateway`, `GMCurrentQuoteGateway`, `models.py`, `logging_setup.py`

---

## Planned File Structure

**Create:**
- `src/gmtrade_live/services/sell_candidate_pipeline.py` - 共享评估管线，只做持仓/行情/决策态同步/卖出判定/变化事件汇总。
- `observe_decisions.py` - 正式决策观测入口脚本。
- `tools/debug/check_connectivity.py` - 调试用连通性检查脚本。
- `tools/debug/manual_trade.py` - 调试用手工交易脚本。
- `tests/unit/test_sell_candidate_pipeline.py` - 共享评估管线测试。
- `tests/unit/test_observe_decisions.py` - 决策观测脚本入口测试。
- `tests/debug/test_check_connectivity.py` - 调试连通性脚本测试。
- `tests/debug/test_manual_trade.py` - 调试手工交易脚本测试。
- `tests/unit/test_stage_name_guard.py` - 主干活跃代码面 stage name 守卫测试。
- `docs/auto-sell-runtime.md` - 面向成品的主运行说明文档。

**Modify / Rename:**
- `src/gmtrade_live/bootstrap.py` -> `src/gmtrade_live/app_runner.py`
- `src/gmtrade_live/services/m2_decision_engine.py` -> `src/gmtrade_live/services/sell_decision_engine.py`
- `src/gmtrade_live/services/m2_state_manager.py` -> `src/gmtrade_live/services/position_decision_state.py`
- `src/gmtrade_live/services/m2_dry_run.py` -> `src/gmtrade_live/services/decision_observer.py`
- `src/gmtrade_live/services/m3_quantity_rules.py` -> `src/gmtrade_live/services/sell_quantity_policy.py`
- `src/gmtrade_live/services/m3_state_manager.py` -> `src/gmtrade_live/services/order_execution_state.py`
- `src/gmtrade_live/services/m3_execution_service.py` -> `src/gmtrade_live/services/auto_sell_service.py`
- `src/gmtrade_live/models.py` - 新增 `SellCandidate` / `CandidateRound`，并把 `M2*` / `M3*` 输出 dataclass 改成产品语义。
- `main.py` - 改成只承载正式自动卖出入口，不再暴露 `--mode`。
- `AGENTS.md` - 改运行命令、入口说明和 smoke 口径。
- `config/sim_account.example.yaml` - 改示例 `strategy_name` 和命令语义。
- `tests/unit/test_m2_decision_engine.py` -> `tests/unit/test_sell_decision_engine.py`
- `tests/unit/test_m2_state_manager.py` -> `tests/unit/test_position_decision_state.py`
- `tests/unit/test_m2_models.py` -> `tests/unit/test_decision_models.py`
- `tests/unit/test_m2_dry_run.py` -> `tests/unit/test_decision_observer.py`
- `tests/integration/test_m2_dry_run_integration.py` -> `tests/integration/test_decision_observer_integration.py`
- `tests/unit/test_m3_quantity_rules.py` -> `tests/unit/test_sell_quantity_policy.py`
- `tests/unit/test_m3_state_manager.py` -> `tests/unit/test_order_execution_state.py`
- `tests/unit/test_m3_models.py` -> `tests/unit/test_auto_sell_models.py`
- `tests/unit/test_m3_execution_service.py` -> `tests/unit/test_auto_sell_service.py`
- `tests/integration/test_m3_execution_integration.py` -> `tests/integration/test_auto_sell_integration.py`
- `tests/unit/test_bootstrap.py` -> `tests/unit/test_app_runner.py`
- `tests/smoke/test_m4_local_smoke.py` -> `tests/smoke/test_auto_sell_smoke.py`
- `tests/unit/test_main.py` - 改成自动卖出入口参数测试。
- `tests/unit/test_config.py` - 改示例 `strategy_name` 断言。

**Delete:**
- `src/gmtrade_live/services/m0_connectivity.py`
- `src/gmtrade_live/services/m1_manual_trade.py`
- `src/gmtrade_live/bootstrap.py`
- 所有活跃路径中以 `M0~M4` 表示当前产品能力的残余字符串

**Read-only references:**
- `docs/superpowers/specs/2026-04-14-auto-sell-productization-design.md`
- `scripts/query_smoke_test.py`
- 历史 `docs/superpowers/specs/2026-04-0*.md`
- 历史 `docs/superpowers/plans/2026-04-0*.md`

## Scope Guard

- 不修改策略判定公式，不修改卖量归一化行为，不修改“自动卖出单轮异常立即退出”的交易语义。
- 不把未来市场扩展能力纳入本次实现；只保留命名和分层上的扩展边界。
- 不修改用户本地 `config/sim_account.yaml`；只更新 `config/sim_account.example.yaml` 和相关测试。
- 历史 spec / plan 文档允许继续保留阶段名；本次只清理活跃运行代码、测试、命令文档和示例配置中的阶段名。
- `scripts/query_smoke_test.py` 本轮不迁移目录，只在文档里重新归类为辅助脚本。

### Task 1: 决策层去阶段化并抽出共享评估管线

**Files:**
- Create: `src/gmtrade_live/services/sell_candidate_pipeline.py`
- Create: `tests/unit/test_sell_candidate_pipeline.py`
- Modify: `src/gmtrade_live/models.py`
- Rename: `src/gmtrade_live/services/m2_decision_engine.py` -> `src/gmtrade_live/services/sell_decision_engine.py`
- Rename: `src/gmtrade_live/services/m2_state_manager.py` -> `src/gmtrade_live/services/position_decision_state.py`
- Rename: `src/gmtrade_live/services/m2_dry_run.py` -> `src/gmtrade_live/services/decision_observer.py`
- Rename: `tests/unit/test_m2_decision_engine.py` -> `tests/unit/test_sell_decision_engine.py`
- Rename: `tests/unit/test_m2_state_manager.py` -> `tests/unit/test_position_decision_state.py`
- Rename: `tests/unit/test_m2_models.py` -> `tests/unit/test_decision_models.py`
- Rename: `tests/unit/test_m2_dry_run.py` -> `tests/unit/test_decision_observer.py`
- Rename: `tests/integration/test_m2_dry_run_integration.py` -> `tests/integration/test_decision_observer_integration.py`

- [ ] **Step 1: 先把决策层测试名和共享评估测试改成最终形态**

```bash
git mv tests/unit/test_m2_decision_engine.py tests/unit/test_sell_decision_engine.py
git mv tests/unit/test_m2_state_manager.py tests/unit/test_position_decision_state.py
git mv tests/unit/test_m2_models.py tests/unit/test_decision_models.py
git mv tests/unit/test_m2_dry_run.py tests/unit/test_decision_observer.py
git mv tests/integration/test_m2_dry_run_integration.py tests/integration/test_decision_observer_integration.py
```

```python
# tests/unit/test_sell_candidate_pipeline.py
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import CandidateRound, PositionSnapshot, QuoteSnapshot
from gmtrade_live.services.position_decision_state import PositionDecisionStateStore
from gmtrade_live.services.sell_candidate_pipeline import SellCandidatePipeline
from gmtrade_live.services.sell_decision_engine import SellDecisionEngine


def _now() -> datetime:
    return datetime(2026, 4, 14, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-auto-sell",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal("1.0"),
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


class FakeTradeGateway:
    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SHSE.600036",
                exchange="SHSE",
                volume=200,
                available_volume=200,
                cost_price=Decimal("10.00"),
                last_update_time=_now(),
            )
        ]


class FakeMarketGateway:
    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        return [
            QuoteSnapshot(
                symbol="SHSE.600036",
                last_price=Decimal("10.80"),
                quote_time=_now(),
                source="fake",
            )
        ]


def test_sell_candidate_pipeline_returns_candidate_round() -> None:
    pipeline = SellCandidatePipeline(
        trade_gateway=FakeTradeGateway(),
        market_gateway=FakeMarketGateway(),
        decision_state_store=PositionDecisionStateStore(logging.getLogger("test")),
        decision_engine=SellDecisionEngine(),
    )

    result = pipeline.evaluate_round(config=_config(), now=_now())

    assert isinstance(result, CandidateRound)
    assert result.session_state.value == "trading"
    assert result.candidates[0].decision.should_sell is True
    assert result.candidates[0].decision_state.symbol == "SHSE.600036"
```

```python
# tests/unit/test_decision_observer.py
from gmtrade_live.services.decision_observer import DecisionObserverService
from gmtrade_live.services.position_decision_state import PositionDecisionStateStore
from gmtrade_live.services.sell_candidate_pipeline import SellCandidatePipeline
from gmtrade_live.services.sell_decision_engine import SellDecisionEngine
```

- [ ] **Step 2: 运行决策层新测试，确认因为新模块还不存在而失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_sell_candidate_pipeline.py tests/unit/test_decision_observer.py -q`

Expected: `ModuleNotFoundError`，至少提示 `gmtrade_live.services.sell_candidate_pipeline`、`sell_decision_engine`、`position_decision_state` 或 `decision_observer` 不存在。

- [ ] **Step 3: 重命名决策层源码并实现共享评估管线**

```bash
git mv src/gmtrade_live/services/m2_decision_engine.py src/gmtrade_live/services/sell_decision_engine.py
git mv src/gmtrade_live/services/m2_state_manager.py src/gmtrade_live/services/position_decision_state.py
git mv src/gmtrade_live/services/m2_dry_run.py src/gmtrade_live/services/decision_observer.py
```

```python
# src/gmtrade_live/models.py
@dataclass(frozen=True, slots=True)
class DecisionRoundSummary:
    round_no: int
    session_state: str
    position_count: int
    watching_count: int
    tombstone_count: int
    should_sell_count: int
    can_submit_sell_count: int
    changed_symbol_count: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class DecisionChangeEvent:
    symbol: str
    change_tags: tuple[str, ...]
    decision: DecisionResult | None
    state_snapshot: DecisionPositionStateSnapshot | None


@dataclass(frozen=True, slots=True)
class SellCandidate:
    position: PositionSnapshot
    quote: QuoteSnapshot | None
    decision: DecisionResult
    decision_state: DecisionPositionStateSnapshot


@dataclass(frozen=True, slots=True)
class CandidateRound:
    session_state: object
    positions: tuple[PositionSnapshot, ...]
    candidates: tuple[SellCandidate, ...]
    change_events: tuple[DecisionChangeEvent, ...]


@dataclass(frozen=True, slots=True)
class DecisionObservationReport:
    summary: DecisionRoundSummary
    evaluated_symbols: tuple[SellCandidate, ...]
    tombstones: tuple[DecisionPositionStateSnapshot, ...]
    change_events: tuple[DecisionChangeEvent, ...]
```

```python
# src/gmtrade_live/services/sell_candidate_pipeline.py
from __future__ import annotations

from gmtrade_live.models import CandidateRound, DecisionChangeEvent, SellCandidate
from gmtrade_live.session import resolve_trading_session


class SellCandidatePipeline:
    def __init__(
        self,
        *,
        trade_gateway,
        market_gateway,
        decision_state_store,
        decision_engine,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._decision_state_store = decision_state_store
        self._decision_engine = decision_engine
        self._last_decisions: dict[str, object] = {}

    def evaluate_round(self, *, config, now) -> CandidateRound:
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
        self._decision_state_store.sync_positions(positions=positions, now=now)
        symbols = [position.symbol for position in positions]
        quotes = tuple(self._market_gateway.get_quotes(symbols)) if symbols else ()
        quote_map = {quote.symbol: quote for quote in quotes}

        candidates: list[SellCandidate] = []
        change_events: list[DecisionChangeEvent] = []
        for position in positions:
            state = self._decision_state_store.get_state(position.symbol)
            if state is None:
                continue
            decision = self._decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=state,
                config=config,
                now=now,
            )
            updated_state = self._decision_state_store.update_decision_feedback(
                position.symbol,
                trigger_reason=decision.trigger_reason,
                block_reason=decision.block_reason,
                volume=decision.volume,
                available_volume=decision.available_volume,
                sellable_now=decision.sellable_now,
                decision_time=decision.evaluated_at,
            )
            candidates.append(
                SellCandidate(
                    position=position,
                    quote=quote_map.get(position.symbol),
                    decision=decision,
                    decision_state=updated_state,
                )
            )
            previous = self._last_decisions.get(position.symbol)
            if previous is None or previous != decision:
                change_events.append(
                    DecisionChangeEvent(
                        symbol=position.symbol,
                        change_tags=("decision_updated",),
                        decision=decision,
                        state_snapshot=updated_state,
                    )
                )
            self._last_decisions[position.symbol] = decision

        return CandidateRound(
            session_state=session_state,
            positions=positions,
            candidates=tuple(candidates),
            change_events=tuple(change_events),
        )
```

```python
# src/gmtrade_live/services/decision_observer.py
class DecisionObserverService:
    def __init__(self, *, candidate_pipeline, logger, clock=None, timer=None) -> None:
        self._candidate_pipeline = candidate_pipeline
        self._logger = logger
        self._clock = clock
        self._timer = timer

    def run_round(self, *, config, round_no: int):
        started_at = self._timer()
        now = self._clock()
        candidate_round = self._candidate_pipeline.evaluate_round(config=config, now=now)
        return DecisionObservationReport(
            summary=DecisionRoundSummary(
                round_no=round_no,
                session_state=candidate_round.session_state.value,
                position_count=len(candidate_round.positions),
                watching_count=len(candidate_round.candidates),
                tombstone_count=len(
                    [
                        item
                        for item in self._candidate_pipeline._decision_state_store.active_states()
                        if item.lifecycle_state.value == "tombstone"
                    ]
                ),
                should_sell_count=sum(1 for item in candidate_round.candidates if item.decision.should_sell),
                can_submit_sell_count=sum(1 for item in candidate_round.candidates if item.decision.can_submit_sell),
                changed_symbol_count=len({event.symbol for event in candidate_round.change_events}),
                duration_ms=int((self._timer() - started_at) * 1000),
            ),
            evaluated_symbols=candidate_round.candidates,
            tombstones=tuple(
                item
                for item in self._candidate_pipeline._decision_state_store.active_states()
                if item.lifecycle_state.value == "tombstone"
            ),
            change_events=candidate_round.change_events,
        )
```

```python
# src/gmtrade_live/services/sell_decision_engine.py
class SellDecisionEngine:
    """保留原 `M2DecisionEngine` 的 `evaluate()` 方法体，只把类名改成产品语义。"""
```

```python
# src/gmtrade_live/services/position_decision_state.py
class PositionDecisionStateStore:
    """保留原 `M2StateManager` 的状态缓存、同步和反馈更新实现，只做类名替换。"""
```

- [ ] **Step 4: 运行决策层定向测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_sell_candidate_pipeline.py tests/unit/test_sell_decision_engine.py tests/unit/test_position_decision_state.py tests/unit/test_decision_models.py tests/unit/test_decision_observer.py -q`

Expected: 以上测试通过；若 `tests/integration/test_decision_observer_integration.py` 仍引用旧名字，先一并修正导入再继续。

- [ ] **Step 5: 提交决策层重命名与共享评估管线**

```bash
git add src/gmtrade_live/models.py src/gmtrade_live/services/sell_candidate_pipeline.py src/gmtrade_live/services/sell_decision_engine.py src/gmtrade_live/services/position_decision_state.py src/gmtrade_live/services/decision_observer.py tests/unit/test_sell_candidate_pipeline.py tests/unit/test_sell_decision_engine.py tests/unit/test_position_decision_state.py tests/unit/test_decision_models.py tests/unit/test_decision_observer.py tests/integration/test_decision_observer_integration.py
git commit -m "refactor(decision): rename decision services and add candidate pipeline"
```

### Task 2: 执行层去阶段化并让自动卖出服务消费共享候选结果

**Files:**
- Modify: `src/gmtrade_live/models.py`
- Rename: `src/gmtrade_live/services/m3_quantity_rules.py` -> `src/gmtrade_live/services/sell_quantity_policy.py`
- Rename: `src/gmtrade_live/services/m3_state_manager.py` -> `src/gmtrade_live/services/order_execution_state.py`
- Rename: `src/gmtrade_live/services/m3_execution_service.py` -> `src/gmtrade_live/services/auto_sell_service.py`
- Rename: `tests/unit/test_m3_quantity_rules.py` -> `tests/unit/test_sell_quantity_policy.py`
- Rename: `tests/unit/test_m3_state_manager.py` -> `tests/unit/test_order_execution_state.py`
- Rename: `tests/unit/test_m3_models.py` -> `tests/unit/test_auto_sell_models.py`
- Rename: `tests/unit/test_m3_execution_service.py` -> `tests/unit/test_auto_sell_service.py`
- Rename: `tests/integration/test_m3_execution_integration.py` -> `tests/integration/test_auto_sell_integration.py`

- [ ] **Step 1: 先把执行层测试名和导入改成最终形态**

```bash
git mv tests/unit/test_m3_quantity_rules.py tests/unit/test_sell_quantity_policy.py
git mv tests/unit/test_m3_state_manager.py tests/unit/test_order_execution_state.py
git mv tests/unit/test_m3_models.py tests/unit/test_auto_sell_models.py
git mv tests/unit/test_m3_execution_service.py tests/unit/test_auto_sell_service.py
git mv tests/integration/test_m3_execution_integration.py tests/integration/test_auto_sell_integration.py
```

```python
# tests/unit/test_auto_sell_service.py
from gmtrade_live.services.auto_sell_service import AutoSellService
from gmtrade_live.services.order_execution_state import (
    OrderExecutionState,
    OrderExecutionStateStore,
)
from gmtrade_live.services.sell_candidate_pipeline import SellCandidatePipeline
from gmtrade_live.services.sell_quantity_policy import build_sell_quantity_plan
```

```python
# tests/unit/test_auto_sell_models.py
from gmtrade_live.models import AutoSellRoundReport, AutoSellRoundSummary, SellBlockDetail, SellExecutionDetail
```

- [ ] **Step 2: 运行执行层新测试，确认新模块名还未落地时失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_sell_quantity_policy.py tests/unit/test_order_execution_state.py tests/unit/test_auto_sell_models.py tests/unit/test_auto_sell_service.py -q`

Expected: `ModuleNotFoundError` 或 `ImportError`，至少提示 `auto_sell_service`、`order_execution_state` 或 `AutoSellRoundReport` 等名字还不存在。

- [ ] **Step 3: 重命名执行层源码并把服务改为消费共享候选结果**

```bash
git mv src/gmtrade_live/services/m3_quantity_rules.py src/gmtrade_live/services/sell_quantity_policy.py
git mv src/gmtrade_live/services/m3_state_manager.py src/gmtrade_live/services/order_execution_state.py
git mv src/gmtrade_live/services/m3_execution_service.py src/gmtrade_live/services/auto_sell_service.py
```

```python
# src/gmtrade_live/models.py
@dataclass(frozen=True, slots=True)
class SellBlockDetail:
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
class SellExecutionDetail:
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
    submit_started_at: datetime | None = None
    submit_accepted_at: datetime | None = None
    terminal_state_at: datetime | None = None
    order_terminal_latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class AutoSellRoundSummary:
    round_no: int
    session_state: str
    position_count: int
    candidate_count: int
    blocked_count: int
    submitted_count: int
    open_order_count: int
    changed_symbol_count: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class AutoSellRoundReport:
    summary: AutoSellRoundSummary
    block_details: tuple[SellBlockDetail, ...]
    execution_details: tuple[SellExecutionDetail, ...]
```

```python
# src/gmtrade_live/services/order_execution_state.py
class OrderExecutionState(str, Enum):
    idle = "idle"
    submitting = "submitting"
    submitted = "submitted"
    partially_filled = "partially_filled"
    filled = "filled"
    cancelled = "cancelled"
    failed = "failed"


class OrderExecutionStateStore:
    """保留原 `M3PositionStateManager` 的缓存、状态推进和 `has_open_order()` 实现，只做类名替换。"""
```

```python
# src/gmtrade_live/services/auto_sell_service.py
class AutoSellService:
    def __init__(
        self,
        *,
        candidate_pipeline,
        trade_gateway,
        execution_state_store,
        quantity_planner,
        logger,
        audit_logger=None,
        clock=None,
        timer=None,
        sleep=None,
    ) -> None:
        self._candidate_pipeline = candidate_pipeline
        self._trade_gateway = trade_gateway
        self._execution_state_store = execution_state_store
        self._quantity_planner = quantity_planner
        self._logger = logger
        self._audit_logger = audit_logger
        self._clock = clock or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self._timer = timer or perf_counter
        self._sleep = sleep or time.sleep

    def run_round(self, *, config, round_no: int, reconcile_timeout_seconds: int):
        started_at = self._timer()
        now = self._clock()
        candidate_round = self._candidate_pipeline.evaluate_round(config=config, now=now)
        block_details: list[SellBlockDetail] = []
        execution_details: list[SellExecutionDetail] = []
        tracked_positions: dict[str, PositionSnapshot] = {}

        for candidate in candidate_round.candidates:
            if not candidate.decision.can_submit_sell:
                continue
            if self._execution_state_store.has_open_order(candidate.position.symbol):
                tracked_positions[candidate.position.symbol] = candidate.position
                continue
            quantity_plan = self._quantity_planner(
                symbol=candidate.position.symbol,
                total_volume=candidate.position.volume,
                available_volume=candidate.position.available_volume,
                sell_quantity_ratio=config.sell_quantity_ratio,
            )
            if quantity_plan.block_reason is not None:
                block_details.append(self._build_block_detail(candidate, quantity_plan))
                continue
            accepted, immediate_detail = self._submit_new_order(
                candidate=candidate,
                requested_volume=quantity_plan.final_target_volume,
                round_no=round_no,
                account_id=config.account_id,
            )
            if immediate_detail is not None:
                execution_details.append(immediate_detail)
                continue
            if accepted:
                tracked_positions[candidate.position.symbol] = candidate.position

        execution_details.extend(
            self._reconcile_open_orders(
                tracked_positions=tracked_positions,
                round_no=round_no,
                account_id=config.account_id,
                reconcile_timeout_seconds=reconcile_timeout_seconds,
            )
        )
        return AutoSellRoundReport(
            summary=AutoSellRoundSummary(
                round_no=round_no,
                session_state=candidate_round.session_state.value,
                position_count=len(candidate_round.positions),
                candidate_count=sum(1 for item in candidate_round.candidates if item.decision.can_submit_sell),
                blocked_count=len(block_details),
                submitted_count=sum(1 for item in execution_details if "submit_accepted" in item.change_tags),
                open_order_count=sum(
                    1
                    for item in self._execution_state_store.active_states()
                    if self._execution_state_store.has_open_order(item.symbol)
                ),
                changed_symbol_count=len({item.symbol for item in block_details} | {item.symbol for item in execution_details}),
                duration_ms=int((self._timer() - started_at) * 1000),
            ),
            block_details=tuple(block_details),
            execution_details=tuple(execution_details),
        )
```

同文件里保留并重命名现有私有方法 `_build_block_detail()`、`_submit_new_order()`、`_reconcile_open_orders()`、`_build_execution_detail()`、`_apply_query_event()` 的实现；方法体直接从现有 `m3_execution_service.py` 迁移，只把依赖类型名和导入切到新名字。

- [ ] **Step 4: 运行执行层定向测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_sell_quantity_policy.py tests/unit/test_order_execution_state.py tests/unit/test_auto_sell_models.py tests/unit/test_auto_sell_service.py tests/integration/test_auto_sell_integration.py -q`

Expected: 执行层测试通过，尤其要覆盖“共享候选评估结果复用”“阻断详情仍含决策态投影”“订单在途不重复发单”“终态收口时间字段不回退”。

- [ ] **Step 5: 提交执行层重命名与自动卖出服务重组**

```bash
git add src/gmtrade_live/models.py src/gmtrade_live/services/sell_quantity_policy.py src/gmtrade_live/services/order_execution_state.py src/gmtrade_live/services/auto_sell_service.py tests/unit/test_sell_quantity_policy.py tests/unit/test_order_execution_state.py tests/unit/test_auto_sell_models.py tests/unit/test_auto_sell_service.py tests/integration/test_auto_sell_integration.py
git commit -m "refactor(execution): rename auto-sell services and models"
```

### Task 3: 用 `app_runner` + 双入口脚本替换阶段式 `main.py --mode`

**Files:**
- Rename: `src/gmtrade_live/bootstrap.py` -> `src/gmtrade_live/app_runner.py`
- Modify: `main.py`
- Create: `observe_decisions.py`
- Modify: `tests/unit/test_main.py`
- Create: `tests/unit/test_observe_decisions.py`
- Rename: `tests/unit/test_bootstrap.py` -> `tests/unit/test_app_runner.py`

- [ ] **Step 1: 先把入口测试改成产品语义**

```bash
git mv tests/unit/test_bootstrap.py tests/unit/test_app_runner.py
```

```python
# tests/unit/test_main.py
def test_parse_cli_args_accepts_auto_sell_flags_without_mode() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--once",
            "--reconcile-timeout-seconds",
            "7",
        ]
    )

    assert args.config == "config/sim_account.yaml"
    assert args.once is True
    assert args.reconcile_timeout_seconds == 7


def test_main_dispatches_to_run_auto_sell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_auto_sell(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    runner = SimpleNamespace(run_auto_sell=_run_auto_sell)
    monkeypatch.setitem(sys.modules, "gmtrade_live.app_runner", runner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--config",
            "config/sim_account.yaml",
            "--once",
            "--reconcile-timeout-seconds",
            "7",
        ],
    )

    assert main.main() == 0
    assert captured["reconcile_timeout_seconds"] == 7
```

```python
# tests/unit/test_observe_decisions.py
from __future__ import annotations

import sys
from types import SimpleNamespace

import observe_decisions


def test_parse_cli_args_accepts_observer_flags() -> None:
    args = observe_decisions.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--max-rounds",
            "3",
        ]
    )

    assert args.config == "config/sim_account.yaml"
    assert args.max_rounds == 3


def test_observe_main_dispatches_to_run_decision_observer(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _run_decision_observer(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    runner = SimpleNamespace(run_decision_observer=_run_decision_observer)
    monkeypatch.setitem(sys.modules, "gmtrade_live.app_runner", runner)
    monkeypatch.setattr(
        sys,
        "argv",
        ["observe_decisions.py", "--config", "config/sim_account.yaml", "--once"],
    )

    assert observe_decisions.main() == 0
    assert captured["once"] is True
```

- [ ] **Step 2: 运行入口测试，确认旧 `--mode` CLI 和旧 `bootstrap` 导入不再满足新契约**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_observe_decisions.py tests/unit/test_app_runner.py -q`

Expected: 失败点至少包括 `main.py` 仍要求 `--mode`、`observe_decisions.py` 不存在、以及 `gmtrade_live.app_runner` 尚未创建。

- [ ] **Step 3: 切换运行入口**

```bash
git mv src/gmtrade_live/bootstrap.py src/gmtrade_live/app_runner.py
```

```python
# main.py
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto-sell runtime")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true")
    group.add_argument("--max-rounds", type=_parse_positive_int)
    parser.add_argument(
        "--reconcile-timeout-seconds",
        type=_parse_positive_int,
        default=5,
    )
    return parser


def main() -> int:
    args = parse_cli_args()
    from gmtrade_live.app_runner import run_auto_sell

    return run_auto_sell(
        config_path=Path(args.config),
        once=args.once,
        max_rounds=args.max_rounds,
        reconcile_timeout_seconds=args.reconcile_timeout_seconds,
    )
```

```python
# observe_decisions.py
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from main import _parse_positive_int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Decision observer runtime")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true")
    group.add_argument("--max-rounds", type=_parse_positive_int)
    return parser


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main() -> int:
    args = parse_cli_args()
    from gmtrade_live.app_runner import run_decision_observer

    return run_decision_observer(
        config_path=Path(args.config),
        once=args.once,
        max_rounds=args.max_rounds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# src/gmtrade_live/app_runner.py
from gmtrade_live.services.auto_sell_service import AutoSellService
from gmtrade_live.services.decision_observer import DecisionObserverService
from gmtrade_live.services.order_execution_state import OrderExecutionStateStore
from gmtrade_live.services.position_decision_state import PositionDecisionStateStore
from gmtrade_live.services.sell_candidate_pipeline import SellCandidatePipeline
from gmtrade_live.services.sell_decision_engine import SellDecisionEngine
from gmtrade_live.services.sell_quantity_policy import build_sell_quantity_plan


def _build_candidate_pipeline(*, trade_gateway, market_gateway, logger):
    return SellCandidatePipeline(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        decision_state_store=PositionDecisionStateStore(logger),
        decision_engine=SellDecisionEngine(),
    )


def _resolve_current_session_state(config) -> object:
    return resolve_trading_session(
        datetime.now(tz=ZoneInfo(config.timezone)),
        timezone_name=config.timezone,
        market_session_mode=config.market_session_mode,
    )


def _emit_decision_observer_outputs(report) -> None:
    print(
        json.dumps(
            {
                "kind": "m2_round_summary",
                "round": report.summary.round_no,
                "session_state": report.summary.session_state,
                "position_count": report.summary.position_count,
                "watching_count": report.summary.watching_count,
                "tombstone_count": report.summary.tombstone_count,
                "should_sell_count": report.summary.should_sell_count,
                "can_submit_sell_count": report.summary.can_submit_sell_count,
                "changed_symbol_count": report.summary.changed_symbol_count,
                "duration_ms": report.summary.duration_ms,
            },
            ensure_ascii=False,
        )
    )
    for event in report.change_events:
        print(
            json.dumps(
                {
                    "kind": "m2_change_detail",
                    "symbol": event.symbol,
                    "change_tags": list(event.change_tags),
                },
                ensure_ascii=False,
            )
        )


def _emit_auto_sell_outputs(report) -> None:
    print(
        json.dumps(
            {
                "kind": "m3_round_summary",
                "round": report.summary.round_no,
                "session_state": report.summary.session_state,
                "position_count": report.summary.position_count,
                "candidate_count": report.summary.candidate_count,
                "blocked_count": report.summary.blocked_count,
                "submitted_count": report.summary.submitted_count,
                "open_order_count": report.summary.open_order_count,
                "changed_symbol_count": report.summary.changed_symbol_count,
                "duration_ms": report.summary.duration_ms,
            },
            ensure_ascii=False,
        )
    )
    for block in report.block_details:
        print(json.dumps({"kind": "m3_block_detail", "symbol": block.symbol}, ensure_ascii=False))
    for detail in report.execution_details:
        print(json.dumps({"kind": "m3_execution_detail", "symbol": detail.symbol}, ensure_ascii=False))


def run_decision_observer(*, config_path: Path, once: bool, max_rounds: int | None) -> int:
    config = load_config(config_path)
    _resolve_current_session_state(config)
    logger = setup_logging(config.strategy_name, config.log_dir)
    trade_gateway = GMTradeGateway()
    market_gateway = GMCurrentQuoteGateway()
    trade_gateway.connect(config)
    market_gateway.connect(config.token)
    candidate_pipeline = _build_candidate_pipeline(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        logger=logger,
    )
    service = DecisionObserverService(
        candidate_pipeline=candidate_pipeline,
        logger=logger,
        clock=lambda: datetime.now(tz=ZoneInfo(config.timezone)),
        timer=perf_counter,
    )

    round_no = 1
    while True:
        logger.info("round_started entry=decision_observer round=%s once=%s max_rounds=%s", round_no, once, max_rounds)
        try:
            report = service.run_round(config=config, round_no=round_no)
        except Exception as exc:
            logger.error("round_failed entry=decision_observer round=%s error_type=%s error=%s", round_no, type(exc).__name__, str(exc), exc_info=True)
            print(json.dumps({"kind": "decision_round_error", "round": round_no, "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
            if once or (max_rounds is not None and round_no >= max_rounds):
                return 1
        else:
            _emit_decision_observer_outputs(report)
            if once or (max_rounds is not None and round_no >= max_rounds):
                return 0
        time.sleep(config.poll_interval_seconds)
        round_no += 1


def run_auto_sell(
    *,
    config_path: Path,
    once: bool,
    max_rounds: int | None,
    reconcile_timeout_seconds: int,
) -> int:
    config = load_config(config_path)
    _resolve_current_session_state(config)
    logger = setup_logging(config.strategy_name, config.log_dir)
    audit_logger = setup_order_audit_logger(config.strategy_name, config.log_dir)
    trade_gateway = GMTradeGateway()
    market_gateway = GMCurrentQuoteGateway()
    trade_gateway.connect(config)
    market_gateway.connect(config.token)
    candidate_pipeline = _build_candidate_pipeline(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        logger=logger,
    )
    service = AutoSellService(
        candidate_pipeline=candidate_pipeline,
        trade_gateway=trade_gateway,
        execution_state_store=OrderExecutionStateStore(logger),
        quantity_planner=build_sell_quantity_plan,
        logger=logger,
        audit_logger=audit_logger,
        clock=lambda: datetime.now(tz=ZoneInfo(config.timezone)),
        timer=perf_counter,
        sleep=time.sleep,
    )

    round_no = 1
    while True:
        logger.info(
            "round_started entry=auto_sell round=%s once=%s max_rounds=%s reconcile_timeout_seconds=%s",
            round_no,
            once,
            max_rounds,
            reconcile_timeout_seconds,
        )
        try:
            report = service.run_round(
                config=config,
                round_no=round_no,
                reconcile_timeout_seconds=reconcile_timeout_seconds,
            )
        except Exception as exc:
            logger.error("round_failed entry=auto_sell round=%s error_type=%s error=%s", round_no, type(exc).__name__, str(exc), exc_info=True)
            print(json.dumps({"kind": "auto_sell_round_error", "round": round_no, "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
            return 1
        _emit_auto_sell_outputs(report)
        if once or (max_rounds is not None and round_no >= max_rounds):
            return 0
        time.sleep(config.poll_interval_seconds)
        round_no += 1
```

- [ ] **Step 4: 运行运行层定向测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_observe_decisions.py tests/unit/test_app_runner.py -q`

Expected: `main.py` 与 `observe_decisions.py` 都能在不带 `--mode` 的前提下正确分发到 `app_runner`。

- [ ] **Step 5: 提交运行入口重构**

```bash
git add main.py observe_decisions.py src/gmtrade_live/app_runner.py tests/unit/test_main.py tests/unit/test_observe_decisions.py tests/unit/test_app_runner.py
git commit -m "refactor(runtime): replace staged cli with product entrypoints"
```

### Task 4: 把 M0/M1 能力迁到 `tools/debug` 并删除阶段服务模块

**Files:**
- Create: `tools/debug/check_connectivity.py`
- Create: `tools/debug/manual_trade.py`
- Create: `tests/debug/test_check_connectivity.py`
- Create: `tests/debug/test_manual_trade.py`
- Delete: `src/gmtrade_live/services/m0_connectivity.py`
- Delete: `src/gmtrade_live/services/m1_manual_trade.py`
- Delete: `tests/unit/test_m1_manual_trade.py`
- Delete: `tests/integration/test_m0_connectivity_service.py`
- Delete: `tests/integration/test_m1_manual_trade_service.py`

- [ ] **Step 1: 先为新 debug 脚本写测试**

```python
# tests/debug/test_check_connectivity.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import CashSnapshot, PositionSnapshot, QuoteSnapshot
from tools.debug.check_connectivity import build_connectivity_summary


def _now() -> datetime:
    return datetime(2026, 4, 14, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_build_connectivity_summary_returns_structured_payload() -> None:
    payload = build_connectivity_summary(
        account_id="demo-account",
        session_state="trading",
        cash=CashSnapshot(
            account_id="demo-account",
            available_cash=Decimal("1000.00"),
            market_value=Decimal("2000.00"),
            total_asset=Decimal("3000.00"),
            update_time=_now(),
        ),
        positions=(
            PositionSnapshot(
                symbol="SHSE.600036",
                exchange="SHSE",
                volume=100,
                available_volume=100,
                cost_price=Decimal("10.00"),
                last_update_time=_now(),
            ),
        ),
        quotes=(
            QuoteSnapshot(
                symbol="SHSE.600036",
                last_price=Decimal("10.80"),
                quote_time=_now(),
                source="fake",
            ),
        ),
    )

    assert payload["account_id"] == "demo-account"
    assert payload["position_count"] == 1
    assert payload["quote_count"] == 1
```

```python
# tests/debug/test_manual_trade.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import TradeReport
from tools.debug.manual_trade import build_manual_trade_payload


def _now() -> datetime:
    return datetime(2026, 4, 14, 9, 50, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_build_manual_trade_payload_keeps_verification_fields() -> None:
    report = TradeReport(
        account_id="demo-account",
        side="sell",
        symbol="SHSE.600036",
        requested_volume=100,
        price_type="market",
        submit_accepted=True,
        cl_ord_id="CL_1",
        broker_order_id="BK_1",
        order_status_confirmed=True,
        execution_status_confirmed=True,
        last_order_status="filled",
        rejection_reason=None,
        filled_volume=100,
        avg_price=Decimal("10.80"),
        verification_passed=True,
        message="ok",
        started_at=_now(),
        finished_at=_now(),
    )

    payload = build_manual_trade_payload(report)

    assert payload["verification_passed"] is True
    assert payload["cl_ord_id"] == "CL_1"
    assert payload["avg_price"] == "10.80"
```

- [ ] **Step 2: 运行新 debug 测试，确认脚本还不存在而失败**

Run: `conda run -n stock_analysis pytest tests/debug/test_check_connectivity.py tests/debug/test_manual_trade.py -q`

Expected: `ModuleNotFoundError: No module named 'tools.debug.check_connectivity'` 或 `tools.debug.manual_trade`。

- [ ] **Step 3: 实现 debug 脚本并删掉旧阶段服务模块**

```python
# tools/debug/check_connectivity.py
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import load_config
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeGateway
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.session import resolve_trading_session


def build_connectivity_summary(*, account_id: str, session_state: str, cash, positions, quotes) -> dict[str, object]:
    return {
        "account_id": account_id,
        "session_state": session_state,
        "available_cash": str(cash.available_cash),
        "position_count": len(positions),
        "quote_count": len(quotes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Connectivity debug tool")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = load_config(Path(args.config))
    logger = setup_logging(config.strategy_name, config.log_dir)
    trade_gateway = GMTradeGateway()
    market_gateway = GMCurrentQuoteGateway()
    trade_gateway.connect(config)
    market_gateway.connect(config.token)
    session_state = resolve_trading_session(
        datetime.now(tz=ZoneInfo(config.timezone)),
        timezone_name=config.timezone,
        market_session_mode=config.market_session_mode,
    )
    cash = trade_gateway.get_cash(config.account_id)
    positions = tuple(position for position in trade_gateway.get_positions(config.account_id) if position.volume > 0)
    quotes = tuple(market_gateway.get_quotes([position.symbol for position in positions])) if positions else ()
    payload = build_connectivity_summary(
        account_id=config.account_id,
        session_state=session_state.value,
        cash=cash,
        positions=positions,
        quotes=quotes,
    )
    logger.info("debug_connectivity account_id=%s positions=%s quotes=%s", config.account_id, len(positions), len(quotes))
    print(json.dumps(payload, ensure_ascii=False))
    return 0
```

```python
# tools/debug/manual_trade.py
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from gmtrade_live.config import load_config
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeGateway
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.models import TradeReport


def build_manual_trade_payload(report: TradeReport) -> dict[str, object]:
    return {
        "verification_passed": report.verification_passed,
        "side": report.side,
        "cl_ord_id": report.cl_ord_id,
        "broker_order_id": report.broker_order_id,
        "submit_accepted": report.submit_accepted,
        "order_status_confirmed": report.order_status_confirmed,
        "execution_status_confirmed": report.execution_status_confirmed,
        "last_order_status": report.last_order_status,
        "rejection_reason": report.rejection_reason,
        "filled_volume": report.filled_volume,
        "avg_price": str(report.avg_price) if report.avg_price is not None else None,
        "message": report.message,
    }
```

```bash
git rm src/gmtrade_live/services/m0_connectivity.py src/gmtrade_live/services/m1_manual_trade.py tests/unit/test_m1_manual_trade.py tests/integration/test_m0_connectivity_service.py tests/integration/test_m1_manual_trade_service.py
```

- [ ] **Step 4: 运行 debug 测试并确认正式入口不再依赖旧模块**

Run: `conda run -n stock_analysis pytest tests/debug/test_check_connectivity.py tests/debug/test_manual_trade.py tests/unit/test_main.py tests/unit/test_app_runner.py -q`

Expected: debug 脚本测试通过，且 `main.py` / `app_runner.py` 不再 import `m0_connectivity`、`m1_manual_trade`。

- [ ] **Step 5: 提交 debug 工具迁移**

```bash
git add tools/debug/check_connectivity.py tools/debug/manual_trade.py tests/debug/test_check_connectivity.py tests/debug/test_manual_trade.py main.py observe_decisions.py src/gmtrade_live/app_runner.py
git rm src/gmtrade_live/services/m0_connectivity.py src/gmtrade_live/services/m1_manual_trade.py tests/unit/test_m1_manual_trade.py tests/integration/test_m0_connectivity_service.py tests/integration/test_m1_manual_trade_service.py
git commit -m "refactor(debug): move connectivity and manual trade to tools"
```

### Task 5: 改结构化输出、smoke、配置示例和主说明文档

**Files:**
- Modify: `src/gmtrade_live/app_runner.py`
- Modify: `tests/unit/test_app_runner.py`
- Modify: `tests/unit/test_config.py`
- Rename: `tests/smoke/test_m4_local_smoke.py` -> `tests/smoke/test_auto_sell_smoke.py`
- Modify: `AGENTS.md`
- Modify: `config/sim_account.example.yaml`
- Create: `docs/auto-sell-runtime.md`

- [ ] **Step 1: 先把 smoke / output / config 测试改成最终口径**

```bash
git mv tests/smoke/test_m4_local_smoke.py tests/smoke/test_auto_sell_smoke.py
```

```python
# tests/unit/test_app_runner.py
assert '"kind": "decision_round_summary"' in lines[0]
assert '"kind": "decision_change_detail"' in lines[1]
assert '"kind": "auto_sell_round_summary"' in lines[0]
assert '"kind": "sell_block_detail"' in lines[1]
assert '"kind": "sell_execution_detail"' in lines[2]
```

```python
# tests/smoke/test_auto_sell_smoke.py
assert "decision_round_summary" in captured.out
assert "entry=decision_observer" in runtime_log
assert "auto_sell_round_summary" in captured.out
assert details, "期待至少有一个 sell_execution_detail"
assert "entry=auto_sell" in runtime_log
```

```python
# tests/unit/test_config.py
assert loaded.strategy_name == "gmtrade-live-auto-sell"
```

- [ ] **Step 2: 运行观测输出和 smoke 相关测试，确认旧 `m2_*` / `m3_*` 名字仍会导致失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_app_runner.py tests/unit/test_config.py tests/smoke/test_auto_sell_smoke.py -q`

Expected: 失败点至少包括旧 `kind` 名、旧 `mode=m2/m3` 日志片段、以及示例配置里的旧 `strategy_name`。

- [ ] **Step 3: 落地去阶段化输出与主文档**

```python
# src/gmtrade_live/app_runner.py
print(
    json.dumps(
        {
            "kind": "decision_round_summary",
            "round": report.summary.round_no,
            "session_state": report.summary.session_state,
            "position_count": report.summary.position_count,
            "watching_count": report.summary.watching_count,
            "tombstone_count": report.summary.tombstone_count,
            "should_sell_count": report.summary.should_sell_count,
            "can_submit_sell_count": report.summary.can_submit_sell_count,
            "changed_symbol_count": report.summary.changed_symbol_count,
            "duration_ms": report.summary.duration_ms,
        },
        ensure_ascii=False,
    )
)
```

```python
# src/gmtrade_live/app_runner.py
logger.info(
    "round_started entry=auto_sell round=%s once=%s max_rounds=%s reconcile_timeout_seconds=%s",
    round_no,
    once,
    max_rounds,
    reconcile_timeout_seconds,
)
```

```yaml
# config/sim_account.example.yaml
strategy_name: gmtrade-live-auto-sell
```

````markdown
# docs/auto-sell-runtime.md
# Auto-Sell Runtime

## 正式入口

```bash
conda run -n stock_analysis python main.py --config config/sim_account.yaml --once
conda run -n stock_analysis python observe_decisions.py --config config/sim_account.yaml --once
```

## Debug 工具

```bash
conda run -n stock_analysis python tools/debug/check_connectivity.py --config config/sim_account.yaml
conda run -n stock_analysis python tools/debug/manual_trade.py --config config/sim_account.yaml --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60
```
````

```markdown
# AGENTS.md 中把运行命令改成：
- 自动卖出：`conda run -n stock_analysis python main.py --config config/sim_account.yaml --once`
- 决策观测：`conda run -n stock_analysis python observe_decisions.py --config config/sim_account.yaml --once`
- 调试连通性：`conda run -n stock_analysis python tools/debug/check_connectivity.py --config config/sim_account.yaml`
- 调试手工交易：`conda run -n stock_analysis python tools/debug/manual_trade.py --config config/sim_account.yaml --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60`
```

- [ ] **Step 4: 运行输出、smoke 和配置测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_app_runner.py tests/unit/test_config.py tests/smoke/test_auto_sell_smoke.py -q`

Expected: 新 `kind`、新 `entry` 日志、新 `strategy_name`、新 smoke 名称全部通过。

- [ ] **Step 5: 提交观测口径与文档收口**

```bash
git add src/gmtrade_live/app_runner.py tests/unit/test_app_runner.py tests/unit/test_config.py tests/smoke/test_auto_sell_smoke.py AGENTS.md config/sim_account.example.yaml docs/auto-sell-runtime.md
git commit -m "refactor(observability): rename outputs smoke and docs"
```

### Task 6: 增加 stage-name 守卫并做全量回归

**Files:**
- Create: `tests/unit/test_stage_name_guard.py`
- Modify: 活跃代码面上仍残留阶段名的任何文件

- [ ] **Step 1: 添加 stage-name 守卫测试**

```python
# tests/unit/test_stage_name_guard.py
from __future__ import annotations

import re
from pathlib import Path


FORBIDDEN = re.compile(r"\b(?:M[0-4]|m[0-4])\b")
TARGETS = [
    Path("main.py"),
    Path("observe_decisions.py"),
    Path("AGENTS.md"),
    Path("config/sim_account.example.yaml"),
    Path("src/gmtrade_live"),
    Path("tests/debug"),
    Path("tests/smoke/test_auto_sell_smoke.py"),
    Path("tests/unit"),
    Path("tests/integration"),
    Path("tools/debug"),
]
ALLOWED_SUBSTRINGS = (
    "docs/superpowers/specs",
    "docs/superpowers/plans",
    "__pycache__",
)


def iter_text_files() -> list[Path]:
    result: list[Path] = []
    for target in TARGETS:
        if target.is_file():
            result.append(target)
            continue
        if target.is_dir():
            result.extend(path for path in target.rglob("*") if path.is_file())
    return result


def test_active_product_surface_does_not_expose_stage_names() -> None:
    offenders: list[str] = []
    for path in iter_text_files():
        normalized = path.as_posix()
        if any(token in normalized for token in ALLOWED_SUBSTRINGS):
            continue
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN.search(text):
            offenders.append(normalized)
    assert offenders == [], f"Found staged names in active files: {offenders}"
```

- [ ] **Step 2: 运行守卫测试并清理残余阶段名**

Run: `conda run -n stock_analysis pytest tests/unit/test_stage_name_guard.py -q`

Expected: 若仍有活跃文件残留 `M0~M4`，测试会列出 offending path；把这些残留清掉后，测试应变为 `1 passed`。

- [ ] **Step 3: 运行全量回归**

Run: `conda run -n stock_analysis pytest tests/unit tests/integration tests/debug tests/smoke -q`

Expected: 全量测试通过，且不会因为阶段名重构回退自动卖出、观测入口或 debug 工具语义。

- [ ] **Step 4: 运行文本扫描确认主干已去阶段化**

Run: `rg -n "\b(?:M[0-4]|m[0-4])\b" main.py observe_decisions.py src tests AGENTS.md config tools -g '!docs/superpowers/**' -g '!**/__pycache__/**'`

Expected: 无输出；若仍有结果，只允许来自用户明确保留的历史样例文件，否则继续清理。

- [ ] **Step 5: 提交最终清理与回归守卫**

```bash
git add tests/unit/test_stage_name_guard.py main.py observe_decisions.py src tests AGENTS.md config tools
git commit -m "test(product): add stage-name guard and finalize rename"
```

## Self-Review Checklist

- [ ] **Spec coverage:** 对照 `docs/superpowers/specs/2026-04-14-auto-sell-productization-design.md` 检查：
  - `SellCandidatePipeline`：Task 1
  - 正式自动卖出入口：Task 2 + Task 3
  - 正式决策观测入口：Task 1 + Task 3
  - `tools/debug`：Task 4
  - JSON / 日志 / smoke / 文档 / 配置去阶段化：Task 5
  - stage-name 清理守卫：Task 6
- [ ] **Placeholder scan:** 搜索本计划，确认没有 `TODO`、`TBD`、`后续补`、`类似 Task N`、`适当处理` 之类占位语句。
- [ ] **Type consistency:** 确认全计划统一使用这些名字：
  - `SellDecisionEngine`
  - `PositionDecisionStateStore`
  - `SellCandidatePipeline`
  - `DecisionObserverService`
  - `OrderExecutionStateStore`
  - `AutoSellService`
  - `DecisionObservationReport`
  - `AutoSellRoundReport`
  - `run_decision_observer`
  - `run_auto_sell`
- [ ] **Guard rails:** 确认计划没有要求修改用户本地 `config/sim_account.yaml`，也没有把历史 `docs/superpowers/**` 当成本轮必须改名的活跃产品面。
