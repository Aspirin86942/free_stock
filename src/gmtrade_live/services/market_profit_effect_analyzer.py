"""赚钱效应分析器。"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from gmtrade_live.market_models import DailyBar, ProfitEffectMetrics
from gmtrade_live.services.hot_stock_resolver import HotStockResolver
from gmtrade_live.services.market_bar_filters import is_valid_return_bar
from gmtrade_live.services.market_repository_cache import MarketDataRepository

logger = logging.getLogger(__name__)


class MarketProfitEffectAnalyzer:
    """赚钱效应指标分析器。"""

    def __init__(
        self,
        repository: MarketDataRepository,
        hot_stock_resolver: HotStockResolver | None = None,
    ) -> None:
        self.repository = repository
        self.hot_stock_resolver = hot_stock_resolver or HotStockResolver(repository)

    def calculate(self, trade_date: date) -> ProfitEffectMetrics:
        """计算指定交易日的赚钱效应指标。"""
        logger.info(f"计算赚钱效应指标: {trade_date}")

        recent_dates = self.repository.get_recent_trade_dates(trade_date, 3)
        if len(recent_dates) < 2:
            return ProfitEffectMetrics(
                limit_up_yesterday_avg_return=None,
                consecutive_limit_up_yesterday_avg_return=None,
                hot_stock_4d_avg_return=None,
            )

        previous_trade_date = recent_dates[-2]
        previous_bars = self.repository.get_daily_bars_by_date(previous_trade_date)
        current_bars = self.repository.get_daily_bars_by_date(trade_date)
        current_by_symbol = {bar.symbol: bar for bar in current_bars}

        limit_up_symbols = [
            bar.symbol
            for bar in previous_bars
            if bar.has_trade and not bar.suspended and self._is_limit_up(bar)
        ]
        limit_up_avg_return = self._average_return(limit_up_symbols, previous_bars, current_by_symbol)

        consecutive_limit_up_avg_return: Decimal | None = None
        if len(recent_dates) >= 3:
            pre_previous_trade_date = recent_dates[-3]
            pre_previous_bars = self.repository.get_daily_bars_by_date(pre_previous_trade_date)
            pre_previous_by_symbol = {bar.symbol: bar for bar in pre_previous_bars}
            consecutive_symbols = [
                symbol
                for symbol in limit_up_symbols
                if symbol in pre_previous_by_symbol and self._is_limit_up(pre_previous_by_symbol[symbol])
            ]
            consecutive_limit_up_avg_return = self._average_return(
                consecutive_symbols, previous_bars, current_by_symbol
            )

        hot_stock_4d_avg_return = self._calculate_hot_stock_4d_avg_return(
            trade_date=trade_date,
        )

        return ProfitEffectMetrics(
            limit_up_yesterday_avg_return=limit_up_avg_return,
            consecutive_limit_up_yesterday_avg_return=consecutive_limit_up_avg_return,
            hot_stock_4d_avg_return=hot_stock_4d_avg_return,
        )

    def _average_return(
        self,
        symbols: list[str],
        previous_bars: list[DailyBar],
        current_by_symbol: dict[str, DailyBar],
    ) -> Decimal | None:
        previous_by_symbol = {bar.symbol: bar for bar in previous_bars}
        returns: list[Decimal] = []

        for symbol in symbols:
            previous_bar = previous_by_symbol.get(symbol)
            current_bar = current_by_symbol.get(symbol)
            if (
                not is_valid_return_bar(previous_bar)
                or not is_valid_return_bar(current_bar)
            ):
                continue
            returns.append((current_bar.close - previous_bar.close) / previous_bar.close)

        if not returns:
            return None
        return sum(returns) / Decimal(len(returns))

    def _is_limit_up(self, bar: DailyBar) -> bool:
        if bar.pre_close <= Decimal("0"):
            return False
        pct_change = (bar.close - bar.pre_close) / bar.pre_close
        limit_threshold = Decimal("0.05") if bar.is_st else Decimal("0.10")
        return pct_change >= limit_threshold * Decimal("0.99")

    def _calculate_hot_stock_4d_avg_return(
        self,
        *,
        trade_date: date,
    ) -> Decimal | None:
        hot_symbols = sorted(self.hot_stock_resolver.resolve(trade_date))
        if not hot_symbols:
            return None

        recent_dates = self.repository.get_recent_trade_dates(trade_date, 5)
        if len(recent_dates) < 5:
            return None
        start_trade_date = recent_dates[-5]

        history_bars = self.repository.get_daily_bars(hot_symbols, start_trade_date, trade_date)
        bars_by_symbol: dict[str, dict[date, DailyBar]] = {}
        for bar in history_bars:
            bars_by_symbol.setdefault(bar.symbol, {})[bar.trade_date] = bar

        returns: list[Decimal] = []
        for symbol in hot_symbols:
            symbol_bars = bars_by_symbol.get(symbol, {})
            start_bar = symbol_bars.get(start_trade_date)
            end_bar = symbol_bars.get(trade_date)
            if not is_valid_return_bar(start_bar) or not is_valid_return_bar(end_bar):
                continue
            returns.append((end_bar.close - start_bar.close) / start_bar.close)

        if not returns:
            return None
        return sum(returns) / Decimal(len(returns))
