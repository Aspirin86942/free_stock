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
        cl_ord_id="ORDER_1",
        broker_order_id="BROKER_1",
        submit_accepted=True,
        order_event_received=False,
        execution_event_received=False,
        callback_chain_closed=False,
        order_status_confirmed=True,
        execution_status_confirmed=True,
        last_order_status="filled",
        rejection_reason=None,
        filled_volume=100,
        avg_price=Decimal("10.450"),
        message="交易状态已确认，但回调链路未闭环",
    )

    class FakeGateway:
        def __init__(self, account_id: str) -> None:
            self.account_id = account_id

        def connect(self, loaded_config) -> None:
            assert loaded_config is config

        def set_callback_handler(self, handler) -> None:
            self.handler = handler

    class FakeService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run(self, **kwargs):
            return report

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(bootstrap, "setup_logging", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "CallbackHandler", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "GMTradeQueryGateway", FakeGateway)
    monkeypatch.setattr(bootstrap, "ManualTradeService", FakeService)

    exit_code = bootstrap.run_m1_manual_trade(
        config_path=Path("config/sim_account.yaml"),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=60,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["verification_passed"] is True
    assert "success" not in payload


def test_run_m1_manual_trade_returns_nonzero_when_verification_failed(
    monkeypatch,
    capsys,
) -> None:
    config = _fake_config()
    report = SimpleNamespace(
        verification_passed=False,
        cl_ord_id="ORDER_1",
        broker_order_id=None,
        submit_accepted=True,
        order_event_received=False,
        execution_event_received=False,
        callback_chain_closed=False,
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

        def set_callback_handler(self, handler) -> None:
            self.handler = handler

    class FakeService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run(self, **kwargs):
            return report

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(bootstrap, "setup_logging", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "CallbackHandler", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "GMTradeQueryGateway", FakeGateway)
    monkeypatch.setattr(bootstrap, "ManualTradeService", FakeService)

    exit_code = bootstrap.run_m1_manual_trade(
        config_path=Path("config/sim_account.yaml"),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=60,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["verification_passed"] is False
    assert payload["message"] == "委托状态已确认但尚未到终态: submitted"
