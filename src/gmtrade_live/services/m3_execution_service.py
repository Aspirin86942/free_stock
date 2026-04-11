"""M3 自动卖出执行编排服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging
from time import perf_counter
import time
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.protocols import MarketGateway, TradeGateway
from gmtrade_live.models import (
    DecisionPositionStateSnapshot,
    DecisionResult,
    M3BlockDetail,
    M3ExecutionDetail,
    M3RoundReport,
    M3RoundSummary,
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.services.m2_state_manager import M2StateManager
from gmtrade_live.services.m3_quantity_rules import build_sell_quantity_plan
from gmtrade_live.services.m3_state_manager import (
    M3ExecutionState,
    M3ExecutionStateSnapshot,
    M3PositionStateManager,
)
from gmtrade_live.session import resolve_trading_session

_RECONCILE_INTERVAL_SECONDS = 0.5


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
    """负责单轮自动卖出编排、批次轮询和执行收口。"""

    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        market_gateway: MarketGateway,
        decision_state_manager: M2StateManager,
        execution_state_manager: M3PositionStateManager,
        decision_engine,
        logger: logging.Logger,
        clock=None,
        timer=None,
        sleep=None,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._decision_state_manager = decision_state_manager
        self._execution_state_manager = execution_state_manager
        self._decision_engine = decision_engine
        self._logger = logger
        self._clock = clock or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self._timer = timer or perf_counter
        self._sleep = sleep or time.sleep

    def run_round(
        self,
        *,
        config: AppConfig,
        round_no: int,
        reconcile_timeout_seconds: int,
    ) -> M3RoundReport:
        """执行单轮 M3 自动卖出评估、提交和查询驱动收口。"""
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
        self._decision_state_manager.sync_positions(positions=positions, now=now)
        quote_map = self._load_quote_map(symbols=[position.symbol for position in positions])

        block_details: list[M3BlockDetail] = []
        execution_details: list[M3ExecutionDetail] = []
        changed_symbols: set[str] = set()
        candidate_count = 0
        submitted_count = 0

        tracked_positions: dict[str, PositionSnapshot] = {}
        pending_change_tags: dict[str, tuple[str, ...]] = {}
        decision_by_symbol: dict[str, DecisionResult] = {}
        decision_state_by_symbol: dict[str, DecisionPositionStateSnapshot] = {}

        for position in positions:
            decision_state = self._decision_state_manager.get_state(position.symbol)
            if decision_state is None:
                continue

            decision = self._decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=decision_state,
                config=config,
                now=now,
            )
            updated_state = self._decision_state_manager.update_decision_feedback(
                position.symbol,
                trigger_reason=decision.trigger_reason,
                block_reason=decision.block_reason,
                volume=decision.volume,
                available_volume=decision.available_volume,
                sellable_now=decision.sellable_now,
                decision_time=decision.evaluated_at,
            )
            decision_by_symbol[position.symbol] = decision
            decision_state_by_symbol[position.symbol] = updated_state

            if not decision.can_submit_sell:
                continue

            candidate_count += 1
            if self._execution_state_manager.has_open_order(position.symbol):
                tracked_positions[position.symbol] = position
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
                    self._build_block_detail(
                        symbol=position.symbol,
                        decision=decision,
                        decision_state=updated_state,
                        total_volume=position.volume,
                        available_volume=position.available_volume,
                        raw_target_volume=quantity_plan.raw_target_volume,
                        promotion_type=quantity_plan.promotion_type,
                        normalized_target_volume=quantity_plan.final_target_volume,
                        requested_ratio=config.sell_quantity_ratio,
                        block_reason=quantity_plan.block_reason,
                        evaluated_at=decision.evaluated_at,
                    )
                )
                changed_symbols.add(position.symbol)
                continue

            accepted, immediate_detail = self._submit_new_order(
                symbol=position.symbol,
                requested_volume=quantity_plan.final_target_volume,
                trigger_reason=decision.trigger_reason,
                now=now,
                decision=decision,
                decision_state=updated_state,
            )
            if immediate_detail is not None:
                execution_details.append(immediate_detail)
                changed_symbols.add(position.symbol)
                continue

            if accepted:
                submitted_count += 1
                tracked_positions[position.symbol] = position
                pending_change_tags[position.symbol] = ("submit_accepted",)
                changed_symbols.add(position.symbol)

        deadline = started_at + float(reconcile_timeout_seconds)
        reconciled_details = self._reconcile_open_orders(
            positions_by_symbol=tracked_positions,
            decision_by_symbol=decision_by_symbol,
            decision_state_by_symbol=decision_state_by_symbol,
            pending_change_tags=pending_change_tags,
            deadline=deadline,
            now=now,
        )
        execution_details.extend(reconciled_details)
        changed_symbols.update(detail.symbol for detail in reconciled_details)

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
                    for snapshot in self._execution_state_manager.active_states()
                    if self._execution_state_manager.has_open_order(snapshot.symbol)
                ),
                changed_symbol_count=len(changed_symbols),
                duration_ms=duration_ms,
            ),
            block_details=tuple(block_details),
            execution_details=tuple(execution_details),
        )

    def _load_quote_map(self, *, symbols: list[str]) -> dict[str, QuoteSnapshot]:
        """批量查询行情并按 symbol 映射。"""
        quotes = tuple(self._market_gateway.get_quotes(symbols)) if symbols else ()
        return {quote.symbol: quote for quote in quotes}

    def _submit_new_order(
        self,
        *,
        symbol: str,
        requested_volume: int,
        trigger_reason: str | None,
        now: datetime,
        decision: DecisionResult,
        decision_state: DecisionPositionStateSnapshot,
    ) -> tuple[bool, M3ExecutionDetail | None]:
        """提交流程只做状态推进；受理成功后交给批次轮询继续收口。"""
        self._execution_state_manager.update_state(
            symbol,
            M3ExecutionState.submitting,
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
            self._execution_state_manager.update_state(
                symbol,
                M3ExecutionState.failed,
                cl_ord_id=result.cl_ord_id,
                broker_order_id=result.broker_order_id,
                requested_volume=requested_volume,
                remaining_volume=requested_volume,
                submit_accepted=False,
                rejection_reason=result.message,
                event_time=result.event_time,
                message=result.message,
            )
            return (
                False,
                self._build_execution_detail(
                    symbol=symbol,
                    decision=decision,
                    decision_state=decision_state,
                    change_tags=("submit_rejected",),
                    now=now,
                ),
            )

        self._execution_state_manager.update_state(
            symbol,
            M3ExecutionState.submitted,
            cl_ord_id=result.cl_ord_id,
            broker_order_id=result.broker_order_id,
            requested_volume=requested_volume,
            remaining_volume=requested_volume,
            submit_accepted=True,
            last_order_status="submitted",
            event_time=result.event_time,
            message=result.message,
        )
        return True, None

    def _reconcile_open_orders(
        self,
        *,
        positions_by_symbol: dict[str, PositionSnapshot],
        decision_by_symbol: dict[str, DecisionResult],
        decision_state_by_symbol: dict[str, DecisionPositionStateSnapshot],
        pending_change_tags: dict[str, tuple[str, ...]],
        deadline: float,
        now: datetime,
    ) -> list[M3ExecutionDetail]:
        """对新单和已有在途单做 round 级批次轮询。"""
        details: list[M3ExecutionDetail] = []
        tracked_positions = dict(positions_by_symbol)

        while tracked_positions and self._timer() < deadline:
            next_tracked_positions: dict[str, PositionSnapshot] = {}
            for symbol, position in tracked_positions.items():
                detail = self._reconcile_trade_state(
                    position=position,
                    decision=decision_by_symbol[symbol],
                    decision_state=decision_state_by_symbol[symbol],
                    extra_change_tags=pending_change_tags.pop(symbol, ()),
                    now=now,
                )
                if detail is not None:
                    details.append(detail)
                if self._execution_state_manager.has_open_order(symbol):
                    next_tracked_positions[symbol] = position

            if not next_tracked_positions:
                return details

            remaining_seconds = max(deadline - self._timer(), 0.0)
            if remaining_seconds <= 0:
                return details

            self._sleep(min(_RECONCILE_INTERVAL_SECONDS, remaining_seconds))
            tracked_positions = next_tracked_positions

        for symbol, change_tags in pending_change_tags.items():
            if not change_tags or symbol not in decision_by_symbol:
                continue
            details.append(
                self._build_execution_detail(
                    symbol=symbol,
                    decision=decision_by_symbol[symbol],
                    decision_state=decision_state_by_symbol[symbol],
                    change_tags=change_tags,
                    now=now,
                )
            )
        return details

    def _reconcile_trade_state(
        self,
        *,
        position: PositionSnapshot,
        decision: DecisionResult,
        decision_state: DecisionPositionStateSnapshot,
        extra_change_tags: tuple[str, ...],
        now: datetime,
    ) -> M3ExecutionDetail | None:
        """把外部查询结果转换成内部事件，再驱动本地执行态更新。"""
        snapshot = self._execution_state_manager.get_state(position.symbol)
        if snapshot.cl_ord_id is None:
            if not extra_change_tags:
                return None
            return self._build_execution_detail(
                symbol=position.symbol,
                decision=decision,
                decision_state=decision_state,
                change_tags=extra_change_tags,
                now=now,
            )

        change_tags: list[str] = list(extra_change_tags)
        for event in self._build_query_events(
            cl_ord_id=snapshot.cl_ord_id,
            symbol=position.symbol,
            last_order_status=snapshot.last_order_status,
        ):
            self._apply_query_event(symbol=position.symbol, event=event)
            if isinstance(event, _OrderStatusQueryEvent):
                change_tags.append("order_status_updated")
            else:
                change_tags.append("execution_reports_updated")

        if not change_tags:
            return None
        return self._build_execution_detail(
            symbol=position.symbol,
            decision=decision,
            decision_state=decision_state,
            change_tags=tuple(change_tags),
            now=now,
        )

    def _build_query_events(
        self,
        *,
        cl_ord_id: str,
        symbol: str,
        last_order_status: str | None,
    ) -> tuple[_OrderStatusQueryEvent | _ExecutionReportsQueryEvent, ...]:
        """查询外部状态，并标准化成内部事件序列。"""
        events: list[_OrderStatusQueryEvent | _ExecutionReportsQueryEvent] = []
        order_snapshot = self._trade_gateway.query_order_status(cl_ord_id, symbol)
        current_status = last_order_status
        if order_snapshot is not None:
            current_status = order_snapshot.status
            events.append(self._to_order_status_event(order_snapshot))

        if current_status in {"filled", "partially_filled"}:
            execution_snapshots = self._trade_gateway.query_execution_reports(cl_ord_id)
            if execution_snapshots:
                events.append(self._to_execution_reports_event(execution_snapshots))

        return tuple(events)

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
        snapshot = self._execution_state_manager.get_state(symbol)
        self._execution_state_manager.update_state(
            symbol,
            _map_execution_state(event.status),
            broker_order_id=event.broker_order_id or snapshot.broker_order_id,
            filled_volume=_resolve_filled_volume(snapshot=snapshot, event=event),
            remaining_volume=_resolve_remaining_volume(snapshot=snapshot, event=event),
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
        snapshot = self._execution_state_manager.get_state(symbol)
        self._execution_state_manager.update_state(
            symbol,
            snapshot.state,
            broker_order_id=event.broker_order_id or snapshot.broker_order_id,
            filled_volume=max(snapshot.filled_volume, event.filled_volume),
            avg_price=event.avg_price if event.avg_price is not None else snapshot.avg_price,
            event_time=event.event_time,
        )

    def _build_block_detail(
        self,
        *,
        symbol: str,
        decision: DecisionResult,
        decision_state: DecisionPositionStateSnapshot,
        total_volume: int,
        available_volume: int,
        raw_target_volume: int,
        promotion_type: str | None,
        normalized_target_volume: int,
        requested_ratio: Decimal,
        block_reason: str,
        evaluated_at: datetime,
    ) -> M3BlockDetail:
        """把当前阻断事实投影成双状态详情。"""
        execution_snapshot = self._execution_state_manager.get_state(symbol)
        execution_state = (
            execution_snapshot.state.value
            if execution_snapshot.state is not M3ExecutionState.idle
            else None
        )
        return M3BlockDetail(
            symbol=symbol,
            decision_lifecycle_state=decision_state.lifecycle_state.value,
            decision_should_sell=decision.should_sell,
            decision_can_submit_sell=decision.can_submit_sell,
            decision_trigger_reason=decision.trigger_reason,
            decision_block_reason=decision.block_reason,
            execution_state=execution_state,
            execution_cl_ord_id=execution_snapshot.cl_ord_id,
            execution_broker_order_id=execution_snapshot.broker_order_id,
            execution_last_order_status=execution_snapshot.last_order_status,
            requested_ratio=requested_ratio,
            total_volume=total_volume,
            available_volume=available_volume,
            raw_target_volume=raw_target_volume,
            promotion_type=promotion_type,
            normalized_target_volume=normalized_target_volume,
            block_reason=block_reason,
            evaluated_at=evaluated_at,
        )

    def _build_execution_detail(
        self,
        *,
        symbol: str,
        decision: DecisionResult,
        decision_state: DecisionPositionStateSnapshot,
        change_tags: tuple[str, ...],
        now: datetime,
    ) -> M3ExecutionDetail:
        """把当前执行态快照整理为对外双状态详情。"""
        snapshot = self._execution_state_manager.get_state(symbol)
        return M3ExecutionDetail(
            symbol=symbol,
            change_tags=change_tags,
            decision_lifecycle_state=decision_state.lifecycle_state.value,
            decision_should_sell=decision.should_sell,
            decision_can_submit_sell=decision.can_submit_sell,
            decision_trigger_reason=decision.trigger_reason,
            decision_block_reason=decision.block_reason,
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


def _map_execution_state(status: str) -> M3ExecutionState:
    """把查单状态映射为执行态状态机。"""
    if status in {"submitted", "pending_new"}:
        return M3ExecutionState.submitted
    if status == "partially_filled":
        return M3ExecutionState.partially_filled
    if status == "filled":
        return M3ExecutionState.filled
    if status in {"cancelled", "expired", "done_for_day", "stopped"}:
        return M3ExecutionState.cancelled
    if status == "rejected":
        return M3ExecutionState.failed
    return M3ExecutionState.submitted


def _resolve_remaining_volume(
    *,
    snapshot: M3ExecutionStateSnapshot,
    event: _OrderStatusQueryEvent,
) -> int:
    """对 pending_new 等早期状态保守保留已知剩余量，避免被缺字段快照误写成 0。"""
    if event.remaining_volume > 0:
        return event.remaining_volume

    if event.status in {"filled", "cancelled", "expired", "done_for_day", "stopped", "rejected"}:
        return 0

    if snapshot.remaining_volume > 0 and event.filled_volume <= snapshot.filled_volume:
        return snapshot.remaining_volume

    if snapshot.requested_volume > event.filled_volume:
        return snapshot.requested_volume - event.filled_volume

    return 0


def _resolve_filled_volume(
    *,
    snapshot: M3ExecutionStateSnapshot,
    event: _OrderStatusQueryEvent,
) -> int:
    """对 filled/partially_filled 的缺字段快照做保守推断，避免日志出现倒退。"""
    resolved = max(snapshot.filled_volume, event.filled_volume)

    if event.status == "filled" and snapshot.requested_volume > 0:
        return max(resolved, snapshot.requested_volume)

    if (
        event.status == "partially_filled"
        and event.remaining_volume > 0
        and snapshot.requested_volume > 0
    ):
        inferred = max(snapshot.requested_volume - event.remaining_volume, 0)
        return max(resolved, inferred)

    return resolved
