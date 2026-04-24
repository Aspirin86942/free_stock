import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gmtrade_live.errors import ServiceError
from gmtrade_live.logging_setup import setup_logging, setup_order_audit_logger
from gmtrade_live.session import TradingSessionState, resolve_trading_session


def test_setup_logging_creates_runtime_log_file(tmp_path: Path) -> None:
    logger = setup_logging("gmtrade-live-auto-sell", tmp_path)
    logger.info("hello runtime")

    assert (tmp_path / "runtime.log").exists()


def test_setup_logging_routes_package_module_logs_to_runtime_file(tmp_path: Path) -> None:
    try:
        setup_logging("market-analysis-scheduler", tmp_path)

        module_logger = logging.getLogger("gmtrade_live.runtime_scheduler")
        module_logger.info("scheduler event")

        for logger_name in ("market-analysis-scheduler", "gmtrade_live"):
            for handler in logging.getLogger(logger_name).handlers:
                handler.flush()

        log_path = tmp_path / "runtime.log"
        assert log_path.exists()
        assert "scheduler event" in log_path.read_text(encoding="utf-8")
    finally:
        # 这里显式回收测试过程中挂到全局 logger 树上的 handler，避免污染后续 caplog。
        for logger_name in ("market-analysis-scheduler", "gmtrade_live"):
            logger = logging.getLogger(logger_name)
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            logger.setLevel(logging.NOTSET)
            logger.propagate = True


def test_setup_order_audit_logger_creates_order_audit_log_file(tmp_path: Path) -> None:
    logger = setup_order_audit_logger("gmtrade-live-auto-sell", tmp_path)
    logger.info('{"event":"audit"}')
    for handler in logger.handlers:
        handler.flush()

    log_path = tmp_path / "order_audit.log"
    assert log_path.exists()
    assert log_path.read_text(encoding="utf-8").strip() == '{"event":"audit"}'


def test_setup_order_audit_logger_keeps_single_handler_on_reinit(tmp_path: Path) -> None:
    logger_initial = setup_order_audit_logger("gmtrade-live-auto-sell", tmp_path)
    logger_initial.info('{"event":"first"}')
    handler_before = logger_initial.handlers[0]
    logger_after = setup_order_audit_logger("gmtrade-live-auto-sell", tmp_path)
    assert len(logger_after.handlers) == 1
    assert logger_after.handlers[0] is not handler_before
    stream = handler_before.stream
    assert stream is None or getattr(stream, "closed", True)


def test_resolve_trading_session_returns_closed_day_on_saturday() -> None:
    saturday = datetime(2026, 4, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    state = resolve_trading_session(
        saturday,
        timezone_name="Asia/Shanghai",
        market_session_mode="a_share",
    )

    assert state is TradingSessionState.CLOSED_DAY


@pytest.mark.parametrize(
    ("moment", "expected_state"),
    [
        (datetime(2026, 4, 10, 9, 29, tzinfo=ZoneInfo("Asia/Shanghai")), TradingSessionState.PRE_OPEN),
        (datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")), TradingSessionState.TRADING),
        (datetime(2026, 4, 10, 11, 45, tzinfo=ZoneInfo("Asia/Shanghai")), TradingSessionState.PRE_OPEN),
        (datetime(2026, 4, 10, 13, 30, tzinfo=ZoneInfo("Asia/Shanghai")), TradingSessionState.TRADING),
        (datetime(2026, 4, 10, 14, 58, tzinfo=ZoneInfo("Asia/Shanghai")), TradingSessionState.POST_CLOSE),
        (datetime(2026, 4, 10, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai")), TradingSessionState.POST_CLOSE),
    ],
)
def test_resolve_trading_session_matches_a_share_schedule(
    moment: datetime,
    expected_state: TradingSessionState,
) -> None:
    state = resolve_trading_session(
        moment,
        timezone_name="Asia/Shanghai",
        market_session_mode="a_share",
    )

    assert state is expected_state


def test_resolve_trading_session_rejects_unimplemented_market_session_mode() -> None:
    with pytest.raises(ServiceError) as exc_info:
        resolve_trading_session(
            datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            timezone_name="Asia/Shanghai",
            market_session_mode="futures_placeholder",
        )

    assert exc_info.value.code == "session.mode_not_implemented"
