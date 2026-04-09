# M2 核心决策与状态管理 Dry-Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `--mode m2` 连续 dry-run 能力，在不发单的前提下完成多标的内存决策态管理、止盈止损判断、可提交性判断和结构化输出。

**Architecture:** M2 新增专用的决策态模型、`M2StateManager`、`M2DecisionEngine` 和 `M2DryRunService`。`main.py --mode m2` 通过现有的 query gateway 与 market gateway 读取持仓和行情，由 `run_m2_dry_run()` 驱动连续轮询；现有 `state.py` 保留给 M3 执行态，不直接承接 M2 主逻辑。`M2RoundReport` 和 `M2ChangeEvent` 是对内稳定契约，后续状态机或状态表应消费这些对象或其规范化结果，CLI JSON 只是投影。

**Tech Stack:** Python 3.10+, pytest, stdlib `argparse/json/logging/time/zoneinfo/dataclasses`, `Decimal`, 现有 `GMTradeQueryGateway`, `GMCurrentQuoteGateway`

---

## Planned File Structure

**New files:**
- `src/gmtrade_live/services/m2_state_manager.py` - M2 内存决策态与墓碑态管理
- `src/gmtrade_live/services/m2_decision_engine.py` - 单标的决策判断
- `src/gmtrade_live/services/m2_dry_run.py` - 单轮 dry-run 编排与变化检测
- `tests/unit/test_m2_models.py` - M2 模型单测
- `tests/unit/test_m2_state_manager.py` - 状态管理器单测
- `tests/unit/test_m2_decision_engine.py` - 决策引擎单测
- `tests/unit/test_m2_dry_run.py` - dry-run 编排单测
- `tests/integration/test_m2_dry_run.py` - 假网关集成测试

**Modified files:**
- `src/gmtrade_live/models.py` - 新增 M2 模型
- `src/gmtrade_live/bootstrap.py` - 新增 `run_m2_dry_run()`
- `main.py` - 新增 `--mode m2` 与 M2 CLI 参数
- `tests/unit/test_main.py` - 新增 M2 参数与 dispatch 测试
- `tests/unit/test_bootstrap.py` - 新增 M2 输出与退出码测试
- `AGENTS.md` - 增加 M2 命令示例

## Scope Guard

M2 只做：读取当前持仓 → 只查询持仓行情 → 连续 dry-run 评估 → 输出决策与状态快照。

M2 不做：发单、未完成委托查询、防重复卖单正式逻辑、执行态更新、数据库持久化。

补充约束：

- M2 输出不是一次性调试文本，而是后续 M3 / 数据库可消费的决策事实
- 不把 callback 作为 M2 或后续闭环成立的前提

---

## Task 1: 扩展 M2 数据模型

**Files:**
- Modify: `src/gmtrade_live/models.py`
- Create: `tests/unit/test_m2_models.py`

- [ ] **Step 1: 写 M2 模型的失败测试**

```python
# tests/unit/test_m2_models.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    DecisionResult,
    EvaluatedSymbol,
    M2ChangeEvent,
    M2RoundReport,
    M2RoundSummary,
)


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_decision_result_allows_should_sell_without_submit() -> None:
    result = DecisionResult(
        symbol="SHSE.600036",
        should_sell=True,
        can_submit_sell=False,
        trigger_reason="take_profit_triggered",
        block_reason="not_in_trading_session",
        current_price=Decimal("10.80"),
        cost_price=Decimal("10.00"),
        take_profit_price=Decimal("10.50"),
        stop_loss_price=Decimal("9.70"),
        volume=100,
        available_volume=100,
        sellable_now=True,
        session_state="post_close",
        evaluated_at=_now(),
    )

    assert result.should_sell is True
    assert result.can_submit_sell is False
    assert result.trigger_reason == "take_profit_triggered"
    assert result.block_reason == "not_in_trading_session"


def test_decision_position_state_snapshot_supports_tombstone() -> None:
    snapshot = DecisionPositionStateSnapshot(
        symbol="SHSE.600036",
        lifecycle_state=DecisionLifecycleState.tombstone,
        has_position=False,
        sellable_now=False,
        volume=0,
        available_volume=0,
        first_seen_at=_now(),
        last_seen_at=_now(),
        disappeared_at=_now(),
        tombstone_rounds=1,
        last_trigger_reason=None,
        last_block_reason="position_missing",
        last_decision_at=_now(),
    )

    assert snapshot.lifecycle_state is DecisionLifecycleState.tombstone
    assert snapshot.disappeared_at is not None
    assert snapshot.tombstone_rounds == 1


def test_m2_round_report_contains_summary_and_change_events() -> None:
    decision = DecisionResult(
        symbol="SHSE.600036",
        should_sell=True,
        can_submit_sell=True,
        trigger_reason="take_profit_triggered",
        block_reason=None,
        current_price=Decimal("10.80"),
        cost_price=Decimal("10.00"),
        take_profit_price=Decimal("10.50"),
        stop_loss_price=Decimal("9.70"),
        volume=100,
        available_volume=100,
        sellable_now=True,
        session_state="trading",
        evaluated_at=_now(),
    )
    state_snapshot = DecisionPositionStateSnapshot(
        symbol="SHSE.600036",
        lifecycle_state=DecisionLifecycleState.watching,
        has_position=True,
        sellable_now=True,
        volume=100,
        available_volume=100,
        first_seen_at=_now(),
        last_seen_at=_now(),
        disappeared_at=None,
        tombstone_rounds=0,
        last_trigger_reason="take_profit_triggered",
        last_block_reason=None,
        last_decision_at=_now(),
    )
    report = M2RoundReport(
        summary=M2RoundSummary(
            round_no=1,
            session_state="trading",
            position_count=1,
            watching_count=1,
            tombstone_count=0,
            should_sell_count=1,
            can_submit_sell_count=1,
            changed_symbol_count=1,
            duration_ms=12,
        ),
        evaluated_symbols=(EvaluatedSymbol(decision=decision, state_snapshot=state_snapshot),),
        tombstones=(),
        change_events=(
            M2ChangeEvent(
                symbol="SHSE.600036",
                change_tags=("trigger_activated", "submit_permission_granted"),
                decision=decision,
                state_snapshot=state_snapshot,
            ),
        ),
    )

    assert report.summary.round_no == 1
    assert report.change_events[0].change_tags == (
        "trigger_activated",
        "submit_permission_granted",
    )
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_models.py -q`

Expected: FAIL with `cannot import name 'DecisionLifecycleState'`

- [ ] **Step 3: 在 `models.py` 中添加 M2 模型**

```python
# src/gmtrade_live/models.py
from enum import Enum


class DecisionLifecycleState(str, Enum):
    watching = "watching"
    tombstone = "tombstone"


@dataclass(frozen=True, slots=True)
class DecisionResult:
    symbol: str
    should_sell: bool
    can_submit_sell: bool
    trigger_reason: str | None
    block_reason: str | None
    current_price: Decimal
    cost_price: Decimal
    take_profit_price: Decimal
    stop_loss_price: Decimal
    volume: int
    available_volume: int
    sellable_now: bool
    session_state: str
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionPositionStateSnapshot:
    symbol: str
    lifecycle_state: DecisionLifecycleState
    has_position: bool
    sellable_now: bool
    volume: int
    available_volume: int
    first_seen_at: datetime
    last_seen_at: datetime
    disappeared_at: datetime | None
    tombstone_rounds: int
    last_trigger_reason: str | None
    last_block_reason: str | None
    last_decision_at: datetime


@dataclass(frozen=True, slots=True)
class EvaluatedSymbol:
    decision: DecisionResult
    state_snapshot: DecisionPositionStateSnapshot


@dataclass(frozen=True, slots=True)
class M2RoundSummary:
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
class M2ChangeEvent:
    symbol: str
    change_tags: tuple[str, ...]
    decision: DecisionResult | None
    state_snapshot: DecisionPositionStateSnapshot | None


@dataclass(frozen=True, slots=True)
class M2RoundReport:
    summary: M2RoundSummary
    evaluated_symbols: tuple[EvaluatedSymbol, ...]
    tombstones: tuple[DecisionPositionStateSnapshot, ...]
    change_events: tuple[M2ChangeEvent, ...]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_models.py -q`

Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add src/gmtrade_live/models.py tests/unit/test_m2_models.py
git commit -m "feat(m2): add decision dry-run models"
```

---

## Task 2: 实现 `M2StateManager`

**Files:**
- Create: `src/gmtrade_live/services/m2_state_manager.py`
- Create: `tests/unit/test_m2_state_manager.py`

- [ ] **Step 1: 写 `M2StateManager` 的失败测试**

```python
# tests/unit/test_m2_state_manager.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from zoneinfo import ZoneInfo

from gmtrade_live.models import DecisionLifecycleState, PositionSnapshot
from gmtrade_live.services.m2_state_manager import M2StateManager


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 5, tzinfo=ZoneInfo("Asia/Shanghai"))


def _position(
    symbol: str,
    *,
    volume: int,
    available_volume: int,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        exchange=symbol.split(".", maxsplit=1)[0],
        volume=volume,
        available_volume=available_volume,
        cost_price=Decimal("10.00"),
        last_update_time=_now(),
    )


def test_sync_positions_creates_watching_state_for_volume_positions() -> None:
    manager = M2StateManager(logging.getLogger("test"))

    snapshots = manager.sync_positions(
        positions=(
            _position("SHSE.600036", volume=100, available_volume=100),
            _position("SZSE.000001", volume=0, available_volume=0),
        ),
        now=_now(),
    )

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "SHSE.600036"
    assert snapshots[0].lifecycle_state is DecisionLifecycleState.watching


def test_sync_positions_transitions_to_tombstone_then_removes() -> None:
    manager = M2StateManager(logging.getLogger("test"))
    manager.sync_positions(
        positions=(_position("SHSE.600036", volume=100, available_volume=100),),
        now=_now(),
    )

    first_missing = manager.sync_positions(positions=(), now=_now())
    assert first_missing[0].lifecycle_state is DecisionLifecycleState.tombstone
    assert first_missing[0].tombstone_rounds == 1

    second_missing = manager.sync_positions(positions=(), now=_now())
    assert second_missing == ()
    assert manager.get_state("SHSE.600036") is None


def test_update_decision_feedback_updates_reason_and_volume() -> None:
    manager = M2StateManager(logging.getLogger("test"))
    manager.sync_positions(
        positions=(_position("SHSE.600036", volume=200, available_volume=0),),
        now=_now(),
    )

    snapshot = manager.update_decision_feedback(
        "SHSE.600036",
        trigger_reason="stop_loss_triggered",
        block_reason="temporarily_not_closable",
        volume=200,
        available_volume=0,
        sellable_now=False,
        decision_time=_now(),
    )

    assert snapshot.last_trigger_reason == "stop_loss_triggered"
    assert snapshot.last_block_reason == "temporarily_not_closable"
    assert snapshot.sellable_now is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_state_manager.py -q`

Expected: FAIL with `No module named 'gmtrade_live.services.m2_state_manager'`

- [ ] **Step 3: 实现 `M2StateManager`**

```python
# src/gmtrade_live/services/m2_state_manager.py
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from logging import Logger

from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    PositionSnapshot,
)


class M2StateManager:
    def __init__(self, logger: Logger | None) -> None:
        self._logger = logger
        self._cache: dict[str, DecisionPositionStateSnapshot] = {}

    def sync_positions(
        self,
        *,
        positions: tuple[PositionSnapshot, ...],
        now: datetime,
    ) -> tuple[DecisionPositionStateSnapshot, ...]:
        active_positions = tuple(position for position in positions if position.volume > 0)
        active_symbols = {position.symbol for position in active_positions}
        next_cache: dict[str, DecisionPositionStateSnapshot] = {}

        for position in active_positions:
            current = self._cache.get(position.symbol)
            if current is None:
                next_cache[position.symbol] = DecisionPositionStateSnapshot(
                    symbol=position.symbol,
                    lifecycle_state=DecisionLifecycleState.watching,
                    has_position=True,
                    sellable_now=position.available_volume > 0,
                    volume=position.volume,
                    available_volume=position.available_volume,
                    first_seen_at=now,
                    last_seen_at=now,
                    disappeared_at=None,
                    tombstone_rounds=0,
                    last_trigger_reason=None,
                    last_block_reason=None,
                    last_decision_at=now,
                )
                continue

            next_cache[position.symbol] = replace(
                current,
                lifecycle_state=DecisionLifecycleState.watching,
                has_position=True,
                sellable_now=position.available_volume > 0,
                volume=position.volume,
                available_volume=position.available_volume,
                last_seen_at=now,
                disappeared_at=None,
                tombstone_rounds=0,
            )

        for symbol, snapshot in self._cache.items():
            if symbol in active_symbols:
                continue
            if snapshot.lifecycle_state is DecisionLifecycleState.tombstone:
                continue
            next_cache[symbol] = replace(
                snapshot,
                lifecycle_state=DecisionLifecycleState.tombstone,
                has_position=False,
                sellable_now=False,
                volume=0,
                available_volume=0,
                disappeared_at=now,
                tombstone_rounds=1,
            )

        self._cache = next_cache
        return self.active_states()

    def get_state(self, symbol: str) -> DecisionPositionStateSnapshot | None:
        return self._cache.get(symbol)

    def update_decision_feedback(
        self,
        symbol: str,
        *,
        trigger_reason: str | None,
        block_reason: str | None,
        volume: int,
        available_volume: int,
        sellable_now: bool,
        decision_time: datetime,
    ) -> DecisionPositionStateSnapshot:
        current = self._cache[symbol]
        updated = replace(
            current,
            sellable_now=sellable_now,
            volume=volume,
            available_volume=available_volume,
            last_trigger_reason=trigger_reason,
            last_block_reason=block_reason,
            last_decision_at=decision_time,
        )
        self._cache[symbol] = updated
        return updated

    def active_states(self) -> tuple[DecisionPositionStateSnapshot, ...]:
        return tuple(sorted(self._cache.values(), key=lambda item: item.symbol))
```

- [ ] **Step 4: 运行测试验证通过**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_state_manager.py -q`

Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add src/gmtrade_live/services/m2_state_manager.py tests/unit/test_m2_state_manager.py
git commit -m "feat(m2): add decision state manager"
```

---

## Task 3: 实现 `M2DecisionEngine`

**Files:**
- Create: `src/gmtrade_live/services/m2_decision_engine.py`
- Create: `tests/unit/test_m2_decision_engine.py`

- [ ] **Step 1: 写 `M2DecisionEngine` 的失败测试**

```python
# tests/unit/test_m2_decision_engine.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.services.m2_decision_engine import M2DecisionEngine
from gmtrade_live.session import TradingSessionState


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config() -> AppConfig:
    from pathlib import Path

    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m2",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        trade_session_start="09:30:00",
        trade_session_end="15:00:00",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


def _state(symbol: str) -> DecisionPositionStateSnapshot:
    return DecisionPositionStateSnapshot(
        symbol=symbol,
        lifecycle_state=DecisionLifecycleState.watching,
        has_position=True,
        sellable_now=True,
        volume=100,
        available_volume=100,
        first_seen_at=_now(),
        last_seen_at=_now(),
        disappeared_at=None,
        tombstone_rounds=0,
        last_trigger_reason=None,
        last_block_reason=None,
        last_decision_at=_now(),
    )


def _position(symbol: str, *, available_volume: int = 100) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        exchange=symbol.split(".", maxsplit=1)[0],
        volume=100,
        available_volume=available_volume,
        cost_price=Decimal("10.00"),
        last_update_time=_now(),
    )


def _quote(symbol: str, price: str) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        last_price=Decimal(price),
        quote_time=_now(),
        source="fake",
    )


def test_evaluate_take_profit_allows_submit_in_trading_session() -> None:
    engine = M2DecisionEngine()

    result = engine.evaluate(
        position=_position("SHSE.600036"),
        quote=_quote("SHSE.600036", "10.80"),
        session_state=TradingSessionState.TRADING,
        state_snapshot=_state("SHSE.600036"),
        config=_config(),
        now=_now(),
    )

    assert result.should_sell is True
    assert result.can_submit_sell is True
    assert result.trigger_reason == "take_profit_triggered"
    assert result.block_reason is None


def test_evaluate_stop_loss_blocks_when_not_sellable() -> None:
    engine = M2DecisionEngine()

    result = engine.evaluate(
        position=_position("SHSE.600036", available_volume=0),
        quote=_quote("SHSE.600036", "9.60"),
        session_state=TradingSessionState.TRADING,
        state_snapshot=_state("SHSE.600036"),
        config=_config(),
        now=_now(),
    )

    assert result.should_sell is True
    assert result.can_submit_sell is False
    assert result.trigger_reason == "stop_loss_triggered"
    assert result.block_reason == "temporarily_not_closable"


def test_evaluate_returns_quote_missing_when_quote_is_none() -> None:
    engine = M2DecisionEngine()

    result = engine.evaluate(
        position=_position("SHSE.600036"),
        quote=None,
        session_state=TradingSessionState.TRADING,
        state_snapshot=_state("SHSE.600036"),
        config=_config(),
        now=_now(),
    )

    assert result.should_sell is False
    assert result.can_submit_sell is False
    assert result.trigger_reason is None
    assert result.block_reason == "quote_missing"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_decision_engine.py -q`

Expected: FAIL with `No module named 'gmtrade_live.services.m2_decision_engine'`

- [ ] **Step 3: 实现 `M2DecisionEngine`**

```python
# src/gmtrade_live/services/m2_decision_engine.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    DecisionPositionStateSnapshot,
    DecisionResult,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.precision import normalize_price
from gmtrade_live.session import TradingSessionState


class M2DecisionEngine:
    def evaluate(
        self,
        *,
        position: PositionSnapshot,
        quote: QuoteSnapshot | None,
        session_state: TradingSessionState,
        state_snapshot: DecisionPositionStateSnapshot,
        config: AppConfig,
        now: datetime,
    ) -> DecisionResult:
        cost_price = normalize_price(position.cost_price)
        take_profit_price = normalize_price(
            cost_price * (Decimal("1") + config.take_profit_ratio)
        )
        stop_loss_price = normalize_price(
            cost_price * (Decimal("1") - config.stop_loss_ratio)
        )

        if quote is None:
            return DecisionResult(
                symbol=position.symbol,
                should_sell=False,
                can_submit_sell=False,
                trigger_reason=None,
                block_reason="quote_missing",
                current_price=Decimal("0"),
                cost_price=cost_price,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                volume=position.volume,
                available_volume=position.available_volume,
                sellable_now=position.available_volume > 0,
                session_state=session_state.value,
                evaluated_at=now,
            )

        current_price = normalize_price(quote.last_price)
        should_sell = False
        trigger_reason: str | None = None

        if current_price >= take_profit_price:
            should_sell = True
            trigger_reason = "take_profit_triggered"
        elif current_price <= stop_loss_price:
            should_sell = True
            trigger_reason = "stop_loss_triggered"

        sellable_now = position.available_volume > 0
        can_submit_sell = False
        block_reason: str | None = None

        if not should_sell:
            block_reason = "price_not_reached"
        elif session_state is not TradingSessionState.TRADING:
            block_reason = "not_in_trading_session"
        elif not sellable_now:
            block_reason = "temporarily_not_closable"
        else:
            can_submit_sell = True

        return DecisionResult(
            symbol=position.symbol,
            should_sell=should_sell,
            can_submit_sell=can_submit_sell,
            trigger_reason=trigger_reason,
            block_reason=block_reason,
            current_price=current_price,
            cost_price=cost_price,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            volume=position.volume,
            available_volume=position.available_volume,
            sellable_now=sellable_now,
            session_state=session_state.value,
            evaluated_at=now,
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_decision_engine.py -q`

Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add src/gmtrade_live/services/m2_decision_engine.py tests/unit/test_m2_decision_engine.py
git commit -m "feat(m2): add decision engine"
```

---

## Task 4: 实现 `M2DryRunService`

**Files:**
- Create: `src/gmtrade_live/services/m2_dry_run.py`
- Create: `tests/unit/test_m2_dry_run.py`
- Create: `tests/integration/test_m2_dry_run.py`

- [ ] **Step 1: 写 `M2DryRunService` 的失败测试**

```python
# tests/unit/test_m2_dry_run.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import PositionSnapshot, QuoteSnapshot
from gmtrade_live.services.m2_decision_engine import M2DecisionEngine
from gmtrade_live.services.m2_dry_run import M2DryRunService
from gmtrade_live.services.m2_state_manager import M2StateManager


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 20, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m2",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        trade_session_start="09:30:00",
        trade_session_end="15:00:00",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


class FakeTradeGateway:
    def __init__(self, positions: tuple[PositionSnapshot, ...]) -> None:
        self.positions = positions

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return list(self.positions)


class FakeMarketGateway:
    def __init__(self, quotes: tuple[QuoteSnapshot, ...]) -> None:
        self.quotes = quotes
        self.last_symbols: list[str] = []

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        self.last_symbols = list(symbols)
        return [quote for quote in self.quotes if quote.symbol in symbols]


def _position(symbol: str, *, volume: int) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        exchange=symbol.split(".", maxsplit=1)[0],
        volume=volume,
        available_volume=volume,
        cost_price=Decimal("10.00"),
        last_update_time=_now(),
    )


def _quote(symbol: str, price: str) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        last_price=Decimal(price),
        quote_time=_now(),
        source="fake",
    )


def test_run_round_queries_quotes_for_volume_positions_only() -> None:
    trade_gateway = FakeTradeGateway(
        (
            _position("SHSE.600036", volume=100),
            _position("SZSE.000001", volume=0),
        )
    )
    market_gateway = FakeMarketGateway((_quote("SHSE.600036", "10.80"),))
    service = M2DryRunService(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        state_manager=M2StateManager(logging.getLogger("test")),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(), round_no=1)

    assert market_gateway.last_symbols == ["SHSE.600036"]
    assert report.summary.position_count == 1
    assert report.summary.should_sell_count == 1


def test_run_round_skips_quote_query_without_positions() -> None:
    trade_gateway = FakeTradeGateway(())
    market_gateway = FakeMarketGateway(())
    service = M2DryRunService(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        state_manager=M2StateManager(logging.getLogger("test")),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(), round_no=1)

    assert market_gateway.last_symbols == []
    assert report.summary.position_count == 0
    assert report.summary.changed_symbol_count == 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_dry_run.py -q`

Expected: FAIL with `No module named 'gmtrade_live.services.m2_dry_run'`

- [ ] **Step 3: 实现 `M2DryRunService`**

```python
# src/gmtrade_live/services/m2_dry_run.py
from __future__ import annotations

from datetime import datetime
from time import perf_counter
import logging
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    DecisionLifecycleState,
    EvaluatedSymbol,
    M2ChangeEvent,
    M2RoundReport,
    M2RoundSummary,
)
from gmtrade_live.session import resolve_trading_session


class M2DryRunService:
    def __init__(
        self,
        *,
        trade_gateway,
        market_gateway,
        state_manager,
        decision_engine,
        logger: logging.Logger,
        clock=None,
        timer=None,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._state_manager = state_manager
        self._decision_engine = decision_engine
        self._logger = logger
        self._clock = clock or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self._timer = timer or perf_counter
        self._last_decisions: dict[str, object] = {}

    def run_round(self, *, config: AppConfig, round_no: int) -> M2RoundReport:
        started_at = self._timer()
        now = self._clock()
        session_state = resolve_trading_session(
            now,
            start_text=config.trade_session_start,
            end_text=config.trade_session_end,
            timezone_name=config.timezone,
        )

        positions = tuple(
            position
            for position in self._trade_gateway.get_positions(config.account_id)
            if position.volume > 0
        )
        before_states = {state.symbol: state for state in self._state_manager.active_states()}
        self._state_manager.sync_positions(positions=positions, now=now)
        active_states = {state.symbol: state for state in self._state_manager.active_states()}

        symbols = [position.symbol for position in positions]
        quotes = tuple(self._market_gateway.get_quotes(symbols)) if symbols else ()
        quote_map = {quote.symbol: quote for quote in quotes}

        change_events: list[M2ChangeEvent] = []
        evaluated_symbols: list[EvaluatedSymbol] = []

        for symbol, snapshot in active_states.items():
            previous = before_states.get(symbol)
            if previous is None:
                change_events.append(
                    M2ChangeEvent(
                        symbol=symbol,
                        change_tags=("symbol_started_watching",),
                        decision=None,
                        state_snapshot=snapshot,
                    )
                )
            elif (
                previous.lifecycle_state is not DecisionLifecycleState.tombstone
                and snapshot.lifecycle_state is DecisionLifecycleState.tombstone
            ):
                change_events.append(
                    M2ChangeEvent(
                        symbol=symbol,
                        change_tags=("entered_tombstone",),
                        decision=None,
                        state_snapshot=snapshot,
                    )
                )

        for position in positions:
            state_snapshot = active_states[position.symbol]
            decision = self._decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=state_snapshot,
                config=config,
                now=now,
            )
            updated_state = self._state_manager.update_decision_feedback(
                position.symbol,
                trigger_reason=decision.trigger_reason,
                block_reason=decision.block_reason,
                volume=decision.volume,
                available_volume=decision.available_volume,
                sellable_now=decision.sellable_now,
                decision_time=decision.evaluated_at,
            )
            evaluated = EvaluatedSymbol(decision=decision, state_snapshot=updated_state)
            evaluated_symbols.append(evaluated)

            previous_decision = self._last_decisions.get(position.symbol)
            change_tags: list[str] = []
            if previous_decision is None and decision.should_sell:
                change_tags.append("trigger_activated")
            elif previous_decision is not None and previous_decision.should_sell != decision.should_sell:
                change_tags.append("trigger_activated" if decision.should_sell else "trigger_cleared")
            if previous_decision is not None and previous_decision.can_submit_sell != decision.can_submit_sell:
                change_tags.append(
                    "submit_permission_granted"
                    if decision.can_submit_sell
                    else "submit_permission_blocked"
                )
            if previous_decision is not None and previous_decision.block_reason != decision.block_reason:
                if decision.block_reason == "quote_missing":
                    change_tags.append("quote_missing_detected")
                elif previous_decision.block_reason == "quote_missing":
                    change_tags.append("quote_missing_recovered")
            if change_tags:
                change_events.append(
                    M2ChangeEvent(
                        symbol=position.symbol,
                        change_tags=tuple(change_tags),
                        decision=decision,
                        state_snapshot=updated_state,
                    )
                )
            self._last_decisions[position.symbol] = decision

        tombstones = tuple(
            state
            for state in self._state_manager.active_states()
            if state.lifecycle_state is DecisionLifecycleState.tombstone
        )
        duration_ms = int((self._timer() - started_at) * 1000)
        return M2RoundReport(
            summary=M2RoundSummary(
                round_no=round_no,
                session_state=session_state.value,
                position_count=len(positions),
                watching_count=len(evaluated_symbols),
                tombstone_count=len(tombstones),
                should_sell_count=sum(1 for item in evaluated_symbols if item.decision.should_sell),
                can_submit_sell_count=sum(1 for item in evaluated_symbols if item.decision.can_submit_sell),
                changed_symbol_count=len({event.symbol for event in change_events}),
                duration_ms=duration_ms,
            ),
            evaluated_symbols=tuple(evaluated_symbols),
            tombstones=tombstones,
            change_events=tuple(change_events),
        )
```

- [ ] **Step 4: 加一条假网关集成测试，覆盖墓碑与变化输出**

```python
# tests/integration/test_m2_dry_run.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import PositionSnapshot, QuoteSnapshot
from gmtrade_live.services.m2_decision_engine import M2DecisionEngine
from gmtrade_live.services.m2_dry_run import M2DryRunService
from gmtrade_live.services.m2_state_manager import M2StateManager


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m2",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        trade_session_start="09:30:00",
        trade_session_end="15:00:00",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


class SequencedTradeGateway:
    def __init__(self, rounds: list[tuple[PositionSnapshot, ...]]) -> None:
        self._rounds = rounds
        self._index = 0

    def get_positions(self, account_id: str):
        value = self._rounds[min(self._index, len(self._rounds) - 1)]
        self._index += 1
        return list(value)


class SequencedMarketGateway:
    def __init__(self, quotes: dict[str, QuoteSnapshot]) -> None:
        self._quotes = quotes

    def get_quotes(self, symbols: list[str]):
        return [self._quotes[symbol] for symbol in symbols if symbol in self._quotes]


def _position(symbol: str, volume: int) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        exchange=symbol.split(".", maxsplit=1)[0],
        volume=volume,
        available_volume=volume,
        cost_price=Decimal("10.00"),
        last_update_time=_now(),
    )


def _quote(symbol: str, price: str) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        last_price=Decimal(price),
        quote_time=_now(),
        source="fake",
    )


def test_m2_dry_run_service_emits_tombstone_on_disappeared_position() -> None:
    service = M2DryRunService(
        trade_gateway=SequencedTradeGateway(
            [
                (_position("SHSE.600036", 100),),
                (),
            ]
        ),
        market_gateway=SequencedMarketGateway({"SHSE.600036": _quote("SHSE.600036", "10.80")}),
        state_manager=M2StateManager(logging.getLogger("test")),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    service.run_round(config=_config(), round_no=1)
    second = service.run_round(config=_config(), round_no=2)

    assert second.summary.tombstone_count == 1
    assert second.change_events[0].change_tags == ("entered_tombstone",)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_dry_run.py tests/integration/test_m2_dry_run.py -q`

Expected: `3 passed`

- [ ] **Step 6: 提交**

```bash
git add src/gmtrade_live/services/m2_dry_run.py tests/unit/test_m2_dry_run.py tests/integration/test_m2_dry_run.py
git commit -m "feat(m2): add dry-run orchestration service"
```

---

## Task 5: 扩展 CLI 与 Bootstrap

**Files:**
- Modify: `main.py`
- Modify: `src/gmtrade_live/bootstrap.py`
- Modify: `tests/unit/test_main.py`
- Modify: `tests/unit/test_bootstrap.py`

- [ ] **Step 1: 先写 CLI 与 Bootstrap 的失败测试**

```python
# tests/unit/test_main.py (追加)
def test_parse_cli_args_accepts_m2_once_mode() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m2",
            "--once",
        ]
    )

    assert args.mode == "m2"
    assert args.once is True
    assert args.max_rounds is None


def test_parse_cli_args_rejects_once_outside_m2() -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--once",
            ]
        )


def test_main_dispatches_to_m2(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_m2_dry_run(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    bootstrap = SimpleNamespace(
        run_m0_connectivity_check=lambda config_path: 1,
        run_m1_manual_trade=lambda **kwargs: 1,
        run_m2_dry_run=_run_m2_dry_run,
    )

    monkeypatch.setitem(sys.modules, "gmtrade_live.bootstrap", bootstrap)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--config", "config/sim_account.yaml", "--mode", "m2", "--max-rounds", "3"],
    )

    assert main.main() == 0
    assert captured["config_path"] == Path("config/sim_account.yaml")
    assert captured["once"] is False
    assert captured["max_rounds"] == 3
```

```python
# tests/unit/test_bootstrap.py (追加)
def test_run_m2_dry_run_prints_summary_and_change_details(monkeypatch, capsys) -> None:
    config = _fake_config()
    summary = SimpleNamespace(
        round_no=1,
        session_state="trading",
        position_count=1,
        watching_count=1,
        tombstone_count=0,
        should_sell_count=1,
        can_submit_sell_count=1,
        changed_symbol_count=1,
        duration_ms=8,
    )
    change = SimpleNamespace(
        symbol="SHSE.600036",
        change_tags=("trigger_activated",),
        decision=SimpleNamespace(
            should_sell=True,
            can_submit_sell=True,
            trigger_reason="take_profit_triggered",
            block_reason=None,
            current_price=Decimal("10.80"),
            session_state="trading",
            evaluated_at=datetime(2026, 4, 9, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        ),
        state_snapshot=SimpleNamespace(
            lifecycle_state="watching",
            volume=100,
            available_volume=100,
            sellable_now=True,
        ),
    )
    report = SimpleNamespace(summary=summary, change_events=(change,))

    class FakeGateway:
        def connect(self, *args, **kwargs) -> None:
            return None

    class FakeService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run_round(self, **kwargs):
            return report

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(
        bootstrap,
        "setup_logging",
        lambda *args, **kwargs: SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(bootstrap, "GMTradeQueryGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "M2StateManager", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M2DecisionEngine", lambda: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M2DryRunService", FakeService)

    exit_code = bootstrap.run_m2_dry_run(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert exit_code == 0
    assert '"kind": "m2_round_summary"' in lines[0]
    assert '"kind": "m2_change_detail"' in lines[1]
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py -q`

Expected: FAIL with `invalid choice: 'm2'` and `module 'gmtrade_live.bootstrap' has no attribute 'run_m2_dry_run'`

- [ ] **Step 3: 扩展 `main.py` 的 M2 参数和 dispatch**

```python
# main.py
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GMTrade connectivity, M1 manual trade, and M2 decision dry-run"
    )
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--mode", choices=("m0", "m1", "m2"), default="m0")
    parser.add_argument("--symbol")
    parser.add_argument("--volume", type=_parse_positive_int)
    parser.add_argument("--price-type", choices=("market", "limit"))
    parser.add_argument("--price", type=_parse_positive_decimal)
    parser.add_argument("--timeout-seconds", type=_parse_positive_int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-rounds", type=_parse_positive_int)
    return parser


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "m1":
        if not args.symbol:
            parser.error("--mode m1 时必须提供 --symbol")
        if args.volume is None:
            parser.error("--mode m1 时必须提供 --volume")
        if not args.price_type:
            parser.error("--mode m1 时必须提供 --price-type")
        if args.price_type == "limit" and args.price is None:
            parser.error("--price-type limit 时必须提供 --price")
        if args.price_type == "market" and args.price is not None:
            parser.error("--price-type market 时不能提供 --price")
    if args.mode != "m2" and (args.once or args.max_rounds is not None):
        parser.error("--once 和 --max-rounds 仅支持 --mode m2")
    if args.mode == "m2" and args.once and args.max_rounds is not None:
        parser.error("--once 和 --max-rounds 不能同时使用")
    return args


def main() -> int:
    args = parse_cli_args()
    from gmtrade_live.bootstrap import (
        run_m0_connectivity_check,
        run_m1_manual_trade,
        run_m2_dry_run,
    )

    config_path = Path(args.config)
    if args.mode == "m1":
        return run_m1_manual_trade(
            config_path=config_path,
            symbol=args.symbol,
            volume=args.volume,
            price_type=args.price_type,
            price=args.price,
            timeout_seconds=args.timeout_seconds,
        )
    if args.mode == "m2":
        return run_m2_dry_run(
            config_path=config_path,
            once=args.once,
            max_rounds=args.max_rounds,
        )
    return run_m0_connectivity_check(config_path)
```

- [ ] **Step 4: 在 `bootstrap.py` 中实现 `run_m2_dry_run()`**

```python
# src/gmtrade_live/bootstrap.py
import time

from gmtrade_live.services.m2_decision_engine import M2DecisionEngine
from gmtrade_live.services.m2_dry_run import M2DryRunService
from gmtrade_live.services.m2_state_manager import M2StateManager


def run_m2_dry_run(
    *,
    config_path: Path,
    once: bool,
    max_rounds: int | None,
) -> int:
    config = load_config(config_path)
    logger = setup_logging(config.strategy_name, config.log_dir)
    trade_gateway = GMTradeQueryGateway()
    market_gateway = GMCurrentQuoteGateway()

    trade_gateway.connect(config)
    market_gateway.connect(config.token)

    service = M2DryRunService(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        state_manager=M2StateManager(logger),
        decision_engine=M2DecisionEngine(),
        logger=logger,
    )

    round_no = 1
    while True:
        report = service.run_round(config=config, round_no=round_no)
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
            payload = {
                "kind": "m2_change_detail",
                "symbol": event.symbol,
                "change_tags": list(event.change_tags),
                "lifecycle_state": (
                    event.state_snapshot.lifecycle_state.value
                    if event.state_snapshot is not None
                    else None
                ),
                "volume": (
                    event.state_snapshot.volume
                    if event.state_snapshot is not None
                    else None
                ),
                "available_volume": (
                    event.state_snapshot.available_volume
                    if event.state_snapshot is not None
                    else None
                ),
                "sellable_now": (
                    event.state_snapshot.sellable_now
                    if event.state_snapshot is not None
                    else None
                ),
            }
            if event.decision is not None:
                payload.update(
                    {
                        "should_sell": event.decision.should_sell,
                        "can_submit_sell": event.decision.can_submit_sell,
                        "trigger_reason": event.decision.trigger_reason,
                        "block_reason": event.decision.block_reason,
                        "current_price": str(event.decision.current_price),
                        "session_state": event.decision.session_state,
                        "evaluated_at": event.decision.evaluated_at.isoformat(),
                    }
                )
            print(json.dumps(payload, ensure_ascii=False))

        if once or (max_rounds is not None and round_no >= max_rounds):
            return 0
        if report.summary.duration_ms > config.poll_interval_seconds * 1000:
            logger.warning(
                "round_overrun round=%s duration_ms=%s interval_seconds=%s",
                round_no,
                report.summary.duration_ms,
                config.poll_interval_seconds,
            )
        time.sleep(config.poll_interval_seconds)
        round_no += 1
```

- [ ] **Step 5: 运行测试验证通过**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py -q`

Expected: PASS with M0/M1 tests still green

- [ ] **Step 6: 提交**

```bash
git add main.py src/gmtrade_live/bootstrap.py tests/unit/test_main.py tests/unit/test_bootstrap.py
git commit -m "feat(m2): expose dry-run cli mode"
```

---

## Task 6: 文档补充与总验收

**Files:**
- Modify: `AGENTS.md`
- Verify: `tests/unit/test_m2_models.py`
- Verify: `tests/unit/test_m2_state_manager.py`
- Verify: `tests/unit/test_m2_decision_engine.py`
- Verify: `tests/unit/test_m2_dry_run.py`
- Verify: `tests/integration/test_m2_dry_run.py`
- Verify: `tests/unit/test_main.py`
- Verify: `tests/unit/test_bootstrap.py`
- Verify: `tests/unit/test_official_gateways.py`

- [ ] **Step 1: 补充 `AGENTS.md` 的 M2 命令说明**

````markdown
## 开发命令

### 安装与运行
```bash
# M2 决策 dry-run（单轮）
python main.py --config config/sim_account.yaml --mode m2 --once

# M2 决策 dry-run（连续 3 轮）
python main.py --config config/sim_account.yaml --mode m2 --max-rounds 3
```
````

- [ ] **Step 2: 运行 M2 相关测试**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit/test_m2_models.py tests/unit/test_m2_state_manager.py tests/unit/test_m2_decision_engine.py tests/unit/test_m2_dry_run.py tests/integration/test_m2_dry_run.py -q`

Expected: PASS

- [ ] **Step 3: 运行主测试集确认无回归**

Run: `conda run --no-capture-output -n stock_analysis pytest tests/unit tests/integration -q`

Expected: PASS, 且 M0/M1 相关测试不回退

- [ ] **Step 4: 手工冒烟验证 CLI**

Run: `conda run --no-capture-output -n stock_analysis python main.py --config config/sim_account.yaml --mode m2 --once`

Expected: 至少输出一行 `kind = "m2_round_summary"` 的 JSON；若存在变化标的，则额外输出 `kind = "m2_change_detail"` 的 JSON

- [ ] **Step 5: 提交**

```bash
git add AGENTS.md
git commit -m "docs(m2): add dry-run command examples"
```

---

## Self-Review Checklist

Spec 覆盖确认：
- `volume > 0` 全量评估：Task 2 + Task 4
- `should_sell / can_submit_sell` 分离：Task 3
- `trigger_reason / block_reason` 分离：Task 3
- 一轮墓碑态：Task 2 + Task 4
- 连续 dry-run：Task 4 + Task 5
- `--mode m2` CLI：Task 5
- 摘要与变化详情输出：Task 4 + Task 5
- M3 执行态隔离：Task 2 不复用 `state.py`
- 输出契约可供后续状态机或状态表消费：Task 1 + Task 4 + Task 5

占位符扫描：
- 无 `TODO` / `TBD`
- 所有实现步骤都包含目标代码或命令
- 所有测试步骤都包含可执行命令和预期结果

类型一致性：
- 生命周期类型统一为 `DecisionLifecycleState`
- dry-run 编排输出统一为 `M2RoundReport`
- 变化输出统一走 `M2ChangeEvent`
- CLI 输出仅为内部契约投影，不另起第二套语义

---

## Execution Complete

M2 implementation plan 已完整覆盖：
- 决策态模型
- 状态管理器
- 决策引擎
- dry-run 编排服务
- CLI / Bootstrap 接入
- 文档补充与总验收

关键约束：
1. 只评估 `volume > 0` 的持仓，但允许 `available_volume = 0`
2. `should_sell` 与 `can_submit_sell` 严格分离
3. `trigger_reason` 与 `block_reason` 严格分离
4. 一轮墓碑态后删除
5. 只查询持仓标的行情
6. 不引入执行态、防重复卖单和数据库
