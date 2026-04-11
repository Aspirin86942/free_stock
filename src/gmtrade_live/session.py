"""交易时段判定逻辑。"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo

from gmtrade_live.errors import ServiceError


class TradingSessionState(str, Enum):
    """简化后的交易时段枚举。"""

    PRE_OPEN = "pre_open"
    TRADING = "trading"
    POST_CLOSE = "post_close"
    CLOSED_DAY = "closed_day"


_A_SHARE_MORNING_TRADING_START = time(9, 30, 0)
_A_SHARE_MORNING_TRADING_END = time(11, 30, 0)
_A_SHARE_AFTERNOON_TRADING_START = time(13, 0, 0)
_A_SHARE_AFTERNOON_TRADING_END = time(14, 57, 0)


def resolve_trading_session(
    now: datetime,
    *,
    timezone_name: str,
    market_session_mode: str,
) -> TradingSessionState:
    """根据市场模式判断当前所处交易阶段。"""
    if market_session_mode == "a_share":
        local_now = now.astimezone(ZoneInfo(timezone_name))
        current_time = local_now.timetz().replace(tzinfo=None)
        if local_now.weekday() >= 5:
            return TradingSessionState.CLOSED_DAY
        return _resolve_a_share_trading_session(current_time)
    if market_session_mode == "futures_placeholder":
        raise ServiceError(
            code="session.mode_not_implemented",
            message="期货交易时段模式尚未实现，当前版本禁止启动",
            retryable=False,
            context={"market_session_mode": market_session_mode},
        )
    raise ServiceError(
        code="session.invalid_mode",
        message="不支持的市场交易时段模式",
        retryable=False,
        context={"market_session_mode": market_session_mode},
    )


def _resolve_a_share_trading_session(current_time: time) -> TradingSessionState:
    """A 股自动卖出第一版只允许连续竞价，集合竞价和午休统一按不可交易处理。"""
    if _in_window(
        current_time,
        _A_SHARE_MORNING_TRADING_START,
        _A_SHARE_MORNING_TRADING_END,
    ) or _in_window(
        current_time,
        _A_SHARE_AFTERNOON_TRADING_START,
        _A_SHARE_AFTERNOON_TRADING_END,
    ):
        return TradingSessionState.TRADING
    if current_time < _A_SHARE_MORNING_TRADING_START or _in_window(
        current_time,
        _A_SHARE_MORNING_TRADING_END,
        _A_SHARE_AFTERNOON_TRADING_START,
    ):
        return TradingSessionState.PRE_OPEN
    return TradingSessionState.POST_CLOSE


def _in_window(current_time: time, start_time: time, end_time: time) -> bool:
    """统一使用左闭右开窗口，避免边界时刻在相邻阶段重复归类。"""
    return start_time <= current_time < end_time
