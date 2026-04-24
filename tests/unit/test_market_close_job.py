from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

import gmtrade_live.services.market_close_job as market_close_job_module
from gmtrade_live.config import (
    FeishuConfig,
    GmConfig,
    MarketAnalysisConfig,
    MySQLConfig,
    RuntimeConfig,
    SchedulerConfig,
    TradeConfig,
)
from gmtrade_live.market_models import (
    DailyReportRow,
    EmotionMetrics,
    MarketBreadthMetrics,
    MarketCloseReport,
    ProfitEffectMetrics,
    ToleranceMetrics,
)
from gmtrade_live.services.feishu_notification_service import FeishuNotificationService
from gmtrade_live.services.market_close_job import run_market_close_job


def _build_config() -> RuntimeConfig:
    return RuntimeConfig(
        gm=GmConfig(token="token", endpoint="127.0.0.1:7001", timezone="Asia/Shanghai"),
        trade=TradeConfig(
            enabled=False,
            account_id="account",
            strategy_name="gmtrade-live-auto-sell",
            poll_interval_seconds=5,
            take_profit_ratio=Decimal("0.015"),
            stop_loss_ratio=Decimal("0.02"),
            sell_quantity_ratio=Decimal("0.02"),
            market_session_mode="a_share",
        ),
        market_analysis=MarketAnalysisConfig(
            enabled=True,
            universe="ashare_main_gem_star",
            history_years=3,
            recent_trade_days=10,
            report_time="19:15",
        ),
        mysql=MySQLConfig(
            host="127.0.0.1",
            port=3306,
            database="market_data",
            user="user",
            password="password",
        ),
        feishu=FeishuConfig(webhook="https://example.invalid/webhook"),
        scheduler=SchedulerConfig(enabled=True, retry_interval_minutes=10, max_attempts=3),
        log_dir="logs",  # type: ignore[arg-type]
    )


def _build_report(report_date: date) -> MarketCloseReport:
    return MarketCloseReport(
        report_trade_date=report_date,
        summary="summary",
        daily_rows=[
            DailyReportRow(
                trade_date=report_date,
                breadth=MarketBreadthMetrics(
                    up_count=1,
                    down_count=1,
                    up_ratio=Decimal("0.5"),
                    total_amount=Decimal("100"),
                    limit_up_count=0,
                    limit_down_count=0,
                    new_high_20d_count=0,
                    new_low_20d_count=0,
                    new_high_60d_count=0,
                    new_low_60d_count=0,
                ),
                profit_effect=ProfitEffectMetrics(
                    limit_up_yesterday_avg_return=None,
                    consecutive_limit_up_yesterday_avg_return=None,
                    hot_stock_4d_avg_return=None,
                ),
                tolerance=ToleranceMetrics(
                    st_count=0,
                    delisting_risk_count=0,
                    broken_limit_up_yesterday_avg_return=None,
                    hot_stock_close_above_avg_price_ratio=None,
                    hot_stock_max_drawdown_median=None,
                ),
                emotion=EmotionMetrics(
                    pct_above_9_5_count=0,
                    pct_below_minus_9_5_count=0,
                    broken_limit_up_ratio=None,
                    pct_above_30_in_3d_count=0,
                ),
            )
        ],
    )


def test_run_market_close_job_closes_repository_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = {"value": False}

    class _FakeRepository:
        def __init__(self, _config) -> None:
            pass

        def connect(self) -> None:
            pass

        def ensure_tables(self) -> None:
            pass

        def close(self) -> None:
            closed["value"] = True

    class _FakeGateway:
        def connect(self, _token: str, _endpoint: str) -> None:
            pass

    class _FailSyncService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def sync(self):
            raise RuntimeError("sync failed")

    monkeypatch.setattr(market_close_job_module, "GMHistoryMarketGateway", _FakeGateway)
    monkeypatch.setattr(market_close_job_module, "MySQLMarketRepository", _FakeRepository)
    monkeypatch.setattr(market_close_job_module, "MarketDataSyncService", _FailSyncService)

    result = run_market_close_job(_build_config())

    assert result.success is False
    assert closed["value"] is True


def test_run_market_close_job_skip_send_when_same_trade_date(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = {"count": 0}

    class _FakeRepository:
        def __init__(self, _config) -> None:
            self._saved: tuple[str, date] | None = None

        def connect(self) -> None:
            pass

        def ensure_tables(self) -> None:
            pass

        def close(self) -> None:
            pass

        def get_last_success_trade_date(self, job_name: str):
            if job_name == "market_close_report_sent":
                return date(2026, 4, 21)
            return date(2026, 4, 20)

    class _FakeGateway:
        def connect(self, _token: str, _endpoint: str) -> None:
            pass

    class _FakeSyncService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def sync(self):
            return type("SyncResult", (), {"latest_trade_date": date(2026, 4, 21), "inserted_rows": 0})

    class _FakeBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def build(self, *_args, **_kwargs):
            return _build_report(date(2026, 4, 21))

    class _FakeFeishu:
        def __init__(self, _config) -> None:
            pass

        def send_market_close_report(self, _report: MarketCloseReport) -> None:
            sent["count"] += 1

    monkeypatch.setattr(market_close_job_module, "GMHistoryMarketGateway", _FakeGateway)
    monkeypatch.setattr(market_close_job_module, "MySQLMarketRepository", _FakeRepository)
    monkeypatch.setattr(market_close_job_module, "MarketDataSyncService", _FakeSyncService)
    monkeypatch.setattr(market_close_job_module, "MarketCloseReportBuilder", _FakeBuilder)
    monkeypatch.setattr(market_close_job_module, "FeishuNotificationService", _FakeFeishu)

    result = run_market_close_job(_build_config())

    assert result.success is True
    assert sent["count"] == 0


def test_feishu_build_message_handles_empty_daily_rows() -> None:
    service = FeishuNotificationService(FeishuConfig(webhook="https://example.invalid/webhook"))
    report = MarketCloseReport(
        report_trade_date=date(2026, 4, 21),
        summary="summary",
        daily_rows=[],
    )

    message = service._build_message(report)

    assert message["msg_type"] == "text"
    assert "暂无可展示数据" in message["content"]["text"]


def test_feishu_build_message_uses_summary_first_and_keeps_trend_lines() -> None:
    service = FeishuNotificationService(FeishuConfig(webhook="https://example.invalid/webhook"))
    report_date = date(2026, 4, 21)
    report = MarketCloseReport(
        report_trade_date=report_date,
        summary="市场概况：上涨 3200 家，下跌 1500 家，上涨占比 68.00%",
        daily_rows=[
            DailyReportRow(
                trade_date=date(2026, 4, 20),
                breadth=MarketBreadthMetrics(
                    up_count=2800,
                    down_count=1700,
                    up_ratio=Decimal("0.61"),
                    total_amount=Decimal("1150000000000"),
                    limit_up_count=92,
                    limit_down_count=10,
                    new_high_20d_count=180,
                    new_low_20d_count=55,
                    new_high_60d_count=96,
                    new_low_60d_count=38,
                ),
                profit_effect=ProfitEffectMetrics(
                    limit_up_yesterday_avg_return=Decimal("0.012"),
                    consecutive_limit_up_yesterday_avg_return=Decimal("0.018"),
                    hot_stock_4d_avg_return=Decimal("0.024"),
                ),
                tolerance=ToleranceMetrics(
                    st_count=110,
                    delisting_risk_count=12,
                    broken_limit_up_yesterday_avg_return=Decimal("-0.006"),
                    hot_stock_close_above_avg_price_ratio=Decimal("0.57"),
                    hot_stock_max_drawdown_median=Decimal("0.032"),
                ),
                emotion=EmotionMetrics(
                    pct_above_9_5_count=81,
                    pct_below_minus_9_5_count=7,
                    broken_limit_up_ratio=Decimal("0.27"),
                    pct_above_30_in_3d_count=18,
                ),
            ),
            DailyReportRow(
                trade_date=report_date,
                breadth=MarketBreadthMetrics(
                    up_count=3200,
                    down_count=1500,
                    up_ratio=Decimal("0.68"),
                    total_amount=Decimal("1230000000000"),
                    limit_up_count=88,
                    limit_down_count=12,
                    new_high_20d_count=210,
                    new_low_20d_count=63,
                    new_high_60d_count=88,
                    new_low_60d_count=42,
                ),
                profit_effect=ProfitEffectMetrics(
                    limit_up_yesterday_avg_return=Decimal("0.035"),
                    consecutive_limit_up_yesterday_avg_return=Decimal("0.028"),
                    hot_stock_4d_avg_return=Decimal("0.076"),
                ),
                tolerance=ToleranceMetrics(
                    st_count=120,
                    delisting_risk_count=15,
                    broken_limit_up_yesterday_avg_return=Decimal("-0.012"),
                    hot_stock_close_above_avg_price_ratio=Decimal("0.61"),
                    hot_stock_max_drawdown_median=Decimal("0.041"),
                ),
                emotion=EmotionMetrics(
                    pct_above_9_5_count=76,
                    pct_below_minus_9_5_count=9,
                    broken_limit_up_ratio=Decimal("0.34"),
                    pct_above_30_in_3d_count=21,
                ),
            )
        ],
        data_quality_flags=(
            "ST历史状态按可得数据计算，相关口径为 best-effort",
            "退市风险按证券名称关键词近似识别，相关口径为 best-effort",
            "口径A说明",
        ),
    )

    message = service._build_message(report)
    text = message["content"]["text"]

    assert "一眼结论" in text
    assert "今日核心" in text
    assert "容错观察" in text
    assert "市场情绪指标（最新交易日）" in text
    assert "• 涨幅 >9.5%: 76家" in text
    assert "• 跌幅 <-9.5%: 9家" in text
    assert "• 炸板率: 34.00%" in text
    assert "• 最近3日涨幅>30%: 21家" in text
    assert "最近 10 日趋势" in text
    assert "04-20 强" in text
    assert "04-21 强" in text
    assert "连板溢价：昨日连板股今日平均收益 2.80%" in text
    assert "成交额：1.15 万亿" in text
    assert "成交额：1.23 万亿" in text
    assert "<20H>: 180" in text
    assert "<20L>: 55" in text
    assert "<60H>: 96" in text
    assert "<60L>: 38" in text
    assert "<20H>: 210" in text
    assert "<20L>: 63" in text
    assert "<60H>: 88" in text
    assert "<60L>: 42" in text
    assert "ST 状态按可得数据近似识别，仅供参考" in text
    assert "退市风险按名称关键词近似识别，仅供参考" in text
    assert "口径A说明" in text
