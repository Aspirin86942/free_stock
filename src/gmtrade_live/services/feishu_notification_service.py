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
        """构建飞书消息格式（纯文本）。"""
        lines = []

        # 标题
        lines.append(f"📊 市场分析日报 {report.report_trade_date}")
        lines.append("")

        # 摘要
        lines.append(report.summary)
        lines.append("")

        # 表格 - 最近10个交易日趋势
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("交易日         上涨   下跌    占比   成交额(万亿)  涨停  跌停")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if not report.daily_rows:
            lines.append("暂无可展示数据（可能尚未完成同步或无有效交易样本）")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return {
                "msg_type": "text",
                "content": {"text": "\n".join(lines)},
            }

        for row in report.daily_rows:
            up_ratio = float(row.breadth.up_ratio)
            # 添加涨跌标记
            if up_ratio >= 0.6:
                marker = "🔴"
            elif up_ratio >= 0.4:
                marker = "⚪"
            else:
                marker = "🟢"

            lines.append(
                f"{row.trade_date} {marker}  "
                f"{row.breadth.up_count:>4}  "
                f"{row.breadth.down_count:>4}  "
                f"{row.breadth.up_ratio:>6.2%}  "
                f"{row.breadth.total_amount / 1000000000000:>10.2f}  "
                f"{row.breadth.limit_up_count:>4}  "
                f"{row.breadth.limit_down_count:>4}"
            )

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")

        # 最新交易日详细指标
        latest_row = report.daily_rows[-1]
        lines.append("📈 市场情绪指标（最新交易日）")
        lines.append(f"  • 涨幅 >9.5%: {latest_row.emotion.pct_above_9_5_count}家")
        lines.append(f"  • 跌幅 <-9.5%: {latest_row.emotion.pct_below_minus_9_5_count}家")
        lines.append("")

        lines.append("⚠️ 风险提示")
        lines.append(f"  • ST股票: {latest_row.tolerance.st_count}家")
        if latest_row.tolerance.delisting_risk_count > 0:
            lines.append(f"  • 退市风险: {latest_row.tolerance.delisting_risk_count}家")
        lines.append("")

        if report.data_quality_flags:
            lines.append("🧪 口径说明")
            for flag in report.data_quality_flags:
                lines.append(f"  • {flag}")
            lines.append("")

        lines.append("🔴 大涨(≥60%)  ⚪ 震荡(40-60%)  🟢 大跌(<40%)")

        return {
            "msg_type": "text",
            "content": {"text": "\n".join(lines)},
        }
