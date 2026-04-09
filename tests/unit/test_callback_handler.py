from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from gmtrade_live.gateways.callback_handler import CallbackHandler
from gmtrade_live.models import ExecutionEvent, OrderEvent


def _build_order_payload() -> SimpleNamespace:
    return SimpleNamespace(
        cl_ord_id="123456",
        symbol="SHSE.600036",
        status=3,
        filled_volume=100,
        volume=100,
        ord_rej_reason_detail="",
        created_at=datetime(2026, 4, 9, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def _build_execution_payload() -> SimpleNamespace:
    return SimpleNamespace(
        cl_ord_id="123456",
        symbol="SHSE.600036",
        volume=100,
        price=10.45,
        created_at=datetime(2026, 4, 9, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def test_callback_handler_on_order_status() -> None:
    handler = CallbackHandler(logging.getLogger("test"))

    handler.on_order_status(_build_order_payload())

    event = handler.event_queue.get_nowait()
    assert isinstance(event, OrderEvent)
    assert event.order_id == "123456"
    assert event.status == "filled"
    assert event.remaining_volume == 0


def test_callback_handler_on_execution_report() -> None:
    handler = CallbackHandler(logging.getLogger("test"))

    handler.on_execution_report(_build_execution_payload())

    event = handler.event_queue.get_nowait()
    assert isinstance(event, ExecutionEvent)
    assert event.filled_volume == 100
    assert event.avg_price == Decimal("10.450")


def test_callback_handler_clear_queue() -> None:
    handler = CallbackHandler(logging.getLogger("test"))
    handler.event_queue.put(_build_order_payload())
    handler.event_queue.put(_build_execution_payload())

    handler.clear_queue()

    assert handler.event_queue.empty()
