from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    OrderExecutionSnapshot,
    OrderStatusSnapshot,
    OrderSubmitResult,
)
from tools.debug import manual_trade
from tools.debug.manual_trade import ManualTradeService, build_manual_trade_payload


class FakeTradeGateway:
    def __init__(
        self,
        submit_result: OrderSubmitResult,
        *,
        order_status_snapshots: tuple[OrderStatusSnapshot | None, ...] = (),
        execution_snapshots: tuple[tuple[OrderExecutionSnapshot, ...], ...] = (),
    ) -> None:
        self.submit_result = submit_result
        self.order_status_snapshots = list(order_status_snapshots)
        self.execution_snapshots = list(execution_snapshots)
        self.last_request = None
        self.order_query_calls = 0
        self.execution_query_calls = 0

    def submit_order(self, request) -> OrderSubmitResult:
        self.last_request = request
        return self.submit_result

    def query_order_status(
        self, cl_ord_id: str, symbol: str
    ) -> OrderStatusSnapshot | None:
        self.order_query_calls += 1
        if self.order_status_snapshots:
            return self.order_status_snapshots.pop(0)
        return None

    def query_execution_reports(
        self, cl_ord_id: str
    ) -> tuple[OrderExecutionSnapshot, ...]:
        self.execution_query_calls += 1
        if self.execution_snapshots:
            return self.execution_snapshots.pop(0)
        return ()


def _build_config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m1",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal("1.0"),
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


def _fixed_time() -> datetime:
    return datetime(2026, 4, 9, 10, 8, tzinfo=ZoneInfo("Asia/Shanghai"))


def _accepted_result() -> OrderSubmitResult:
    return OrderSubmitResult(
        accepted=True,
        cl_ord_id="ORDER_1",
        broker_order_id=None,
        symbol="SHSE.600036",
        message="accepted",
        raw_status="1",
        event_time=_fixed_time(),
    )


def _order_status_snapshot(
    *,
    status: str,
    broker_order_id: str = "BROKER_1",
    filled_volume: int = 0,
    remaining_volume: int = 100,
    rejection_reason: str | None = None,
) -> OrderStatusSnapshot:
    return OrderStatusSnapshot(
        cl_ord_id="ORDER_1",
        broker_order_id=broker_order_id,
        symbol="SHSE.600036",
        status=status,
        filled_volume=filled_volume,
        remaining_volume=remaining_volume,
        rejection_reason=rejection_reason,
        event_time=_fixed_time(),
    )


def _execution_snapshot(
    *,
    filled_volume: int = 100,
    avg_price: str = "10.450",
) -> OrderExecutionSnapshot:
    return OrderExecutionSnapshot(
        cl_ord_id="ORDER_1",
        broker_order_id="BROKER_1",
        symbol="SHSE.600036",
        filled_volume=filled_volume,
        avg_price=Decimal(avg_price),
        event_time=_fixed_time(),
    )


class FixedNowManualTradeService(ManualTradeService):
    def __init__(self, *, trade_gateway, logger, now_values: list[datetime]) -> None:
        super().__init__(trade_gateway=trade_gateway, logger=logger)
        self._now_values = list(now_values)

    def _now(self, timezone_name: str) -> datetime:
        if self._now_values:
            return self._now_values.pop(0)
        return _fixed_time()


def test_build_manual_trade_payload_maps_fields() -> None:
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

    payload = build_manual_trade_payload(report)

    assert payload["verification_passed"] is True
    assert payload["cl_ord_id"] == "ORDER_1"
    assert payload["avg_price"] == "10.450"


def test_main_rejects_invalid_price_without_traceback() -> None:
    with pytest.raises(SystemExit) as exc_info:
        manual_trade.main(
            [
                "--config",
                "dummy.yaml",
                "--symbol",
                "SHSE.600036",
                "--volume",
                "100",
                "--price-type",
                "limit",
                "--price",
                "abc",
                "--timeout-seconds",
                "5",
                "--side",
                "sell",
            ]
        )

    assert exc_info.value.code == 2


def test_main_invalid_market_price_does_not_connect(monkeypatch) -> None:
    def _fail_load_config(_):
        raise AssertionError("load_config should not be called")

    class FakeGateway:
        def __init__(self, account_id: str) -> None:
            self.account_id = account_id

        def connect(self, _config) -> None:
            raise AssertionError("connect should not be called")

    monkeypatch.setattr(manual_trade, "load_config", _fail_load_config)
    monkeypatch.setattr(manual_trade, "GMTradeGateway", FakeGateway)

    with pytest.raises(SystemExit) as exc_info:
        manual_trade.main(
            [
                "--config",
                "dummy.yaml",
                "--symbol",
                "SHSE.600036",
                "--volume",
                "100",
                "--price-type",
                "market",
                "--price",
                "10.5",
                "--timeout-seconds",
                "5",
                "--side",
                "sell",
            ]
        )

    assert exc_info.value.code == 2


def test_manual_trade_service_confirms_filled_order_via_query() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
        ),
        execution_snapshots=((_execution_snapshot(),),),
    )
    service = FixedNowManualTradeService(
        trade_gateway=gateway,
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
        now_values=[_fixed_time(), _fixed_time()],
    )

    report = service.run(
        config=_build_config(),
        side="sell",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    assert report.verification_passed is True
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is True
    assert report.last_order_status == "filled"
    assert report.filled_volume == 100
    assert report.avg_price == Decimal("10.450")


def test_manual_trade_service_submit_rejected() -> None:
    gateway = FakeTradeGateway(
        OrderSubmitResult(
            accepted=False,
            cl_ord_id=None,
            broker_order_id=None,
            symbol="SHSE.600036",
            message="rejected",
            raw_status="8",
            event_time=_fixed_time(),
        )
    )
    service = FixedNowManualTradeService(
        trade_gateway=gateway,
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
        now_values=[_fixed_time(), _fixed_time()],
    )

    report = service.run(
        config=_build_config(),
        side="sell",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=1,
    )

    assert report.verification_passed is False
    assert report.submit_accepted is False
    assert report.message == "rejected"


def test_manual_trade_service_filled_without_execution_report_is_not_success() -> None:
    started_at = _fixed_time()
    deadline = started_at + timedelta(seconds=1)
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
        ),
    )
    service = FixedNowManualTradeService(
        trade_gateway=gateway,
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
        now_values=[started_at, started_at, deadline, deadline],
    )

    report = service.run(
        config=_build_config(),
        side="sell",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=1,
    )

    assert report.verification_passed is False
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is False
    assert report.message == "委托已成交，但成交明细未确认"
