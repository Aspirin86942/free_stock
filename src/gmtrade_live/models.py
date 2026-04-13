"""项目核心数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True, slots=True)
class CashSnapshot:
    """账户资金快照。"""

    account_id: str
    available_cash: Decimal
    market_value: Decimal
    total_asset: Decimal
    update_time: datetime


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """持仓快照。"""

    symbol: str
    exchange: str
    volume: int
    available_volume: int
    cost_price: Decimal
    last_update_time: datetime


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    """行情快照。"""

    symbol: str
    last_price: Decimal
    quote_time: datetime
    source: str


@dataclass(frozen=True, slots=True)
class ConnectivityReport:
    """M0 连通性检查结果。"""

    account_id: str
    session_state: str
    cash: CashSnapshot
    positions: tuple[PositionSnapshot, ...]
    quotes: tuple[QuoteSnapshot, ...]


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """M1 手工交易请求。"""

    symbol: str
    volume: int
    side: str
    price_type: str
    price: Decimal | None


@dataclass(frozen=True, slots=True)
class OrderSubmitResult:
    """委托提交结果。"""

    accepted: bool
    cl_ord_id: str | None
    broker_order_id: str | None
    symbol: str
    message: str
    raw_status: str
    event_time: datetime


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """委托状态回报。"""

    order_id: str
    symbol: str
    status: str
    filled_volume: int
    remaining_volume: int
    event_time: datetime
    message: str


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    """成交回报。"""

    order_id: str
    symbol: str
    filled_volume: int
    avg_price: Decimal
    event_time: datetime


@dataclass(frozen=True, slots=True)
class OrderStatusSnapshot:
    """通过主动查单拿到的委托状态快照。"""

    cl_ord_id: str
    broker_order_id: str | None
    symbol: str
    status: str
    filled_volume: int
    remaining_volume: int
    rejection_reason: str | None
    event_time: datetime


@dataclass(frozen=True, slots=True)
class OrderExecutionSnapshot:
    """通过主动查成交拿到的成交快照。"""

    cl_ord_id: str
    broker_order_id: str | None
    symbol: str
    filled_volume: int
    avg_price: Decimal
    event_time: datetime


@dataclass(frozen=True, slots=True)
class TradeReport:
    """M1 验证报告。"""

    account_id: str
    side: str
    symbol: str
    requested_volume: int
    price_type: str
    submit_accepted: bool
    cl_ord_id: str | None
    broker_order_id: str | None
    order_status_confirmed: bool
    execution_status_confirmed: bool
    last_order_status: str | None
    rejection_reason: str | None
    filled_volume: int
    avg_price: Decimal | None
    verification_passed: bool
    message: str
    started_at: datetime
    finished_at: datetime


class DecisionLifecycleState(str, Enum):
    """M2 决策态生命周期。"""

    watching = "watching"
    tombstone = "tombstone"


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """M2 单标的决策结果。"""

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
    """M2 决策态快照。"""

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
    """M2 单标的评估结果与状态快照。"""

    decision: DecisionResult
    state_snapshot: DecisionPositionStateSnapshot


@dataclass(frozen=True, slots=True)
class M2RoundSummary:
    """M2 单轮摘要。"""

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
    """M2 单标的变化事件。"""

    symbol: str
    change_tags: tuple[str, ...]
    decision: DecisionResult | None
    state_snapshot: DecisionPositionStateSnapshot | None


@dataclass(frozen=True, slots=True)
class M2RoundReport:
    """M2 单轮输出。"""

    summary: M2RoundSummary
    evaluated_symbols: tuple[EvaluatedSymbol, ...]
    tombstones: tuple[DecisionPositionStateSnapshot, ...]
    change_events: tuple[M2ChangeEvent, ...]


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
    """单标的执行链详情。"""

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
