"""热门股共享解析器。"""

from __future__ import annotations

import logging
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

    def resolve(self, trade_date: date) -> set[str]:
        """解析交易日对应的热门股列表。

        逻辑以交易日 T 的前一交易日 T-1 为基准，保守跳过任何缺失数据。
        """
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
            return set()
        if len(recent_trade_dates) < 2:
            logger.info(
                "热门股解析提前结束：缺少前一交易日",
                extra={"trade_date": str(trade_date)},
            )
            return set()

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
            return set()

        candidate_bars = [
            bar
            for bar in previous_bars
            if self._is_hot_bar(bar)
        ]
        if not candidate_bars:
            return set()

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
            return set()

        hot_symbols: set[str] = set()
        for bar in candidate_bars:
            listed_date = listed_date_map.get(bar.symbol)
            if listed_date is None:
                continue
            if not self._has_minimum_listed_trade_days(listed_date, previous_trade_date):
                continue
            hot_symbols.add(bar.symbol)

        resolved_symbols = hot_symbols
        logger.info(
            "热门股解析完成",
            extra={
                "trade_date": str(trade_date),
                "previous_trade_date": str(previous_trade_date),
                "hot_stock_count": len(resolved_symbols),
            },
        )
        return resolved_symbols

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

    def _has_minimum_listed_trade_days(self, listed_date: date, previous_trade_date: date) -> bool:
        """按实际交易日计数，只有满 250 个交易日才允许进入热门股池。

        为什么不能用自然日：上市日期和分析日之间会穿插周末与节假日，
        只有交易日数量才能准确体现股票真实参与市场交易的时间。
        """
        trade_dates = self.repository.get_trade_dates_between(listed_date, previous_trade_date)
        if not trade_dates:
            logger.info(
                "热门股解析提前结束：交易日列表为空",
                extra={
                    "listed_date": str(listed_date),
                    "previous_trade_date": str(previous_trade_date),
                },
            )
            return False
        return len(trade_dates) >= 250
