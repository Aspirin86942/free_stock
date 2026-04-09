"""交易时段判定逻辑。"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo


class TradingSessionState(str, Enum):
    """简化后的交易时段枚举。"""

    PRE_OPEN = "pre_open"
    TRADING = "trading"
    POST_CLOSE = "post_close"
    CLOSED_DAY = "closed_day"


def resolve_trading_session(
    now: datetime,
    *,
    start_text: str,
    end_text: str,
    timezone_name: str,
) -> TradingSessionState:
    """根据本地时间和交易窗口判断当前所处交易阶段。"""
    local_now = now.astimezone(ZoneInfo(timezone_name))
    start_time = time.fromisoformat(start_text)
    end_time = time.fromisoformat(end_text)
    current_time = local_now.timetz().replace(tzinfo=None)

    # M0 只需要判断是否处于固定交易窗口，先按周末和时间区间切分，避免过早引入交易日历依赖。
    if local_now.weekday() >= 5:
        return TradingSessionState.CLOSED_DAY
    if current_time < start_time:
        return TradingSessionState.PRE_OPEN
    if current_time > end_time:
        return TradingSessionState.POST_CLOSE
    return TradingSessionState.TRADING
