"""热门股共享解析器。"""

from __future__ import annotations

import logging
from bisect import bisect_left
from datetime import date
from decimal import Decimal
from typing import Protocol

from gmtrade_live.market_models import DailyBar

logger = logging.getLogger(__name__)


class HotStockRepository(Protocol):
    """热门股解析所需的最小仓储接口。"""

    def get_recent_trade_dates(self, end_date: date, limit: int) -> list[date]:
        """获取最近交易日列表，包含 end_date 且按升序排列。"""

    def get_daily_bars_by_date(self, trade_date: date) -> list[DailyBar]:
        """获取指定交易日的日线数据。"""

    def get_security_listed_date_map(self, symbols: list[str]) -> dict[str, date]:
        """获取证券上市日期映射。"""

    def get_trade_dates_between(self, start_date: date, end_date: date) -> list[date]:
        """获取区间内实际交易日列表。"""


class HotStockResolver:
    """基于前一交易日筛选热门股。"""

    def __init__(self, repository: HotStockRepository) -> None:
        self.repository = repository
        self._resolved_symbols_cache: dict[date, frozenset[str]] = {}

    def resolve(self, trade_date: date) -> set[str]:
        """解析交易日对应的热门股列表。

        逻辑以交易日 T 的前一交易日 T-1 为基准，保守跳过任何缺失数据。
        """
        if trade_date in self._resolved_symbols_cache:
            return set(self._resolved_symbols_cache[trade_date])

        logger.info(
            "开始解析热门股",
            extra={"trade_date": str(trade_date)},
        )
        recent_trade_dates = self.repository.get_recent_trade_dates(trade_date, 2)
        if not recent_trade_dates or recent_trade_dates[-1] != trade_date:
            logger.info(
                "热门股解析提前结束：输入日期不是交易日或最近交易日列表为空",
                extra={"trade_date": str(trade_date)},
            )
            return self._cache_resolved_symbols(trade_date, set())
        if len(recent_trade_dates) < 2:
            logger.info(
                "热门股解析提前结束：缺少前一交易日",
                extra={"trade_date": str(trade_date)},
            )
            return self._cache_resolved_symbols(trade_date, set())

        previous_trade_date = recent_trade_dates[-2]
        previous_bars = self.repository.get_daily_bars_by_date(previous_trade_date)
        if not previous_bars:
            logger.info(
                "热门股解析提前结束：前一交易日日线为空",
                extra={
                    "trade_date": str(trade_date),
                    "previous_trade_date": str(previous_trade_date),
                },
            )
            return self._cache_resolved_symbols(trade_date, set())

        candidate_bars = [
            bar
            for bar in previous_bars
            if self._is_hot_bar(bar)
        ]
        if not candidate_bars:
            return self._cache_resolved_symbols(trade_date, set())

        symbols = [bar.symbol for bar in candidate_bars]
        listed_date_map = self.repository.get_security_listed_date_map(symbols)
        if not listed_date_map:
            logger.info(
                "热门股解析提前结束：上市日期映射为空",
                extra={
                    "trade_date": str(trade_date),
                    "previous_trade_date": str(previous_trade_date),
                },
            )
            return self._cache_resolved_symbols(trade_date, set())

        hot_symbols = self._filter_symbols_by_listed_trade_days(
            candidate_bars=candidate_bars,
            listed_date_map=listed_date_map,
            previous_trade_date=previous_trade_date,
        )

        resolved_symbols = hot_symbols
        logger.info(
            "热门股解析完成",
            extra={
                "trade_date": str(trade_date),
                "previous_trade_date": str(previous_trade_date),
                "hot_stock_count": len(resolved_symbols),
            },
        )
        return self._cache_resolved_symbols(trade_date, resolved_symbols)

    def _cache_resolved_symbols(self, trade_date: date, symbols: set[str]) -> set[str]:
        """缓存解析结果，并返回副本避免调用方误改内部状态。"""
        self._resolved_symbols_cache[trade_date] = frozenset(symbols)
        return set(symbols)

    def _is_hot_bar(self, bar: DailyBar) -> bool:
        """判断前一交易日行情是否满足热门股基础条件。"""
        return (
            bar.has_trade
            and not bar.suspended
            and not bar.is_st
            and bar.close > Decimal("10")
            and self._is_turnover_over_10(bar.turnover_rate)
        )

    def _is_turnover_over_10(self, turnover_rate: Decimal | None) -> bool:
        """兼容百分比口径与比例口径的换手率阈值判断。"""
        if turnover_rate is None:
            return False
        if turnover_rate > Decimal("1"):
            return turnover_rate > Decimal("10")
        return turnover_rate > Decimal("0.10")

    def _filter_symbols_by_listed_trade_days(
        self,
        *,
        candidate_bars: list[DailyBar],
        listed_date_map: dict[str, date],
        previous_trade_date: date,
    ) -> set[str]:
        """按实际交易日批量过滤上市未满 250 日的候选股票。

        为什么一次查询最早上市日至前一交易日：候选股票可能有几百个，
        逐个查询交易日会把报告生成放大成大量重复 SQL。
        """
        available_listed_dates = [
            listed_date
            for bar in candidate_bars
            if (listed_date := listed_date_map.get(bar.symbol)) is not None
        ]
        if not available_listed_dates:
            return set()

        earliest_listed_date = min(available_listed_dates)
        trade_dates = self.repository.get_trade_dates_between(earliest_listed_date, previous_trade_date)
        if not trade_dates:
            logger.info(
                "热门股解析提前结束：交易日列表为空",
                extra={
                    "listed_date": str(earliest_listed_date),
                    "previous_trade_date": str(previous_trade_date),
                },
            )
            return set()

        sorted_trade_dates = sorted(trade_dates)
        hot_symbols: set[str] = set()
        for bar in candidate_bars:
            listed_date = listed_date_map.get(bar.symbol)
            if listed_date is None:
                continue
            first_trade_index = bisect_left(sorted_trade_dates, listed_date)
            listed_trade_days = len(sorted_trade_dates) - first_trade_index
            if listed_trade_days >= 250:
                hot_symbols.add(bar.symbol)
        return hot_symbols
