from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import gmtrade_live.bootstrap as bootstrap
from gmtrade_live.errors import ServiceError


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        account_id="demo-account",
        strategy_name="gmtrade-live-m1",
        log_dir=Path("logs"),
        poll_interval_seconds=5,
        sell_quantity_ratio=Decimal("1.0"),
        token="demo-token",
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
        market_session_mode="a_share",
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
    monkeypatch.setattr(bootstrap, "GMTradeGateway", FakeGateway)
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
    monkeypatch.setattr(bootstrap, "GMTradeGateway", FakeGateway)
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
    monkeypatch.setattr(bootstrap, "GMTradeGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "DecisionObserverService", FakeService)

    exit_code = bootstrap.run_m2_dry_run(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert exit_code == 0
    assert '"kind": "m2_round_summary"' in lines[0]
    assert '"kind": "m2_change_detail"' in lines[1]


def test_run_m2_dry_run_logs_and_continues_after_round_exception(monkeypatch, capsys) -> None:
    config = _fake_config()
    config.poll_interval_seconds = 5
    logger_calls: list[str] = []

    summary = SimpleNamespace(
        round_no=2,
        session_state="trading",
        position_count=1,
        watching_count=1,
        tombstone_count=0,
        should_sell_count=1,
        can_submit_sell_count=1,
        changed_symbol_count=0,
        duration_ms=8,
    )
    report = SimpleNamespace(summary=summary, change_events=())

    class FakeGateway:
        def connect(self, *args, **kwargs) -> None:
            return None

    class FakeService:
        def __init__(self, **kwargs) -> None:
            self.calls = 0

        def run_round(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return report

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(
        bootstrap,
        "setup_logging",
        lambda *args, **kwargs: SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda message, *a, **k: logger_calls.append(message % a if a else message),
        ),
    )
    monkeypatch.setattr(bootstrap, "GMTradeGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "DecisionObserverService", FakeService)
    sleep_calls: list[int] = []
    monkeypatch.setattr(bootstrap.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    exit_code = bootstrap.run_m2_dry_run(
        config_path=Path("config/sim_account.yaml"),
        once=False,
        max_rounds=2,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert exit_code == 0
    assert '"kind": "m2_round_error"' in lines[0]
    assert '"kind": "m2_round_summary"' in lines[1]
    assert any("round_failed mode=m2 round=1" in call for call in logger_calls)
    assert sleep_calls == [5]


def test_run_m2_dry_run_logs_round_started_and_completed(monkeypatch, capsys) -> None:
    config = _fake_config()
    logger_calls: list[str] = []
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
    report = SimpleNamespace(summary=summary, change_events=())

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
            info=lambda message, *a, **k: logger_calls.append(message % a if a else message),
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(bootstrap, "GMTradeGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "DecisionObserverService", FakeService)

    exit_code = bootstrap.run_m2_dry_run(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
    )

    capsys.readouterr()
    assert exit_code == 0
    assert any("round_started mode=m2 round=1" in call for call in logger_calls)
    assert any("round_completed mode=m2 round=1 duration_ms=8" in call for call in logger_calls)


def test_run_m1_manual_trade_rejects_unimplemented_market_session_mode(monkeypatch) -> None:
    config = _fake_config()
    config.market_session_mode = "futures_placeholder"

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(bootstrap, "setup_logging", lambda *args, **kwargs: SimpleNamespace())

    with pytest.raises(ServiceError) as exc_info:
        bootstrap.run_m1_manual_trade(
            config_path=Path("config/sim_account.yaml"),
            symbol="SHSE.600036",
            volume=100,
            price_type="market",
            price=None,
            timeout_seconds=60,
            side="sell",
        )

    assert exc_info.value.code == "session.mode_not_implemented"


def test_run_m3_execution_prints_summary_block_and_execution_details(
    monkeypatch,
    capsys,
) -> None:
    config = _fake_config()
    report = SimpleNamespace(
        summary=SimpleNamespace(
            round_no=1,
            session_state="trading",
            position_count=2,
            candidate_count=1,
            blocked_count=1,
            submitted_count=1,
            open_order_count=1,
            changed_symbol_count=2,
            duration_ms=12,
        ),
        block_details=(
            SimpleNamespace(
                symbol="SHSE.600000",
                decision_lifecycle_state="watching",
                decision_should_sell=True,
                decision_can_submit_sell=True,
                decision_trigger_reason="take_profit_triggered",
                decision_block_reason=None,
                execution_state=None,
                execution_cl_ord_id=None,
                execution_broker_order_id=None,
                execution_last_order_status=None,
                requested_ratio=Decimal("1.0"),
                total_volume=100,
                available_volume=0,
                raw_target_volume=100,
                promotion_type=None,
                normalized_target_volume=100,
                block_reason="sell_quantity_exceeds_available",
                evaluated_at=datetime(
                    2026,
                    4,
                    10,
                    10,
                    0,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            ),
        ),
        execution_details=(
            SimpleNamespace(
                symbol="SHSE.600036",
                change_tags=("submit_accepted", "order_status_updated"),
                decision_lifecycle_state="watching",
                decision_should_sell=True,
                decision_can_submit_sell=True,
                decision_trigger_reason="take_profit_triggered",
                decision_block_reason=None,
                execution_state="submitted",
                cl_ord_id="CL_1",
                broker_order_id="BK_1",
                requested_volume=200,
                filled_volume=0,
                remaining_volume=200,
                submit_accepted=True,
                last_order_status="submitted",
                rejection_reason=None,
                avg_price=None,
                event_time=datetime(
                    2026,
                    4,
                    10,
                    10,
                    0,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
                message="accepted",
                submit_started_at=datetime(
                    2026,
                    4,
                    10,
                    9,
                    59,
                    59,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
                submit_accepted_at=datetime(
                    2026,
                    4,
                    10,
                    10,
                    0,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
                terminal_state_at=None,
                order_terminal_latency_ms=None,
            ),
        ),
    )

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
            error=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "setup_order_audit_logger",
        lambda *args, **kwargs: SimpleNamespace(info=lambda *a, **k: None),
    )
    monkeypatch.setattr(bootstrap, "GMTradeGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "OrderExecutionStateStore", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "PositionDecisionStateStore", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "SellDecisionEngine", lambda: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M3ExecutionService", FakeService)

    exit_code = bootstrap.run_m3_execution(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
        reconcile_timeout_seconds=7,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert exit_code == 0
    assert '"kind": "m3_round_summary"' in lines[0]
    assert '"kind": "m3_block_detail"' in lines[1]
    assert '"decision_lifecycle_state": "watching"' in lines[1]
    assert '"kind": "m3_execution_detail"' in lines[2]
    assert '"decision_trigger_reason": "take_profit_triggered"' in lines[2]
    assert '"submit_accepted_at": "2026-04-10T10:00:00+08:00"' in lines[2]
    assert '"order_terminal_latency_ms": null' in lines[2]


def test_run_m3_execution_returns_nonzero_when_round_raises(
    monkeypatch,
    capsys,
) -> None:
    config = _fake_config()

    class FakeGateway:
        def connect(self, *args, **kwargs) -> None:
            return None

    class FakeService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run_round(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(
        bootstrap,
        "setup_logging",
        lambda *args, **kwargs: SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "setup_order_audit_logger",
        lambda *args, **kwargs: SimpleNamespace(info=lambda *a, **k: None),
    )
    monkeypatch.setattr(bootstrap, "GMTradeGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "OrderExecutionStateStore", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "PositionDecisionStateStore", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "SellDecisionEngine", lambda: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M3ExecutionService", FakeService)

    exit_code = bootstrap.run_m3_execution(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
        reconcile_timeout_seconds=7,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["kind"] == "m3_round_error"
    assert payload["message"] == "boom"


def test_run_m3_execution_prints_latency_fields(monkeypatch, capsys) -> None:
    config = _fake_config()
    audit_loggers: list[object] = []
    service_kwargs_list: list[dict[str, object]] = []
    sentinel_pipeline = SimpleNamespace(name="candidate-pipeline")
    report = SimpleNamespace(
        summary=SimpleNamespace(
            round_no=1,
            session_state="trading",
            position_count=1,
            candidate_count=1,
            blocked_count=0,
            submitted_count=1,
            open_order_count=0,
            changed_symbol_count=1,
            duration_ms=12,
        ),
        block_details=(),
        execution_details=(
            SimpleNamespace(
                symbol="SHSE.600036",
                change_tags=("terminal_state_reached",),
                decision_lifecycle_state="watching",
                decision_should_sell=True,
                decision_can_submit_sell=True,
                decision_trigger_reason="take_profit_triggered",
                decision_block_reason=None,
                execution_state="filled",
                cl_ord_id="CL_1",
                broker_order_id="BK_1",
                requested_volume=200,
                filled_volume=200,
                remaining_volume=0,
                submit_accepted=True,
                last_order_status="filled",
                rejection_reason=None,
                avg_price=Decimal("10.80"),
                event_time=datetime(2026, 4, 13, 10, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
                message="filled",
                submit_started_at=datetime(2026, 4, 13, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                submit_accepted_at=datetime(2026, 4, 13, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                terminal_state_at=datetime(2026, 4, 13, 10, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
                order_terminal_latency_ms=1000,
            ),
        ),
    )

    class FakeGateway:
        def connect(self, *args, **kwargs) -> None:
            return None

    class FakeService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            service_kwargs_list.append(kwargs)
            audit_loggers.append(kwargs["audit_logger"])

        def run_round(self, **kwargs):
            return report

    monkeypatch.setattr(bootstrap, "load_config", lambda path: config)
    monkeypatch.setattr(
        bootstrap,
        "setup_logging",
        lambda *a, **k: SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "setup_order_audit_logger",
        lambda *a, **k: SimpleNamespace(info=lambda *a, **k: None),
    )
    monkeypatch.setattr(bootstrap, "GMTradeGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "GMCurrentQuoteGateway", lambda: FakeGateway())
    monkeypatch.setattr(bootstrap, "SellCandidatePipeline", lambda **kwargs: sentinel_pipeline)
    monkeypatch.setattr(bootstrap, "OrderExecutionStateStore", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "PositionDecisionStateStore", lambda logger: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "SellDecisionEngine", lambda: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "M3ExecutionService", FakeService)

    exit_code = bootstrap.run_m3_execution(
        config_path=Path("config/sim_account.yaml"),
        once=True,
        max_rounds=None,
        reconcile_timeout_seconds=5,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert exit_code == 0
    assert audit_loggers
    assert service_kwargs_list
    assert service_kwargs_list[0]["candidate_pipeline"] is sentinel_pipeline
    assert "market_gateway" not in service_kwargs_list[0]
    assert "decision_state_manager" not in service_kwargs_list[0]
    assert "decision_engine" not in service_kwargs_list[0]
    assert '"order_terminal_latency_ms": 1000' in lines[1]
    assert '"submit_accepted_at": "2026-04-13T10:00:00+08:00"' in lines[1]


def test_bootstrap_m3_execution_service_compat_accepts_legacy_constructor_args(monkeypatch) -> None:
    created_pipelines: list[SimpleNamespace] = []

    def _fake_pipeline(**kwargs):
        pipeline = SimpleNamespace(**kwargs)
        created_pipelines.append(pipeline)
        return pipeline

    monkeypatch.setattr(bootstrap, "SellCandidatePipeline", _fake_pipeline)

    service = bootstrap.M3ExecutionService(
        trade_gateway=SimpleNamespace(),
        market_gateway=SimpleNamespace(),
        decision_state_manager=SimpleNamespace(),
        execution_state_manager=SimpleNamespace(),
        decision_engine=SimpleNamespace(),
        logger=SimpleNamespace(),
    )

    assert created_pipelines
    assert service._candidate_pipeline is created_pipelines[0]
