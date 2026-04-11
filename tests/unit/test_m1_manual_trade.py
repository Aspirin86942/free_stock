from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    OrderExecutionSnapshot,
    OrderStatusSnapshot,
    OrderSubmitResult,
)
from gmtrade_live.services.m1_manual_trade import ManualTradeService


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

    def query_order_status(self, cl_ord_id: str, symbol: str) -> OrderStatusSnapshot | None:
        self.order_query_calls += 1
        if self.order_status_snapshots:
            return self.order_status_snapshots.pop(0)
        return None

    def query_execution_reports(self, cl_ord_id: str) -> tuple[OrderExecutionSnapshot, ...]:
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
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 8, tzinfo=ZoneInfo("Asia/Shanghai"))


def _accepted_result() -> OrderSubmitResult:
    return OrderSubmitResult(
        accepted=True,
        cl_ord_id="ORDER_1",
        broker_order_id=None,
        symbol="SHSE.600036",
        message="accepted",
        raw_status="1",
        event_time=_now(),
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
        event_time=_now(),
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
        event_time=_now(),
    )


def _build_service(gateway: FakeTradeGateway) -> ManualTradeService:
    return ManualTradeService(
        trade_gateway=gateway,
        logger=logging.getLogger("test"),
    )


def test_manual_trade_service_confirms_filled_order_via_query() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
        ),
        execution_snapshots=((_execution_snapshot(),),),
    )
    service = _build_service(gateway)

    report = service.run(
        config=_build_config(),
        side="sell",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    assert gateway.last_request is not None
    assert gateway.last_request.side == "sell"
    assert report.side == "sell"
    assert report.verification_passed is True
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is True
    assert report.last_order_status == "filled"
    assert report.filled_volume == 100
    assert report.avg_price == Decimal("10.450")
    assert report.message == "交易状态已确认"


def test_manual_trade_service_confirms_rejected_order_via_query_without_execution() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(
                status="rejected",
                rejection_reason="invalid_volume",
            ),
        ),
    )
    service = _build_service(gateway)

    report = service.run(
        config=_build_config(),
        side="sell",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=1,
    )

    assert report.verification_passed is True
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is False
    assert report.broker_order_id == "BROKER_1"
    assert report.last_order_status == "rejected"
    assert report.rejection_reason == "invalid_volume"
    assert report.message == "交易状态已确认"
    assert gateway.execution_query_calls == 0


def test_manual_trade_service_confirms_buy_order_via_query() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
        ),
        execution_snapshots=((_execution_snapshot(),),),
    )
    service = _build_service(gateway)

    report = service.run(
        config=_build_config(),
        side="buy",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    assert gateway.last_request is not None
    assert gateway.last_request.side == "buy"
    assert report.side == "buy"
    assert report.verification_passed is True
    assert report.message == "交易状态已确认"


def test_manual_trade_service_submit_rejected() -> None:
    gateway = FakeTradeGateway(
        OrderSubmitResult(
            accepted=False,
            cl_ord_id=None,
            broker_order_id=None,
            symbol="SHSE.600036",
            message="rejected",
            raw_status="8",
            event_time=_now(),
        )
    )
    service = _build_service(gateway)

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
    assert report.cl_ord_id is None


def test_manual_trade_service_submitted_status_confirmed_is_not_success() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(status="submitted"),
            _order_status_snapshot(status="submitted"),
        ),
    )
    service = _build_service(gateway)

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
    assert report.message == "委托状态已确认但尚未到终态: submitted"


def test_manual_trade_service_filled_without_execution_report_is_not_success() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
        ),
    )
    service = _build_service(gateway)

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


def test_manual_trade_service_waits_until_query_confirms_terminal_status() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            None,
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
        ),
        execution_snapshots=((_execution_snapshot(),),),
    )
    service = _build_service(gateway)

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
    assert report.message == "交易状态已确认"
    assert gateway.order_query_calls >= 2
    assert gateway.order_query_calls < 5


def test_manual_trade_service_partially_filled_still_requires_terminal_status() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(
                status="partially_filled",
                filled_volume=50,
                remaining_volume=50,
            ),
            _order_status_snapshot(
                status="partially_filled",
                filled_volume=50,
                remaining_volume=50,
            ),
        ),
        execution_snapshots=((_execution_snapshot(filled_volume=50, avg_price="10.400"),), ()),
    )
    service = _build_service(gateway)

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
    assert report.execution_status_confirmed is True
    assert report.filled_volume == 50
    assert report.avg_price == Decimal("10.400")
    assert report.message == "委托状态已确认但尚未到终态: partially_filled"
