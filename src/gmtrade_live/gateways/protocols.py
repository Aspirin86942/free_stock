"""网关协议定义。"""

from __future__ import annotations

from typing import Protocol

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    CashSnapshot,
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    OrderSubmitResult,
    PositionSnapshot,
    QuoteSnapshot,
)


class TradeGateway(Protocol):
    """交易网关协议。"""

    def connect(self, config: AppConfig) -> None:
        ...

    def get_cash(self, account_id: str) -> CashSnapshot:
        ...

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        ...

    def submit_order(self, request: OrderRequest) -> OrderSubmitResult:
        ...

    def query_order_status(self, cl_ord_id: str, symbol: str) -> OrderStatusSnapshot | None:
        ...

    def query_execution_reports(self, cl_ord_id: str) -> tuple[OrderExecutionSnapshot, ...]:
        ...


class MarketGateway(Protocol):
    """行情网关协议。"""

    def connect(self, token: str) -> None:
        ...

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        ...
