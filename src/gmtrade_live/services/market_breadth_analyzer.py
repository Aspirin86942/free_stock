"""市场宽度分析器。"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from gmtrade_live.market_models import MarketBreadthMetrics
from gmtrade_live.repositories.mysql_market_repository import MySQLMarketRepository

logger = logging.getLogger(__name__)


class MarketBreadthAnalyzer:
    """市场整体指标分析器。"""

    def __init__(self, repository: MySQLMarketRepository) -> None:
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
                new_high_20d_count=0,
                new_low_20d_count=0,
                new_high_60d_count=0,
                new_low_60d_count=0,
            )

        # 过滤有效交易数据（排除停牌和无交易的股票）
        valid_bars = [bar for bar in bars if bar.has_trade and not bar.suspended]

        # 计算涨跌家数（对比昨收价）
        up_count = sum(1 for bar in valid_bars if bar.close > bar.pre_close)
        down_count = sum(1 for bar in valid_bars if bar.close < bar.pre_close)
        total_count = len(valid_bars)
        up_ratio = Decimal(up_count) / Decimal(total_count) if total_count > 0 else Decimal("0")

        # 计算总成交金额
        total_amount = sum(bar.amount for bar in valid_bars)

        # TODO: 实现新高新低统计（需要查询历史数据）
        # 当前简化实现，返回 0
        new_high_20d_count = 0
        new_low_20d_count = 0
        new_high_60d_count = 0
        new_low_60d_count = 0

        logger.info(
            f"市场宽度: 上涨{up_count}家, 下跌{down_count}家, "
            f"上涨占比{up_ratio:.2%}, 成交额{total_amount/100000000:.0f}亿"
        )

        return MarketBreadthMetrics(
            up_count=up_count,
            down_count=down_count,
            up_ratio=up_ratio,
            total_amount=total_amount,
            new_high_20d_count=new_high_20d_count,
            new_low_20d_count=new_low_20d_count,
            new_high_60d_count=new_high_60d_count,
            new_low_60d_count=new_low_60d_count,
        )
