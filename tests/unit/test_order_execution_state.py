from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from gmtrade_live.services.order_execution_state import (
    OrderExecutionState,
    OrderExecutionStateStore,
)


def test_order_execution_state_returns_idle_snapshot_for_new_symbol() -> None:
    manager = OrderExecutionStateStore(logger=None)

    snapshot = manager.get_state("SHSE.600036")

    assert snapshot.symbol == "SHSE.600036"
    assert snapshot.state is OrderExecutionState.idle
    assert snapshot.cl_ord_id is None


def test_order_execution_state_treats_submitting_submitted_and_partial_as_open() -> None:
    manager = OrderExecutionStateStore(logger=None)

    manager.update_state(
        "SHSE.600036",
        OrderExecutionState.submitting,
        requested_volume=200,
        remaining_volume=200,
    )
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", OrderExecutionState.partially_filled)
    assert manager.has_open_order("SHSE.600036") is True

    manager.update_state("SHSE.600036", OrderExecutionState.filled)
    assert manager.has_open_order("SHSE.600036") is False


def test_order_execution_state_records_first_terminal_state_once() -> None:
    manager = OrderExecutionStateStore(logger=None)
    first_terminal = datetime(2026, 4, 13, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    second_terminal = datetime(2026, 4, 13, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai"))

    manager.update_state(
        "SHSE.600036",
        OrderExecutionState.submitted,
        event_time=first_terminal,
    )
    manager.update_state(
        "SHSE.600036",
        OrderExecutionState.filled,
        event_time=first_terminal,
    )
    manager.update_state(
        "SHSE.600036",
        OrderExecutionState.filled,
        event_time=second_terminal,
    )

    assert manager.get_state("SHSE.600036").terminal_state_at == first_terminal


def test_order_execution_state_ignores_external_terminal_state_override() -> None:
    manager = OrderExecutionStateStore(logger=None)
    first_terminal = datetime(2026, 4, 13, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    fake_terminal = datetime(2026, 4, 13, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai"))

    manager.update_state(
        "SHSE.600036",
        OrderExecutionState.submitting,
        terminal_state_at=fake_terminal,
    )
    assert manager.get_state("SHSE.600036").terminal_state_at is None

    manager.update_state(
        "SHSE.600036",
        OrderExecutionState.filled,
        event_time=first_terminal,
        terminal_state_at=fake_terminal,
    )

    assert manager.get_state("SHSE.600036").terminal_state_at == first_terminal


def test_order_execution_state_logs_only_effective_terminal_timestamp() -> None:
    logger = Mock()
    manager = OrderExecutionStateStore(logger=logger)
    first_terminal = datetime(2026, 4, 13, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    fake_terminal = datetime(2026, 4, 13, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai"))

    manager.update_state(
        "SHSE.600036",
        OrderExecutionState.submitting,
        terminal_state_at=fake_terminal,
    )
    first_extra_text = logger.info.call_args.args[4]
    assert "terminal_state_at" not in first_extra_text

    manager.update_state(
        "SHSE.600036",
        OrderExecutionState.filled,
        event_time=first_terminal,
        terminal_state_at=fake_terminal,
    )
    second_extra_text = logger.info.call_args.args[4]
    assert f"terminal_state_at={first_terminal}" in second_extra_text
    assert f"terminal_state_at={fake_terminal}" not in second_extra_text
