"""M2 决策态管理。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from logging import Logger

from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    PositionSnapshot,
)


class M2StateManager:
    """维护 M2 逐标的决策态和一轮墓碑态。"""

    def __init__(self, logger: Logger | None) -> None:
        self._logger = logger
        self._cache: dict[str, DecisionPositionStateSnapshot] = {}

    def sync_positions(
        self,
        *,
        positions: tuple[PositionSnapshot, ...],
        now: datetime,
    ) -> tuple[DecisionPositionStateSnapshot, ...]:
        """根据当前持仓集合同步 watching/tombstone 状态。"""
        # 只保留真正有仓位的持仓
        active_positions = tuple(
            position for position in positions if position.volume > 0
        )
        active_symbols = {position.symbol for position in active_positions}
        next_cache: dict[str, DecisionPositionStateSnapshot] = {}
        # 处理当前还在持仓里的股票，这只股票是新出现的，创建一条 watching 状态；
        # 这只股票以前就存在，更新成最新 watching 状态
        for position in active_positions:
            current = self._cache.get(position.symbol)
            if current is None:
                next_cache[position.symbol] = DecisionPositionStateSnapshot(
                    symbol=position.symbol,
                    lifecycle_state=DecisionLifecycleState.watching,
                    has_position=True,
                    sellable_now=position.available_volume > 0,
                    volume=position.volume,
                    available_volume=position.available_volume,
                    first_seen_at=now,
                    last_seen_at=now,
                    disappeared_at=None,
                    tombstone_rounds=0,
                    last_trigger_reason=None,
                    last_block_reason=None,
                    last_decision_at=now,
                )
                continue

            next_cache[position.symbol] = replace(
                current,
                lifecycle_state=DecisionLifecycleState.watching,
                has_position=True,
                sellable_now=position.available_volume > 0,
                volume=position.volume,
                available_volume=position.available_volume,
                last_seen_at=now,
                disappeared_at=None,
                tombstone_rounds=0,
            )
        # 处理当前不再持仓里的股票，这只股票以前就存在，更新成最新 tombstone 状态；
        for symbol, snapshot in self._cache.items():
            if symbol in active_symbols:
                continue
            if snapshot.lifecycle_state is DecisionLifecycleState.tombstone:
                continue

            # 这里保留一轮墓碑，是为了让持仓消失也能被后续变化检测和审计层看见。
            next_cache[symbol] = replace(
                snapshot,
                lifecycle_state=DecisionLifecycleState.tombstone,
                has_position=False,
                sellable_now=False,
                volume=0,
                available_volume=0,
                disappeared_at=now,
                tombstone_rounds=1,
            )

        self._cache = next_cache
        return self.active_states()

    def get_state(self, symbol: str) -> DecisionPositionStateSnapshot | None:
        """获取当前标的状态。"""
        return self._cache.get(symbol)

    def update_decision_feedback(
        self,
        symbol: str,
        *,
        trigger_reason: str | None,
        block_reason: str | None,
        volume: int,
        available_volume: int,
        sellable_now: bool,
        decision_time: datetime,
    ) -> DecisionPositionStateSnapshot:
        """回写本轮决策反馈。"""
        current = self._cache[symbol]
        updated = replace(
            current,
            sellable_now=sellable_now,
            volume=volume,
            available_volume=available_volume,
            last_trigger_reason=trigger_reason,
            last_block_reason=block_reason,
            last_decision_at=decision_time,
        )
        self._cache[symbol] = updated
        return updated

    def active_states(self) -> tuple[DecisionPositionStateSnapshot, ...]:
        """返回当前活跃状态快照。"""
        return tuple(sorted(self._cache.values(), key=lambda item: item.symbol))
