from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
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
        sell_quantity_ratio=Decimal("1.0"),
        market_session_mode="a_share",
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
