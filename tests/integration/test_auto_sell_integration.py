from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    CandidateRound,
    CandidateRoundSummary,
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


def _config(*, ratio: str = "1.0") -> AppConfig:
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


def _position(symbol: str = "SZSE.002594") -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        exchange=symbol.split(".", maxsplit=1)[0],
        volume=200,
        available_volume=200,
        cost_price=Decimal("10.00"),
        last_update_time=_now(),
    )


def _candidate(position: PositionSnapshot) -> SellCandidate:
    decision = DecisionResult(
        symbol=position.symbol,
        should_sell=True,
        can_submit_sell=True,
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
    state_snapshot = DecisionPositionStateSnapshot(
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
    return SellCandidate(decision=decision, state_snapshot=state_snapshot)


def _candidate_round(round_no: int, candidates: tuple[SellCandidate, ...]) -> CandidateRound:
    return CandidateRound(
        summary=CandidateRoundSummary(
            round_no=round_no,
            session_state="trading",
            position_count=len(candidates),
            watching_count=len(candidates),
            tombstone_count=0,
            should_sell_count=len(candidates),
            can_submit_sell_count=len(candidates),
            changed_symbol_count=0,
            duration_ms=1,
        ),
        candidates=candidates,
        tombstones=(),
        change_events=(),
    )


def _execution(
    filled_volume: int,
    *,
    symbol: str = "SZSE.002594",
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
        order_statuses: list[tuple[str, int, int, str | None]] | None = None,
        execution_reports: list[tuple[OrderExecutionSnapshot, ...]] | None = None,
    ) -> None:
        self.order_statuses = order_statuses or [("filled", 200, 0, "BK_1")]
        self.execution_reports = execution_reports or [(_execution(200),)]
        self.submit_calls = 0
        self.query_order_status_calls = 0
        self._last_query_index = 0

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


def test_auto_sell_once_round_keeps_polling_until_budget_exhausted_or_order_finishes() -> None:
    service = AutoSellService(
        trade_gateway=SequencedTradeGateway(
            order_statuses=[
                ("pending_new", 0, 0, "BK_1"),
                ("partially_filled", 100, 100, "BK_1"),
                ("filled", 200, 0, "BK_1"),
            ],
            execution_reports=[
                (),
                (_execution(100),),
                (_execution(200),),
            ],
        ),
        candidate_pipeline=FakeCandidatePipeline(
            rounds=[_candidate_round(1, (_candidate(_position()),))]
        ),
        execution_state_manager=OrderExecutionStateStore(logger=None),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2, 0.7, 0.8, 1.3, 1.4]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=5)

    assert report.summary.submitted_count == 1
    assert report.summary.open_order_count == 0
    assert report.execution_details[-1].execution_state == "filled"
    assert report.execution_details[-1].decision_trigger_reason == "take_profit_triggered"


def test_open_order_continues_in_next_round_after_timeout() -> None:
    trade_gateway = SequencedTradeGateway(
        order_statuses=[
            ("pending_new", 0, 0, "BK_1"),
            ("filled", 200, 0, "BK_1"),
        ],
        execution_reports=[
            (),
            (_execution(200),),
        ],
    )
    candidate = _candidate(_position())
    service = AutoSellService(
        trade_gateway=trade_gateway,
        candidate_pipeline=FakeCandidatePipeline(
            rounds=[
                _candidate_round(1, (candidate,)),
                _candidate_round(2, (candidate,)),
            ]
        ),
        execution_state_manager=OrderExecutionStateStore(logger=None),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 1.2, 2.0, 2.1, 2.2]),
        sleep=lambda seconds: None,
    )

    first_round = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=1)
    second_round = service.run_round(config=_config(), round_no=2, reconcile_timeout_seconds=5)

    assert first_round.summary.submitted_count == 1
    assert first_round.summary.open_order_count == 1
    assert second_round.summary.submitted_count == 0
    assert second_round.execution_details[-1].execution_state == "filled"
    assert second_round.execution_details[-1].filled_volume == 200
    assert trade_gateway.submit_calls == 1
    assert (
        service._execution_state_manager.get_state("SZSE.002594").state
        is OrderExecutionState.filled
    )
