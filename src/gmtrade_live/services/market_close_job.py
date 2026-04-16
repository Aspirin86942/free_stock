"""盘后任务编排：补数 -> 分析 -> 飞书推送。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from gmtrade_live.config import RuntimeConfig
from gmtrade_live.gateways.gm_history_market_gateway import GMHistoryMarketGateway
from gmtrade_live.repositories.mysql_market_repository import MySQLMarketRepository
from gmtrade_live.services.feishu_notification_service import FeishuNotificationService
from gmtrade_live.services.market_breadth_analyzer import MarketBreadthAnalyzer
from gmtrade_live.services.market_close_report_builder import MarketCloseReportBuilder
from gmtrade_live.services.market_data_sync_service import MarketDataSyncService
from gmtrade_live.services.market_emotion_analyzer import MarketEmotionAnalyzer
from gmtrade_live.services.market_profit_effect_analyzer import MarketProfitEffectAnalyzer
from gmtrade_live.services.market_tolerance_analyzer import MarketToleranceAnalyzer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MarketCloseJobResult:
    """盘后任务执行结果。"""

    success: bool
    message: str
    sync_inserted_rows: int
    report_trade_date: str


def run_market_close_job(config: RuntimeConfig) -> MarketCloseJobResult:
    """执行盘后任务：补数 -> 分析 -> 飞书推送。"""
    logger.info("开始执行盘后任务")

    try:
        # 1. 初始化组件
        gateway = GMHistoryMarketGateway()
        gateway.connect(config.gm.token, config.gm.endpoint)

        repository = MySQLMarketRepository(config.mysql)
        repository.connect()
        repository.ensure_tables()

        # 2. 同步市场数据
        sync_service = MarketDataSyncService(config.market_analysis, gateway, repository)
        sync_result = sync_service.sync()
        logger.info(
            f"数据同步完成: {sync_result.latest_trade_date}, "
            f"插入行数: {sync_result.inserted_rows}"
        )

        # 3. 生成盘后分析报告
        breadth_analyzer = MarketBreadthAnalyzer(repository)
        profit_effect_analyzer = MarketProfitEffectAnalyzer(repository)
        tolerance_analyzer = MarketToleranceAnalyzer(repository)
        emotion_analyzer = MarketEmotionAnalyzer(repository)

        report_builder = MarketCloseReportBuilder(
            repository,
            breadth_analyzer,
            profit_effect_analyzer,
            tolerance_analyzer,
            emotion_analyzer,
        )

        report = report_builder.build(
            sync_result.latest_trade_date, config.market_analysis.recent_trade_days
        )
        logger.info(f"报告生成完成: {report.report_trade_date}")

        # 4. 发送飞书通知
        feishu_service = FeishuNotificationService(config.feishu)
        feishu_service.send_market_close_report(report)
        logger.info("飞书通知发送完成")

        # 5. 清理资源
        repository.close()

        return MarketCloseJobResult(
            success=True,
            message="盘后任务执行成功",
            sync_inserted_rows=sync_result.inserted_rows,
            report_trade_date=str(sync_result.latest_trade_date),
        )

    except Exception as exc:
        logger.error(f"盘后任务执行失败: {exc}", exc_info=True)
        return MarketCloseJobResult(
            success=False,
            message=f"盘后任务执行失败: {exc}",
            sync_inserted_rows=0,
            report_trade_date="",
        )
