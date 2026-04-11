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
from gmtrade_live.state import PositionState, PositionStateManager


def _now() -> datetime:
    return datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config(*, ratio: str = "0.80") -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal(ratio),
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


class FakeTradeGateway:
    def __init__(
        self,
        *,
        available_volume: int = 201,
        order_status: str = "submitted",
        execution_filled_volume: int = 0,
    ) -> None:
        self.available_volume = available_volume
        self.order_status = order_status
        self.execution_filled_volume = execution_filled_volume
        self.submitted_requests: list[object] = []

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SHSE.600036",
                exchange="SHSE",
                volume=250,
                available_volume=self.available_volume,
                cost_price=Decimal("10.00"),
                last_update_time=_now(),
            )
        ]

    def submit_order(self, request):
        self.submitted_requests.append(request)
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
            status=self.order_status,
            filled_volume=self.execution_filled_volume,
            remaining_volume=max(200 - self.execution_filled_volume, 0),
            rejection_reason=None,
            event_time=_now(),
        )

    def query_execution_reports(self, cl_ord_id: str):
        if self.execution_filled_volume <= 0:
            return ()
        return (
            OrderExecutionSnapshot(
                cl_ord_id=cl_ord_id,
                broker_order_id="BK_1",
                symbol="SHSE.600036",
                filled_volume=self.execution_filled_volume,
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


def test_run_round_submits_sell_order_with_non_promoted_target_when_full_position_not_available() -> None:
    trade_gateway = FakeTradeGateway(available_volume=201, order_status="submitted")
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        state_manager=PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(ratio="0.80"), round_no=1)

    assert trade_gateway.submitted_requests[0].volume == 200
    assert report.summary.candidate_count == 1
    assert report.summary.submitted_count == 1
    assert report.execution_details[0].requested_volume == 200
    assert report.execution_details[0].execution_state == "submitted"


def test_run_round_tracks_existing_open_order_without_duplicate_submit() -> None:
    trade_gateway = FakeTradeGateway(
        available_volume=250,
        order_status="partially_filled",
        execution_filled_volume=100,
    )
    state_manager = PositionStateManager(logger=None)
    state_manager.update_state(
        "SHSE.600036",
        PositionState.submitted,
        cl_ord_id="CL_EXIST",
        requested_volume=200,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="submitted",
    )
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        state_manager=state_manager,
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(ratio="0.80"), round_no=2)

    assert trade_gateway.submitted_requests == []
    assert report.summary.open_order_count == 1
    assert report.execution_details[0].execution_state == "partially_filled"
    assert report.execution_details[0].filled_volume == 100


def test_run_round_emits_block_detail_when_quantity_plan_is_blocked() -> None:
    trade_gateway = FakeTradeGateway(available_volume=201, order_status="submitted")
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        state_manager=PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(ratio="1.0"), round_no=1)

    assert report.summary.blocked_count == 1
    assert report.block_details[0].block_reason == "sell_quantity_exceeds_available"
    assert trade_gateway.submitted_requests == []


def test_run_round_preserves_submit_broker_order_id_when_query_has_no_broker_order_id() -> None:
    class QueryMissingBrokerOrderIdGateway(FakeTradeGateway):
        def query_order_status(self, cl_ord_id: str, symbol: str):
            return OrderStatusSnapshot(
                cl_ord_id=cl_ord_id,
                broker_order_id=None,
                symbol=symbol,
                status="submitted",
                filled_volume=0,
                remaining_volume=200,
                rejection_reason=None,
                event_time=_now(),
            )

    trade_gateway = QueryMissingBrokerOrderIdGateway()
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        state_manager=PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(ratio="0.80"), round_no=1)

    assert report.execution_details[0].broker_order_id == "BK_1"


def test_run_round_preserves_remaining_volume_when_pending_new_snapshot_reports_zero() -> None:
    class PendingNewZeroRemainingGateway(FakeTradeGateway):
        def query_order_status(self, cl_ord_id: str, symbol: str):
            return OrderStatusSnapshot(
                cl_ord_id=cl_ord_id,
                broker_order_id=None,
                symbol=symbol,
                status="pending_new",
                filled_volume=0,
                remaining_volume=0,
                rejection_reason=None,
                event_time=_now(),
            )

    trade_gateway = PendingNewZeroRemainingGateway()
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        state_manager=PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=lambda: 0.0,
    )

    report = service.run_round(config=_config(ratio="0.80"), round_no=1)

    assert report.execution_details[0].last_order_status == "pending_new"
    assert report.execution_details[0].remaining_volume == 200
