from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import (
    ExecutionEvent,
    OrderEvent,
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    OrderSubmitResult,
    TradeReport,
)


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_order_request_market_order() -> None:
    request = OrderRequest(
        symbol="SHSE.600036",
        volume=100,
        side="sell",
        price_type="market",
        price=None,
    )

    assert request.symbol == "SHSE.600036"
    assert request.volume == 100
    assert request.side == "sell"
    assert request.price_type == "market"
    assert request.price is None


def test_order_request_limit_order() -> None:
    request = OrderRequest(
        symbol="SHSE.600036",
        volume=100,
        side="sell",
        price_type="limit",
        price=Decimal("10.50"),
    )

    assert request.price == Decimal("10.50")


def test_order_request_buy_market_order() -> None:
    request = OrderRequest(
        symbol="SHSE.600036",
        volume=100,
        side="buy",
        price_type="market",
        price=None,
    )

    assert request.side == "buy"


def test_order_submit_result_accepted() -> None:
    result = OrderSubmitResult(
        accepted=True,
        cl_ord_id="123456",
        broker_order_id="654321",
        symbol="SHSE.600036",
        message="accepted",
        raw_status="1",
        event_time=_now(),
    )

    assert result.accepted is True
    assert result.cl_ord_id == "123456"
    assert result.broker_order_id == "654321"
    assert result.raw_status == "1"


def test_order_submit_result_rejected() -> None:
    result = OrderSubmitResult(
        accepted=False,
        cl_ord_id=None,
        broker_order_id=None,
        symbol="SHSE.600036",
        message="rejected",
        raw_status="8",
        event_time=_now(),
    )

    assert result.accepted is False
    assert result.cl_ord_id is None
    assert result.broker_order_id is None


def test_order_event() -> None:
    event = OrderEvent(
        order_id="123456",
        symbol="SHSE.600036",
        status="filled",
        filled_volume=100,
        remaining_volume=0,
        event_time=_now(),
        message="filled",
    )

    assert event.order_id == "123456"
    assert event.status == "filled"
    assert event.filled_volume == 100


def test_execution_event() -> None:
    event = ExecutionEvent(
        order_id="123456",
        symbol="SHSE.600036",
        filled_volume=100,
        avg_price=Decimal("10.45"),
        event_time=_now(),
    )

    assert event.filled_volume == 100
    assert event.avg_price == Decimal("10.45")


def test_order_status_snapshot() -> None:
    snapshot = OrderStatusSnapshot(
        cl_ord_id="123456",
        broker_order_id="654321",
        symbol="SHSE.600036",
        status="rejected",
        filled_volume=0,
        remaining_volume=100,
        rejection_reason="invalid_volume",
        event_time=_now(),
    )

    assert snapshot.cl_ord_id == "123456"
    assert snapshot.broker_order_id == "654321"
    assert snapshot.status == "rejected"
    assert snapshot.rejection_reason == "invalid_volume"


def test_order_execution_snapshot() -> None:
    snapshot = OrderExecutionSnapshot(
        cl_ord_id="123456",
        broker_order_id="654321",
        symbol="SHSE.600036",
        filled_volume=100,
        avg_price=Decimal("10.45"),
        event_time=_now(),
    )

    assert snapshot.cl_ord_id == "123456"
    assert snapshot.broker_order_id == "654321"
    assert snapshot.avg_price == Decimal("10.45")


def test_trade_report_success() -> None:
    report = TradeReport(
        account_id="demo-account",
        side="sell",
        symbol="SHSE.600036",
        requested_volume=100,
        price_type="market",
        submit_accepted=True,
        cl_ord_id="123456",
        broker_order_id="654321",
        order_status_confirmed=True,
        execution_status_confirmed=True,
        last_order_status="filled",
        rejection_reason=None,
        filled_volume=100,
        avg_price=Decimal("10.45"),
        verification_passed=True,
        message="交易状态已确认",
        started_at=_now(),
        finished_at=_now(),
    )

    assert report.verification_passed is True
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is True
    assert report.message == "交易状态已确认"


def test_trade_report_timeout() -> None:
    report = TradeReport(
        account_id="demo-account",
        side="sell",
        symbol="SHSE.600036",
        requested_volume=100,
        price_type="market",
        submit_accepted=True,
        cl_ord_id="123456",
        broker_order_id="654321",
        order_status_confirmed=True,
        execution_status_confirmed=False,
        last_order_status="rejected",
        rejection_reason="invalid_volume",
        filled_volume=0,
        avg_price=None,
        verification_passed=True,
        message="交易状态已确认",
        started_at=_now(),
        finished_at=_now(),
    )

    assert report.verification_passed is True
    assert report.order_status_confirmed is True
    assert report.rejection_reason == "invalid_volume"
    assert report.message == "交易状态已确认"


def test_trade_report_includes_side() -> None:
    report = TradeReport(
        account_id="demo-account",
        side="sell",
        symbol="SHSE.600036",
        requested_volume=1,
        price_type="market",
        submit_accepted=False,
        cl_ord_id=None,
        broker_order_id=None,
        order_status_confirmed=False,
        execution_status_confirmed=False,
        last_order_status=None,
        rejection_reason=None,
        filled_volume=0,
        avg_price=None,
        verification_passed=False,
        message="",
        started_at=_now(),
        finished_at=_now(),
    )

    assert report.side == "sell"
