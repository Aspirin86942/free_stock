from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.services.sell_decision_engine import SellDecisionEngine
from gmtrade_live.session import TradingSessionState


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


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
    engine = SellDecisionEngine()

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
    engine = SellDecisionEngine()

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
    engine = SellDecisionEngine()

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

