from __future__ import annotations

from datetime import date
from decimal import Decimal

from gmtrade_live.market_models import DailyBar
from gmtrade_live.services.market_emotion_analyzer import MarketEmotionAnalyzer
from gmtrade_live.services.market_profit_effect_analyzer import MarketProfitEffectAnalyzer
from gmtrade_live.services.market_tolerance_analyzer import MarketToleranceAnalyzer


class _FakeRepository:
    def __init__(self, bars: list[DailyBar]) -> None:
        self._bars = bars

    def get_daily_bars_by_date(self, trade_date: date) -> list[DailyBar]:
        return [bar for bar in self._bars if bar.trade_date == trade_date]

    def get_recent_trade_dates(self, end_date: date, limit: int) -> list[date]:
        dates = sorted({bar.trade_date for bar in self._bars if bar.trade_date <= end_date})
        return dates[-limit:]

    def get_daily_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> list[DailyBar]:
        symbols_set = set(symbols)
        return [
            bar
            for bar in self._bars
            if bar.symbol in symbols_set and start_date <= bar.trade_date <= end_date
        ]


def _bar(
    *,
    symbol: str,
    trade_date: date,
    close: str,
    pre_close: str,
    high: str,
    volume: int = 100,
    amount: str = "1000",
    turnover_rate: str | None = None,
) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(close),
        close=Decimal(close),
        pre_close=Decimal(pre_close),
        volume=volume,
        amount=Decimal(amount),
        turnover_rate=Decimal(turnover_rate) if turnover_rate is not None else None,
        is_st=False,
        suspended=False,
        has_trade=True,
    )


def _build_bars() -> list[DailyBar]:
    d1 = date(2026, 4, 16)
    d2 = date(2026, 4, 17)
    d3 = date(2026, 4, 18)
    d4 = date(2026, 4, 19)
    d5 = date(2026, 4, 20)

    return [
        _bar(symbol="AAA", trade_date=d1, close="10.0", pre_close="9.8", high="10.1", turnover_rate="8"),
        _bar(symbol="AAA", trade_date=d2, close="10.2", pre_close="10.0", high="10.3", turnover_rate="8"),
        _bar(symbol="AAA", trade_date=d3, close="10.9", pre_close="10.2", high="10.9", turnover_rate="9"),
        _bar(symbol="AAA", trade_date=d4, close="12.0", pre_close="10.9", high="12.0", turnover_rate="12"),
        _bar(symbol="AAA", trade_date=d5, close="13.0", pre_close="12.0", high="13.5", amount="1300", turnover_rate="9"),
        _bar(symbol="BBB", trade_date=d1, close="10.0", pre_close="9.9", high="10.1", turnover_rate="6"),
        _bar(symbol="BBB", trade_date=d2, close="10.5", pre_close="10.0", high="10.6", turnover_rate="6"),
        _bar(symbol="BBB", trade_date=d3, close="11.0", pre_close="10.0", high="11.0", turnover_rate="7"),
        _bar(symbol="BBB", trade_date=d4, close="12.1", pre_close="11.0", high="12.1", turnover_rate="7"),
        _bar(symbol="BBB", trade_date=d5, close="12.1", pre_close="12.1", high="12.1", turnover_rate="7"),
        _bar(symbol="CCC", trade_date=d1, close="10.0", pre_close="10.0", high="10.0", turnover_rate="4"),
        _bar(symbol="CCC", trade_date=d2, close="10.0", pre_close="10.0", high="10.0", turnover_rate="4"),
        _bar(symbol="CCC", trade_date=d3, close="10.0", pre_close="10.0", high="10.0", turnover_rate="4"),
        _bar(symbol="CCC", trade_date=d4, close="10.5", pre_close="10.0", high="11.0", turnover_rate="4"),
        _bar(symbol="CCC", trade_date=d5, close="10.0", pre_close="10.5", high="10.3", turnover_rate="4"),
        _bar(symbol="DDD", trade_date=d1, close="5.0", pre_close="5.0", high="5.1", turnover_rate="20"),
        _bar(symbol="DDD", trade_date=d2, close="5.0", pre_close="5.0", high="5.1", turnover_rate="20"),
        _bar(symbol="DDD", trade_date=d3, close="5.5", pre_close="5.0", high="5.5", turnover_rate="20"),
        _bar(symbol="DDD", trade_date=d4, close="6.0", pre_close="5.5", high="6.0", turnover_rate="20"),
        _bar(symbol="DDD", trade_date=d5, close="7.0", pre_close="6.0", high="7.0", turnover_rate="20"),
    ]


def test_profit_effect_analyzer_calculates_from_repository_data() -> None:
    analyzer = MarketProfitEffectAnalyzer(_FakeRepository(_build_bars()))  # type: ignore[arg-type]
    metrics = analyzer.calculate(date(2026, 4, 20))

    assert metrics.limit_up_yesterday_avg_return is not None
    assert metrics.limit_up_yesterday_avg_return > Decimal("0")
    assert metrics.consecutive_limit_up_yesterday_avg_return is not None
    assert metrics.hot_stock_4d_avg_return is not None
    assert metrics.hot_stock_4d_avg_return > Decimal("0")


def test_tolerance_analyzer_calculates_broken_limit_and_hot_stock_metrics() -> None:
    analyzer = MarketToleranceAnalyzer(_FakeRepository(_build_bars()))  # type: ignore[arg-type]
    metrics = analyzer.calculate(date(2026, 4, 20))

    assert metrics.broken_limit_up_yesterday_avg_return is not None
    assert metrics.hot_stock_close_above_avg_price_ratio is not None
    assert metrics.hot_stock_max_drawdown_median is not None


def test_emotion_analyzer_calculates_broken_ratio_and_three_day_breakout() -> None:
    analyzer = MarketEmotionAnalyzer(_FakeRepository(_build_bars()))  # type: ignore[arg-type]
    metrics = analyzer.calculate(date(2026, 4, 20))

    assert metrics.pct_above_9_5_count >= 1
    assert metrics.broken_limit_up_ratio is not None
    assert metrics.pct_above_30_in_3d_count >= 1
