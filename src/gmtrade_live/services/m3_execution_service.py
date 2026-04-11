"""M3 自动卖出执行编排服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging
from time import perf_counter
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.protocols import MarketGateway, TradeGateway
from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionPositionStateSnapshot,
    M3BlockDetail,
    M3ExecutionDetail,
    M3RoundReport,
    M3RoundSummary,
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    PositionSnapshot,
)
from gmtrade_live.services.m3_quantity_rules import build_sell_quantity_plan
from gmtrade_live.session import resolve_trading_session
from gmtrade_live.state import PositionState, PositionStateManager


@dataclass(frozen=True, slots=True)
class _OrderStatusQueryEvent:
    """把一次查单结果转换成内部事件。"""

    broker_order_id: str | None
    status: str
    filled_volume: int
    remaining_volume: int
    rejection_reason: str | None
    event_time: datetime


@dataclass(frozen=True, slots=True)
class _ExecutionReportsQueryEvent:
    """把一次查成交结果转换成内部事件。"""

    broker_order_id: str | None
    filled_volume: int
    avg_price: Decimal | None
    event_time: datetime


class M3ExecutionService:
    """负责单轮自动卖出执行和查询驱动收口。"""

    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        market_gateway: MarketGateway,
        state_manager: PositionStateManager,
        decision_engine,
        logger: logging.Logger,
        clock=None,
        timer=None,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._state_manager = state_manager
        self._decision_engine = decision_engine
        self._logger = logger
        self._clock = clock or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self._timer = timer or perf_counter

    def run_round(self, *, config: AppConfig, round_no: int) -> M3RoundReport:
        """执行单轮 M3 自动卖出评估、提交和查询收口。"""
        started_at = self._timer()
        now = self._clock()
        session_state = resolve_trading_session(
            now,
            timezone_name=config.timezone,
            market_session_mode=config.market_session_mode,
        )

        positions = tuple(
            position
            for position in self._trade_gateway.get_positions(config.account_id)
            if position.volume > 0
        )
        symbols = [position.symbol for position in positions]
        quotes = tuple(self._market_gateway.get_quotes(symbols)) if symbols else ()
        quote_map = {quote.symbol: quote for quote in quotes}

        block_details: list[M3BlockDetail] = []
        execution_details: list[M3ExecutionDetail] = []
        changed_symbols: set[str] = set()
        submitted_count = 0
        candidate_count = 0

        for position in positions:
            decision = self._decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=_build_ephemeral_decision_state(position=position, now=now),
                config=config,
                now=now,
            )
            if not decision.can_submit_sell:
                continue

            candidate_count += 1

            if self._state_manager.has_open_order(position.symbol):
                tracked = self._track_existing_order(symbol=position.symbol, now=now)
                if tracked:
                    execution_details.extend(tracked)
                    changed_symbols.add(position.symbol)
                continue

            quantity_plan = build_sell_quantity_plan(
                symbol=position.symbol,
                total_volume=position.volume,
                available_volume=position.available_volume,
                sell_quantity_ratio=config.sell_quantity_ratio,
            )
            self._logger.info(
                "m3_quantity_evaluated symbol=%s raw_target_volume=%s final_target_volume=%s block_reason=%s",
                position.symbol,
                quantity_plan.raw_target_volume,
                quantity_plan.final_target_volume,
                quantity_plan.block_reason,
            )
            if quantity_plan.block_reason is not None:
                block_details.append(
                    M3BlockDetail(
                        symbol=position.symbol,
                        trigger_reason=decision.trigger_reason,
                        requested_ratio=config.sell_quantity_ratio,
                        total_volume=position.volume,
                        available_volume=position.available_volume,
                        raw_target_volume=quantity_plan.raw_target_volume,
                        promotion_type=quantity_plan.promotion_type,
                        normalized_target_volume=quantity_plan.final_target_volume,
                        block_reason=quantity_plan.block_reason,
                        evaluated_at=decision.evaluated_at,
                    )
                )
                changed_symbols.add(position.symbol)
                continue

            detail = self._submit_new_order(
                symbol=position.symbol,
                requested_volume=quantity_plan.final_target_volume,
                trigger_reason=decision.trigger_reason,
                now=now,
            )
            execution_details.append(detail)
            changed_symbols.add(position.symbol)
            if detail.submit_accepted is True:
                submitted_count += 1

        duration_ms = int((self._timer() - started_at) * 1000)
        return M3RoundReport(
            summary=M3RoundSummary(
                round_no=round_no,
                session_state=session_state.value,
                position_count=len(positions),
                candidate_count=candidate_count,
                blocked_count=len(block_details),
                submitted_count=submitted_count,
                open_order_count=sum(
                    1
                    for position in positions
                    if self._state_manager.has_open_order(position.symbol)
                ),
                changed_symbol_count=len(changed_symbols),
                duration_ms=duration_ms,
            ),
            block_details=tuple(block_details),
            execution_details=tuple(execution_details),
        )

    def _submit_new_order(
        self,
        *,
        symbol: str,
        requested_volume: int,
        trigger_reason: str | None,
        now: datetime,
    ) -> M3ExecutionDetail:
        """为新候选标的发起一次自动卖单提交。"""
        if self._state_manager.has_open_order(symbol):
            tracked = self._track_existing_order(symbol=symbol, now=now)
            if tracked:
                return tracked[0]
            return self._build_execution_detail(
                symbol=symbol,
                change_tags=("duplicate_submit_blocked",),
                now=now,
            )

        self._state_manager.update_state(
            symbol,
            PositionState.submitting,
            trigger_reason=trigger_reason,
            requested_volume=requested_volume,
            remaining_volume=requested_volume,
            message="submitting",
        )
        result = self._trade_gateway.submit_order(
            OrderRequest(
                symbol=symbol,
                volume=requested_volume,
                side="sell",
                price_type="market",
                price=None,
            )
        )
        if not result.accepted or result.cl_ord_id is None:
            self._state_manager.update_state(
                symbol,
                PositionState.failed,
                cl_ord_id=result.cl_ord_id,
                broker_order_id=result.broker_order_id,
                trigger_reason=trigger_reason,
                requested_volume=requested_volume,
                remaining_volume=requested_volume,
                submit_accepted=False,
                rejection_reason=result.message,
                event_time=result.event_time,
                message=result.message,
            )
            return self._build_execution_detail(
                symbol=symbol,
                change_tags=("submit_rejected",),
                now=now,
            )

        self._state_manager.update_state(
            symbol,
            PositionState.submitted,
            cl_ord_id=result.cl_ord_id,
            broker_order_id=result.broker_order_id,
            trigger_reason=trigger_reason,
            requested_volume=requested_volume,
            remaining_volume=requested_volume,
            submit_accepted=True,
            last_order_status="submitted",
            event_time=result.event_time,
            message=result.message,
        )
        tracked = self._track_existing_order(
            symbol=symbol,
            now=now,
            extra_change_tags=("submit_accepted",),
        )
        if tracked:
            return tracked[0]
        return self._build_execution_detail(
            symbol=symbol,
            change_tags=("submit_accepted",),
            now=now,
        )

    def _track_existing_order(
        self,
        *,
        symbol: str,
        now: datetime,
        extra_change_tags: tuple[str, ...] = (),
    ) -> list[M3ExecutionDetail]:
        """按已有状态查询委托和成交，驱动执行态收口。"""
        snapshot = self._state_manager.get_state(symbol)
        if snapshot.cl_ord_id is None:
            return []

        change_tags: list[str] = list(extra_change_tags)
        order_snapshot = self._trade_gateway.query_order_status(snapshot.cl_ord_id, symbol)
        if order_snapshot is not None:
            self._apply_query_event(
                symbol=symbol,
                event=self._to_order_status_event(order_snapshot),
            )
            change_tags.append("order_status_updated")

            if order_snapshot.status in {"filled", "partially_filled"}:
                execution_snapshots = self._trade_gateway.query_execution_reports(
                    snapshot.cl_ord_id
                )
                if execution_snapshots:
                    self._apply_query_event(
                        symbol=symbol,
                        event=self._to_execution_reports_event(execution_snapshots),
                    )
                    change_tags.append("execution_reports_updated")

        if not change_tags:
            return []
        return [
            self._build_execution_detail(
                symbol=symbol,
                change_tags=tuple(change_tags),
                now=now,
            )
        ]

    def _to_order_status_event(
        self,
        snapshot: OrderStatusSnapshot,
    ) -> _OrderStatusQueryEvent:
        """把查单快照标准化为内部事件。"""
        return _OrderStatusQueryEvent(
            broker_order_id=snapshot.broker_order_id,
            status=snapshot.status,
            filled_volume=snapshot.filled_volume,
            remaining_volume=snapshot.remaining_volume,
            rejection_reason=snapshot.rejection_reason,
            event_time=snapshot.event_time,
        )

    def _to_execution_reports_event(
        self,
        snapshots: tuple[OrderExecutionSnapshot, ...],
    ) -> _ExecutionReportsQueryEvent:
        """把成交快照列表聚合成一个内部事件。"""
        last_snapshot = snapshots[-1]
        return _ExecutionReportsQueryEvent(
            broker_order_id=last_snapshot.broker_order_id,
            filled_volume=sum(item.filled_volume for item in snapshots),
            avg_price=last_snapshot.avg_price,
            event_time=last_snapshot.event_time,
        )

    def _apply_query_event(
        self,
        *,
        symbol: str,
        event: _OrderStatusQueryEvent | _ExecutionReportsQueryEvent,
    ) -> None:
        """按事件类型更新执行态。"""
        if isinstance(event, _OrderStatusQueryEvent):
            self._apply_order_status_event(symbol=symbol, event=event)
            return
        self._apply_execution_reports_event(symbol=symbol, event=event)

    def _apply_order_status_event(
        self,
        *,
        symbol: str,
        event: _OrderStatusQueryEvent,
    ) -> None:
        """把查单结果并入当前执行态。"""
        self._state_manager.update_state(
            symbol,
            _map_execution_state(event.status),
            broker_order_id=event.broker_order_id,
            filled_volume=event.filled_volume,
            remaining_volume=event.remaining_volume,
            last_order_status=event.status,
            rejection_reason=event.rejection_reason,
            event_time=event.event_time,
        )

    def _apply_execution_reports_event(
        self,
        *,
        symbol: str,
        event: _ExecutionReportsQueryEvent,
    ) -> None:
        """把查成交结果并入当前执行态。"""
        self._state_manager.update_state(
            symbol,
            self._state_manager.get_state(symbol).state,
            broker_order_id=event.broker_order_id,
            filled_volume=event.filled_volume,
            avg_price=event.avg_price,
            event_time=event.event_time,
        )

    def _build_execution_detail(
        self,
        *,
        symbol: str,
        change_tags: tuple[str, ...],
        now: datetime,
    ) -> M3ExecutionDetail:
        """把当前执行态快照整理为对外详情。"""
        snapshot = self._state_manager.get_state(symbol)
        return M3ExecutionDetail(
            symbol=symbol,
            change_tags=change_tags,
            execution_state=snapshot.state.value,
            cl_ord_id=snapshot.cl_ord_id,
            broker_order_id=snapshot.broker_order_id,
            requested_volume=snapshot.requested_volume,
            filled_volume=snapshot.filled_volume,
            remaining_volume=snapshot.remaining_volume,
            submit_accepted=snapshot.submit_accepted,
            last_order_status=snapshot.last_order_status,
            rejection_reason=snapshot.rejection_reason,
            avg_price=snapshot.avg_price,
            event_time=snapshot.event_time or now,
            message=snapshot.message,
        )


def _build_ephemeral_decision_state(
    *,
    position: PositionSnapshot,
    now: datetime,
) -> DecisionPositionStateSnapshot:
    """M3 只需要满足 M2DecisionEngine 的入参契约，不复用 M2StateManager。"""
    return DecisionPositionStateSnapshot(
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


def _map_execution_state(status: str) -> PositionState:
    """把查单状态映射为执行态状态机。"""
    if status == "submitted":
        return PositionState.submitted
    if status == "partially_filled":
        return PositionState.partially_filled
    if status == "filled":
        return PositionState.filled
    if status in {"cancelled", "expired", "done_for_day", "stopped"}:
        return PositionState.cancelled
    if status == "rejected":
        return PositionState.failed
    return PositionState.submitted
