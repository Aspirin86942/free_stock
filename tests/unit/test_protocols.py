from __future__ import annotations

from gmtrade_live.gateways.protocols import TradeGateway


def test_trade_gateway_protocol_has_submit_order() -> None:
    assert hasattr(TradeGateway, "submit_order")


def test_trade_gateway_protocol_has_order_reconciliation_methods() -> None:
    assert hasattr(TradeGateway, "query_order_status")
    assert hasattr(TradeGateway, "query_execution_reports")
