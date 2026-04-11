# M3 自动卖出执行闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `--mode m3` 自动卖出执行闭环，在显式运行时复用 `M2DecisionEngine` 完成连续卖出、查询驱动收口、防重复卖单和结构化 CLI 输出，并保持当前 `market_session_mode` / gateway / M2 契约不回退。

**Architecture:** M3 继续复用现有 `GMTradeGateway`、`GMCurrentQuoteGateway`、`M2DecisionEngine` 和 `resolve_trading_session()`。`state.py` 收敛为纯执行态，查询结果先规范化为内部执行事件，再驱动执行态聚合与 `M3RoundReport` 输出；按当前 M3 范围收紧实现，自动卖出请求固定为 `side="sell"` 且 `price_type="market"`，不引入额外自动报价配置。

**Tech Stack:** Python 3.10+, pytest, stdlib `argparse/json/logging/time/zoneinfo/dataclasses`, `Decimal`, 现有 `GMTradeGateway`, `GMCurrentQuoteGateway`, `M2DecisionEngine`, `market_session_mode`, `PositionStateManager`

---

## Planned File Structure

**New files:**
- `src/gmtrade_live/services/m3_quantity_rules.py` - M3 卖量规划与市场规则归整
- `src/gmtrade_live/services/m3_execution_service.py` - M3 单轮执行编排、内部执行事件和查询驱动收口
- `tests/unit/test_m3_models.py` - M3 报告模型与卖量模型单测
- `tests/unit/test_m3_quantity_rules.py` - M3 卖量规则单测
- `tests/unit/test_m3_execution_service.py` - M3 执行服务单测
- `tests/integration/test_m3_execution_integration.py` - M3 假网关集成测试

**Modified files:**
- `src/gmtrade_live/config.py` - 新增 `sell_quantity_ratio` 配置字段与范围校验
- `src/gmtrade_live/models.py` - 新增 M3 报告模型与卖量规划模型
- `src/gmtrade_live/state.py` - 去掉旧触发态语义，收敛为纯执行态
- `src/gmtrade_live/bootstrap.py` - 新增 `run_m3_execution()`
- `main.py` - 新增 `--mode m3` 与 `m3` 专属参数注册
- `config/sim_account.example.yaml` - 补充 `sell_quantity_ratio`
- `AGENTS.md` - 补充 M3 运行示例
- `tests/unit/test_config.py` - 配置加载和范围校验测试
- `tests/unit/test_main.py` - M3 CLI 参数和 dispatch 测试
- `tests/unit/test_bootstrap.py` - M3 JSON 投影和异常出口测试
- `tests/unit/test_state.py` - 执行态字段与 open-order 语义测试
- `tests/unit/test_m1_manual_trade.py` - `AppConfig` 构造补齐新字段
- `tests/unit/test_m2_decision_engine.py` - `AppConfig` 构造补齐新字段
- `tests/unit/test_m2_dry_run.py` - `AppConfig` 构造补齐新字段
- `tests/unit/test_official_gateways.py` - `AppConfig` 构造补齐新字段
- `tests/integration/test_m0_connectivity_service.py` - `AppConfig` 构造补齐新字段
- `tests/integration/test_m1_manual_trade_service.py` - `AppConfig` 构造补齐新字段
- `tests/integration/test_m2_dry_run_integration.py` - `AppConfig` 构造补齐新字段

## Scope Guard

M3 只做：

- 显式 `--mode m3` 自动卖出
- 复用 `M2DecisionEngine` 的卖出判断结果
- 基于 `position.volume` 的卖量计算、odd-lot 整仓提升和市场规则归整
- 提交前 `available_volume` 校验
- 查询驱动收口
- 逐标的执行态管理
- 结构化 CLI / 日志输出

M3 不做：

- 自动买入
- callback 驱动主闭环
- 数据库持久化
- 多账户或多策略并发
- 自动价格策略配置扩展
- “整可用仓位卖出”规则

补充约束：

- 当前项目继续以 `market_session_mode` 为唯一交易时段配置，不重新引入 `trade_session_start` / `trade_session_end`
- `sell_quantity_ratio` 没有默认值，且必须满足 `0 < sell_quantity_ratio <= 1`
- `state.py` 只维护执行态，不再承载 M2 的 `triggered` 语义
- M3 自动下单请求固定为 `side="sell"`、`price_type="market"`、`price=None`，当前不扩展限价或自动报价配置
- 当前存在未完成卖单时，M3 只能跟踪，不能重复发单
- `bootstrap.run_m3_execution()` 对未处理的轮次异常直接输出 `m3_round_error` 并返回非零，避免真实执行链路在不确定状态下继续运行

---

## Task 1: 扩展配置契约并补齐所有 `AppConfig` 构造

**Files:**
- Modify: `src/gmtrade_live/config.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/test_m1_manual_trade.py`
- Modify: `tests/unit/test_m2_decision_engine.py`
- Modify: `tests/unit/test_m2_dry_run.py`
- Modify: `tests/unit/test_official_gateways.py`
- Modify: `tests/integration/test_m0_connectivity_service.py`
- Modify: `tests/integration/test_m1_manual_trade_service.py`
- Modify: `tests/integration/test_m2_dry_run_integration.py`

- [ ] **Step 1: 先写配置失败测试**

```python
# tests/unit/test_config.py
def test_load_config_reads_sell_quantity_ratio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GM_ACCOUNT_ID", "demo-account")
    monkeypatch.setenv("GM_TOKEN", "demo-token")

    config_file = tmp_path / "sim_account.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: ${GM_ACCOUNT_ID}",
                "token: ${GM_TOKEN}",
                "strategy_name: gmtrade-live-m0",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "sell_quantity_ratio: '1.0'",
                "market_session_mode: a_share",
                "log_dir: logs",
                "timezone: Asia/Shanghai",
                "gmtrade_endpoint: 127.0.0.1:7001",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.sell_quantity_ratio == Decimal("1.0")


def test_load_config_rejects_missing_sell_quantity_ratio(tmp_path: Path) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: demo-account",
                "token: demo-token",
                "strategy_name: gmtrade-live-m0",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "market_session_mode: a_share",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    assert exc_info.value.code == "config.missing_field"


def test_load_config_rejects_sell_quantity_ratio_above_one(tmp_path: Path) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: demo-account",
                "token: demo-token",
                "strategy_name: gmtrade-live-m0",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "sell_quantity_ratio: '1.2'",
                "market_session_mode: a_share",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    assert exc_info.value.code == "config.invalid_sell_quantity_ratio"
```

- [ ] **Step 2: 运行配置测试，确认因缺少字段实现而失败**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_config.py -q
```

Expected:

```text
FAIL tests/unit/test_config.py::test_load_config_reads_sell_quantity_ratio
FAIL tests/unit/test_config.py::test_load_config_rejects_missing_sell_quantity_ratio
FAIL tests/unit/test_config.py::test_load_config_rejects_sell_quantity_ratio_above_one
```

- [ ] **Step 3: 最小实现配置字段和范围校验，并补齐所有 `AppConfig(...)` 构造**

```python
# src/gmtrade_live/config.py
@dataclass(frozen=True, slots=True)
class AppConfig:
    """应用运行所需的只读配置快照。"""

    account_id: str
    token: str
    strategy_name: str
    poll_interval_seconds: int
    take_profit_ratio: Decimal
    stop_loss_ratio: Decimal
    sell_quantity_ratio: Decimal
    market_session_mode: str
    log_dir: Path
    timezone: str
    gmtrade_endpoint: str


_REQUIRED_FIELDS = (
    "account_id",
    "token",
    "strategy_name",
    "poll_interval_seconds",
    "take_profit_ratio",
    "stop_loss_ratio",
    "sell_quantity_ratio",
    "market_session_mode",
    "log_dir",
)


def _parse_sell_quantity_ratio(value: Any, field_name: str) -> Decimal:
    """解析 M3 每轮卖出比例，并把范围限制收口在配置层。"""
    result = _parse_decimal(value, field_name)
    if result > Decimal("1"):
        _raise(
            "config.invalid_sell_quantity_ratio",
            f"字段 {field_name} 必须小于等于 1",
            context={"field": field_name, "value": str(value)},
        )
    return result


return AppConfig(
    account_id=str(resolved["account_id"]),
    token=str(resolved["token"]),
    strategy_name=str(resolved["strategy_name"]),
    poll_interval_seconds=_parse_positive_int(
        resolved["poll_interval_seconds"],
        "poll_interval_seconds",
    ),
    take_profit_ratio=_parse_decimal(
        resolved["take_profit_ratio"],
        "take_profit_ratio",
    ),
    stop_loss_ratio=_parse_decimal(
        resolved["stop_loss_ratio"],
        "stop_loss_ratio",
    ),
    sell_quantity_ratio=_parse_sell_quantity_ratio(
        resolved["sell_quantity_ratio"],
        "sell_quantity_ratio",
    ),
    market_session_mode=_parse_market_session_mode(
        resolved["market_session_mode"],
        "market_session_mode",
    ),
    log_dir=Path(str(resolved["log_dir"])),
    timezone=str(resolved.get("timezone", "Asia/Shanghai")),
    gmtrade_endpoint=str(resolved.get("gmtrade_endpoint", "127.0.0.1:7001")),
)
```

```python
# 以下每个测试文件里的 AppConfig(...) 构造都加同一行
sell_quantity_ratio=Decimal("1.0"),
```

- [ ] **Step 4: 运行配置和受影响测试，确认新字段没有破坏现有基线**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_config.py tests/unit/test_m1_manual_trade.py tests/unit/test_m2_decision_engine.py tests/unit/test_m2_dry_run.py tests/unit/test_official_gateways.py tests/integration/test_m0_connectivity_service.py tests/integration/test_m1_manual_trade_service.py tests/integration/test_m2_dry_run_integration.py -q
```

Expected:

```text
all selected tests PASS
```

- [ ] **Step 5: 提交配置契约改动**

```bash
git add src/gmtrade_live/config.py tests/unit/test_config.py tests/unit/test_m1_manual_trade.py tests/unit/test_m2_decision_engine.py tests/unit/test_m2_dry_run.py tests/unit/test_official_gateways.py tests/integration/test_m0_connectivity_service.py tests/integration/test_m1_manual_trade_service.py tests/integration/test_m2_dry_run_integration.py
git commit -m "feat(config): add m3 sell quantity ratio"
```

## Task 2: 增加 M3 模型与卖量规划模块

**Files:**
- Modify: `src/gmtrade_live/models.py`
- Create: `src/gmtrade_live/services/m3_quantity_rules.py`
- Create: `tests/unit/test_m3_models.py`
- Create: `tests/unit/test_m3_quantity_rules.py`

- [ ] **Step 1: 先写 M3 模型和卖量规划的失败测试**

```python
# tests/unit/test_m3_models.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import (
    M3BlockDetail,
    M3ExecutionDetail,
    M3RoundReport,
    M3RoundSummary,
    SellQuantityPlan,
)


def _now() -> datetime:
    return datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_sell_quantity_plan_carries_final_target_and_promotion_type() -> None:
    plan = SellQuantityPlan(
        symbol="SHSE.600036",
        requested_ratio=Decimal("0.804"),
        total_volume=250,
        available_volume=250,
        raw_target_volume=201,
        final_target_volume=250,
        promotion_type="full_position",
        block_reason=None,
    )

    assert plan.final_target_volume == 250
    assert plan.promotion_type == "full_position"


def test_m3_round_report_exposes_block_and_execution_details() -> None:
    report = M3RoundReport(
        summary=M3RoundSummary(
            round_no=1,
            session_state="trading",
            position_count=1,
            candidate_count=1,
            blocked_count=0,
            submitted_count=1,
            open_order_count=1,
            changed_symbol_count=1,
            duration_ms=10,
        ),
        block_details=(),
        execution_details=(
            M3ExecutionDetail(
                symbol="SHSE.600036",
                change_tags=("submit_accepted",),
                execution_state="submitted",
                cl_ord_id="CL_1",
                broker_order_id="BK_1",
                requested_volume=200,
                filled_volume=0,
                remaining_volume=200,
                submit_accepted=True,
                last_order_status="submitted",
                rejection_reason=None,
                avg_price=None,
                event_time=_now(),
                message="accepted",
            ),
        ),
    )

    assert report.summary.submitted_count == 1
    assert report.execution_details[0].cl_ord_id == "CL_1"
```

```python
# tests/unit/test_m3_quantity_rules.py
from __future__ import annotations

from decimal import Decimal

from gmtrade_live.services.m3_quantity_rules import build_sell_quantity_plan


def test_build_sell_quantity_plan_promotes_full_position_when_total_remainder_is_odd_lot() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.600036",
        total_volume=250,
        available_volume=250,
        sell_quantity_ratio=Decimal("0.804"),
    )

    assert plan.raw_target_volume == 201
    assert plan.final_target_volume == 250
    assert plan.promotion_type == "full_position"
    assert plan.block_reason is None


def test_build_sell_quantity_plan_keeps_target_when_full_position_is_not_currently_sellable() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.600036",
        total_volume=250,
        available_volume=201,
        sell_quantity_ratio=Decimal("0.80"),
    )

    assert plan.raw_target_volume == 200
    assert plan.final_target_volume == 200
    assert plan.promotion_type is None
    assert plan.block_reason is None


def test_build_sell_quantity_plan_blocks_when_final_target_exceeds_available() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.600036",
        total_volume=250,
        available_volume=201,
        sell_quantity_ratio=Decimal("1.0"),
    )

    assert plan.final_target_volume == 250
    assert plan.block_reason == "sell_quantity_exceeds_available"


def test_build_sell_quantity_plan_blocks_when_normalized_target_is_zero() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.600036",
        total_volume=250,
        available_volume=250,
        sell_quantity_ratio=Decimal("0.01"),
    )

    assert plan.final_target_volume == 0
    assert plan.block_reason == "sell_quantity_below_min_order"


def test_build_sell_quantity_plan_supports_star_market_non_multiple_of_two_hundred() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.688188",
        total_volume=10000,
        available_volume=10000,
        sell_quantity_ratio=Decimal("0.0201"),
    )

    assert plan.raw_target_volume == 201
    assert plan.final_target_volume == 201
    assert plan.block_reason is None
```

- [ ] **Step 2: 运行模型与卖量规则测试，确认当前还不存在实现**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_m3_models.py tests/unit/test_m3_quantity_rules.py -q
```

Expected:

```text
FAIL with ImportError or AttributeError for missing M3 classes/functions
```

- [ ] **Step 3: 实现 M3 模型和卖量规划**

```python
# src/gmtrade_live/models.py
@dataclass(frozen=True, slots=True)
class SellQuantityPlan:
    """单标的卖量规划结果。"""

    symbol: str
    requested_ratio: Decimal
    total_volume: int
    available_volume: int
    raw_target_volume: int
    final_target_volume: int
    promotion_type: str | None
    block_reason: str | None


@dataclass(frozen=True, slots=True)
class M3BlockDetail:
    """单标的执行前阻断详情。"""

    symbol: str
    trigger_reason: str | None
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
    """单标的执行链详情。"""

    symbol: str
    change_tags: tuple[str, ...]
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


@dataclass(frozen=True, slots=True)
class M3RoundSummary:
    """M3 单轮摘要。"""

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
class M3RoundReport:
    """M3 单轮对外稳定输出。"""

    summary: M3RoundSummary
    block_details: tuple[M3BlockDetail, ...]
    execution_details: tuple[M3ExecutionDetail, ...]
```

```python
# src/gmtrade_live/services/m3_quantity_rules.py
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from gmtrade_live.models import SellQuantityPlan


def build_sell_quantity_plan(
    *,
    symbol: str,
    total_volume: int,
    available_volume: int,
    sell_quantity_ratio: Decimal,
) -> SellQuantityPlan:
    """按“总仓比例 -> odd-lot 整仓提升 -> 市场规则归整 -> available 校验”生成卖量。"""
    raw_target_volume = int(
        (Decimal(total_volume) * sell_quantity_ratio).to_integral_value(
            rounding=ROUND_DOWN
        )
    )
    minimum_lot = _minimum_lot_for_symbol(symbol)
    raw_remaining_total = total_volume - raw_target_volume

    if 0 < raw_remaining_total < minimum_lot and total_volume <= available_volume:
        # 这里优先整仓，是为了避免留下无法再卖的总仓残量。
        final_target_volume = total_volume
        promotion_type = "full_position"
    else:
        final_target_volume = _normalize_target_volume(
            symbol=symbol,
            total_volume=total_volume,
            target_volume=raw_target_volume,
        )
        promotion_type = None

    block_reason: str | None = None
    if final_target_volume <= 0:
        block_reason = "sell_quantity_below_min_order"
    elif final_target_volume > available_volume:
        block_reason = "sell_quantity_exceeds_available"

    return SellQuantityPlan(
        symbol=symbol,
        requested_ratio=sell_quantity_ratio,
        total_volume=total_volume,
        available_volume=available_volume,
        raw_target_volume=raw_target_volume,
        final_target_volume=final_target_volume,
        promotion_type=promotion_type,
        block_reason=block_reason,
    )


def _minimum_lot_for_symbol(symbol: str) -> int:
    return 200 if _is_star_market(symbol) else 100


def _is_star_market(symbol: str) -> bool:
    return symbol.startswith("SHSE.688")


def _normalize_target_volume(*, symbol: str, total_volume: int, target_volume: int) -> int:
    if _is_star_market(symbol):
        return _normalize_star_market_sell_volume(
            total_volume=total_volume,
            target_volume=target_volume,
        )
    return _normalize_a_share_sell_volume(
        total_volume=total_volume,
        target_volume=target_volume,
    )


def _normalize_a_share_sell_volume(*, total_volume: int, target_volume: int) -> int:
    for candidate in range(target_volume, 0, -1):
        if candidate % 100 == 0:
            return candidate
        if (total_volume - candidate) % 100 == 0:
            return candidate
    return 0


def _normalize_star_market_sell_volume(*, total_volume: int, target_volume: int) -> int:
    if total_volume < 200:
        return total_volume if target_volume >= total_volume else 0
    return target_volume if target_volume >= 200 else 0
```

- [ ] **Step 4: 运行新模型和卖量规则测试**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_m3_models.py tests/unit/test_m3_quantity_rules.py -q
```

Expected:

```text
all selected tests PASS
```

- [ ] **Step 5: 提交模型与卖量规划**

```bash
git add src/gmtrade_live/models.py src/gmtrade_live/services/m3_quantity_rules.py tests/unit/test_m3_models.py tests/unit/test_m3_quantity_rules.py
git commit -m "feat(m3): add quantity planning contracts"
```

## Task 3: 收敛 `state.py` 为纯执行态

**Files:**
- Modify: `src/gmtrade_live/state.py`
- Modify: `tests/unit/test_state.py`

- [ ] **Step 1: 先写执行态字段和 open-order 语义的失败测试**

```python
# tests/unit/test_state.py
from gmtrade_live.state import PositionState, PositionStateManager


def test_state_manager_tracks_query_driven_execution_fields() -> None:
    manager = PositionStateManager(logger=None)

    manager.update_state(
        "SHSE.600036",
        PositionState.submitted,
        cl_ord_id="CL_1",
        broker_order_id="BK_1",
        trigger_reason="take_profit_triggered",
        requested_volume=200,
        filled_volume=0,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="submitted",
        rejection_reason=None,
        avg_price=None,
        message="accepted",
    )

    snapshot = manager.get_state("SHSE.600036")

    assert snapshot.cl_ord_id == "CL_1"
    assert snapshot.broker_order_id == "BK_1"
    assert snapshot.trigger_reason == "take_profit_triggered"
    assert snapshot.remaining_volume == 200
    assert snapshot.submit_accepted is True
    assert snapshot.last_order_status == "submitted"


def test_state_manager_treats_submitting_as_open_order() -> None:
    manager = PositionStateManager(logger=None)

    manager.update_state(
        "SHSE.600036",
        PositionState.submitting,
        requested_volume=200,
        remaining_volume=200,
    )

    assert manager.has_open_order("SHSE.600036") is True


def test_state_manager_isolates_symbols_with_execution_state() -> None:
    manager = PositionStateManager(logger=None)

    manager.update_state(
        "SHSE.600036",
        PositionState.submitted,
        cl_ord_id="CL_1",
        requested_volume=200,
        remaining_volume=200,
    )
    manager.update_state(
        "SHSE.600000",
        PositionState.failed,
        rejection_reason="broker_rejected",
    )

    assert manager.get_state("SHSE.600036").state is PositionState.submitted
    assert manager.get_state("SHSE.600000").state is PositionState.failed
    assert manager.has_open_order("SHSE.600036") is True
    assert manager.has_open_order("SHSE.600000") is False
```

- [ ] **Step 2: 运行状态管理测试，确认新增字段尚不存在**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_state.py -q
```

Expected:

```text
FAIL with unexpected keyword arguments like cl_ord_id or submit_accepted
```

- [ ] **Step 3: 最小重构 `PositionState` 和 `PositionStateSnapshot`**

```python
# src/gmtrade_live/state.py
"""单标的执行态管理。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from logging import Logger


class PositionState(str, Enum):
    """自动卖出执行链的最小状态机。"""

    idle = "idle"
    submitting = "submitting"
    submitted = "submitted"
    partially_filled = "partially_filled"
    filled = "filled"
    cancelled = "cancelled"
    failed = "failed"


@dataclass(slots=True)
class PositionStateSnapshot:
    """单个标的的执行态快照。"""

    symbol: str
    state: PositionState
    cl_ord_id: str | None = None
    broker_order_id: str | None = None
    trigger_reason: str | None = None
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


class PositionStateManager:
    """按标的维护执行态，避免不同股票之间互相污染。"""

    def __init__(self, logger: Logger | None) -> None:
        self._logger = logger
        self._cache: dict[str, PositionStateSnapshot] = {}

    def get_state(self, symbol: str) -> PositionStateSnapshot:
        if symbol not in self._cache:
            return PositionStateSnapshot(symbol=symbol, state=PositionState.idle)
        return self._cache[symbol]

    def update_state(
        self,
        symbol: str,
        new_state: PositionState,
        **kwargs: object,
    ) -> None:
        snapshot = self.get_state(symbol)
        old_state = snapshot.state

        snapshot.state = new_state
        snapshot.last_update_time = datetime.now()

        for key, value in kwargs.items():
            if hasattr(snapshot, key):
                setattr(snapshot, key, value)

        self._cache[symbol] = snapshot

        if self._logger:
            extra_text = " ".join(f"{key}={value}" for key, value in kwargs.items())
            self._logger.info(
                "state_change symbol=%s old_state=%s new_state=%s%s",
                symbol,
                old_state.value,
                new_state.value,
                f" {extra_text}" if extra_text else "",
            )

    def has_open_order(self, symbol: str) -> bool:
        """把 submitting 也当成 open-order，挡住提交和查单之间的重复发单窗口。"""
        state = self.get_state(symbol).state
        return state in (
            PositionState.submitting,
            PositionState.submitted,
            PositionState.partially_filled,
        )
```

- [ ] **Step 4: 运行状态管理测试**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_state.py -q
```

Expected:

```text
all selected tests PASS
```

- [ ] **Step 5: 提交执行态重构**

```bash
git add src/gmtrade_live/state.py tests/unit/test_state.py
git commit -m "refactor(m3): align execution state with query-driven flow"
```

## Task 4: 实现 M3 查询驱动执行服务

**Files:**
- Create: `src/gmtrade_live/services/m3_execution_service.py`
- Create: `tests/unit/test_m3_execution_service.py`

- [ ] **Step 1: 先写 M3 执行编排的失败测试**

```python
# tests/unit/test_m3_execution_service.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    OrderExecutionSnapshot,
    OrderStatusSnapshot,
    OrderSubmitResult,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.services.m2_decision_engine import M2DecisionEngine
from gmtrade_live.services.m3_execution_service import M3ExecutionService
from gmtrade_live.state import PositionState, PositionStateManager


def _now() -> datetime:
    return datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config(*, ratio: str = "0.80") -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal(ratio),
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


class FakeTradeGateway:
    def __init__(
        self,
        *,
        available_volume: int = 201,
        order_status: str = "submitted",
        execution_filled_volume: int = 0,
    ) -> None:
        self.available_volume = available_volume
        self.order_status = order_status
        self.execution_filled_volume = execution_filled_volume
        self.submitted_requests = []

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SHSE.600036",
                exchange="SHSE",
                volume=250,
                available_volume=self.available_volume,
                cost_price=Decimal("10.00"),
                last_update_time=_now(),
            )
        ]

    def submit_order(self, request):
        self.submitted_requests.append(request)
        return OrderSubmitResult(
            accepted=True,
            cl_ord_id="CL_1",
            broker_order_id="BK_1",
            symbol=request.symbol,
            message="accepted",
            raw_status="1",
            event_time=_now(),
        )

    def query_order_status(self, cl_ord_id: str, symbol: str):
        return OrderStatusSnapshot(
            cl_ord_id=cl_ord_id,
            broker_order_id="BK_1",
            symbol=symbol,
            status=self.order_status,
            filled_volume=self.execution_filled_volume,
            remaining_volume=max(200 - self.execution_filled_volume, 0),
            rejection_reason=None,
            event_time=_now(),
        )

    def query_execution_reports(self, cl_ord_id: str):
        if self.execution_filled_volume <= 0:
            return ()
        return (
            OrderExecutionSnapshot(
                cl_ord_id=cl_ord_id,
                broker_order_id="BK_1",
                symbol="SHSE.600036",
                filled_volume=self.execution_filled_volume,
                avg_price=Decimal("10.80"),
                event_time=_now(),
            ),
        )


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


def test_run_round_submits_sell_order_with_non_promoted_target_when_full_position_not_available() -> None:
    trade_gateway = FakeTradeGateway(available_volume=201, order_status="submitted")
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        state_manager=PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(ratio="0.80"), round_no=1)

    assert trade_gateway.submitted_requests[0].volume == 200
    assert report.summary.candidate_count == 1
    assert report.summary.submitted_count == 1
    assert report.execution_details[0].requested_volume == 200
    assert report.execution_details[0].execution_state == "submitted"


def test_run_round_tracks_existing_open_order_without_duplicate_submit() -> None:
    trade_gateway = FakeTradeGateway(
        available_volume=250,
        order_status="partially_filled",
        execution_filled_volume=100,
    )
    state_manager = PositionStateManager(logger=None)
    state_manager.update_state(
        "SHSE.600036",
        PositionState.submitted,
        cl_ord_id="CL_EXIST",
        requested_volume=200,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="submitted",
    )
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        state_manager=state_manager,
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(ratio="0.80"), round_no=2)

    assert trade_gateway.submitted_requests == []
    assert report.summary.open_order_count == 1
    assert report.execution_details[0].execution_state == "partially_filled"
    assert report.execution_details[0].filled_volume == 100


def test_run_round_emits_block_detail_when_quantity_plan_is_blocked() -> None:
    trade_gateway = FakeTradeGateway(available_volume=201, order_status="submitted")
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        state_manager=PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(ratio="1.0"), round_no=1)

    assert report.summary.blocked_count == 1
    assert report.block_details[0].block_reason == "sell_quantity_exceeds_available"
    assert trade_gateway.submitted_requests == []
```

- [ ] **Step 2: 运行 M3 服务测试，确认服务文件尚不存在**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_m3_execution_service.py -q
```

Expected:

```text
FAIL with ImportError for gmtrade_live.services.m3_execution_service
```

- [ ] **Step 3: 实现 `M3ExecutionService`，复用 M2 决策并走查询驱动闭环**

```python
# src/gmtrade_live/services/m3_execution_service.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging
from time import perf_counter
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    M3BlockDetail,
    M3ExecutionDetail,
    M3RoundReport,
    M3RoundSummary,
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    PositionSnapshot,
)
from gmtrade_live.services.m3_quantity_rules import build_sell_quantity_plan
from gmtrade_live.session import resolve_trading_session
from gmtrade_live.state import PositionState, PositionStateManager


@dataclass(frozen=True, slots=True)
class _OrderStatusQueryEvent:
    broker_order_id: str | None
    status: str
    filled_volume: int
    remaining_volume: int
    rejection_reason: str | None
    event_time: datetime


@dataclass(frozen=True, slots=True)
class _ExecutionReportsQueryEvent:
    broker_order_id: str | None
    filled_volume: int
    avg_price: Decimal | None
    event_time: datetime


class M3ExecutionService:
    """负责单轮自动卖出执行和查询驱动收口。"""

    def __init__(
        self,
        *,
        trade_gateway,
        market_gateway,
        state_manager: PositionStateManager,
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

    def run_round(self, *, config: AppConfig, round_no: int) -> M3RoundReport:
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
        symbols = [position.symbol for position in positions]
        quotes = tuple(self._market_gateway.get_quotes(symbols)) if symbols else ()
        quote_map = {quote.symbol: quote for quote in quotes}

        block_details: list[M3BlockDetail] = []
        execution_details: list[M3ExecutionDetail] = []
        changed_symbols: set[str] = set()
        submitted_count = 0
        candidate_count = 0

        for position in positions:
            decision = self._decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=_build_ephemeral_decision_state(position=position, now=now),
                config=config,
                now=now,
            )
            if not decision.can_submit_sell:
                continue

            candidate_count += 1

            if self._state_manager.has_open_order(position.symbol):
                tracked = self._track_existing_order(symbol=position.symbol, now=now)
                if tracked:
                    execution_details.extend(tracked)
                    changed_symbols.add(position.symbol)
                continue

            quantity_plan = build_sell_quantity_plan(
                symbol=position.symbol,
                total_volume=position.volume,
                available_volume=position.available_volume,
                sell_quantity_ratio=config.sell_quantity_ratio,
            )
            self._logger.info(
                "m3_quantity_evaluated symbol=%s raw_target_volume=%s final_target_volume=%s block_reason=%s",
                position.symbol,
                quantity_plan.raw_target_volume,
                quantity_plan.final_target_volume,
                quantity_plan.block_reason,
            )
            if quantity_plan.block_reason is not None:
                block_details.append(
                    M3BlockDetail(
                        symbol=position.symbol,
                        trigger_reason=decision.trigger_reason,
                        requested_ratio=config.sell_quantity_ratio,
                        total_volume=position.volume,
                        available_volume=position.available_volume,
                        raw_target_volume=quantity_plan.raw_target_volume,
                        promotion_type=quantity_plan.promotion_type,
                        normalized_target_volume=quantity_plan.final_target_volume,
                        block_reason=quantity_plan.block_reason,
                        evaluated_at=decision.evaluated_at,
                    )
                )
                changed_symbols.add(position.symbol)
                continue

            detail = self._submit_new_order(
                symbol=position.symbol,
                requested_volume=quantity_plan.final_target_volume,
                trigger_reason=decision.trigger_reason,
                now=now,
            )
            execution_details.append(detail)
            changed_symbols.add(position.symbol)
            if detail.submit_accepted is True:
                submitted_count += 1

        duration_ms = int((self._timer() - started_at) * 1000)
        return M3RoundReport(
            summary=M3RoundSummary(
                round_no=round_no,
                session_state=session_state.value,
                position_count=len(positions),
                candidate_count=candidate_count,
                blocked_count=len(block_details),
                submitted_count=submitted_count,
                open_order_count=sum(
                    1 for position in positions if self._state_manager.has_open_order(position.symbol)
                ),
                changed_symbol_count=len(changed_symbols),
                duration_ms=duration_ms,
            ),
            block_details=tuple(block_details),
            execution_details=tuple(execution_details),
        )

    def _submit_new_order(
        self,
        *,
        symbol: str,
        requested_volume: int,
        trigger_reason: str | None,
        now: datetime,
    ) -> M3ExecutionDetail:
        if self._state_manager.has_open_order(symbol):
            tracked = self._track_existing_order(symbol=symbol, now=now)
            return tracked[0] if tracked else self._build_execution_detail(symbol=symbol, change_tags=("duplicate_submit_blocked",), now=now)

        self._state_manager.update_state(
            symbol,
            PositionState.submitting,
            trigger_reason=trigger_reason,
            requested_volume=requested_volume,
            remaining_volume=requested_volume,
            message="submitting",
        )
        result = self._trade_gateway.submit_order(
            OrderRequest(
                symbol=symbol,
                volume=requested_volume,
                side="sell",
                price_type="market",
                price=None,
            )
        )
        if not result.accepted or result.cl_ord_id is None:
            self._state_manager.update_state(
                symbol,
                PositionState.failed,
                cl_ord_id=result.cl_ord_id,
                broker_order_id=result.broker_order_id,
                trigger_reason=trigger_reason,
                requested_volume=requested_volume,
                remaining_volume=requested_volume,
                submit_accepted=False,
                rejection_reason=result.message,
                event_time=result.event_time,
                message=result.message,
            )
            return self._build_execution_detail(
                symbol=symbol,
                change_tags=("submit_rejected",),
                now=now,
            )

        self._state_manager.update_state(
            symbol,
            PositionState.submitted,
            cl_ord_id=result.cl_ord_id,
            broker_order_id=result.broker_order_id,
            trigger_reason=trigger_reason,
            requested_volume=requested_volume,
            remaining_volume=requested_volume,
            submit_accepted=True,
            last_order_status="submitted",
            event_time=result.event_time,
            message=result.message,
        )
        tracked = self._track_existing_order(symbol=symbol, now=now, extra_change_tags=("submit_accepted",))
        return tracked[0] if tracked else self._build_execution_detail(
            symbol=symbol,
            change_tags=("submit_accepted",),
            now=now,
        )

    def _track_existing_order(
        self,
        *,
        symbol: str,
        now: datetime,
        extra_change_tags: tuple[str, ...] = (),
    ) -> list[M3ExecutionDetail]:
        snapshot = self._state_manager.get_state(symbol)
        if snapshot.cl_ord_id is None:
            return []

        change_tags: list[str] = list(extra_change_tags)
        order_snapshot = self._trade_gateway.query_order_status(snapshot.cl_ord_id, symbol)
        if order_snapshot is not None:
            self._apply_query_event(
                symbol=symbol,
                event=self._to_order_status_event(order_snapshot),
            )
            change_tags.append("order_status_updated")

            if order_snapshot.status in {"filled", "partially_filled"}:
                execution_snapshots = self._trade_gateway.query_execution_reports(snapshot.cl_ord_id)
                if execution_snapshots:
                    self._apply_query_event(
                        symbol=symbol,
                        event=self._to_execution_reports_event(execution_snapshots),
                    )
                    change_tags.append("execution_reports_updated")

        if not change_tags:
            return []
        return [
            self._build_execution_detail(
                symbol=symbol,
                change_tags=tuple(change_tags),
                now=now,
            )
        ]

    def _to_order_status_event(
        self,
        snapshot: OrderStatusSnapshot,
    ) -> _OrderStatusQueryEvent:
        return _OrderStatusQueryEvent(
            broker_order_id=snapshot.broker_order_id,
            status=snapshot.status,
            filled_volume=snapshot.filled_volume,
            remaining_volume=snapshot.remaining_volume,
            rejection_reason=snapshot.rejection_reason,
            event_time=snapshot.event_time,
        )

    def _to_execution_reports_event(
        self,
        snapshots: tuple[OrderExecutionSnapshot, ...],
    ) -> _ExecutionReportsQueryEvent:
        last_snapshot = snapshots[-1]
        return _ExecutionReportsQueryEvent(
            broker_order_id=last_snapshot.broker_order_id,
            filled_volume=sum(item.filled_volume for item in snapshots),
            avg_price=last_snapshot.avg_price,
            event_time=last_snapshot.event_time,
        )

    def _apply_query_event(
        self,
        *,
        symbol: str,
        event: _OrderStatusQueryEvent | _ExecutionReportsQueryEvent,
    ) -> None:
        if isinstance(event, _OrderStatusQueryEvent):
            self._apply_order_status_event(symbol=symbol, event=event)
            return
        self._apply_execution_reports_event(symbol=symbol, event=event)

    def _apply_order_status_event(self, *, symbol: str, event: _OrderStatusQueryEvent) -> None:
        self._state_manager.update_state(
            symbol,
            _map_execution_state(event.status),
            broker_order_id=event.broker_order_id,
            filled_volume=event.filled_volume,
            remaining_volume=event.remaining_volume,
            last_order_status=event.status,
            rejection_reason=event.rejection_reason,
            event_time=event.event_time,
        )

    def _apply_execution_reports_event(
        self,
        *,
        symbol: str,
        event: _ExecutionReportsQueryEvent,
    ) -> None:
        self._state_manager.update_state(
            symbol,
            self._state_manager.get_state(symbol).state,
            broker_order_id=event.broker_order_id,
            filled_volume=event.filled_volume,
            avg_price=event.avg_price,
            event_time=event.event_time,
        )

    def _build_execution_detail(
        self,
        *,
        symbol: str,
        change_tags: tuple[str, ...],
        now: datetime,
    ) -> M3ExecutionDetail:
        snapshot = self._state_manager.get_state(symbol)
        return M3ExecutionDetail(
            symbol=symbol,
            change_tags=change_tags,
            execution_state=snapshot.state.value,
            cl_ord_id=snapshot.cl_ord_id,
            broker_order_id=snapshot.broker_order_id,
            requested_volume=snapshot.requested_volume,
            filled_volume=snapshot.filled_volume,
            remaining_volume=snapshot.remaining_volume,
            submit_accepted=snapshot.submit_accepted,
            last_order_status=snapshot.last_order_status,
            rejection_reason=snapshot.rejection_reason,
            avg_price=snapshot.avg_price,
            event_time=snapshot.event_time or now,
            message=snapshot.message,
        )


def _build_ephemeral_decision_state(
    *,
    position: PositionSnapshot,
    now: datetime,
) -> DecisionPositionStateSnapshot:
    """M3 只需要满足 M2DecisionEngine 的入参契约，不复用 M2StateManager。"""
    return DecisionPositionStateSnapshot(
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


def _map_execution_state(status: str) -> PositionState:
    if status == "submitted":
        return PositionState.submitted
    if status == "partially_filled":
        return PositionState.partially_filled
    if status == "filled":
        return PositionState.filled
    if status in {"cancelled", "expired", "done_for_day", "stopped"}:
        return PositionState.cancelled
    if status == "rejected":
        return PositionState.failed
    return PositionState.submitted
```

- [ ] **Step 4: 运行 M3 服务单测**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_m3_execution_service.py -q
```

Expected:

```text
all selected tests PASS
```

- [ ] **Step 5: 提交 M3 执行服务**

```bash
git add src/gmtrade_live/services/m3_execution_service.py tests/unit/test_m3_execution_service.py
git commit -m "feat(m3): add query-driven execution service"
```

## Task 5: 接入 CLI / bootstrap，并把 M3 报告投影到 JSON

**Files:**
- Modify: `main.py`
- Modify: `src/gmtrade_live/bootstrap.py`
- Modify: `tests/unit/test_main.py`
- Modify: `tests/unit/test_bootstrap.py`

- [ ] **Step 1: 先写 M3 CLI 与 bootstrap 的失败测试**

```python
# tests/unit/test_main.py
def test_parse_cli_args_accepts_m3_once_mode() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m3",
            "--once",
        ]
    )

    assert args.mode == "m3"
    assert args.once is True
    assert args.max_rounds is None


def test_main_dispatches_to_m3(monkeypatch: pytest.MonkeyPatch) -> None:
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
        ["main.py", "--config", "config/sim_account.yaml", "--mode", "m3", "--max-rounds", "2"],
    )

    assert main.main() == 0
    assert captured["config_path"] == Path("config/sim_account.yaml")
    assert captured["once"] is False
    assert captured["max_rounds"] == 2
```

```python
# tests/unit/test_bootstrap.py
def test_run_m3_execution_prints_summary_block_and_execution_details(monkeypatch, capsys) -> None:
    config = SimpleNamespace(
        account_id="demo-account",
        strategy_name="gmtrade-live",
        log_dir=Path("logs"),
        token="demo-token",
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
        poll_interval_seconds=5,
        market_session_mode="a_share",
        sell_quantity_ratio=Decimal("0.80"),
    )

    report = SimpleNamespace(
        summary=SimpleNamespace(
            round_no=1,
            session_state="trading",
            position_count=1,
            candidate_count=1,
            blocked_count=1,
            submitted_count=1,
            open_order_count=1,
            changed_symbol_count=1,
            duration_ms=12,
        ),
        block_details=(
            SimpleNamespace(
                symbol="SHSE.600036",
                trigger_reason="take_profit_triggered",
                requested_ratio=Decimal("0.80"),
                total_volume=250,
                available_volume=201,
                raw_target_volume=200,
                promotion_type=None,
                normalized_target_volume=200,
                block_reason="sell_quantity_exceeds_available",
                evaluated_at=datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            ),
        ),
        execution_details=(
            SimpleNamespace(
                symbol="SHSE.600036",
                change_tags=("submit_accepted",),
                execution_state="submitted",
                cl_ord_id="CL_1",
                broker_order_id="BK_1",
                requested_volume=200,
                filled_volume=0,
                remaining_volume=200,
                submit_accepted=True,
                last_order_status="submitted",
                rejection_reason=None,
                avg_price=None,
                event_time=datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                message="accepted",
            ),
        ),
    )

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
            error=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(bootstrap, "GMTradeGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "PositionStateManager", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M2DecisionEngine", lambda: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M3ExecutionService", FakeService)

    exit_code = bootstrap.run_m3_execution(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert exit_code == 0
    assert '"kind": "m3_round_summary"' in lines[0]
    assert '"kind": "m3_block_detail"' in lines[1]
    assert '"kind": "m3_execution_detail"' in lines[2]


def test_run_m3_execution_prints_round_error_and_returns_nonzero(monkeypatch, capsys) -> None:
    config = SimpleNamespace(
        account_id="demo-account",
        strategy_name="gmtrade-live",
        log_dir=Path("logs"),
        token="demo-token",
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
        poll_interval_seconds=5,
        market_session_mode="a_share",
        sell_quantity_ratio=Decimal("0.80"),
    )

    class FakeGateway:
        def connect(self, *args, **kwargs) -> None:
            return None

    class FakeService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run_round(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(
        bootstrap,
        "setup_logging",
        lambda *args, **kwargs: SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(bootstrap, "GMTradeGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "PositionStateManager", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M2DecisionEngine", lambda: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M3ExecutionService", FakeService)

    exit_code = bootstrap.run_m3_execution(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["kind"] == "m3_round_error"
    assert payload["message"] == "boom"
```

- [ ] **Step 2: 运行 CLI / bootstrap 测试，确认入口尚未接入**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py -q
```

Expected:

```text
FAIL for unknown mode "m3" and missing run_m3_execution
```

- [ ] **Step 3: 最小接入 `main.py` 和 `bootstrap.py`**

```python
# main.py
def build_parser() -> argparse.ArgumentParser:
    """构建基础 CLI 参数。"""
    parser = argparse.ArgumentParser(
        description="GMTrade connectivity, M1 manual trade, M2 decision dry-run, and M3 auto sell execution"
    )
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--mode", choices=("m0", "m1", "m2", "m3"), default="m0")
    parser.set_defaults(
        symbol=None,
        volume=None,
        price_type=None,
        price=None,
        timeout_seconds=60,
        side=None,
    )
    return parser


def build_parser_for_mode(mode: str) -> argparse.ArgumentParser:
    """按运行模式构建完整 CLI 参数。"""
    parser = build_parser()
    if mode == "m1":
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--volume", type=_parse_positive_int, required=True)
        parser.add_argument("--price-type", choices=("market", "limit"), required=True)
        parser.add_argument("--price", type=_parse_positive_decimal)
        parser.add_argument("--timeout-seconds", type=_parse_positive_int, default=60)
        parser.add_argument("--side", choices=("buy", "sell"), required=True)
        return parser

    if mode in {"m2", "m3"}:
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--once", action="store_true")
        group.add_argument("--max-rounds", type=_parse_positive_int)
    return parser


from gmtrade_live.bootstrap import (
    run_m0_connectivity_check,
    run_m1_manual_trade,
    run_m2_dry_run,
    run_m3_execution,
)

if args.mode == "m3":
    return run_m3_execution(
        config_path=config_path,
        once=args.once,
        max_rounds=args.max_rounds,
    )
```

```python
# src/gmtrade_live/bootstrap.py
from gmtrade_live.services.m3_execution_service import M3ExecutionService
from gmtrade_live.state import PositionStateManager


def run_m3_execution(
    *,
    config_path: Path,
    once: bool,
    max_rounds: int | None,
) -> int:
    """执行 M3 自动卖出闭环并输出结构化结果。"""
    config = load_config(config_path)
    _resolve_current_session_state(config)
    logger = setup_logging(config.strategy_name, config.log_dir)
    trade_gateway = GMTradeGateway()
    market_gateway = GMCurrentQuoteGateway()

    trade_gateway.connect(config)
    market_gateway.connect(config.token)

    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        state_manager=PositionStateManager(logger),
        decision_engine=M2DecisionEngine(),
        logger=logger,
    )

    round_no = 1
    while True:
        try:
            report = service.run_round(config=config, round_no=round_no)
        except Exception as exc:
            logger.error(
                "m3_round_failed round=%s error_type=%s error=%s",
                round_no,
                type(exc).__name__,
                str(exc),
                exc_info=True,
            )
            print(
                json.dumps(
                    {
                        "kind": "m3_round_error",
                        "round": round_no,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
            return 1

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
            print(
                json.dumps(
                    {
                        "kind": "m3_block_detail",
                        "symbol": block.symbol,
                        "trigger_reason": block.trigger_reason,
                        "requested_ratio": str(block.requested_ratio),
                        "total_volume": block.total_volume,
                        "available_volume": block.available_volume,
                        "raw_target_volume": block.raw_target_volume,
                        "promotion_type": block.promotion_type,
                        "normalized_target_volume": block.normalized_target_volume,
                        "block_reason": block.block_reason,
                        "evaluated_at": block.evaluated_at.isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
        for detail in report.execution_details:
            print(
                json.dumps(
                    {
                        "kind": "m3_execution_detail",
                        "symbol": detail.symbol,
                        "change_tags": list(detail.change_tags),
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

- [ ] **Step 4: 运行 CLI / bootstrap 测试**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py -q
```

Expected:

```text
all selected tests PASS
```

- [ ] **Step 5: 提交 CLI 和 bootstrap 接入**

```bash
git add main.py src/gmtrade_live/bootstrap.py tests/unit/test_main.py tests/unit/test_bootstrap.py
git commit -m "feat(m3): wire cli and bootstrap output"
```

## Task 6: 集成测试、示例配置、命令文档与全量验证

**Files:**
- Create: `tests/integration/test_m3_execution_integration.py`
- Modify: `src/gmtrade_live/services/m3_execution_service.py`
- Modify: `config/sim_account.example.yaml`
- Modify: `AGENTS.md`

- [ ] **Step 1: 先写 M3 集成测试和文档变更**

```python
# tests/integration/test_m3_execution_integration.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    OrderExecutionSnapshot,
    OrderStatusSnapshot,
    OrderSubmitResult,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.services.m2_decision_engine import M2DecisionEngine
from gmtrade_live.services.m3_execution_service import M3ExecutionService
from gmtrade_live.state import PositionState, PositionStateManager


def _now() -> datetime:
    return datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live",
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
    def __init__(self) -> None:
        self.submit_calls = 0

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SHSE.600036",
                exchange="SHSE",
                volume=100,
                available_volume=100,
                cost_price=Decimal("10.00"),
                last_update_time=_now(),
            )
        ]

    def submit_order(self, request):
        self.submit_calls += 1
        return OrderSubmitResult(
            accepted=True,
            cl_ord_id="CL_1",
            broker_order_id="BK_1",
            symbol=request.symbol,
            message="accepted",
            raw_status="1",
            event_time=_now(),
        )

    def query_order_status(self, cl_ord_id: str, symbol: str):
        return OrderStatusSnapshot(
            cl_ord_id=cl_ord_id,
            broker_order_id="BK_1",
            symbol=symbol,
            status="filled",
            filled_volume=100,
            remaining_volume=0,
            rejection_reason=None,
            event_time=_now(),
        )

    def query_execution_reports(self, cl_ord_id: str):
        return (
            OrderExecutionSnapshot(
                cl_ord_id=cl_ord_id,
                broker_order_id="BK_1",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("10.80"),
                event_time=_now(),
            ),
        )


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


def test_m3_execution_service_completes_query_driven_sell_round() -> None:
    state_manager = PositionStateManager(logging.getLogger("test"))
    service = M3ExecutionService(
        trade_gateway=FakeTradeGateway(),
        market_gateway=FakeMarketGateway(),
        state_manager=state_manager,
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(), round_no=1)

    assert report.summary.submitted_count == 1
    assert report.execution_details[0].execution_state == "filled"
    assert report.execution_details[0].filled_volume == 100
    assert report.execution_details[0].avg_price == Decimal("10.80")
    assert state_manager.get_state("SHSE.600036").state is PositionState.filled
```

```yaml
# config/sim_account.example.yaml
account_id: ${GM_ACCOUNT_ID}
token: ${GM_TOKEN}
strategy_name: gmtrade-live-m0
poll_interval_seconds: 5
take_profit_ratio: "0.05"
stop_loss_ratio: "0.03"
sell_quantity_ratio: "1.0"
market_session_mode: a_share
log_dir: logs
timezone: Asia/Shanghai
gmtrade_endpoint: 127.0.0.1:7001
```

```text
# AGENTS.md 补一条 M3 运行示例
### M3 自动卖出执行
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m3 --once
```

- [ ] **Step 2: 运行 M3 集成测试，确认终态收口还未补齐前会失败**

Run:

```bash
conda run -n stock_analysis pytest tests/integration/test_m3_execution_integration.py -q
```

Expected:

```text
FAIL until execution service maps filled order status and execution reports into PositionState.filled with avg_price
```

- [ ] **Step 3: 补齐 filled 终态收口，并更新示例配置和命令文档**

```python
# src/gmtrade_live/services/m3_execution_service.py
def _track_existing_order(
    self,
    *,
    symbol: str,
    now: datetime,
    extra_change_tags: tuple[str, ...] = (),
) -> list[M3ExecutionDetail]:
    snapshot = self._state_manager.get_state(symbol)
    if snapshot.cl_ord_id is None:
        return []

    change_tags: list[str] = list(extra_change_tags)
    order_snapshot = self._trade_gateway.query_order_status(snapshot.cl_ord_id, symbol)
    if order_snapshot is not None:
        self._apply_query_event(
            symbol=symbol,
            event=self._to_order_status_event(order_snapshot),
        )
        change_tags.append("order_status_updated")

        if order_snapshot.status in {"filled", "partially_filled"}:
            execution_snapshots = self._trade_gateway.query_execution_reports(snapshot.cl_ord_id)
            if execution_snapshots:
                self._apply_query_event(
                    symbol=symbol,
                    event=self._to_execution_reports_event(execution_snapshots),
                )
                change_tags.append("execution_reports_updated")

    if not change_tags:
        return []
    return [
        self._build_execution_detail(
            symbol=symbol,
            change_tags=tuple(change_tags),
            now=now,
        )
    ]


def _to_order_status_event(
    self,
    snapshot: OrderStatusSnapshot,
) -> _OrderStatusQueryEvent:
    return _OrderStatusQueryEvent(
        broker_order_id=snapshot.broker_order_id,
        status=snapshot.status,
        filled_volume=snapshot.filled_volume,
        remaining_volume=snapshot.remaining_volume,
        rejection_reason=snapshot.rejection_reason,
        event_time=snapshot.event_time,
    )


def _to_execution_reports_event(
    self,
    snapshots: tuple[OrderExecutionSnapshot, ...],
) -> _ExecutionReportsQueryEvent:
    last_snapshot = snapshots[-1]
    return _ExecutionReportsQueryEvent(
        broker_order_id=last_snapshot.broker_order_id,
        filled_volume=sum(item.filled_volume for item in snapshots),
        avg_price=last_snapshot.avg_price,
        event_time=last_snapshot.event_time,
    )


def _apply_query_event(
    self,
    *,
    symbol: str,
    event: _OrderStatusQueryEvent | _ExecutionReportsQueryEvent,
) -> None:
    if isinstance(event, _OrderStatusQueryEvent):
        self._apply_order_status_event(symbol=symbol, event=event)
        return
    self._apply_execution_reports_event(symbol=symbol, event=event)


def _apply_order_status_event(self, *, symbol: str, event: _OrderStatusQueryEvent) -> None:
    self._state_manager.update_state(
        symbol,
        _map_execution_state(event.status),
        broker_order_id=event.broker_order_id,
        filled_volume=event.filled_volume,
        remaining_volume=event.remaining_volume,
        last_order_status=event.status,
        rejection_reason=event.rejection_reason,
        event_time=event.event_time,
    )


def _apply_execution_reports_event(
    self,
    *,
    symbol: str,
    event: _ExecutionReportsQueryEvent,
) -> None:
    self._state_manager.update_state(
        symbol,
        self._state_manager.get_state(symbol).state,
        broker_order_id=event.broker_order_id,
        filled_volume=event.filled_volume,
        avg_price=event.avg_price,
        event_time=event.event_time,
    )
```

- [ ] **Step 4: 运行 M3 目标测试和全量回归**

Run:

```bash
conda run -n stock_analysis pytest tests/unit/test_m3_models.py tests/unit/test_m3_quantity_rules.py tests/unit/test_m3_execution_service.py tests/unit/test_main.py tests/unit/test_bootstrap.py tests/unit/test_state.py tests/integration/test_m3_execution_integration.py -q
```

Then run:

```bash
conda run -n stock_analysis pytest tests/unit tests/integration -q
```

Expected:

```text
all selected tests PASS
all unit and integration tests PASS with M3 additions
```

- [ ] **Step 5: 提交集成测试、示例配置和文档**

```bash
git add tests/integration/test_m3_execution_integration.py src/gmtrade_live/services/m3_execution_service.py config/sim_account.example.yaml AGENTS.md
git commit -m "test(m3): add integration coverage and docs"
```

## Self-Review Checklist

- [ ] 逐节对照 [2026-04-10-m3-auto-sell-execution-design.md](/D:/Program_python/free_stock/docs/superpowers/specs/2026-04-10-m3-auto-sell-execution-design.md)，确认每条要求至少有一个任务承接
- [ ] 搜索计划文件内是否包含 `TBD`、`TODO`、`待补`、`implement later` 等占位词
- [ ] 通读所有任务，确认统一使用这些名字：`sell_quantity_ratio`、`SellQuantityPlan`、`M3ExecutionService`、`run_m3_execution`、`m3_round_summary`、`m3_block_detail`、`m3_execution_detail`
- [ ] 检查计划里不再出现 `trade_session_start` / `trade_session_end`，统一使用 `market_session_mode`
- [ ] 检查计划里不再把 `triggered` 当成 M3 持久执行态

## Execution Notes

- 先执行 Task 1，再往下走；不要跳过配置契约
- Task 3 不是简单加字段，而是把 `state.py` 从旧触发态语义收敛为纯执行态
- Task 4 完成前不要接 CLI / bootstrap
- Task 6 结束前不要宣布 M3 已完成；必须拿到集成测试和全量回归结果
- 若实现过程中发现自动卖出需要额外价格策略配置，停止执行本计划，先回到设计稿补充 scope
