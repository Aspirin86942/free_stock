from gmtrade_live.state import PositionState, PositionStateManager


def test_state_manager_returns_idle_for_new_symbol() -> None:
    manager = PositionStateManager(logger=None)

    snapshot = manager.get_state("SHSE.600036")

    assert snapshot.symbol == "SHSE.600036"
    assert snapshot.state == PositionState.idle


def test_state_manager_updates_state() -> None:
    manager = PositionStateManager(logger=None)

    manager.update_state(
        "SHSE.600036",
        PositionState.submitted,
        cl_ord_id="CL_1",
        broker_order_id="BK_1",
        trigger_reason="take_profit_triggered",
        requested_volume=200,
        filled_volume=0,
        remaining_volume=200,
        submit_accepted=True,
        last_order_status="submitted",
        rejection_reason=None,
        avg_price=None,
        message="accepted",
    )

    snapshot = manager.get_state("SHSE.600036")
    assert snapshot.state is PositionState.submitted
    assert snapshot.cl_ord_id == "CL_1"
    assert snapshot.broker_order_id == "BK_1"
    assert snapshot.trigger_reason == "take_profit_triggered"
    assert snapshot.remaining_volume == 200
    assert snapshot.submit_accepted is True
    assert snapshot.last_order_status == "submitted"


def test_state_manager_detects_open_orders() -> None:
    manager = PositionStateManager(logger=None)

    assert manager.has_open_order("SHSE.600036") is False

    manager.update_state(
        "SHSE.600036",
        PositionState.submitting,
        requested_volume=200,
        remaining_volume=200,
    )
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state(
        "SHSE.600036",
        PositionState.submitted,
        cl_ord_id="CL_1",
        remaining_volume=200,
    )
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", PositionState.partially_filled)
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", PositionState.filled)
    assert manager.has_open_order("SHSE.600036") is False


def test_state_manager_isolates_symbols() -> None:
    manager = PositionStateManager(logger=None)

    manager.update_state(
        "SHSE.600036",
        PositionState.submitted,
        cl_ord_id="CL_1",
        requested_volume=200,
        remaining_volume=200,
    )
    manager.update_state(
        "SHSE.600000",
        PositionState.failed,
        rejection_reason="broker_rejected",
    )

    assert manager.get_state("SHSE.600036").state is PositionState.submitted
    assert manager.get_state("SHSE.600000").state is PositionState.failed
    assert manager.has_open_order("SHSE.600036") is True
    assert manager.has_open_order("SHSE.600000") is False
