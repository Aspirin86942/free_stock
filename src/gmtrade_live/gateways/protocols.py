"""网关协议定义。"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from gmtrade_live.config import AppConfig
from gmtrade_live.market_models import DailyBar, SecurityMaster
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


class HistoryMarketGateway(Protocol):
    """历史行情网关协议。"""

    def connect(self, token: str, endpoint: str) -> None:
        ...

    def get_security_master(self, scope: str) -> list[SecurityMaster]:
        ...

    def fetch_daily_bars(
        self, symbols: list[str], start_date: date, end_date: date
    ) -> list[DailyBar]:
        ...

    def get_trade_dates(self, start_date: date, end_date: date) -> list[date]:
        ...

    def get_latest_trade_date(self, reference_date: date | None = None) -> date:
        ...

    def get_trade_date_n_years_ago(self, years: int, reference_date: date | None = None) -> date:
        ...

    def get_next_trade_date(self, current_date: date) -> date:
        ...
