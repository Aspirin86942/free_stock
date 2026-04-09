from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import logging
from threading import Thread
import time
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.callback_handler import CallbackHandler
from gmtrade_live.models import (
    ExecutionEvent,
    OrderEvent,
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
        order_status_snapshot: OrderStatusSnapshot | None = None,
        execution_snapshots: tuple[OrderExecutionSnapshot, ...] = (),
    ) -> None:
        self.submit_result = submit_result
        self.order_status_snapshot = order_status_snapshot
        self.execution_snapshots = execution_snapshots
        self.last_request = None
        self.poll_calls = 0

    def submit_order(self, request) -> OrderSubmitResult:
        self.last_request = request
        return self.submit_result

    def poll_callbacks(self) -> None:
        self.poll_calls += 1

    def query_order_status(self, cl_ord_id: str, symbol: str) -> OrderStatusSnapshot | None:
        if self.order_status_snapshot is None:
            return None
        if self.order_status_snapshot.cl_ord_id != cl_ord_id:
            return None
        return self.order_status_snapshot

    def query_execution_reports(self, cl_ord_id: str) -> tuple[OrderExecutionSnapshot, ...]:
        return tuple(
            snapshot
            for snapshot in self.execution_snapshots
            if snapshot.cl_ord_id == cl_ord_id
        )


def _build_config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m1",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        trade_session_start="09:30:00",
        trade_session_end="15:00:00",
        log_dir=__import__("pathlib").Path("logs"),
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


def test_manual_trade_service_success() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(_accepted_result())
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    def emit_events() -> None:
        time.sleep(0.05)
        handler.event_queue.put(
            OrderEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                status="filled",
                filled_volume=100,
                remaining_volume=0,
                event_time=_now(),
                message="filled",
            )
        )
        handler.event_queue.put(
            ExecutionEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("10.450"),
                event_time=_now(),
            )
        )

    thread = Thread(target=emit_events)
    thread.start()

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    thread.join()
    assert gateway.last_request is not None
    assert gateway.last_request.side == "sell"
    assert report.verification_passed is True
    assert report.order_event_received is True
    assert report.execution_event_received is True
    assert report.filled_volume == 100


def test_manual_trade_service_timeout_missing_execution_event() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(_accepted_result())
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    def emit_order_event() -> None:
        time.sleep(0.05)
        handler.event_queue.put(
            OrderEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                status="submitted",
                filled_volume=0,
                remaining_volume=100,
                event_time=_now(),
                message="submitted",
            )
        )

    thread = Thread(target=emit_order_event)
    thread.start()

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=1,
    )

    thread.join()
    assert report.verification_passed is False
    assert report.order_event_received is True
    assert report.execution_event_received is False
    assert report.message == "委托状态已确认但尚未到终态: submitted"


def test_manual_trade_service_submit_rejected() -> None:
    logger = logging.getLogger("test")
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
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    report = service.run(
        config=_build_config(),
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


def test_manual_trade_service_out_of_order_events() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(_accepted_result())
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    def emit_events() -> None:
        time.sleep(0.05)
        handler.event_queue.put(
            ExecutionEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("10.450"),
                event_time=_now(),
            )
        )
        time.sleep(0.05)
        handler.event_queue.put(
            OrderEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                status="filled",
                filled_volume=100,
                remaining_volume=0,
                event_time=_now(),
                message="filled",
            )
        )

    thread = Thread(target=emit_events)
    thread.start()

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    thread.join()
    assert report.verification_passed is True
    assert report.avg_price == Decimal("10.450")


def test_manual_trade_service_multiple_execution_events() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(_accepted_result())
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    def emit_events() -> None:
        time.sleep(0.05)
        handler.event_queue.put(
            OrderEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                status="partially_filled",
                filled_volume=50,
                remaining_volume=50,
                event_time=_now(),
                message="partial",
            )
        )
        handler.event_queue.put(
            ExecutionEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                filled_volume=50,
                avg_price=Decimal("10.400"),
                event_time=_now(),
            )
        )
        handler.event_queue.put(
            ExecutionEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                filled_volume=50,
                avg_price=Decimal("10.500"),
                event_time=_now(),
            )
        )

    thread = Thread(target=emit_events)
    thread.start()

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    thread.join()
    assert report.verification_passed is True
    assert report.filled_volume == 100
    assert report.avg_price == Decimal("10.500")


def test_manual_trade_service_ignore_mismatched_order_id() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(_accepted_result())
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    def emit_events() -> None:
        time.sleep(0.05)
        handler.event_queue.put(
            OrderEvent(
                order_id="OLD_ORDER",
                symbol="SHSE.600036",
                status="filled",
                filled_volume=100,
                remaining_volume=0,
                event_time=_now() - timedelta(minutes=1),
                message="old",
            )
        )
        handler.event_queue.put(
            ExecutionEvent(
                order_id="OLD_ORDER",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("9.000"),
                event_time=_now() - timedelta(minutes=1),
            )
        )
        handler.event_queue.put(
            OrderEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                status="filled",
                filled_volume=100,
                remaining_volume=0,
                event_time=_now(),
                message="filled",
            )
        )
        handler.event_queue.put(
            ExecutionEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("10.450"),
                event_time=_now(),
            )
        )

    thread = Thread(target=emit_events)
    thread.start()

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    thread.join()
    assert report.verification_passed is True
    assert report.avg_price == Decimal("10.450")


def test_manual_trade_service_polls_gateway_callbacks() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(_accepted_result())
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    def emit_events() -> None:
        time.sleep(0.1)
        handler.event_queue.put(
            OrderEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                status="filled",
                filled_volume=100,
                remaining_volume=0,
                event_time=_now(),
                message="filled",
            )
        )
        handler.event_queue.put(
            ExecutionEvent(
                order_id="ORDER_1",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("10.450"),
                event_time=_now(),
            )
        )

    thread = Thread(target=emit_events)
    thread.start()

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    thread.join()
    assert report.verification_passed is True
    assert gateway.poll_calls > 0


def test_manual_trade_service_queries_rejected_status_when_callbacks_missing() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshot=OrderStatusSnapshot(
            cl_ord_id="ORDER_1",
            broker_order_id="BROKER_1",
            symbol="SHSE.600036",
            status="rejected",
            filled_volume=0,
            remaining_volume=100,
            rejection_reason="invalid_volume",
            event_time=_now(),
        ),
    )
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=1,
    )

    assert report.verification_passed is True
    assert report.callback_chain_closed is False
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is False
    assert report.cl_ord_id == "ORDER_1"
    assert report.broker_order_id == "BROKER_1"
    assert report.last_order_status == "rejected"
    assert report.rejection_reason == "invalid_volume"
    assert report.message == "交易状态已确认，但回调链路未闭环"


def test_manual_trade_service_queries_execution_reports_when_callbacks_missing() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshot=OrderStatusSnapshot(
            cl_ord_id="ORDER_1",
            broker_order_id="BROKER_1",
            symbol="SHSE.600036",
            status="filled",
            filled_volume=100,
            remaining_volume=0,
            rejection_reason=None,
            event_time=_now(),
        ),
        execution_snapshots=(
            OrderExecutionSnapshot(
                cl_ord_id="ORDER_1",
                broker_order_id="BROKER_1",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("10.450"),
                event_time=_now(),
            ),
        ),
    )
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=1,
    )

    assert report.verification_passed is True
    assert report.callback_chain_closed is False
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is True
    assert report.cl_ord_id == "ORDER_1"
    assert report.broker_order_id == "BROKER_1"
    assert report.last_order_status == "filled"
    assert report.filled_volume == 100
    assert report.avg_price == Decimal("10.450")
    assert report.message == "交易状态已确认，但回调链路未闭环"


def test_manual_trade_service_submitted_status_confirmed_is_not_success() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshot=OrderStatusSnapshot(
            cl_ord_id="ORDER_1",
            broker_order_id="BROKER_1",
            symbol="SHSE.600036",
            status="submitted",
            filled_volume=0,
            remaining_volume=100,
            rejection_reason=None,
            event_time=_now(),
        ),
    )
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=1,
    )

    assert report.verification_passed is False
    assert report.order_status_confirmed is True
    assert report.message == "委托状态已确认但尚未到终态: submitted"


def test_manual_trade_service_returns_early_when_query_confirms_terminal_status() -> None:
    logger = logging.getLogger("test")
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshot=OrderStatusSnapshot(
            cl_ord_id="ORDER_1",
            broker_order_id="BROKER_1",
            symbol="SHSE.600036",
            status="filled",
            filled_volume=100,
            remaining_volume=0,
            rejection_reason=None,
            event_time=_now(),
        ),
        execution_snapshots=(
            OrderExecutionSnapshot(
                cl_ord_id="ORDER_1",
                broker_order_id="BROKER_1",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("10.450"),
                event_time=_now(),
            ),
        ),
    )
    handler = CallbackHandler(logger)
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=handler,
        logger=logger,
    )

    report = service.run(
        config=_build_config(),
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=3,
    )

    assert report.verification_passed is True
    assert report.callback_chain_closed is False
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is True
    assert report.message == "交易状态已确认，但回调链路未闭环"
    assert gateway.poll_calls < 8
    assert report.last_order_status == "filled"
    assert report.filled_volume == 100
