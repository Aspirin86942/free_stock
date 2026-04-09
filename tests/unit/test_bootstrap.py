from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import gmtrade_live.bootstrap as bootstrap


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        account_id="demo-account",
        strategy_name="gmtrade-live-m1",
        log_dir=Path("logs"),
        token="demo-token",
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


def test_run_m1_manual_trade_prints_verification_passed(
    monkeypatch,
    capsys,
) -> None:
    config = _fake_config()
    report = SimpleNamespace(
        verification_passed=True,
        side="sell",
        cl_ord_id="ORDER_1",
        broker_order_id="BROKER_1",
        submit_accepted=True,
        order_status_confirmed=True,
        execution_status_confirmed=True,
        last_order_status="filled",
        rejection_reason=None,
        filled_volume=100,
        avg_price=Decimal("10.450"),
        message="交易状态已确认",
    )

    class FakeGateway:
        def __init__(self, account_id: str) -> None:
            self.account_id = account_id

        def connect(self, loaded_config) -> None:
            assert loaded_config is config

    service_instance: "FakeService" | None = None

    class FakeService:
        def __init__(self, **kwargs) -> None:
            nonlocal service_instance
            service_instance = self
            self.last_run_kwargs: dict[str, object] | None = None

        def run(self, **kwargs):
            self.last_run_kwargs = kwargs
            return report

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(bootstrap, "setup_logging", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "GMTradeQueryGateway", FakeGateway)
    monkeypatch.setattr(bootstrap, "ManualTradeService", FakeService)

    exit_code = bootstrap.run_m1_manual_trade(
        config_path=Path("config/sim_account.yaml"),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=60,
        side="sell",
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["verification_passed"] is True
    assert set(payload) == {
        "verification_passed",
        "side",
        "cl_ord_id",
        "broker_order_id",
        "submit_accepted",
        "order_status_confirmed",
        "execution_status_confirmed",
        "last_order_status",
        "rejection_reason",
        "filled_volume",
        "avg_price",
        "message",
    }
    assert "success" not in payload
    assert payload["side"] == "sell"
    assert service_instance is not None
    assert service_instance.last_run_kwargs is not None
    assert service_instance.last_run_kwargs["side"] == "sell"


def test_run_m1_manual_trade_returns_nonzero_when_verification_failed(
    monkeypatch,
    capsys,
) -> None:
    config = _fake_config()
    report = SimpleNamespace(
        verification_passed=False,
        side="sell",
        cl_ord_id="ORDER_1",
        broker_order_id=None,
        submit_accepted=True,
        order_status_confirmed=True,
        execution_status_confirmed=False,
        last_order_status="submitted",
        rejection_reason=None,
        filled_volume=0,
        avg_price=None,
        message="委托状态已确认但尚未到终态: submitted",
    )

    class FakeGateway:
        def __init__(self, account_id: str) -> None:
            self.account_id = account_id

        def connect(self, loaded_config) -> None:
            assert loaded_config is config

    service_instance: "FakeService" | None = None

    class FakeService:
        def __init__(self, **kwargs) -> None:
            nonlocal service_instance
            service_instance = self
            self.last_run_kwargs: dict[str, object] | None = None

        def run(self, **kwargs):
            self.last_run_kwargs = kwargs
            return report

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(bootstrap, "setup_logging", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "GMTradeQueryGateway", FakeGateway)
    monkeypatch.setattr(bootstrap, "ManualTradeService", FakeService)

    exit_code = bootstrap.run_m1_manual_trade(
        config_path=Path("config/sim_account.yaml"),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=60,
        side="sell",
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["verification_passed"] is False
    assert set(payload) == {
        "verification_passed",
        "side",
        "cl_ord_id",
        "broker_order_id",
        "submit_accepted",
        "order_status_confirmed",
        "execution_status_confirmed",
        "last_order_status",
        "rejection_reason",
        "filled_volume",
        "avg_price",
        "message",
    }
    assert payload["message"] == "委托状态已确认但尚未到终态: submitted"
    assert payload["side"] == "sell"
    assert service_instance is not None
    assert service_instance.last_run_kwargs is not None
    assert service_instance.last_run_kwargs["side"] == "sell"


def test_run_m2_dry_run_prints_summary_and_change_details(monkeypatch, capsys) -> None:
    config = _fake_config()
    config.poll_interval_seconds = 5
    config.trade_session_start = "09:30:00"
    config.trade_session_end = "15:00:00"
    summary = SimpleNamespace(
        round_no=1,
        session_state="trading",
        position_count=1,
        watching_count=1,
        tombstone_count=0,
        should_sell_count=1,
        can_submit_sell_count=1,
        changed_symbol_count=1,
        duration_ms=8,
    )
    change = SimpleNamespace(
        symbol="SHSE.600036",
        change_tags=("trigger_activated",),
        decision=SimpleNamespace(
            should_sell=True,
            can_submit_sell=True,
            trigger_reason="take_profit_triggered",
            block_reason=None,
            current_price=Decimal("10.80"),
            session_state="trading",
            evaluated_at=datetime(2026, 4, 9, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        ),
        state_snapshot=SimpleNamespace(
            lifecycle_state="watching",
            volume=100,
            available_volume=100,
            sellable_now=True,
        ),
    )
    report = SimpleNamespace(summary=summary, change_events=(change,))

    class FakeGateway:
        def connect(self, *args, **kwargs) -> None:
            return None

    class FakeService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run_round(self, **kwargs):
            return report

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(
        bootstrap,
        "setup_logging",
        lambda *args, **kwargs: SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(bootstrap, "GMTradeQueryGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "M2StateManager", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M2DecisionEngine", lambda: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M2DryRunService", FakeService)

    exit_code = bootstrap.run_m2_dry_run(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert exit_code == 0
    assert '"kind": "m2_round_summary"' in lines[0]
    assert '"kind": "m2_change_detail"' in lines[1]
