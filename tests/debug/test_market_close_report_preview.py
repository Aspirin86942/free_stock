from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from gmtrade_live.config import RuntimeConfig, load_runtime_config
from gmtrade_live.repositories.mysql_market_repository import MySQLMarketRepository
from gmtrade_live.services.feishu_notification_service import render_market_close_report_text
from gmtrade_live.services.hot_stock_resolver import HotStockResolver
from gmtrade_live.services.market_breadth_analyzer import MarketBreadthAnalyzer
from gmtrade_live.services.market_close_report_builder import MarketCloseReportBuilder
from gmtrade_live.services.market_emotion_analyzer import MarketEmotionAnalyzer
from gmtrade_live.services.market_profit_effect_analyzer import MarketProfitEffectAnalyzer
from gmtrade_live.services.market_repository_cache import CachedMarketDataRepository
from gmtrade_live.services.market_tolerance_analyzer import MarketToleranceAnalyzer

pytestmark = pytest.mark.real_env_debug

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "sim_account.yaml"
_TRADE_DATE_ENV = "MARKET_CLOSE_REPORT_TRADE_DATE"


def _load_preview_config(config_path: Path) -> RuntimeConfig:
    """加载日报预览测试配置。"""
    if not config_path.exists():
        raise AssertionError(f"配置文件不存在: {config_path}")
    return load_runtime_config(config_path)


def _resolve_preview_trade_date(
    env_value: str | None,
    fallback_trade_date: date | None,
) -> date:
    """解析目标交易日，保证调试时优先支持手工指定历史日期。"""
    if env_value:
        try:
            return date.fromisoformat(env_value)
        except ValueError as exc:
            raise AssertionError(
                f"环境变量 {_TRADE_DATE_ENV} 不是合法日期: {env_value}"
            ) from exc

    if fallback_trade_date is None:
        raise AssertionError("market_daily_bar 为空，无法生成日报预览")
    return fallback_trade_date


def test_print_market_close_report_preview() -> None:
    config = _load_preview_config(_CONFIG_PATH)
    repository = MySQLMarketRepository(config.mysql)
    repository.connect()

    try:
        target_trade_date = _resolve_preview_trade_date(
            env_value=os.getenv(_TRADE_DATE_ENV),
            fallback_trade_date=repository.get_latest_trade_date_in_daily_bar(),
        )

        # 这里显式复用正式分析链路的 analyzer 组合，避免“预览文案”和“正式发送文案”长期漂移。
        cached_repository = CachedMarketDataRepository(repository)
        hot_stock_resolver = HotStockResolver(cached_repository)
        report_builder = MarketCloseReportBuilder(
            cached_repository,
            MarketBreadthAnalyzer(cached_repository),
            MarketProfitEffectAnalyzer(
                cached_repository,
                hot_stock_resolver=hot_stock_resolver,
            ),
            MarketToleranceAnalyzer(
                cached_repository,
                hot_stock_resolver=hot_stock_resolver,
            ),
            MarketEmotionAnalyzer(cached_repository),
        )
        report = report_builder.build(
            target_trade_date,
            config.market_analysis.recent_trade_days,
        )

        text = render_market_close_report_text(report)
        print(text)

        assert "市场分析日报" in text
        assert str(target_trade_date) in text
        assert "一眼结论" in text
        assert f"最近 {config.market_analysis.recent_trade_days} 日趋势" in text
    finally:
        repository.close()
