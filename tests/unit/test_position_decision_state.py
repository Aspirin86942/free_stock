from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import DecisionLifecycleState, PositionSnapshot
from gmtrade_live.services.position_decision_state import PositionDecisionStateStore


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 5, tzinfo=ZoneInfo("Asia/Shanghai"))


def _position(
    symbol: str,
    *,
    volume: int,
    available_volume: int,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        exchange=symbol.split(".", maxsplit=1)[0],
        volume=volume,
        available_volume=available_volume,
        cost_price=Decimal("10.00"),
        last_update_time=_now(),
    )


def test_sync_positions_creates_watching_state_for_volume_positions() -> None:
    manager = PositionDecisionStateStore(logging.getLogger("test"))

    snapshots = manager.sync_positions(
        positions=(
            _position("SHSE.600036", volume=100, available_volume=100),
            _position("SZSE.000001", volume=0, available_volume=0),
        ),
        now=_now(),
    )

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "SHSE.600036"
    assert snapshots[0].lifecycle_state is DecisionLifecycleState.watching


def test_sync_positions_transitions_to_tombstone_then_removes() -> None:
    manager = PositionDecisionStateStore(logging.getLogger("test"))
    manager.sync_positions(
        positions=(_position("SHSE.600036", volume=100, available_volume=100),),
        now=_now(),
    )

    first_missing = manager.sync_positions(positions=(), now=_now())
    assert first_missing[0].lifecycle_state is DecisionLifecycleState.tombstone
    assert first_missing[0].tombstone_rounds == 1

    second_missing = manager.sync_positions(positions=(), now=_now())
    assert second_missing == ()
    assert manager.get_state("SHSE.600036") is None


def test_update_decision_feedback_updates_reason_and_volume() -> None:
    manager = PositionDecisionStateStore(logging.getLogger("test"))
    manager.sync_positions(
        positions=(_position("SHSE.600036", volume=200, available_volume=0),),
        now=_now(),
    )

    snapshot = manager.update_decision_feedback(
        "SHSE.600036",
        trigger_reason="stop_loss_triggered",
        block_reason="temporarily_not_closable",
        volume=200,
        available_volume=0,
        sellable_now=False,
        decision_time=_now(),
    )

    assert snapshot.last_trigger_reason == "stop_loss_triggered"
    assert snapshot.last_block_reason == "temporarily_not_closable"
    assert snapshot.sellable_now is False

