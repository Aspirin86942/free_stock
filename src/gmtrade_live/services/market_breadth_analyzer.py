"""市场宽度分析器。"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from gmtrade_live.market_models import DailyBar, MarketBreadthMetrics
from gmtrade_live.services.market_bar_filters import (
    filter_price_calculable_bars,
    filter_tradable_bars,
)
from gmtrade_live.services.market_repository_cache import MarketDataRepository

logger = logging.getLogger(__name__)


class MarketBreadthAnalyzer:
    """市场整体指标分析器。"""

    def __init__(self, repository: MarketDataRepository) -> None:
        self.repository = repository

    def calculate(self, trade_date: date) -> MarketBreadthMetrics:
        """计算指定交易日的市场宽度指标。"""
        logger.info(f"计算市场宽度指标: {trade_date}")

        # 获取当日所有股票数据
        bars = self.repository.get_daily_bars_by_date(trade_date)

        if not bars:
            logger.warning(f"没有找到 {trade_date} 的数据")
            return MarketBreadthMetrics(
                up_count=0,
                down_count=0,
                up_ratio=Decimal("0"),
                total_amount=Decimal("0"),
                limit_up_count=0,
                limit_down_count=0,
                new_high_20d_count=0,
                new_low_20d_count=0,
                new_high_60d_count=0,
                new_low_60d_count=0,
            )

        # 先排除停牌/无交易，再跳过 pre_close 异常的单行脏数据，避免个别坏行中断整份日报。
        tradable_bars = filter_tradable_bars(bars)
        valid_bars = filter_price_calculable_bars(
            tradable_bars,
            logger=logger,
            context="market_breadth",
        )

        # 计算涨跌家数（对比昨收价）
        up_count = sum(1 for bar in valid_bars if bar.close > bar.pre_close)
        down_count = sum(1 for bar in valid_bars if bar.close < bar.pre_close)
        total_count = len(valid_bars)
        up_ratio = Decimal(up_count) / Decimal(total_count) if total_count > 0 else Decimal("0")

        # 计算总成交金额
        total_amount = sum(bar.amount for bar in valid_bars)

        # 计算涨停/跌停数量
        limit_up_count = 0
        limit_down_count = 0
        for bar in valid_bars:
            pct_change = (bar.close - bar.pre_close) / bar.pre_close
            # ST 股票涨跌停限制为 5%，其他为 10%
            limit_threshold = Decimal("0.05") if bar.is_st else Decimal("0.10")

            if pct_change >= limit_threshold * Decimal("0.99"):  # 9.9% 或 4.95%
                limit_up_count += 1
            elif pct_change <= -limit_threshold * Decimal("0.99"):
                limit_down_count += 1

        symbols = [bar.symbol for bar in valid_bars]
        new_high_low_counts = self._count_new_high_low_by_windows(
            trade_date=trade_date,
            symbols=symbols,
            lookback_trade_days_list=(20, 60),
        )
        new_high_20d_count, new_low_20d_count = new_high_low_counts[20]
        new_high_60d_count, new_low_60d_count = new_high_low_counts[60]

        logger.info(
            f"市场宽度: 上涨{up_count}家, 下跌{down_count}家, "
            f"上涨占比{up_ratio:.2%}, 成交额{total_amount/100000000:.0f}亿, "
            f"涨停{limit_up_count}家, 跌停{limit_down_count}家"
        )

        return MarketBreadthMetrics(
            up_count=up_count,
            down_count=down_count,
            up_ratio=up_ratio,
            total_amount=total_amount,
            limit_up_count=limit_up_count,
            limit_down_count=limit_down_count,
            new_high_20d_count=new_high_20d_count,
            new_low_20d_count=new_low_20d_count,
            new_high_60d_count=new_high_60d_count,
            new_low_60d_count=new_low_60d_count,
        )

    def _count_new_high_low(
        self,
        *,
        trade_date: date,
        symbols: list[str],
        lookback_trade_days: int,
    ) -> tuple[int, int]:
        if not symbols:
            return 0, 0

        trade_dates = self.repository.get_recent_trade_dates(trade_date, lookback_trade_days + 1)
        if len(trade_dates) < lookback_trade_days + 1:
            return 0, 0

        start_date = trade_dates[0]
        history_bars = self.repository.get_daily_bars(symbols, start_date, trade_date)

        bars_by_symbol: dict[str, list[DailyBar]] = {}
        for bar in history_bars:
            bars_by_symbol.setdefault(bar.symbol, []).append(bar)

        high_count = 0
        low_count = 0
        for symbol in symbols:
            symbol_bars = sorted(
                bars_by_symbol.get(symbol, []),
                key=lambda item: item.trade_date,
            )
            if len(symbol_bars) < lookback_trade_days + 1:
                continue

            current_bar = symbol_bars[-1]
            previous_closes = [bar.close for bar in symbol_bars[:-1] if bar.close > Decimal("0")]
            if not previous_closes:
                continue

            if current_bar.close > max(previous_closes):
                high_count += 1
            if current_bar.close < min(previous_closes):
                low_count += 1

        return high_count, low_count

    def _count_new_high_low_by_windows(
        self,
        *,
        trade_date: date,
        symbols: list[str],
        lookback_trade_days_list: tuple[int, ...],
    ) -> dict[int, tuple[int, int]]:
        """一次历史查询计算多个新高/新低窗口。

        为什么保留旧单窗口方法：历史调用方和单元定位仍可复用；报告主路径则用该方法
        避免 20 日与 60 日窗口分别查交易日和区间日线。
        """
        default_counts = {lookback: (0, 0) for lookback in lookback_trade_days_list}
        if not symbols or not lookback_trade_days_list:
            return default_counts

        max_lookback_trade_days = max(lookback_trade_days_list)
        trade_dates = self.repository.get_recent_trade_dates(
            trade_date,
            max_lookback_trade_days + 1,
        )
        if len(trade_dates) < max_lookback_trade_days + 1:
            return default_counts

        start_date = trade_dates[0]
        history_bars = self.repository.get_daily_bars(symbols, start_date, trade_date)

        bars_by_symbol: dict[str, list[DailyBar]] = {}
        for bar in history_bars:
            bars_by_symbol.setdefault(bar.symbol, []).append(bar)

        counts = dict(default_counts)
        sorted_lookbacks = tuple(sorted(lookback_trade_days_list))
        for lookback_trade_days in sorted_lookbacks:
            high_count = 0
            low_count = 0
            required_bar_count = lookback_trade_days + 1
            for symbol in symbols:
                symbol_bars = sorted(
                    bars_by_symbol.get(symbol, []),
                    key=lambda item: item.trade_date,
                )
                if len(symbol_bars) < required_bar_count:
                    continue

                window_bars = symbol_bars[-required_bar_count:]
                current_bar = window_bars[-1]
                previous_closes = [bar.close for bar in window_bars[:-1] if bar.close > Decimal("0")]
                if not previous_closes:
                    continue

                if current_bar.close > max(previous_closes):
                    high_count += 1
                if current_bar.close < min(previous_closes):
                    low_count += 1
            counts[lookback_trade_days] = (high_count, low_count)
        return counts
