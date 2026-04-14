from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from tools.debug.manual_trade import build_manual_trade_payload


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
