from decimal import Decimal

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
        PositionState.triggered,
        trigger_type="take_profit",
        trigger_price=Decimal("10.50"),
    )

    snapshot = manager.get_state("SHSE.600036")
    assert snapshot.state == PositionState.triggered
    assert snapshot.trigger_type == "take_profit"
    assert snapshot.trigger_price == Decimal("10.50")


def test_state_manager_detects_open_orders() -> None:
    manager = PositionStateManager(logger=None)

    assert manager.has_open_order("SHSE.600036") is False

    manager.update_state("SHSE.600036", PositionState.submitted, order_id="ORDER_123")
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", PositionState.partially_filled)
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", PositionState.filled)
    assert manager.has_open_order("SHSE.600036") is False


def test_state_manager_isolates_symbols() -> None:
    manager = PositionStateManager(logger=None)

    manager.update_state("SHSE.600036", PositionState.submitted, order_id="ORDER_1")
    manager.update_state("SHSE.600000", PositionState.triggered)

    assert manager.get_state("SHSE.600036").state == PositionState.submitted
    assert manager.get_state("SHSE.600000").state == PositionState.triggered
    assert manager.has_open_order("SHSE.600036") is True
    assert manager.has_open_order("SHSE.600000") is False
