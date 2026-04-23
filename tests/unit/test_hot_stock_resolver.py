from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest

from gmtrade_live.market_models import DailyBar
from gmtrade_live.services.hot_stock_resolver import HotStockResolver


@dataclass
class _FakeRepository:
    trade_dates: list[date]
    bars_by_date: dict[date, list[DailyBar]]
    listed_date_map: dict[str, date]

    def get_recent_trade_dates(self, end_date: date, limit: int) -> list[date]:
        return [trade_date for trade_date in self.trade_dates if trade_date <= end_date][-limit:]

    def get_daily_bars_by_date(self, trade_date: date) -> list[DailyBar]:
        return self.bars_by_date.get(trade_date, [])

    def get_security_listed_date_map(self, symbols: list[str]) -> dict[str, date]:
        return {
            symbol: self.listed_date_map[symbol]
            for symbol in symbols
            if symbol in self.listed_date_map
        }

    def get_trade_dates_between(self, start_date: date, end_date: date) -> list[date]:
        return [trade_date for trade_date in self.trade_dates if start_date <= trade_date <= end_date]


def _bar(
    *,
    symbol: str,
    trade_date: date,
    close: str = "11.5",
    turnover_rate: str = "12",
    has_trade: bool = True,
    suspended: bool = False,
    is_st: bool = False,
) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        pre_close=Decimal("10"),
        volume=1000,
        amount=Decimal("10000"),
        turnover_rate=Decimal(turnover_rate),
        is_st=is_st,
        suspended=suspended,
        has_trade=has_trade,
    )


def _build_sparse_trade_dates(count: int = 251) -> list[date]:
    """构造明显稀疏的交易日序列，避免用连续自然日近似交易日。"""
    start_date = date(2025, 1, 1)
    return [start_date + timedelta(days=offset * 2) for offset in range(count)]


def test_hot_stock_resolver_excludes_symbols_listed_for_fewer_than_250_trade_days() -> None:
    trade_dates = _build_sparse_trade_dates()
    trade_date = trade_dates[-1]
    previous_trade_date = trade_dates[-2]
    keeper_listed_date = trade_dates[1]
    dropped_listed_date = trade_dates[2]

    repository = _FakeRepository(
        trade_dates=trade_dates,
        bars_by_date={
            previous_trade_date: [
                _bar(symbol="KEEP", trade_date=previous_trade_date),
                _bar(symbol="DROP", trade_date=previous_trade_date),
            ],
        },
        listed_date_map={
            "KEEP": keeper_listed_date,
            "DROP": dropped_listed_date,
        },
    )

    resolver = HotStockResolver(repository)

    assert resolver.resolve(trade_date) == set()


def test_hot_stock_resolver_keeps_symbols_listed_for_exactly_250_trade_days() -> None:
    trade_dates = _build_sparse_trade_dates()
    trade_date = trade_dates[-1]
    previous_trade_date = trade_dates[-2]
    listed_date = trade_dates[0]

    repository = _FakeRepository(
        trade_dates=trade_dates,
        bars_by_date={
            previous_trade_date: [
                _bar(symbol="KEEP", trade_date=previous_trade_date),
            ]
        },
        listed_date_map={
            "KEEP": listed_date,
        },
    )

    resolver = HotStockResolver(repository)

    assert resolver.resolve(trade_date) == {"KEEP"}


def test_hot_stock_resolver_accepts_percent_turnover_rate_ratio_0_11() -> None:
    trade_dates = _build_sparse_trade_dates()
    trade_date = trade_dates[-1]
    previous_trade_date = trade_dates[-2]

    repository = _FakeRepository(
        trade_dates=trade_dates,
        bars_by_date={
            previous_trade_date: [
                _bar(
                    symbol="KEEP",
                    trade_date=previous_trade_date,
                    close="11.5",
                    turnover_rate="0.11",
                ),
            ],
        },
        listed_date_map={
            "KEEP": trade_dates[0],
        },
    )

    resolver = HotStockResolver(repository)

    assert resolver.resolve(trade_date) == {"KEEP"}


def test_hot_stock_resolver_excludes_symbol_without_listed_date() -> None:
    trade_dates = _build_sparse_trade_dates()
    trade_date = trade_dates[-1]
    previous_trade_date = trade_dates[-2]

    repository = _FakeRepository(
        trade_dates=trade_dates,
        bars_by_date={
            previous_trade_date: [
                _bar(symbol="KEEP", trade_date=previous_trade_date),
            ]
        },
        listed_date_map={},
    )

    resolver = HotStockResolver(repository)

    assert resolver.resolve(trade_date) == set()


def test_hot_stock_resolver_returns_empty_set_when_trade_date_is_not_a_trade_day(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    trade_dates = _build_sparse_trade_dates()
    non_trade_date = trade_dates[-1] + timedelta(days=1)
    repository = _FakeRepository(
        trade_dates=trade_dates,
        bars_by_date={},
        listed_date_map={},
    )

    resolver = HotStockResolver(repository)

    result = resolver.resolve(non_trade_date)

    assert result == set()
    assert "开始解析热门股" in caplog.text
    assert "输入日期不是交易日或最近交易日列表为空" in caplog.text


@pytest.mark.parametrize(
    "trade_dates, bars_by_date, listed_date_map, expected_log",
    [
        (
            [date(2025, 1, 1)],
            {},
            {},
            "热门股解析提前结束：缺少前一交易日",
        ),
        (
            [],
            {},
            {},
            "热门股解析提前结束：输入日期不是交易日或最近交易日列表为空",
        ),
        (
            [date(2025, 1, 1), date(2025, 1, 2)],
            {date(2025, 1, 1): []},
            {},
            "热门股解析提前结束：前一交易日日线为空",
        ),
        (
            [date(2025, 1, 1), date(2025, 1, 2)],
            {
                date(2025, 1, 1): [_bar(symbol="KEEP", trade_date=date(2025, 1, 1))],
            },
            {},
            "热门股解析提前结束：上市日期映射为空",
        ),
        (
            [date(2025, 1, 1), date(2025, 1, 2)],
            {
                date(2025, 1, 1): [_bar(symbol="KEEP", trade_date=date(2025, 1, 1))],
            },
            {"KEEP": date(2025, 1, 3)},
            "热门股解析提前结束：交易日列表为空",
        ),
    ],
)
def test_hot_stock_resolver_logs_early_exit_reasons(
    caplog: pytest.LogCaptureFixture,
    trade_dates: list[date],
    bars_by_date: dict[date, list[DailyBar]],
    listed_date_map: dict[str, date],
    expected_log: str,
) -> None:
    caplog.set_level(logging.INFO)
    trade_date = trade_dates[-1] if trade_dates else date(2025, 1, 1)
    repository = _FakeRepository(
        trade_dates=trade_dates,
        bars_by_date=bars_by_date,
        listed_date_map=listed_date_map,
    )

    resolver = HotStockResolver(repository)

    result = resolver.resolve(trade_date)

    assert result == set()
    assert "开始解析热门股" in caplog.text
    assert expected_log in caplog.text
