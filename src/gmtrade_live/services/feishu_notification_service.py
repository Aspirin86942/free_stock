"""飞书通知服务。"""

from __future__ import annotations

import logging
from typing import Any

import requests

from gmtrade_live.config import FeishuConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.market_models import MarketCloseReport

logger = logging.getLogger(__name__)


class FeishuNotificationService:
    """飞书 Webhook 通知服务。"""

    def __init__(self, config: FeishuConfig) -> None:
        self.config = config

    def send_market_close_report(self, report: MarketCloseReport) -> None:
        """发送盘后市场分析报告到飞书。"""
        logger.info(f"发送盘后报告到飞书: {report.report_trade_date}")

        # 构建飞书消息
        message = self._build_message(report)

        # 发送到飞书 Webhook
        try:
            response = requests.post(
                self.config.webhook,
                json=message,
                timeout=10,
            )
            response.raise_for_status()
            logger.info("飞书消息发送成功")
        except requests.RequestException as exc:
            raise ServiceError(
                code="feishu.send_failed",
                message=f"飞书消息发送失败: {exc}",
                retryable=True,
                context={"webhook": self.config.webhook},
            ) from exc

    def _build_message(self, report: MarketCloseReport) -> dict[str, Any]:
        """构建飞书消息格式。"""
        # 标题
        title = f"📊 市场分析日报 - {report.report_trade_date}"

        # 摘要
        summary_text = f"**{report.summary}**"

        # 明细表（最近 10 个交易日）
        table_rows = ["| 交易日 | 上涨家数 | 下跌家数 | 上涨占比 | 成交金额(亿) |"]
        table_rows.append("|--------|----------|----------|----------|--------------|")

        for row in report.daily_rows:
            table_rows.append(
                f"| {row.trade_date} "
                f"| {row.breadth.up_count} "
                f"| {row.breadth.down_count} "
                f"| {row.breadth.up_ratio:.2%} "
                f"| {row.breadth.total_amount / 100000000:.0f} |"
            )

        table_text = "\n".join(table_rows)

        # 飞书消息格式（Markdown）
        content = f"{title}\n\n{summary_text}\n\n{table_text}"

        return {
            "msg_type": "text",
            "content": {"text": content},
        }
