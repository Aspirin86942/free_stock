from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from logging import Logger


class PositionState(str, Enum):
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
    def __init__(self, logger: Logger | None) -> None:
        self._logger = logger
        self._cache: dict[str, PositionStateSnapshot] = {}

    def get_state(self, symbol: str) -> PositionStateSnapshot:
        if symbol not in self._cache:
            return PositionStateSnapshot(symbol=symbol, state=PositionState.idle)
        return self._cache[symbol]

    def update_state(
        self,
        symbol: str,
        new_state: PositionState,
        **kwargs: object,
    ) -> None:
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
        state = self.get_state(symbol).state
        return state in [PositionState.submitted, PositionState.partially_filled]
