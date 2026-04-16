"""盘后市场分析报告生成器。"""

from __future__ import annotations

import logging
from datetime import date

from gmtrade_live.market_models import DailyReportRow, MarketCloseReport
from gmtrade_live.repositories.mysql_market_repository import MySQLMarketRepository
from gmtrade_live.services.market_breadth_analyzer import MarketBreadthAnalyzer
from gmtrade_live.services.market_emotion_analyzer import MarketEmotionAnalyzer
from gmtrade_live.services.market_profit_effect_analyzer import MarketProfitEffectAnalyzer
from gmtrade_live.services.market_tolerance_analyzer import MarketToleranceAnalyzer

logger = logging.getLogger(__name__)


class MarketCloseReportBuilder:
    """盘后市场分析报告生成器。"""

    def __init__(
        self,
        repository: MySQLMarketRepository,
        breadth_analyzer: MarketBreadthAnalyzer,
        profit_effect_analyzer: MarketProfitEffectAnalyzer,
        tolerance_analyzer: MarketToleranceAnalyzer,
        emotion_analyzer: MarketEmotionAnalyzer,
    ) -> None:
        self.repository = repository
        self.breadth_analyzer = breadth_analyzer
        self.profit_effect_analyzer = profit_effect_analyzer
        self.tolerance_analyzer = tolerance_analyzer
        self.emotion_analyzer = emotion_analyzer

    def build(self, report_trade_date: date, recent_trade_days: int) -> MarketCloseReport:
        """生成盘后分析报告（包含最近 N 个交易日明细表）。"""
        logger.info(f"生成盘后报告: {report_trade_date}，最近 {recent_trade_days} 个交易日")

        # 1. 获取最近 N 个交易日
        trade_dates = self.repository.get_recent_trade_dates(report_trade_date, recent_trade_days)
        logger.info(f"获取到 {len(trade_dates)} 个交易日")

        # 2. 逐日计算指标
        daily_rows: list[DailyReportRow] = []
        for trade_date in trade_dates:
            breadth = self.breadth_analyzer.calculate(trade_date)
            profit_effect = self.profit_effect_analyzer.calculate(trade_date)
            tolerance = self.tolerance_analyzer.calculate(trade_date)
            emotion = self.emotion_analyzer.calculate(trade_date)

            daily_rows.append(
                DailyReportRow(
                    trade_date=trade_date,
                    breadth=breadth,
                    profit_effect=profit_effect,
                    tolerance=tolerance,
                    emotion=emotion,
                )
            )

        # 3. 生成摘要（当天数据）
        if daily_rows:
            latest_row = daily_rows[-1]
            summary = (
                f"市场概况：上涨 {latest_row.breadth.up_count} 家，"
                f"下跌 {latest_row.breadth.down_count} 家，"
                f"上涨占比 {latest_row.breadth.up_ratio:.2%}"
            )
        else:
            summary = "暂无数据"

        logger.info(f"报告生成完成，包含 {len(daily_rows)} 个交易日数据")

        return MarketCloseReport(
            report_trade_date=report_trade_date,
            summary=summary,
            daily_rows=daily_rows,
        )
