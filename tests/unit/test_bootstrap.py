from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

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
