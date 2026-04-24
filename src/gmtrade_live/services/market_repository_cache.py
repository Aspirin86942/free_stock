"""市场分析报告期的只读缓存仓储。"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from gmtrade_live.market_models import DailyBar


class MarketDataRepository(Protocol):
    """市场分析器依赖的最小只读仓储接口。"""

    def get_recent_trade_dates(self, end_date: date, limit: int) -> list[date]:
        """获取最近交易日列表。"""

    def get_daily_bars_by_date(self, trade_date: date) -> list[DailyBar]:
        """获取指定交易日的全市场日线。"""

    def get_daily_bars(self, symbols: list[str], start_date: date, end_date: date) -> list[DailyBar]:
        """获取指定股票区间日线。"""

    def get_security_name_map(self, symbols: list[str]) -> dict[str, str]:
        """获取证券名称映射。"""

    def get_security_listed_date_map(self, symbols: list[str]) -> dict[str, date]:
        """获取证券上市日期映射。"""

    def get_trade_dates_between(self, start_date: date, end_date: date) -> list[date]:
        """获取区间交易日列表。"""


class CachedMarketDataRepository:
    """为单次报告生成复用高频只读查询结果。

    为什么放在服务层：底层 MySQL 仓储保持无状态，避免跨任务缓存旧数据；
    单次盘后报告内的同日行情、交易日列表和证券元数据则天然可以复用。
    """

    def __init__(self, repository: MarketDataRepository) -> None:
        self._repository = repository
        self._recent_trade_dates_cache: dict[tuple[date, int], list[date]] = {}
        self._daily_bars_by_date_cache: dict[date, list[DailyBar]] = {}
        self._daily_bars_cache: dict[tuple[tuple[str, ...], date, date], list[DailyBar]] = {}
        self._trade_dates_between_cache: dict[tuple[date, date], list[date]] = {}
        self._security_name_cache: dict[str, str] = {}
        self._security_listed_date_cache: dict[str, date] = {}
        self._security_name_misses: set[str] = set()
        self._security_listed_date_misses: set[str] = set()

    def get_recent_trade_dates(self, end_date: date, limit: int) -> list[date]:
        """缓存最近交易日查询，避免 analyzer 间重复查询。"""
        key = (end_date, limit)
        if key in self._recent_trade_dates_cache:
            return list(self._recent_trade_dates_cache[key])

        reusable_dates = self._find_reusable_recent_trade_dates(end_date, limit)
        if reusable_dates is not None:
            self._recent_trade_dates_cache[key] = reusable_dates
            return list(reusable_dates)

        self._recent_trade_dates_cache[key] = list(
            self._repository.get_recent_trade_dates(end_date, limit)
        )
        return list(self._recent_trade_dates_cache[key])

    def _find_reusable_recent_trade_dates(self, end_date: date, limit: int) -> list[date] | None:
        """从同一 end_date 已缓存的大窗口派生小窗口。"""
        reusable_limits = [
            cached_limit
            for cached_end_date, cached_limit in self._recent_trade_dates_cache
            if cached_end_date == end_date and cached_limit >= limit
        ]
        if not reusable_limits:
            return None

        # 选最小可复用窗口，减少切片来源差异，仍保持“最近 N 日”的升序语义。
        source_key = (end_date, min(reusable_limits))
        return list(self._recent_trade_dates_cache[source_key][-limit:])

    def get_daily_bars_by_date(self, trade_date: date) -> list[DailyBar]:
        """缓存单日全市场日线，这是报告生成期最高频的大结果集。"""
        if trade_date not in self._daily_bars_by_date_cache:
            self._daily_bars_by_date_cache[trade_date] = list(
                self._repository.get_daily_bars_by_date(trade_date)
            )
        return list(self._daily_bars_by_date_cache[trade_date])

    def get_daily_bars(self, symbols: list[str], start_date: date, end_date: date) -> list[DailyBar]:
        """按规范化 symbol 集合缓存区间日线查询。"""
        key = (tuple(sorted(set(symbols))), start_date, end_date)
        if not key[0]:
            return []
        if key not in self._daily_bars_cache:
            self._daily_bars_cache[key] = list(
                self._repository.get_daily_bars(list(key[0]), start_date, end_date)
            )
        return list(self._daily_bars_cache[key])

    def get_security_name_map(self, symbols: list[str]) -> dict[str, str]:
        """增量缓存证券名称，已确认缺失的 symbol 不重复查。"""
        requested_symbols = list(dict.fromkeys(symbols))
        missing_symbols = [
            symbol
            for symbol in requested_symbols
            if symbol not in self._security_name_cache and symbol not in self._security_name_misses
        ]
        if missing_symbols:
            fetched_map = self._repository.get_security_name_map(missing_symbols)
            self._security_name_cache.update(fetched_map)
            self._security_name_misses.update(set(missing_symbols) - set(fetched_map))
        return {
            symbol: self._security_name_cache[symbol]
            for symbol in requested_symbols
            if symbol in self._security_name_cache
        }

    def get_security_listed_date_map(self, symbols: list[str]) -> dict[str, date]:
        """增量缓存上市日期，避免热门股解析重复访问证券主数据。"""
        requested_symbols = list(dict.fromkeys(symbols))
        missing_symbols = [
            symbol
            for symbol in requested_symbols
            if symbol not in self._security_listed_date_cache
            and symbol not in self._security_listed_date_misses
        ]
        if missing_symbols:
            fetched_map = self._repository.get_security_listed_date_map(missing_symbols)
            self._security_listed_date_cache.update(fetched_map)
            self._security_listed_date_misses.update(set(missing_symbols) - set(fetched_map))
        return {
            symbol: self._security_listed_date_cache[symbol]
            for symbol in requested_symbols
            if symbol in self._security_listed_date_cache
        }

    def get_trade_dates_between(self, start_date: date, end_date: date) -> list[date]:
        """缓存区间交易日查询，支撑热门股上市满 250 日判断。"""
        key = (start_date, end_date)
        if key not in self._trade_dates_between_cache:
            self._trade_dates_between_cache[key] = list(
                self._repository.get_trade_dates_between(start_date, end_date)
            )
        return list(self._trade_dates_between_cache[key])

    def __getattr__(self, name: str) -> object:
        """透传非分析期高频方法，兼容作业中 checkpoint 等仓储能力。"""
        return getattr(self._repository, name)
