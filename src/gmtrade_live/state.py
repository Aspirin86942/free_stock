"""单标的状态管理。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from logging import Logger


class PositionState(str, Enum):
    """卖出流程中的持仓状态枚举。"""

    idle = "idle"
    triggered = "triggered"
    submitting = "submitting"
    submitted = "submitted"
    partially_filled = "partially_filled"
    filled = "filled"
    cancelled = "cancelled"
    failed = "failed"


@dataclass(slots=True)
class PositionStateSnapshot:
    """单个标的的状态快照。"""

    symbol: str
    state: PositionState
    order_id: str | None = None
    trigger_type: str | None = None
    trigger_price: Decimal | None = None
    requested_volume: int = 0
    filled_volume: int = 0
    last_update_time: datetime | None = None
    message: str = ""


class PositionStateManager:
    """按标的维护状态，避免不同股票之间互相污染。"""

    def __init__(self, logger: Logger | None) -> None:
        self._logger = logger
        self._cache: dict[str, PositionStateSnapshot] = {}

    def get_state(self, symbol: str) -> PositionStateSnapshot:
        """读取标的状态；未出现过的标的默认返回 idle。"""
        if symbol not in self._cache:
            return PositionStateSnapshot(symbol=symbol, state=PositionState.idle)
        return self._cache[symbol]

    def update_state(
        self,
        symbol: str,
        new_state: PositionState,
        **kwargs: object,
    ) -> None:
        """更新标的状态并记录迁移日志。"""
        snapshot = self.get_state(symbol)
        old_state = snapshot.state

        snapshot.state = new_state
        snapshot.last_update_time = datetime.now()

        for key, value in kwargs.items():
            if hasattr(snapshot, key):
                setattr(snapshot, key, value)

        self._cache[symbol] = snapshot

        # 这里统一记录状态迁移，是为了后续接入真实报单回报时仍能追溯单标的状态变化链路。
        if self._logger:
            extra_text = " ".join(f"{key}={value}" for key, value in kwargs.items())
            self._logger.info(
                "state_change symbol=%s old_state=%s new_state=%s%s",
                symbol,
                old_state.value,
                new_state.value,
                f" {extra_text}" if extra_text else "",
            )

    def has_open_order(self, symbol: str) -> bool:
        """判断标的是否仍有未完结卖单。"""
        state = self.get_state(symbol).state
        return state in [PositionState.submitted, PositionState.partially_filled]
