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
