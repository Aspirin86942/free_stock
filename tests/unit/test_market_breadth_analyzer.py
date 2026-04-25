from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from gmtrade_live.market_models import DailyBar
from gmtrade_live.services.market_breadth_analyzer import MarketBreadthAnalyzer


class _CountingRepository:
    def __init__(self, bars: list[DailyBar]) -> None:
        self._bars = bars
        self.calls: dict[str, int] = {
            "get_daily_bars_by_date": 0,
            "get_recent_trade_dates": 0,
            "get_daily_bars": 0,
        }

    def get_daily_bars_by_date(self, trade_date: date) -> list[DailyBar]:
        self.calls["get_daily_bars_by_date"] += 1
        return [bar for bar in self._bars if bar.trade_date == trade_date]

    def get_recent_trade_dates(self, end_date: date, limit: int) -> list[date]:
        self.calls["get_recent_trade_dates"] += 1
        dates = sorted({bar.trade_date for bar in self._bars if bar.trade_date <= end_date})
        return dates[-limit:]

    def get_daily_bars(self, symbols: list[str], start_date: date, end_date: date) -> list[DailyBar]:
        self.calls["get_daily_bars"] += 1
        symbol_set = set(symbols)
        return [
            bar
            for bar in self._bars
            if bar.symbol in symbol_set and start_date <= bar.trade_date <= end_date
        ]


def _bar(symbol: str, trade_date: date, close: str, pre_close: str = "10") -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        pre_close=Decimal(pre_close),
        volume=100,
        amount=Decimal("1000"),
        turnover_rate=Decimal("12"),
        is_st=False,
        suspended=False,
        has_trade=True,
    )


def test_market_breadth_analyzer_queries_history_once_for_20d_and_60d() -> None:
    start_date = date(2026, 2, 20)
    trade_dates = [start_date + timedelta(days=offset) for offset in range(61)]
    latest_date = trade_dates[-1]
    bars: list[DailyBar] = []
    for trade_date in trade_dates[:-1]:
        bars.append(_bar("AAA", trade_date, "10"))
        bars.append(_bar("BBB", trade_date, "10"))
    bars.append(_bar("AAA", latest_date, "12"))
    bars.append(_bar("BBB", latest_date, "8"))
    repository = _CountingRepository(bars)

    metrics = MarketBreadthAnalyzer(repository).calculate(latest_date)  # type: ignore[arg-type]

    assert metrics.new_high_20d_count == 1
    assert metrics.new_low_20d_count == 1
    assert metrics.new_high_60d_count == 1
    assert metrics.new_low_60d_count == 1
    assert repository.calls == {
        "get_daily_bars_by_date": 1,
        "get_recent_trade_dates": 1,
        "get_daily_bars": 1,
    }


def test_market_breadth_analyzer_skips_invalid_pre_close_and_logs_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    trade_date = date(2026, 4, 20)
    repository = _CountingRepository(
        [
            _bar("BAD", trade_date, "10", pre_close="0"),
            _bar("GOOD", trade_date, "11", pre_close="10"),
        ]
    )

    metrics = MarketBreadthAnalyzer(repository).calculate(trade_date)  # type: ignore[arg-type]

    assert metrics.up_count == 1
    assert metrics.down_count == 0
    assert metrics.up_ratio == Decimal("1")
    assert "invalid_price_bar_skipped" in caplog.text
    assert "BAD" in caplog.text
