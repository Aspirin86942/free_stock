"""M3 按标的维护订单执行态。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from logging import Logger


class M3ExecutionState(str, Enum):
    """自动卖出执行链的最小状态机。"""

    idle = "idle"
    submitting = "submitting"
    submitted = "submitted"
    partially_filled = "partially_filled"
    filled = "filled"
    cancelled = "cancelled"
    failed = "failed"


_TERMINAL_STATES = {
    M3ExecutionState.filled,
    M3ExecutionState.cancelled,
    M3ExecutionState.failed,
}


@dataclass(slots=True)
class M3ExecutionStateSnapshot:
    """单个标的的执行态快照。"""

    symbol: str
    state: M3ExecutionState
    cl_ord_id: str | None = None
    broker_order_id: str | None = None
    trigger_reason: str | None = None
    requested_volume: int = 0
    filled_volume: int = 0
    remaining_volume: int = 0
    submit_accepted: bool | None = None
    last_order_status: str | None = None
    rejection_reason: str | None = None
    avg_price: Decimal | None = None
    event_time: datetime | None = None
    last_update_time: datetime | None = None
    submit_started_at: datetime | None = None
    submit_accepted_at: datetime | None = None
    terminal_state_at: datetime | None = None
    message: str = ""


class M3PositionStateManager:
    """按标的维护执行态，避免不同股票之间互相污染。"""

    def __init__(self, logger: Logger | None) -> None:
        self._logger = logger
        self._cache: dict[str, M3ExecutionStateSnapshot] = {}

    def get_state(self, symbol: str) -> M3ExecutionStateSnapshot:
        """读取标的状态；未出现过的标的默认返回 idle。"""
        if symbol not in self._cache:
            return M3ExecutionStateSnapshot(symbol=symbol, state=M3ExecutionState.idle)
        return self._cache[symbol]

    def active_states(self) -> tuple[M3ExecutionStateSnapshot, ...]:
        """返回当前缓存里的所有执行态快照。"""
        return tuple(sorted(self._cache.values(), key=lambda item: item.symbol))

    def update_state(
        self,
        symbol: str,
        new_state: M3ExecutionState,
        **kwargs: object,
    ) -> None:
        """更新标的执行态并记录迁移日志。"""
        snapshot = self.get_state(symbol)
        old_state = snapshot.state

        snapshot.state = new_state
        snapshot.last_update_time = datetime.now()
        terminal_event_time = kwargs.get("event_time")
        if not isinstance(terminal_event_time, datetime):
            terminal_event_time = snapshot.last_update_time

        applied_updates: dict[str, object] = {}
        for key, value in kwargs.items():
            if key == "terminal_state_at":
                continue
            if hasattr(snapshot, key):
                setattr(snapshot, key, value)
                applied_updates[key] = value

        if new_state in _TERMINAL_STATES and snapshot.terminal_state_at is None:
            # 终态时间只记录第一次真实终态事件，避免后续轮询或外部传参把原始时点覆盖掉。
            snapshot.terminal_state_at = terminal_event_time
            applied_updates["terminal_state_at"] = terminal_event_time

        self._cache[symbol] = snapshot

        # 这里统一记录状态迁移，是为了后续基于查询驱动链路追溯单标的执行收口过程。
        if self._logger:
            extra_text = " ".join(
                f"{key}={value}" for key, value in applied_updates.items()
            )
            self._logger.info(
                "state_change symbol=%s old_state=%s new_state=%s%s",
                symbol,
                old_state.value,
                new_state.value,
                f" {extra_text}" if extra_text else "",
            )

    def has_open_order(self, symbol: str) -> bool:
        """把 submitting 也当成 open-order，挡住提交和查单之间的重复发单窗口。"""
        state = self.get_state(symbol).state
        return state in (
            M3ExecutionState.submitting,
            M3ExecutionState.submitted,
            M3ExecutionState.partially_filled,
        )
