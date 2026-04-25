from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    CandidateRound,
    CandidateRoundSummary,
    DecisionChangeEvent,
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    DecisionResult,
    OrderExecutionSnapshot,
    OrderStatusSnapshot,
    OrderSubmitResult,
    PositionSnapshot,
    SellCandidate,
)
from gmtrade_live.services.auto_sell_service import AutoSellService
from gmtrade_live.services.order_execution_state import (
    OrderExecutionState,
    OrderExecutionStateStore,
)


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


def _decision(position: PositionSnapshot, *, can_submit_sell: bool = True) -> DecisionResult:
    return DecisionResult(
        symbol=position.symbol,
        should_sell=True,
        can_submit_sell=can_submit_sell,
        trigger_reason="take_profit_triggered",
        block_reason=None,
        current_price=Decimal("10.80"),
        cost_price=position.cost_price,
        take_profit_price=Decimal("10.50"),
        stop_loss_price=Decimal("9.70"),
        volume=position.volume,
        available_volume=position.available_volume,
        sellable_now=True,
        session_state="trading",
        evaluated_at=_now(),
    )


def _decision_state(position: PositionSnapshot) -> DecisionPositionStateSnapshot:
    return DecisionPositionStateSnapshot(
        symbol=position.symbol,
        lifecycle_state=DecisionLifecycleState.watching,
        has_position=True,
        sellable_now=True,
        volume=position.volume,
        available_volume=position.available_volume,
        first_seen_at=_now(),
        last_seen_at=_now(),
        disappeared_at=None,
        tombstone_rounds=0,
        last_trigger_reason="take_profit_triggered",
        last_block_reason=None,
        last_decision_at=_now(),
    )


def _candidate(position: PositionSnapshot, *, can_submit_sell: bool = True) -> SellCandidate:
    return SellCandidate(
        decision=_decision(position, can_submit_sell=can_submit_sell),
        state_snapshot=_decision_state(position),
    )


def _candidate_round(
    *,
    round_no: int = 1,
    candidates: tuple[SellCandidate, ...],
) -> CandidateRound:
    return CandidateRound(
        summary=CandidateRoundSummary(
            round_no=round_no,
            session_state="trading",
            position_count=len(candidates),
            watching_count=len(candidates),
            tombstone_count=0,
            should_sell_count=sum(1 for item in candidates if item.decision.should_sell),
            can_submit_sell_count=sum(
                1 for item in candidates if item.decision.can_submit_sell
            ),
            changed_symbol_count=0,
            duration_ms=1,
        ),
        candidates=candidates,
        tombstones=(),
        change_events=(
            DecisionChangeEvent(
                symbol=candidates[0].decision.symbol,
                change_tags=("trigger_activated",),
                decision=candidates[0].decision,
                state_snapshot=candidates[0].state_snapshot,
            ),
        )
        if candidates
        else (),
    )


def _execution(
    filled_volume: int,
    *,
    symbol: str = "SHSE.600036",
    event_time: datetime | None = None,
) -> OrderExecutionSnapshot:
    return OrderExecutionSnapshot(
        cl_ord_id="CL_1",
        broker_order_id="BK_1",
        symbol=symbol,
        filled_volume=filled_volume,
        avg_price=Decimal("10.80"),
        event_time=event_time or _now(),
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


class FakeCandidatePipeline:
    def __init__(self, rounds: list[CandidateRound]) -> None:
        self._rounds = rounds
        self.calls = 0

    def run_round(self, *, config: AppConfig, round_no: int) -> CandidateRound:
        del config, round_no
        index = min(self.calls, len(self._rounds) - 1)
        self.calls += 1
        return self._rounds[index]


class SequencedTradeGateway:
    def __init__(
        self,
        *,
        submit_result: OrderSubmitResult | None = None,
        order_statuses: list[tuple[str, int, int, str | None]] | None = None,
        order_status_event_times: list[datetime] | None = None,
        execution_reports: list[tuple[OrderExecutionSnapshot, ...]] | None = None,
    ) -> None:
        self.submit_result = submit_result or OrderSubmitResult(
            accepted=True,
            cl_ord_id="CL_1",
            broker_order_id="BK_1",
            symbol="SHSE.600036",
            message="accepted",
            raw_status="1",
            event_time=_now(),
        )
        self.order_statuses = order_statuses or [("filled", 200, 0, "BK_1")]
        self.order_status_event_times = order_status_event_times or [_now()]
        self.execution_reports = execution_reports or [(_execution(200),)]
        self.submit_calls = 0
        self.submitted_requests: list[object] = []
        self.query_order_status_calls = 0
        self._last_query_index = 0

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
        event_time = self.order_status_event_times[
            min(index, len(self.order_status_event_times) - 1)
        ]
        return OrderStatusSnapshot(
            cl_ord_id=cl_ord_id,
            broker_order_id=broker_order_id,
            symbol=symbol,
            status=status,
            filled_volume=filled_volume,
            remaining_volume=remaining_volume,
            rejection_reason=None,
            event_time=event_time,
        )

    def query_execution_reports(self, cl_ord_id: str):
        index = min(self._last_query_index, len(self.execution_reports) - 1)
        return self.execution_reports[index]


class CapturingLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *args, **kwargs) -> None:
        del kwargs
        self.messages.append(message % args if args else message)


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def info(self, message: str, *args, **kwargs) -> None:
        del kwargs
        rendered = message % args if args else message
        self.events.append(json.loads(rendered))


def test_run_round_consumes_shared_candidate_round() -> None:
    pipeline = FakeCandidatePipeline(rounds=[_candidate_round(candidates=(_candidate(_position()),))])
    service = AutoSellService(
        trade_gateway=SequencedTradeGateway(),
        candidate_pipeline=pipeline,
        execution_state_manager=OrderExecutionStateStore(logger=None),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=5)

    assert pipeline.calls == 1
    assert report.execution_details[-1].decision_lifecycle_state == "watching"
    assert report.execution_details[-1].decision_can_submit_sell is True
    assert report.execution_details[-1].execution_state == "filled"

def test_run_round_reconciles_new_submit_until_filled_within_shared_budget() -> None:
    sleep_calls: list[float] = []
    candidate = _candidate(_position(volume=250, available_volume=201))
    service = AutoSellService(
        trade_gateway=SequencedTradeGateway(
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
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(candidate,))]),
        execution_state_manager=OrderExecutionStateStore(logger=None),
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
    execution_manager = OrderExecutionStateStore(logger=None)
    execution_manager.update_state(
        "SHSE.600036",
        OrderExecutionState.submitted,
        cl_ord_id="CL_EXIST",
        broker_order_id="BK_1",
        requested_volume=200,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="submitted",
    )
    service = AutoSellService(
        trade_gateway=trade_gateway,
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(_candidate(_position()),))]),
        execution_state_manager=execution_manager,
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


def test_run_round_reconciles_existing_open_order_when_candidate_is_not_submittable() -> None:
    trade_gateway = SequencedTradeGateway(
        order_statuses=[("filled", 200, 0, "BK_1")],
        execution_reports=[(_execution(200),)],
    )
    execution_manager = OrderExecutionStateStore(logger=None)
    execution_manager.update_state(
        "SHSE.600036",
        OrderExecutionState.submitted,
        cl_ord_id="CL_EXIST",
        broker_order_id="BK_1",
        requested_volume=200,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="submitted",
    )
    service = AutoSellService(
        trade_gateway=trade_gateway,
        candidate_pipeline=FakeCandidatePipeline(
            rounds=[_candidate_round(candidates=(_candidate(_position(), can_submit_sell=False),))]
        ),
        execution_state_manager=execution_manager,
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(), round_no=2, reconcile_timeout_seconds=5)

    assert trade_gateway.submit_calls == 0
    assert trade_gateway.query_order_status_calls == 1
    assert report.execution_details[-1].execution_state == "filled"


def test_run_round_reconciles_existing_open_order_when_symbol_missing_from_candidates() -> None:
    trade_gateway = SequencedTradeGateway(
        order_statuses=[("filled", 200, 0, "BK_1")],
        execution_reports=[(_execution(200),)],
    )
    execution_manager = OrderExecutionStateStore(logger=None)
    execution_manager.update_state(
        "SHSE.600036",
        OrderExecutionState.submitted,
        cl_ord_id="CL_EXIST",
        broker_order_id="BK_1",
        trigger_reason="take_profit_triggered",
        requested_volume=200,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="submitted",
    )
    service = AutoSellService(
        trade_gateway=trade_gateway,
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=())]),
        execution_state_manager=execution_manager,
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(), round_no=2, reconcile_timeout_seconds=5)

    assert trade_gateway.submit_calls == 0
    assert trade_gateway.query_order_status_calls == 1
    assert report.execution_details[-1].symbol == "SHSE.600036"
    assert report.execution_details[-1].execution_state == "filled"
    assert report.execution_details[-1].decision_can_submit_sell is False


def test_run_round_emits_block_detail_with_decision_projection() -> None:
    trade_gateway = SequencedTradeGateway()
    candidate = _candidate(_position(volume=250, available_volume=201))
    service = AutoSellService(
        trade_gateway=trade_gateway,
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(candidate,))]),
        execution_state_manager=OrderExecutionStateStore(logger=None),
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
    candidate = _candidate(_position(volume=250, available_volume=201))
    service = AutoSellService(
        trade_gateway=SequencedTradeGateway(
            order_statuses=[("pending_new", 0, 0, None)],
            execution_reports=[()],
        ),
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(candidate,))]),
        execution_state_manager=OrderExecutionStateStore(logger=None),
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
    candidate = _candidate(_position(volume=100, available_volume=100))
    service = AutoSellService(
        trade_gateway=SequencedTradeGateway(
            order_statuses=[("filled", 0, 0, "BK_1")],
            execution_reports=[(_execution(100),)],
        ),
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(candidate,))]),
        execution_state_manager=OrderExecutionStateStore(logger=state_logger),
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
        order_statuses=[
            ("filled", 100, 0, "BK_1"),
            ("pending_new", 0, 0, None),
        ],
        execution_reports=[
            (_execution(100),),
            (),
        ],
    )
    candidate = _candidate(_position(volume=100, available_volume=100))
    service = AutoSellService(
        trade_gateway=gateway,
        candidate_pipeline=FakeCandidatePipeline(
            rounds=[
                _candidate_round(round_no=1, candidates=(candidate,)),
                _candidate_round(round_no=2, candidates=(candidate,)),
            ]
        ),
        execution_state_manager=OrderExecutionStateStore(logger=None),
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


def test_run_round_emits_terminal_audit_event_with_latency() -> None:
    submit_time = datetime(2026, 4, 13, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    fill_time = datetime(2026, 4, 13, 10, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    audit_logger = CapturingAuditLogger()
    trade_gateway = SequencedTradeGateway(
        submit_result=OrderSubmitResult(
            accepted=True,
            cl_ord_id="CL_1",
            broker_order_id="BK_1",
            symbol="SHSE.600036",
            message="accepted",
            raw_status="1",
            event_time=submit_time,
        ),
        order_statuses=[("filled", 200, 0, "BK_1")],
        order_status_event_times=[fill_time],
        execution_reports=[(_execution(200, event_time=fill_time),)],
    )
    service = AutoSellService(
        trade_gateway=trade_gateway,
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(_candidate(_position()),))]),
        execution_state_manager=OrderExecutionStateStore(logger=None),
        logger=logging.getLogger("test"),
        audit_logger=audit_logger,
        clock=lambda: submit_time,
        timer=FakeTimer([0.0, 0.1, 0.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(ratio="1.0"), round_no=1, reconcile_timeout_seconds=5)

    terminal_events = [
        event
        for event in audit_logger.events
        if event["event_type"] == "terminal_state_reached"
    ]
    assert terminal_events[0]["order_terminal_latency_ms"] == 1000
    assert terminal_events[0]["submit_accepted_at"] == submit_time.isoformat()
    assert terminal_events[0]["terminal_state_at"] == fill_time.isoformat()
    assert report.execution_details[-1].order_terminal_latency_ms == 1000


def test_run_round_emits_reconcile_timeout_without_latency() -> None:
    audit_logger = CapturingAuditLogger()
    candidate = _candidate(_position(volume=250, available_volume=201))
    service = AutoSellService(
        trade_gateway=SequencedTradeGateway(
            order_statuses=[("pending_new", 0, 0, "BK_1")],
            execution_reports=[()],
        ),
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(candidate,))]),
        execution_state_manager=OrderExecutionStateStore(logger=None),
        logger=logging.getLogger("test"),
        audit_logger=audit_logger,
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 5.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(ratio="0.80"), round_no=1, reconcile_timeout_seconds=5)

    timeout_events = [
        event for event in audit_logger.events if event["event_type"] == "reconcile_timeout"
    ]
    assert timeout_events[0]["order_terminal_latency_ms"] is None
    assert report.execution_details[-1].terminal_state_at is None


def test_run_round_emits_submit_rejected_audit_event() -> None:
    audit_logger = CapturingAuditLogger()
    trade_gateway = SequencedTradeGateway(
        submit_result=OrderSubmitResult(
            accepted=False,
            cl_ord_id=None,
            broker_order_id=None,
            symbol="SHSE.600036",
            message="rejected",
            raw_status="rejected",
            event_time=_now(),
        ),
    )
    service = AutoSellService(
        trade_gateway=trade_gateway,
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(_candidate(_position()),))]),
        execution_state_manager=OrderExecutionStateStore(logger=None),
        logger=logging.getLogger("test"),
        audit_logger=audit_logger,
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(ratio="1.0"), round_no=1, reconcile_timeout_seconds=5)

    rejected_events = [
        event for event in audit_logger.events if event["event_type"] == "submit_rejected"
    ]
    assert rejected_events[0]["message"] == "rejected"
    assert report.execution_details[0].change_tags == ("submit_rejected",)


def test_run_round_delays_terminal_audit_until_execution_report_arrives() -> None:
    submit_time = datetime(2026, 4, 13, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    fill_time = datetime(2026, 4, 13, 10, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    audit_logger = CapturingAuditLogger()
    service = AutoSellService(
        trade_gateway=SequencedTradeGateway(
            submit_result=OrderSubmitResult(
                accepted=True,
                cl_ord_id="CL_1",
                broker_order_id="BK_1",
                symbol="SHSE.600036",
                message="accepted",
                raw_status="1",
                event_time=submit_time,
            ),
            order_statuses=[
                ("filled", 200, 0, "BK_1"),
                ("filled", 200, 0, "BK_1"),
            ],
            order_status_event_times=[fill_time, fill_time],
            execution_reports=[
                (),
                (_execution(200, event_time=fill_time),),
            ],
        ),
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(_candidate(_position()),))]),
        execution_state_manager=OrderExecutionStateStore(logger=None),
        logger=logging.getLogger("test"),
        audit_logger=audit_logger,
        clock=lambda: submit_time,
        timer=FakeTimer([0.0, 0.1, 0.2, 0.7, 0.8]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(ratio="1.0"), round_no=1, reconcile_timeout_seconds=5)

    terminal_events = [
        event
        for event in audit_logger.events
        if event["event_type"] == "terminal_state_reached"
    ]
    assert len(terminal_events) == 1
    assert terminal_events[0]["avg_price"] == "10.80"
    assert report.execution_details[-1].avg_price == Decimal("10.80")


def test_run_round_uses_reconcile_timeout_when_terminal_audit_is_still_pending() -> None:
    submit_time = datetime(2026, 4, 13, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    fill_time = datetime(2026, 4, 13, 10, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    audit_logger = CapturingAuditLogger()
    service = AutoSellService(
        trade_gateway=SequencedTradeGateway(
            submit_result=OrderSubmitResult(
                accepted=True,
                cl_ord_id="CL_1",
                broker_order_id="BK_1",
                symbol="SHSE.600036",
                message="accepted",
                raw_status="1",
                event_time=submit_time,
            ),
            order_statuses=[("filled", 200, 0, "BK_1")],
            order_status_event_times=[fill_time],
            execution_reports=[()],
        ),
        candidate_pipeline=FakeCandidatePipeline(rounds=[_candidate_round(candidates=(_candidate(_position()),))]),
        execution_state_manager=OrderExecutionStateStore(logger=None),
        logger=logging.getLogger("test"),
        audit_logger=audit_logger,
        clock=lambda: submit_time,
        timer=FakeTimer([0.0, 0.1, 5.2]),
        sleep=lambda seconds: None,
    )

    service.run_round(config=_config(ratio="1.0"), round_no=1, reconcile_timeout_seconds=5)

    terminal_events = [
        event
        for event in audit_logger.events
        if event["event_type"] == "terminal_state_reached"
    ]
    timeout_events = [
        event for event in audit_logger.events if event["event_type"] == "reconcile_timeout"
    ]
    assert not terminal_events
    assert timeout_events[0]["message"] == "terminal_audit_pending"
    assert timeout_events[0]["avg_price"] is None
