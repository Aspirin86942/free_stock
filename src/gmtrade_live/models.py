from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CashSnapshot:
    account_id: str
    available_cash: Decimal
    market_value: Decimal
    total_asset: Decimal
    update_time: datetime


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    exchange: str
    volume: int
    available_volume: int
    cost_price: Decimal
    last_update_time: datetime


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    symbol: str
    last_price: Decimal
    quote_time: datetime
    source: str


@dataclass(frozen=True, slots=True)
class ConnectivityReport:
    account_id: str
    session_state: str
    cash: CashSnapshot
    positions: tuple[PositionSnapshot, ...]
    quotes: tuple[QuoteSnapshot, ...]


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """M1 手动卖单请求。"""

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
    symbol: str
    requested_volume: int
    price_type: str
    submit_accepted: bool
    cl_ord_id: str | None
    broker_order_id: str | None
    order_event_received: bool
    execution_event_received: bool
    callback_chain_closed: bool
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
