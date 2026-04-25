"""飞书通知服务。"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import requests

from gmtrade_live.config import FeishuConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.market_models import DailyReportRow, MarketCloseReport

logger = logging.getLogger(__name__)


def render_market_close_report_text(report: MarketCloseReport) -> str:
    """把盘后报告渲染成飞书纯文本，供发送链路和调试预览共用。"""
    return _MarketCloseReportRenderer().render_text(report)


def build_market_close_report_message(report: MarketCloseReport) -> dict[str, Any]:
    """把盘后报告包装成飞书 Webhook 消息体。"""
    return {
        "msg_type": "text",
        "content": {"text": render_market_close_report_text(report)},
    }


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
        return build_market_close_report_message(report)


class _MarketCloseReportRenderer:
    """盘后报告飞书文本渲染器。"""

    def render_text(self, report: MarketCloseReport) -> str:
        """构建飞书消息格式（纯文本）。"""
        lines = []

        # 标题
        lines.append(f"📊 市场分析日报 | {report.report_trade_date}")
        lines.append("")

        if not report.daily_rows:
            lines.append("最近 10 日趋势")
            lines.append("• 暂无可展示数据（可能尚未完成同步或无有效交易样本）")
            return "\n".join(lines)

        # 最新交易日详细指标
        latest_row = report.daily_rows[-1]
        # 飞书群阅读通常先看结论再决定是否展开复盘，这里把摘要放在最前，避免宽表压住关键信息。
        lines.extend(self._build_summary_section(report.summary, latest_row))
        lines.append("")

        lines.append("今日核心")
        lines.append(
            "• 连板溢价：昨日连板股今日平均收益 "
            f"{self._format_percentage(latest_row.profit_effect.consecutive_limit_up_yesterday_avg_return)}"
        )
        lines.append(
            "• 涨停溢价：昨日涨停股今日平均收益 "
            f"{self._format_percentage(latest_row.profit_effect.limit_up_yesterday_avg_return)}"
        )
        lines.append(
            "• 热门股表现：热门股 4 日平均收益 "
            f"{self._format_percentage(latest_row.profit_effect.hot_stock_4d_avg_return)}"
        )
        lines.append("")

        lines.append("容错观察")
        lines.append(
            "• 昨日炸板股今日平均收益："
            f"{self._format_percentage(latest_row.tolerance.broken_limit_up_yesterday_avg_return)}"
        )
        lines.append(
            "• 热门股收盘高于均价占比："
            f"{self._format_percentage(latest_row.tolerance.hot_stock_close_above_avg_price_ratio)}"
        )
        lines.append(
            "• 热门股日内最大回撤中位数："
            f"{self._format_percentage(latest_row.tolerance.hot_stock_max_drawdown_median)}"
        )
        lines.append("")

        lines.extend(self._build_latest_emotion_section(latest_row))
        lines.append("")

        lines.append("最近 10 日趋势")
        for row in report.daily_rows:
            lines.append(self._build_trend_line(row))
        lines.append("")

        if report.data_quality_flags:
            lines.append("口径说明")
            for flag in report.data_quality_flags:
                lines.append(f"• {self._normalize_quality_flag(flag)}")

        return "\n".join(lines)

    def _build_summary_section(self, summary: str, latest_row: DailyReportRow) -> list[str]:
        """构建飞书消息顶部摘要。"""
        return [
            "一眼结论",
            f"• {summary}",
            "• 情绪观察："
            f"涨停 {latest_row.breadth.limit_up_count} 家，"
            f"跌停 {latest_row.breadth.limit_down_count} 家，"
            f"炸板率 {self._format_percentage(latest_row.emotion.broken_limit_up_ratio)}",
            "• 风险观察："
            f"跌幅 < -9.5% 个股 {latest_row.emotion.pct_below_minus_9_5_count} 家，"
            f"退市风险 {latest_row.tolerance.delisting_risk_count} 家",
        ]

    def _build_latest_emotion_section(self, latest_row: DailyReportRow) -> list[str]:
        """构建最新交易日情绪指标分组。"""
        return [
            "市场情绪指标（最新交易日）",
            f"• 涨幅 >9.5%: {latest_row.emotion.pct_above_9_5_count}家",
            f"• 跌幅 <-9.5%: {latest_row.emotion.pct_below_minus_9_5_count}家",
            f"• 炸板率: {self._format_percentage(latest_row.emotion.broken_limit_up_ratio)}",
            f"• 最近3日涨幅>30%: {latest_row.emotion.pct_above_30_in_3d_count}家",
        ]

    def _build_trend_line(self, row: DailyReportRow) -> str:
        """构建单个交易日趋势文本。"""
        trade_date_text = self._format_trade_date(row.trade_date)
        trend_label = self._resolve_trend_label(row.breadth.up_ratio)
        amount_trillion = row.breadth.total_amount / Decimal("1000000000000")
        return (
            f"• {trade_date_text} {trend_label}："
            f"上涨占比 {row.breadth.up_ratio:.2%}，"
            f"成交额：{amount_trillion:.2f} 万亿，"
            f"涨停：{row.breadth.limit_up_count}，"
            f"跌停：{row.breadth.limit_down_count}，"
            f"<20H>: {row.breadth.new_high_20d_count}，"
            f"<20L>: {row.breadth.new_low_20d_count}，"
            f"<60H>: {row.breadth.new_high_60d_count}，"
            f"<60L>: {row.breadth.new_low_60d_count}"
        )

    def _format_trade_date(self, trade_date: date) -> str:
        """把日期格式化为更紧凑的 MM-DD。"""
        return trade_date.strftime("%m-%d")

    def _resolve_trend_label(self, up_ratio: Decimal) -> str:
        """把上涨占比分桶成更适合群消息速读的标签。"""
        if up_ratio >= Decimal("0.70"):
            return "明显走强"
        if up_ratio >= Decimal("0.60"):
            return "强"
        if up_ratio >= Decimal("0.40"):
            return "震荡"
        if up_ratio >= Decimal("0.30"):
            return "弱"
        return "明显转弱"

    def _normalize_quality_flag(self, flag: str) -> str:
        """把内部质量说明转成更适合业务群阅读的中文文案。"""
        replacements = {
            "ST历史状态按可得数据计算，相关口径为 best-effort": "ST 状态按可得数据近似识别，仅供参考",
            "退市风险按证券名称关键词近似识别，相关口径为 best-effort": "退市风险按名称关键词近似识别，仅供参考",
        }
        return replacements.get(flag, flag.replace("best-effort", "仅供参考"))

    def _format_percentage(self, value: Decimal | None) -> str:
        """把可空比例指标格式化为百分比文本。"""
        if value is None:
            return "N/A"
        return f"{value:.2%}"
