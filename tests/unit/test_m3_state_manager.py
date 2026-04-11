from gmtrade_live.services.m3_state_manager import (
    M3ExecutionState,
    M3PositionStateManager,
)


def test_m3_state_manager_returns_idle_snapshot_for_new_symbol() -> None:
    manager = M3PositionStateManager(logger=None)

    snapshot = manager.get_state("SHSE.600036")

    assert snapshot.symbol == "SHSE.600036"
    assert snapshot.state is M3ExecutionState.idle
    assert snapshot.cl_ord_id is None


def test_m3_state_manager_treats_submitting_submitted_and_partial_as_open() -> None:
    manager = M3PositionStateManager(logger=None)

    manager.update_state(
        "SHSE.600036",
        M3ExecutionState.submitting,
        requested_volume=200,
        remaining_volume=200,
    )
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", M3ExecutionState.partially_filled)
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", M3ExecutionState.filled)
    assert manager.has_open_order("SHSE.600036") is False
