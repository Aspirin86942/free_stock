"""运行时调度器，负责任务调度、重试和日志。"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from gmtrade_live.config import RuntimeConfig
from gmtrade_live.services.market_close_job import run_market_close_job

logger = logging.getLogger(__name__)


class RuntimeScheduler:
    """运行时调度器。"""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.scheduler = BlockingScheduler(timezone=config.gm.timezone)

    def start(self) -> None:
        """启动调度器。"""
        logger.info("启动调度器")

        # 注册盘后分析任务
        if self.config.market_analysis.enabled:
            self._register_market_close_job()

        # 注册自动交易任务（如果启用）
        if self.config.trade.enabled:
            logger.warning("自动交易任务已启用，但当前版本未实现")

        # 启动调度器
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("调度器已停止")

    def _register_market_close_job(self) -> None:
        """注册盘后分析任务。"""
        # 解析报告时间（格式：HH:MM）
        hour, minute = map(int, self.config.market_analysis.report_time.split(":"))

        # 创建 Cron 触发器（每个交易日的指定时间）
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=self.config.gm.timezone,
        )

        # 注册任务
        self.scheduler.add_job(
            func=self._run_market_close_job_with_retry,
            trigger=trigger,
            id="market_close_job",
            name="盘后市场分析任务",
            max_instances=1,
        )

        logger.info(
            f"盘后分析任务已注册，触发时间: 每日 {self.config.market_analysis.report_time}"
        )

    def _run_market_close_job_with_retry(self) -> None:
        """执行盘后任务（带重试机制）。"""
        max_attempts = self.config.scheduler.max_attempts
        retry_interval_seconds = self.config.scheduler.retry_interval_minutes * 60

        for attempt in range(1, max_attempts + 1):
            logger.info(f"盘后任务执行，尝试 {attempt}/{max_attempts}")

            result = run_market_close_job(self.config)

            if result.success:
                logger.info(
                    f"盘后任务执行成功: {result.message}, "
                    f"同步行数: {result.sync_inserted_rows}, "
                    f"报告日期: {result.report_trade_date}"
                )
                return

            logger.error(f"盘后任务执行失败: {result.message}")

            if attempt < max_attempts:
                logger.info(f"等待 {self.config.scheduler.retry_interval_minutes} 分钟后重试")
                time.sleep(retry_interval_seconds)

        logger.error(f"盘后任务执行失败，已达到最大重试次数 {max_attempts}")

    def run_once(self) -> None:
        """手动触发一次盘后任务（用于测试）。"""
        logger.info("手动触发盘后任务")
        self._run_market_close_job_with_retry()
