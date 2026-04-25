"""情绪指标分析器。"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from gmtrade_live.market_models import DailyBar, EmotionMetrics
from gmtrade_live.services.market_bar_filters import (
    filter_price_calculable_bars,
    filter_tradable_bars,
)
from gmtrade_live.services.market_repository_cache import MarketDataRepository

logger = logging.getLogger(__name__)


class MarketEmotionAnalyzer:
    """情绪指标分析器。"""

    def __init__(self, repository: MarketDataRepository) -> None:
        self.repository = repository

    def calculate(self, trade_date: date) -> EmotionMetrics:
        """计算指定交易日的情绪指标。"""
        logger.info(f"计算情绪指标: {trade_date}")

        # 获取当日所有股票数据
        bars = self.repository.get_daily_bars_by_date(trade_date)

        if not bars:
            logger.warning(f"没有找到 {trade_date} 的数据")
            return EmotionMetrics(
                pct_above_9_5_count=0,
                pct_below_minus_9_5_count=0,
                broken_limit_up_ratio=None,
                pct_above_30_in_3d_count=0,
            )

        # 先排除停牌/无交易，再跳过 pre_close 异常的单行脏数据，避免情绪计算被坏行中断。
        tradable_bars = filter_tradable_bars(bars)
        valid_bars = filter_price_calculable_bars(
            tradable_bars,
            logger=logger,
            context="market_emotion",
        )

        # 计算涨幅 >9.5% 和跌幅 <-9.5% 的数量
        pct_above_9_5_count = 0
        pct_below_minus_9_5_count = 0

        for bar in valid_bars:
            pct_change = (bar.close - bar.pre_close) / bar.pre_close
            if pct_change > Decimal("0.095"):
                pct_above_9_5_count += 1
            elif pct_change < Decimal("-0.095"):
                pct_below_minus_9_5_count += 1

        touched_limit_up_count = sum(1 for bar in valid_bars if self._touched_limit_up(bar))
        broken_limit_up_count = sum(
            1
            for bar in valid_bars
            if self._touched_limit_up(bar) and not self._is_limit_up(bar)
        )
        broken_limit_up_ratio = None
        if touched_limit_up_count > 0:
            broken_limit_up_ratio = Decimal(broken_limit_up_count) / Decimal(touched_limit_up_count)

        pct_above_30_in_3d_count = self._count_pct_above_30_in_3d(
            trade_date=trade_date,
            symbols=[bar.symbol for bar in valid_bars],
        )

        logger.info(
            f"情绪指标: 涨幅>9.5% {pct_above_9_5_count}家, "
            f"跌幅<-9.5% {pct_below_minus_9_5_count}家"
        )

        return EmotionMetrics(
            pct_above_9_5_count=pct_above_9_5_count,
            pct_below_minus_9_5_count=pct_below_minus_9_5_count,
            broken_limit_up_ratio=broken_limit_up_ratio,
            pct_above_30_in_3d_count=pct_above_30_in_3d_count,
        )

    def _count_pct_above_30_in_3d(self, *, trade_date: date, symbols: list[str]) -> int:
        if not symbols:
            return 0

        recent_dates = self.repository.get_recent_trade_dates(trade_date, 4)
        if len(recent_dates) < 4:
            return 0
        start_trade_date = recent_dates[-4]

        history_bars = self.repository.get_daily_bars(symbols, start_trade_date, trade_date)
        bars_by_symbol: dict[str, dict[date, DailyBar]] = {}
        for bar in history_bars:
            bars_by_symbol.setdefault(bar.symbol, {})[bar.trade_date] = bar

        count = 0
        for symbol in symbols:
            symbol_bars = bars_by_symbol.get(symbol, {})
            start_bar = symbol_bars.get(start_trade_date)
            end_bar = symbol_bars.get(trade_date)
            if start_bar is None or end_bar is None or start_bar.close <= Decimal("0"):
                continue
            pct_change = (end_bar.close - start_bar.close) / start_bar.close
            if pct_change > Decimal("0.30"):
                count += 1
        return count

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
