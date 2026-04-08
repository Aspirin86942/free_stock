from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.session import TradingSessionState, resolve_trading_session


def test_setup_logging_creates_runtime_log_file(tmp_path: Path) -> None:
    logger = setup_logging("gmtrade-live-m0", tmp_path)
    logger.info("hello m0")

    assert (tmp_path / "runtime.log").exists()


def test_resolve_trading_session_returns_closed_day_on_saturday() -> None:
    saturday = datetime(2026, 4, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    state = resolve_trading_session(
        saturday,
        start_text="09:30:00",
        end_text="15:00:00",
        timezone_name="Asia/Shanghai",
    )

    assert state is TradingSessionState.CLOSED_DAY
