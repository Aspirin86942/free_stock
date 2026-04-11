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
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.services.m2_decision_engine import M2DecisionEngine
from gmtrade_live.services.m3_execution_service import M3ExecutionService
from gmtrade_live.services.m3_state_manager import (
    M3ExecutionState,
    M3PositionStateManager,
)


def _now() -> datetime:
    return datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal("1.0"),
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


class FakeTradeGateway:
    def __init__(self) -> None:
        self.submit_calls = 0

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SHSE.600036",
                exchange="SHSE",
                volume=100,
                available_volume=100,
                cost_price=Decimal("10.00"),
                last_update_time=_now(),
            )
        ]

    def submit_order(self, request):
        self.submit_calls += 1
        return OrderSubmitResult(
            accepted=True,
            cl_ord_id="CL_1",
            broker_order_id="BK_1",
            symbol=request.symbol,
            message="accepted",
            raw_status="1",
            event_time=_now(),
        )

    def query_order_status(self, cl_ord_id: str, symbol: str):
        return OrderStatusSnapshot(
            cl_ord_id=cl_ord_id,
            broker_order_id="BK_1",
            symbol=symbol,
            status="filled",
            filled_volume=100,
            remaining_volume=0,
            rejection_reason=None,
            event_time=_now(),
        )

    def query_execution_reports(self, cl_ord_id: str):
        return (
            OrderExecutionSnapshot(
                cl_ord_id=cl_ord_id,
                broker_order_id="BK_1",
                symbol="SHSE.600036",
                filled_volume=100,
                avg_price=Decimal("10.80"),
                event_time=_now(),
            ),
        )


class FakeMarketGateway:
    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        return [
            QuoteSnapshot(
                symbol="SHSE.600036",
                last_price=Decimal("10.80"),
                quote_time=_now(),
                source="fake",
            )
        ]


def test_m3_execution_service_completes_query_driven_sell_round() -> None:
    state_manager = M3PositionStateManager(logging.getLogger("test"))
    service = M3ExecutionService(
        trade_gateway=FakeTradeGateway(),
        market_gateway=FakeMarketGateway(),
        state_manager=state_manager,
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(), round_no=1)

    assert report.summary.submitted_count == 1
    assert report.execution_details[0].execution_state == "filled"
    assert report.execution_details[0].filled_volume == 100
    assert report.execution_details[0].avg_price == Decimal("10.80")
    assert state_manager.get_state("SHSE.600036").state is M3ExecutionState.filled
