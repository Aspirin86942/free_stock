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
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


class SequencedTradeGateway:
    def __init__(self, rounds: list[tuple[PositionSnapshot, ...]]) -> None:
        self._rounds = rounds
        self._index = 0

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        value = self._rounds[min(self._index, len(self._rounds) - 1)]
        self._index += 1
        return list(value)


class SequencedMarketGateway:
    def __init__(self, quotes: dict[str, QuoteSnapshot]) -> None:
        self._quotes = quotes

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
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
