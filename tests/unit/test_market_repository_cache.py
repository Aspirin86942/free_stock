from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from gmtrade_live.market_models import DailyBar
from gmtrade_live.services.market_repository_cache import CachedMarketDataRepository


def _bar(symbol: str, trade_date: date) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        pre_close=Decimal("10"),
        volume=100,
        amount=Decimal("1000"),
        turnover_rate=Decimal("12"),
        is_st=False,
        suspended=False,
        has_trade=True,
    )


@dataclass
class _FakeRepository:
    bars_by_date: dict[date, list[DailyBar]]
    listed_date_map: dict[str, date]
    name_map: dict[str, str]
    trade_dates: list[date] | None = None

    def __post_init__(self) -> None:
        self.calls: dict[str, int] = {
            "get_recent_trade_dates": 0,
            "get_daily_bars_by_date": 0,
            "get_security_listed_date_map": 0,
            "get_security_name_map": 0,
        }

    def get_recent_trade_dates(self, end_date: date, limit: int) -> list[date]:
        self.calls["get_recent_trade_dates"] += 1
        trade_dates = self.trade_dates or sorted(self.bars_by_date)
        return [trade_date for trade_date in trade_dates if trade_date <= end_date][-limit:]

    def get_daily_bars_by_date(self, trade_date: date) -> list[DailyBar]:
        self.calls["get_daily_bars_by_date"] += 1
        return list(self.bars_by_date.get(trade_date, []))

    def get_security_listed_date_map(self, symbols: list[str]) -> dict[str, date]:
        self.calls["get_security_listed_date_map"] += 1
        return {
            symbol: self.listed_date_map[symbol]
            for symbol in symbols
            if symbol in self.listed_date_map
        }

    def get_security_name_map(self, symbols: list[str]) -> dict[str, str]:
        self.calls["get_security_name_map"] += 1
        return {
            symbol: self.name_map[symbol]
            for symbol in symbols
            if symbol in self.name_map
        }


def test_cached_market_repository_reuses_daily_bars_by_date() -> None:
    trade_date = date(2026, 4, 21)
    repository = _FakeRepository(
        bars_by_date={trade_date: [_bar("AAA", trade_date)]},
        listed_date_map={},
        name_map={},
    )
    cached_repository = CachedMarketDataRepository(repository)

    first_result = cached_repository.get_daily_bars_by_date(trade_date)
    second_result = cached_repository.get_daily_bars_by_date(trade_date)

    assert first_result == second_result
    assert first_result is not second_result
    assert repository.calls["get_daily_bars_by_date"] == 1


def test_cached_market_repository_fetches_only_missing_security_metadata() -> None:
    repository = _FakeRepository(
        bars_by_date={},
        listed_date_map={"AAA": date(2020, 1, 1), "BBB": date(2021, 1, 1)},
        name_map={"AAA": "A公司", "BBB": "B公司"},
    )
    cached_repository = CachedMarketDataRepository(repository)

    assert cached_repository.get_security_listed_date_map(["AAA"]) == {"AAA": date(2020, 1, 1)}
    assert cached_repository.get_security_listed_date_map(["AAA", "BBB"]) == {
        "AAA": date(2020, 1, 1),
        "BBB": date(2021, 1, 1),
    }
    assert cached_repository.get_security_name_map(["AAA"]) == {"AAA": "A公司"}
    assert cached_repository.get_security_name_map(["AAA", "BBB"]) == {
        "AAA": "A公司",
        "BBB": "B公司",
    }

    assert repository.calls["get_security_listed_date_map"] == 2
    assert repository.calls["get_security_name_map"] == 2


def test_cached_market_repository_reuses_larger_recent_trade_date_window() -> None:
    trade_dates = [date(2026, 4, day) for day in range(1, 11)]
    repository = _FakeRepository(
        bars_by_date={},
        listed_date_map={},
        name_map={},
        trade_dates=trade_dates,
    )
    cached_repository = CachedMarketDataRepository(repository)

    assert cached_repository.get_recent_trade_dates(date(2026, 4, 10), 5) == trade_dates[-5:]
    assert cached_repository.get_recent_trade_dates(date(2026, 4, 10), 2) == trade_dates[-2:]

    assert repository.calls["get_recent_trade_dates"] == 1
