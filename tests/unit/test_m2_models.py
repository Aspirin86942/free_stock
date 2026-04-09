from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    DecisionResult,
    EvaluatedSymbol,
    M2ChangeEvent,
    M2RoundReport,
    M2RoundSummary,
)


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_decision_result_allows_should_sell_without_submit() -> None:
    result = DecisionResult(
        symbol="SHSE.600036",
        should_sell=True,
        can_submit_sell=False,
        trigger_reason="take_profit_triggered",
        block_reason="not_in_trading_session",
        current_price=Decimal("10.80"),
        cost_price=Decimal("10.00"),
        take_profit_price=Decimal("10.50"),
        stop_loss_price=Decimal("9.70"),
        volume=100,
        available_volume=100,
        sellable_now=True,
        session_state="post_close",
        evaluated_at=_now(),
    )

    assert result.should_sell is True
    assert result.can_submit_sell is False
    assert result.trigger_reason == "take_profit_triggered"
    assert result.block_reason == "not_in_trading_session"


def test_decision_position_state_snapshot_supports_tombstone() -> None:
    snapshot = DecisionPositionStateSnapshot(
        symbol="SHSE.600036",
        lifecycle_state=DecisionLifecycleState.tombstone,
        has_position=False,
        sellable_now=False,
        volume=0,
        available_volume=0,
        first_seen_at=_now(),
        last_seen_at=_now(),
        disappeared_at=_now(),
        tombstone_rounds=1,
        last_trigger_reason=None,
        last_block_reason="position_missing",
        last_decision_at=_now(),
    )

    assert snapshot.lifecycle_state is DecisionLifecycleState.tombstone
    assert snapshot.disappeared_at is not None
    assert snapshot.tombstone_rounds == 1


def test_m2_round_report_contains_summary_and_change_events() -> None:
    decision = DecisionResult(
        symbol="SHSE.600036",
        should_sell=True,
        can_submit_sell=True,
        trigger_reason="take_profit_triggered",
        block_reason=None,
        current_price=Decimal("10.80"),
        cost_price=Decimal("10.00"),
        take_profit_price=Decimal("10.50"),
        stop_loss_price=Decimal("9.70"),
        volume=100,
        available_volume=100,
        sellable_now=True,
        session_state="trading",
        evaluated_at=_now(),
    )
    state_snapshot = DecisionPositionStateSnapshot(
        symbol="SHSE.600036",
        lifecycle_state=DecisionLifecycleState.watching,
        has_position=True,
        sellable_now=True,
        volume=100,
        available_volume=100,
        first_seen_at=_now(),
        last_seen_at=_now(),
        disappeared_at=None,
        tombstone_rounds=0,
        last_trigger_reason="take_profit_triggered",
        last_block_reason=None,
        last_decision_at=_now(),
    )
    report = M2RoundReport(
        summary=M2RoundSummary(
            round_no=1,
            session_state="trading",
            position_count=1,
            watching_count=1,
            tombstone_count=0,
            should_sell_count=1,
            can_submit_sell_count=1,
            changed_symbol_count=1,
            duration_ms=12,
        ),
        evaluated_symbols=(EvaluatedSymbol(decision=decision, state_snapshot=state_snapshot),),
        tombstones=(),
        change_events=(
            M2ChangeEvent(
                symbol="SHSE.600036",
                change_tags=("trigger_activated", "submit_permission_granted"),
                decision=decision,
                state_snapshot=state_snapshot,
            ),
        ),
    )

    assert report.summary.round_no == 1
    assert report.change_events[0].change_tags == (
        "trigger_activated",
        "submit_permission_granted",
    )
