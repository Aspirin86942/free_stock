from __future__ import annotations

from decimal import Decimal

from gm.enum import OrderSide_Buy, OrderType_Limit, PositionEffect_Open

from scripts.query_smoke_test import build_buy_order_kwargs, build_summary


def test_build_buy_order_kwargs_uses_limit_buy_open() -> None:
    kwargs = build_buy_order_kwargs(
        symbol="SHSE.600839",
        volume=100,
        limit_price=Decimal("9.870"),
        account_id="demo-account",
    )

    assert kwargs["symbol"] == "SHSE.600839"
    assert kwargs["volume"] == 100
    assert kwargs["side"] == OrderSide_Buy
    assert kwargs["order_type"] == OrderType_Limit
    assert kwargs["position_effect"] == PositionEffect_Open
    assert kwargs["price"] == 9.87
    assert kwargs["account"] == "demo-account"


def test_build_summary_reports_query_results() -> None:
    summary = build_summary(
        submit_accepted=True,
        query_order_status_confirmed=True,
        query_execution_count=1,
        final_order_status="filled",
        final_rejection_reason=None,
    )

    assert summary["submit_accepted"] is True
    assert summary["query_order_status_confirmed"] is True
    assert summary["query_execution_count"] == 1
    assert summary["final_order_status"] == "filled"
    assert summary["final_rejection_reason"] is None
