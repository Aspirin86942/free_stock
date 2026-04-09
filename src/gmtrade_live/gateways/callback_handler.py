from __future__ import annotations

from datetime import datetime
import logging
from queue import Empty, Queue
from typing import Any
from zoneinfo import ZoneInfo

from gmtrade_live.models import ExecutionEvent, OrderEvent
from gmtrade_live.precision import normalize_price


_ORDER_STATUS_MAP = {
    0: "unknown",
    1: "submitted",
    2: "partially_filled",
    3: "filled",
    4: "done_for_day",
    5: "cancelled",
    6: "pending_cancel",
    7: "stopped",
    8: "rejected",
    9: "suspended",
    10: "pending_new",
    11: "calculated",
    12: "expired",
    13: "accepted_for_bidding",
    14: "pending_replace",
}


class CallbackHandler:
    """把 SDK 回报转换成内部事件并放入线程安全队列。"""

    def __init__(self, logger: logging.Logger) -> None:
        self.event_queue: Queue[OrderEvent | ExecutionEvent] = Queue()
        self._logger = logger

    def on_order_status(self, context_or_order: Any, order: Any | None = None) -> None:
        """SDK 回调线程里只做转换和入队，避免把业务阻塞带进回调。"""
        payload = order if order is not None else context_or_order
        try:
            event = self._convert_to_order_event(payload)
            self.event_queue.put(event)
            self._logger.info(
                "order_callback_received order_id=%s symbol=%s status=%s",
                event.order_id,
                event.symbol,
                event.status,
            )
        except Exception as exc:
            self._logger.error(
                "order_callback_error error=%s payload=%s",
                str(exc),
                str(payload)[:200],
                exc_info=True,
            )

    def on_execution_report(
        self,
        context_or_execution: Any,
        execution: Any | None = None,
    ) -> None:
        """SDK 回调线程里只做转换和入队，后续业务处理由主线程同步消费。"""
        payload = execution if execution is not None else context_or_execution
        try:
            event = self._convert_to_execution_event(payload)
            self.event_queue.put(event)
            self._logger.info(
                "execution_callback_received order_id=%s symbol=%s filled_volume=%s",
                event.order_id,
                event.symbol,
                event.filled_volume,
            )
        except Exception as exc:
            self._logger.error(
                "execution_callback_error error=%s payload=%s",
                str(exc),
                str(payload)[:200],
                exc_info=True,
            )

    def clear_queue(self) -> None:
        """M1 只验证单笔订单，运行前必须清掉历史残留事件。"""
        while True:
            try:
                self.event_queue.get_nowait()
            except Empty:
                return

    def _convert_to_order_event(self, payload: Any) -> OrderEvent:
        order_id = str(_read_value(payload, "cl_ord_id", "order_id"))
        symbol = str(_read_value(payload, "symbol"))
        status_code = int(_read_value(payload, "status", default=0))
        filled_volume = int(_read_value(payload, "filled_volume", default=0))
        volume = int(_read_value(payload, "volume", default=filled_volume))
        remaining_volume = max(volume - filled_volume, 0)
        message = str(
            _read_value(
                payload,
                "ord_rej_reason_detail",
                "status_msg",
                "message",
                default="",
            )
        )

        return OrderEvent(
            order_id=order_id,
            symbol=symbol,
            status=_ORDER_STATUS_MAP.get(status_code, f"unknown_{status_code}"),
            filled_volume=filled_volume,
            remaining_volume=remaining_volume,
            event_time=_read_datetime(payload),
            message=message,
        )

    def _convert_to_execution_event(self, payload: Any) -> ExecutionEvent:
        filled_volume = int(_read_value(payload, "volume", "filled_volume", default=0))
        return ExecutionEvent(
            order_id=str(_read_value(payload, "cl_ord_id", "order_id")),
            symbol=str(_read_value(payload, "symbol")),
            filled_volume=filled_volume,
            avg_price=normalize_price(_read_value(payload, "filled_vwap", "price", default=0)),
            event_time=_read_datetime(payload),
        )


def _read_value(payload: Any, *keys: str, default: Any | None = None) -> Any:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return default

    for key in keys:
        if hasattr(payload, key):
            value = getattr(payload, key)
            if value is not None:
                return value
    return default


def _read_datetime(payload: Any) -> datetime:
    for key in ("updated_at", "created_at"):
        value = _read_value(payload, key)
        if isinstance(value, datetime):
            return value
    return datetime.now(tz=ZoneInfo("Asia/Shanghai"))
