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
from gmtrade_live.services.m2_state_manager import M2StateManager
from gmtrade_live.services.m3_execution_service import M3ExecutionService
from gmtrade_live.services.m3_state_manager import (
    M3ExecutionState,
    M3PositionStateManager,
)


def _now() -> datetime:
    return datetime(2026, 4, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


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


def _position(
    symbol: str = "SHSE.600036",
    *,
    volume: int = 250,
    available_volume: int = 250,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        exchange=symbol.split(".", maxsplit=1)[0],
        volume=volume,
        available_volume=available_volume,
        cost_price=Decimal("10.00"),
        last_update_time=_now(),
    )


def _quote(symbol: str = "SHSE.600036") -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        last_price=Decimal("10.80"),
        quote_time=_now(),
        source="fake",
    )


def _execution(
    filled_volume: int,
    *,
    symbol: str = "SHSE.600036",
) -> OrderExecutionSnapshot:
    return OrderExecutionSnapshot(
        cl_ord_id="CL_1",
        broker_order_id="BK_1",
        symbol=symbol,
        filled_volume=filled_volume,
        avg_price=Decimal("10.80"),
        event_time=_now(),
    )


class FakeTimer:
    def __init__(self, values: list[float]) -> None:
        self._values = values
        self._index = 0

    def __call__(self) -> float:
        if self._index < len(self._values):
            value = self._values[self._index]
            self._index += 1
            return value
        return self._values[-1]


class SequencedTradeGateway:
    def __init__(
        self,
        *,
        positions: tuple[PositionSnapshot, ...] | None = None,
        available_volume: int = 250,
        submit_result: OrderSubmitResult | None = None,
        order_statuses: list[tuple[str, int, int, str | None]] | None = None,
        execution_reports: list[tuple[OrderExecutionSnapshot, ...]] | None = None,
    ) -> None:
        self.positions = positions or (_position(available_volume=available_volume),)
        self.submit_result = submit_result or OrderSubmitResult(
            accepted=True,
            cl_ord_id="CL_1",
            broker_order_id="BK_1",
            symbol=self.positions[0].symbol,
            message="accepted",
            raw_status="1",
            event_time=_now(),
        )
        self.order_statuses = order_statuses or [("filled", 200, 0, "BK_1")]
        self.execution_reports = execution_reports or [(_execution(200),)]
        self.submit_calls = 0
        self.submitted_requests: list[object] = []
        self.query_order_status_calls = 0
        self._last_query_index = 0

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return list(self.positions)

    def submit_order(self, request):
        self.submit_calls += 1
        self.submitted_requests.append(request)
        return self.submit_result

    def query_order_status(self, cl_ord_id: str, symbol: str):
        index = min(self.query_order_status_calls, len(self.order_statuses) - 1)
        self.query_order_status_calls += 1
        self._last_query_index = index
        status, filled_volume, remaining_volume, broker_order_id = self.order_statuses[
            index
        ]
        return OrderStatusSnapshot(
            cl_ord_id=cl_ord_id,
            broker_order_id=broker_order_id,
            symbol=symbol,
            status=status,
            filled_volume=filled_volume,
            remaining_volume=remaining_volume,
            rejection_reason=None,
            event_time=_now(),
        )

    def query_execution_reports(self, cl_ord_id: str):
        index = min(self._last_query_index, len(self.execution_reports) - 1)
        return self.execution_reports[index]


class FakeMarketGateway:
    def __init__(self, *, quotes: tuple[QuoteSnapshot, ...] | None = None) -> None:
        self._quotes = quotes or (_quote(),)

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        return [quote for quote in self._quotes if quote.symbol in symbols]


class CapturingLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *args, **kwargs) -> None:
        del kwargs
        self.messages.append(message % args if args else message)


def test_run_round_uses_real_m2_state_and_writes_decision_feedback() -> None:
    decision_manager = M2StateManager(logging.getLogger("test"))
    execution_manager = M3PositionStateManager(logger=None)
    service = M3ExecutionService(
        trade_gateway=SequencedTradeGateway(),
        market_gateway=FakeMarketGateway(),
        decision_state_manager=decision_manager,
        execution_state_manager=execution_manager,
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=5)

    state = decision_manager.get_state("SHSE.600036")
    assert state is not None
    assert state.last_trigger_reason == "take_profit_triggered"
    assert state.last_block_reason is None
    assert report.execution_details[-1].decision_lifecycle_state == "watching"
    assert report.execution_details[-1].decision_can_submit_sell is True
    assert report.execution_details[-1].execution_state == "filled"


def test_run_round_reconciles_new_submit_until_filled_within_shared_budget() -> None:
    sleep_calls: list[float] = []
    service = M3ExecutionService(
        trade_gateway=SequencedTradeGateway(
            available_volume=201,
            order_statuses=[
                ("pending_new", 0, 0, None),
                ("partially_filled", 100, 100, "BK_1"),
                ("filled", 200, 0, "BK_1"),
            ],
            execution_reports=[
                (),
                (_execution(100),),
                (_execution(200),),
            ],
        ),
        market_gateway=FakeMarketGateway(),
        decision_state_manager=M2StateManager(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2, 0.7, 0.8, 1.3, 1.4]),
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    report = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=5)

    assert sleep_calls == [0.5, 0.5]
    assert report.summary.submitted_count == 1
    assert report.summary.open_order_count == 0
    assert report.execution_details[-1].execution_state == "filled"
    assert report.execution_details[-1].filled_volume == 200
    assert report.execution_details[-1].last_order_status == "filled"


def test_run_round_tracks_existing_open_order_without_duplicate_submit() -> None:
    trade_gateway = SequencedTradeGateway(
        order_statuses=[("partially_filled", 100, 100, "BK_1")],
        execution_reports=[(_execution(100),)],
    )
    execution_manager = M3PositionStateManager(logger=None)
    execution_manager.update_state(
        "SHSE.600036",
        M3ExecutionState.submitted,
        cl_ord_id="CL_EXIST",
        broker_order_id="BK_1",
        requested_volume=200,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="submitted",
    )
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        decision_state_manager=M2StateManager(logging.getLogger("test")),
        execution_state_manager=execution_manager,
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 5.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(), round_no=2, reconcile_timeout_seconds=5)

    assert trade_gateway.submit_calls == 0
    assert report.summary.submitted_count == 0
    assert report.execution_details[-1].execution_state == "partially_filled"
    assert report.execution_details[-1].filled_volume == 100


def test_run_round_emits_block_detail_with_decision_projection() -> None:
    trade_gateway = SequencedTradeGateway(available_volume=201)
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        decision_state_manager=M2StateManager(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(ratio="1.0"), round_no=1, reconcile_timeout_seconds=5)

    assert report.summary.blocked_count == 1
    assert report.block_details[0].decision_lifecycle_state == "watching"
    assert report.block_details[0].decision_trigger_reason == "take_profit_triggered"
    assert report.block_details[0].execution_state is None
    assert report.block_details[0].block_reason == "sell_quantity_exceeds_available"
    assert trade_gateway.submit_calls == 0


def test_run_round_preserves_submit_broker_order_id_and_remaining_volume_on_bad_snapshot() -> None:
    service = M3ExecutionService(
        trade_gateway=SequencedTradeGateway(
            available_volume=201,
            order_statuses=[("pending_new", 0, 0, None)],
            execution_reports=[()],
        ),
        market_gateway=FakeMarketGateway(),
        decision_state_manager=M2StateManager(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 5.1]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(ratio="0.80"), round_no=1, reconcile_timeout_seconds=5)

    assert report.execution_details[-1].broker_order_id == "BK_1"
    assert report.execution_details[-1].last_order_status == "pending_new"
    assert report.execution_details[-1].remaining_volume == 200


def test_run_round_does_not_log_filled_state_with_zero_filled_volume() -> None:
    state_logger = CapturingLogger()
    service = M3ExecutionService(
        trade_gateway=SequencedTradeGateway(
            positions=(_position(volume=100, available_volume=100),),
            order_statuses=[("filled", 0, 0, "BK_1")],
            execution_reports=[(_execution(100),)],
        ),
        market_gateway=FakeMarketGateway(),
        decision_state_manager=M2StateManager(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=state_logger),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(ratio="1.0"), round_no=1, reconcile_timeout_seconds=5)

    filled_logs = [
        message
        for message in state_logger.messages
        if "old_state=submitted new_state=filled" in message
    ]
    assert filled_logs
    assert not any("filled_volume=0" in message for message in filled_logs)
    assert any("filled_volume=100" in message for message in filled_logs)
    assert report.execution_details[-1].filled_volume == 100


def test_new_submit_clears_previous_order_filled_fields() -> None:
    class MultiSubmitGateway(SequencedTradeGateway):
        def submit_order(self, request):
            self.submit_calls += 1
            self.submitted_requests.append(request)
            return OrderSubmitResult(
                accepted=True,
                cl_ord_id=f"CL_{self.submit_calls}",
                broker_order_id=f"BK_{self.submit_calls}",
                symbol=request.symbol,
                message="accepted",
                raw_status="1",
                event_time=_now(),
            )

    gateway = MultiSubmitGateway(
        positions=(_position(volume=100, available_volume=100),),
        order_statuses=[
            ("filled", 100, 0, "BK_1"),
            ("pending_new", 0, 0, None),
        ],
        execution_reports=[
            (_execution(100),),
            (),
        ],
    )
    service = M3ExecutionService(
        trade_gateway=gateway,
        market_gateway=FakeMarketGateway(),
        decision_state_manager=M2StateManager(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=M2DecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2, 1.0, 1.1, 6.2]),
        sleep=lambda seconds: None,
    )

    first_round = service.run_round(config=_config(ratio="1.0"), round_no=1, reconcile_timeout_seconds=5)
    second_round = service.run_round(config=_config(ratio="1.0"), round_no=2, reconcile_timeout_seconds=5)

    assert first_round.execution_details[-1].execution_state == "filled"
    assert second_round.execution_details[0].cl_ord_id == "CL_2"
    assert second_round.execution_details[0].filled_volume == 0
    assert second_round.execution_details[0].avg_price is None
    assert second_round.execution_details[0].last_order_status == "pending_new"
