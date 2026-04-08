from __future__ import annotations

from typing import Protocol

from gmtrade_live.config import AppConfig
from gmtrade_live.models import CashSnapshot, PositionSnapshot, QuoteSnapshot


class TradeGateway(Protocol):
    def connect(self, config: AppConfig) -> None:
        ...

    def get_cash(self, account_id: str) -> CashSnapshot:
        ...

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        ...


class MarketGateway(Protocol):
    def connect(self, token: str) -> None:
        ...

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        ...
