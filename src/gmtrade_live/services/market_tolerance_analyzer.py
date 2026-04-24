"""容错指标分析器。"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from gmtrade_live.market_models import DailyBar, ToleranceMetrics
from gmtrade_live.services.hot_stock_resolver import HotStockResolver
from gmtrade_live.services.market_repository_cache import MarketDataRepository

logger = logging.getLogger(__name__)


class MarketToleranceAnalyzer:
    """容错指标分析器。"""

    def __init__(
        self,
        repository: MarketDataRepository,
        hot_stock_resolver: HotStockResolver | None = None,
    ) -> None:
        self.repository = repository
        self.hot_stock_resolver = hot_stock_resolver or HotStockResolver(repository)

    def calculate(self, trade_date: date) -> ToleranceMetrics:
        """计算指定交易日的容错指标。"""
        logger.info(f"计算容错指标: {trade_date}")

        # 获取当日所有股票数据
        bars = self.repository.get_daily_bars_by_date(trade_date)

        if not bars:
            logger.warning(f"没有找到 {trade_date} 的数据")
            return ToleranceMetrics(
                st_count=0,
                delisting_risk_count=0,
                broken_limit_up_yesterday_avg_return=None,
                hot_stock_close_above_avg_price_ratio=None,
                hot_stock_max_drawdown_median=None,
            )

        # 过滤有效交易数据
        valid_bars = [bar for bar in bars if bar.has_trade and not bar.suspended]

        # 统计 ST 股票数量
        st_count = sum(1 for bar in valid_bars if bar.is_st)

        # 退市风险标识依赖证券名称关键词，使用 security_master 做 best-effort 识别。
        delisting_risk_count = self._count_delisting_risk_count(
            symbols=[bar.symbol for bar in valid_bars]
        )

        broken_limit_up_yesterday_avg_return = self._calculate_broken_limit_up_yesterday_avg_return(
            trade_date=trade_date,
        )
        hot_stock_close_above_avg_price_ratio = self._calculate_hot_stock_close_above_avg_price_ratio(
            trade_date=trade_date,
            current_bars=valid_bars,
        )
        hot_stock_max_drawdown_median = self._calculate_hot_stock_drawdown_median(
            trade_date=trade_date,
            current_bars=valid_bars,
        )

        logger.info(f"容错指标: ST股票 {st_count}家")

        return ToleranceMetrics(
            st_count=st_count,
            delisting_risk_count=delisting_risk_count,
            broken_limit_up_yesterday_avg_return=broken_limit_up_yesterday_avg_return,
            hot_stock_close_above_avg_price_ratio=hot_stock_close_above_avg_price_ratio,
            hot_stock_max_drawdown_median=hot_stock_max_drawdown_median,
        )

    def _count_delisting_risk_count(self, symbols: list[str]) -> int:
        if not symbols:
            return 0
        security_name_map = self.repository.get_security_name_map(symbols)
        return sum(
            1
            for name in security_name_map.values()
            if self._is_delisting_risk_name(name)
        )

    def _is_delisting_risk_name(self, name: str) -> bool:
        normalized_name = name.replace(" ", "").upper()
        # 使用最保守关键词，避免把普通股票误判成退市风险。
        return normalized_name.startswith("*ST") or normalized_name.startswith("退市")

    def _calculate_broken_limit_up_yesterday_avg_return(self, *, trade_date: date) -> Decimal | None:
        recent_dates = self.repository.get_recent_trade_dates(trade_date, 2)
        if len(recent_dates) < 2:
            return None

        previous_trade_date = recent_dates[-2]
        previous_bars = self.repository.get_daily_bars_by_date(previous_trade_date)
        current_by_symbol = {bar.symbol: bar for bar in self.repository.get_daily_bars_by_date(trade_date)}

        broken_symbols = [
            bar.symbol
            for bar in previous_bars
            if (
                bar.has_trade
                and not bar.suspended
                and self._touched_limit_up(bar)
                and not self._is_limit_up(bar)
            )
        ]
        if not broken_symbols:
            return None

        previous_by_symbol = {bar.symbol: bar for bar in previous_bars}
        returns: list[Decimal] = []
        for symbol in broken_symbols:
            previous_bar = previous_by_symbol.get(symbol)
            current_bar = current_by_symbol.get(symbol)
            if (
                previous_bar is None
                or current_bar is None
                or previous_bar.close <= Decimal("0")
                or not current_bar.has_trade
                or current_bar.suspended
            ):
                continue
            returns.append((current_bar.close - previous_bar.close) / previous_bar.close)

        if not returns:
            return None
        return sum(returns) / Decimal(len(returns))

    def _calculate_hot_stock_close_above_avg_price_ratio(
        self,
        *,
        trade_date: date,
        current_bars: list[DailyBar],
    ) -> Decimal | None:
        hot_symbols = self.hot_stock_resolver.resolve(trade_date)
        if not hot_symbols:
            return None

        hot_bars = [bar for bar in current_bars if bar.symbol in hot_symbols and bar.volume > 0]
        if not hot_bars:
            return None

        close_above_count = 0
        for bar in hot_bars:
            avg_price = bar.amount / Decimal(bar.volume)
            if bar.close > avg_price:
                close_above_count += 1

        return Decimal(close_above_count) / Decimal(len(hot_bars))

    def _calculate_hot_stock_drawdown_median(
        self,
        *,
        trade_date: date,
        current_bars: list[DailyBar],
    ) -> Decimal | None:
        hot_symbols = self.hot_stock_resolver.resolve(trade_date)
        if not hot_symbols:
            return None

        drawdowns = [
            (bar.high - bar.close) / bar.high
            for bar in current_bars
            if bar.symbol in hot_symbols and bar.high > Decimal("0")
        ]
        if not drawdowns:
            return None

        drawdowns.sort()
        middle = len(drawdowns) // 2
        if len(drawdowns) % 2 == 1:
            return drawdowns[middle]
        return (drawdowns[middle - 1] + drawdowns[middle]) / Decimal("2")

    def _is_limit_up(self, bar: DailyBar) -> bool:
        if bar.pre_close <= Decimal("0"):
            return False
        pct_change = (bar.close - bar.pre_close) / bar.pre_close
        limit_threshold = Decimal("0.05") if bar.is_st else Decimal("0.10")
        return pct_change >= limit_threshold * Decimal("0.99")

    def _touched_limit_up(self, bar: DailyBar) -> bool:
        if bar.pre_close <= Decimal("0"):
            return False
        limit_threshold = Decimal("0.05") if bar.is_st else Decimal("0.10")
        limit_up_price = bar.pre_close * (Decimal("1") + limit_threshold)
        return bar.high >= limit_up_price * Decimal("0.99")
