from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import gmtrade_live.runtime_scheduler as runtime_scheduler_module
from gmtrade_live.config import (
    FeishuConfig,
    GmConfig,
    MarketAnalysisConfig,
    MySQLConfig,
    RuntimeConfig,
    SchedulerConfig,
    TradeConfig,
)
from gmtrade_live.runtime_scheduler import RuntimeScheduler


class _FakeBlockingScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []
        self.started = False

    def add_job(self, **kwargs: object) -> None:
        self.jobs.append(kwargs)

    def start(self) -> None:
        self.started = True


def _build_config(*, trade_enabled: bool = False, market_enabled: bool = True) -> RuntimeConfig:
    return RuntimeConfig(
        gm=GmConfig(token="token", endpoint="127.0.0.1:7001", timezone="Asia/Shanghai"),
        trade=TradeConfig(
            enabled=trade_enabled,
            account_id="account",
            strategy_name="gmtrade-live-auto-sell",
            poll_interval_seconds=5,
            take_profit_ratio=Decimal("0.015"),
            stop_loss_ratio=Decimal("0.02"),
            sell_quantity_ratio=Decimal("0.02"),
            market_session_mode="a_share",
        ),
        market_analysis=MarketAnalysisConfig(
            enabled=market_enabled,
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
        scheduler=SchedulerConfig(
            enabled=True,
            retry_interval_minutes=1,
            max_attempts=3,
        ),
        log_dir=Path("logs"),
    )


def test_start_registers_market_job_when_enabled() -> None:
    scheduler = RuntimeScheduler(_build_config())
    fake_scheduler = _FakeBlockingScheduler()
    scheduler.scheduler = fake_scheduler

    scheduler.start()

    assert fake_scheduler.started is True
    assert len(fake_scheduler.jobs) == 1
    assert fake_scheduler.jobs[0]["id"] == "market_close_job"


def test_start_warns_when_trade_enabled_but_unimplemented(caplog: pytest.LogCaptureFixture) -> None:
    scheduler = RuntimeScheduler(_build_config(trade_enabled=True))
    fake_scheduler = _FakeBlockingScheduler()
    scheduler.scheduler = fake_scheduler

    scheduler.start()

    assert "自动交易任务已启用，但当前版本未实现" in caplog.text


def test_market_close_job_skips_when_no_completed_trade_day(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = RuntimeScheduler(_build_config())

    monkeypatch.setattr(scheduler, "_has_completed_trade_day", lambda: False)

    called = {"count": 0}

    def _fake_run_market_close_job(config: RuntimeConfig):
        called["count"] += 1
        return SimpleNamespace(success=True, message="ok", sync_inserted_rows=0, report_trade_date="2026-04-21")

    monkeypatch.setattr(runtime_scheduler_module, "run_market_close_job", _fake_run_market_close_job)
    monkeypatch.setattr(runtime_scheduler_module.time, "sleep", lambda _: None)

    scheduler._run_market_close_job_with_retry()

    assert called["count"] == 0


def test_market_close_job_retries_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = RuntimeScheduler(_build_config())
    monkeypatch.setattr(scheduler, "_has_completed_trade_day", lambda: True)
    monkeypatch.setattr(runtime_scheduler_module.time, "sleep", lambda _: None)

    called = {"count": 0}

    def _fake_run_market_close_job(config: RuntimeConfig):
        called["count"] += 1
        if called["count"] == 1:
            return SimpleNamespace(
                success=False,
                message="failed",
                sync_inserted_rows=0,
                report_trade_date="",
            )
        return SimpleNamespace(
            success=True,
            message="ok",
            sync_inserted_rows=10,
            report_trade_date="2026-04-21",
        )

    monkeypatch.setattr(runtime_scheduler_module, "run_market_close_job", _fake_run_market_close_job)

    scheduler._run_market_close_job_with_retry()

    assert called["count"] == 2


def test_has_completed_trade_day_uses_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = RuntimeScheduler(_build_config())

    class _FakeGateway:
        def connect(self, token: str, endpoint: str) -> None:
            assert token == "token"
            assert endpoint == "127.0.0.1:7001"

        def get_trade_dates(self, start_date: date, end_date: date) -> list[date]:
            return [start_date]

        def get_latest_trade_date(self, reference_date: date) -> date:
            return reference_date

    monkeypatch.setattr(runtime_scheduler_module, "GMHistoryMarketGateway", _FakeGateway)

    assert scheduler._has_completed_trade_day() is True
