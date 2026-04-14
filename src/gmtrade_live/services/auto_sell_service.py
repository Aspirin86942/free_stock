"""自动卖出执行编排服务。"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.protocols import TradeGateway
from gmtrade_live.models import (
    AutoSellRoundReport,
    AutoSellRoundSummary,
    DecisionPositionStateSnapshot,
    DecisionResult,
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    SellBlockDetail,
    SellCandidate,
    SellExecutionDetail,
)
from gmtrade_live.services.order_execution_state import (
    OrderExecutionState,
    OrderExecutionStateSnapshot,
    OrderExecutionStateStore,
)
from gmtrade_live.services.sell_quantity_policy import build_sell_quantity_plan

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


class AutoSellService:
    """负责单轮自动卖出编排、批次轮询和执行收口。"""

    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        candidate_pipeline,
        execution_state_manager: OrderExecutionStateStore,
        logger: logging.Logger,
        audit_logger: logging.Logger | None = None,
        clock=None,
        timer=None,
        sleep=None,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._candidate_pipeline = candidate_pipeline
        self._execution_state_manager = execution_state_manager
        self._logger = logger
        self._audit_logger = audit_logger
        self._clock = clock or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self._timer = timer or perf_counter
        self._sleep = sleep or time.sleep

    def _format_dt(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()

    def _resolve_order_terminal_latency_ms(
        self, *, submit_accepted_at: datetime | None, terminal_state_at: datetime | None
    ) -> int | None:
        # timeout / 未受理等场景没有终态或受理时间，无法计算耗时投影。
        if submit_accepted_at is None or terminal_state_at is None:
            return None
        return int((terminal_state_at - submit_accepted_at).total_seconds() * 1000)

    def _emit_order_audit_event(
        self,
        *,
        event_type: str,
        account_id: str,
        round_no: int,
        symbol: str,
        decision: DecisionResult,
        snapshot: OrderExecutionStateSnapshot,
        message: str | None = None,
    ) -> None:
        if self._audit_logger is None:
            return

        order_terminal_latency_ms = self._resolve_order_terminal_latency_ms(
            submit_accepted_at=snapshot.submit_accepted_at,
            terminal_state_at=snapshot.terminal_state_at,
        )
        payload = {
            "event_type": event_type,
            "mode": "m3",
            "round_no": round_no,
            "account_id": account_id,
            "symbol": symbol,
            "cl_ord_id": snapshot.cl_ord_id,
            "broker_order_id": snapshot.broker_order_id,
            "decision_trigger_reason": decision.trigger_reason,
            "decision_block_reason": decision.block_reason,
            "execution_state": snapshot.state.value,
            "last_order_status": snapshot.last_order_status,
            "requested_volume": snapshot.requested_volume,
            "filled_volume": snapshot.filled_volume,
            "remaining_volume": snapshot.remaining_volume,
            "avg_price": str(snapshot.avg_price) if snapshot.avg_price is not None else None,
            "message": message if message is not None else snapshot.message,
            "submit_started_at": self._format_dt(snapshot.submit_started_at),
            "submit_accepted_at": self._format_dt(snapshot.submit_accepted_at),
            "terminal_state_at": self._format_dt(snapshot.terminal_state_at),
            "order_terminal_latency_ms": order_terminal_latency_ms,
        }
        self._audit_logger.info(json.dumps(payload, ensure_ascii=False))

    def run_round(
        self,
        *,
        config: AppConfig,
        round_no: int,
        reconcile_timeout_seconds: int,
    ) -> AutoSellRoundReport:
        """执行单轮自动卖出：消费共享候选结果并完成提交与收口。"""
        started_at = self._timer()
        now = self._clock()
        candidate_round = self._candidate_pipeline.run_round(config=config, round_no=round_no)

        block_details: list[SellBlockDetail] = []
        execution_details: list[SellExecutionDetail] = []
        changed_symbols: set[str] = set()
        submitted_count = 0

        tracked_symbols: set[str] = set()
        pending_change_tags: dict[str, tuple[str, ...]] = {}
        decision_by_symbol: dict[str, DecisionResult] = {}
        decision_state_by_symbol: dict[str, DecisionPositionStateSnapshot] = {}

        for candidate in candidate_round.candidates:
            decision, decision_state = candidate.decision, candidate.state_snapshot
            symbol = decision.symbol
            decision_by_symbol[symbol] = decision
            decision_state_by_symbol[symbol] = decision_state

            if not decision.can_submit_sell:
                continue

            if self._execution_state_manager.has_open_order(symbol):
                tracked_symbols.add(symbol)
                continue

            quantity_plan = build_sell_quantity_plan(
                symbol=symbol,
                total_volume=decision.volume,
                available_volume=decision.available_volume,
                sell_quantity_ratio=config.sell_quantity_ratio,
            )
            self._logger.info(
                "m3_quantity_evaluated symbol=%s raw_target_volume=%s final_target_volume=%s block_reason=%s",
                symbol,
                quantity_plan.raw_target_volume,
                quantity_plan.final_target_volume,
                quantity_plan.block_reason,
            )
            if quantity_plan.block_reason is not None:
                block_details.append(
                    self._build_block_detail(
                        symbol=symbol,
                        decision=decision,
                        decision_state=decision_state,
                        total_volume=decision.volume,
                        available_volume=decision.available_volume,
                        raw_target_volume=quantity_plan.raw_target_volume,
                        promotion_type=quantity_plan.promotion_type,
                        normalized_target_volume=quantity_plan.final_target_volume,
                        requested_ratio=config.sell_quantity_ratio,
                        block_reason=quantity_plan.block_reason,
                        evaluated_at=decision.evaluated_at,
                    )
                )
                changed_symbols.add(symbol)
                continue

            accepted, immediate_detail = self._submit_new_order(
                symbol=symbol,
                requested_volume=quantity_plan.final_target_volume,
                trigger_reason=decision.trigger_reason,
                now=now,
                decision=decision,
                decision_state=decision_state,
                account_id=config.account_id,
                round_no=round_no,
            )
            if immediate_detail is not None:
                execution_details.append(immediate_detail)
                changed_symbols.add(symbol)
                continue
            if accepted:
                submitted_count += 1
                tracked_symbols.add(symbol)
                pending_change_tags[symbol] = ("submit_accepted",)
                changed_symbols.add(symbol)

        deadline = started_at + float(reconcile_timeout_seconds)
        reconciled_details = self._reconcile_open_orders(
            tracked_symbols=tracked_symbols,
            decision_by_symbol=decision_by_symbol,
            decision_state_by_symbol=decision_state_by_symbol,
            pending_change_tags=pending_change_tags,
            deadline=deadline,
            now=now,
            account_id=config.account_id,
            round_no=round_no,
        )
        execution_details.extend(reconciled_details)
        changed_symbols.update(detail.symbol for detail in reconciled_details)

        duration_ms = int((self._timer() - started_at) * 1000)
        return AutoSellRoundReport(
            summary=AutoSellRoundSummary(
                round_no=round_no,
                session_state=candidate_round.summary.session_state,
                position_count=candidate_round.summary.position_count,
                candidate_count=sum(
                    1 for item in candidate_round.candidates if item.decision.can_submit_sell
                ),
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

    def _submit_new_order(
        self,
        *,
        symbol: str,
        requested_volume: int,
        trigger_reason: str | None,
        now: datetime,
        decision: DecisionResult,
        decision_state: DecisionPositionStateSnapshot,
        account_id: str,
        round_no: int,
    ) -> tuple[bool, SellExecutionDetail | None]:
        """提交流程只做状态推进；受理成功后交给批次轮询继续收口。"""
        # 为什么要重置时间字段：执行态是按 symbol 缓存的；新单提交前不清理上一单的时间点，
        # 会导致后续审计/终态耗时投影串单（例如沿用旧的 submit_accepted_at / terminal_state_at）。
        snapshot = self._execution_state_manager.get_state(symbol)
        snapshot.submit_accepted_at = None
        snapshot.terminal_state_at = None
        self._execution_state_manager.update_state(
            symbol,
            OrderExecutionState.submitting,
            cl_ord_id=None,
            broker_order_id=None,
            trigger_reason=trigger_reason,
            requested_volume=requested_volume,
            filled_volume=0,
            remaining_volume=requested_volume,
            submit_accepted=None,
            last_order_status=None,
            rejection_reason=None,
            avg_price=None,
            submit_started_at=now,
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
                OrderExecutionState.failed,
                cl_ord_id=result.cl_ord_id,
                broker_order_id=result.broker_order_id,
                requested_volume=requested_volume,
                filled_volume=0,
                remaining_volume=requested_volume,
                submit_accepted=False,
                last_order_status=None,
                rejection_reason=result.message,
                avg_price=None,
                event_time=result.event_time,
                message=result.message,
            )
            self._emit_order_audit_event(
                event_type="submit_rejected",
                account_id=account_id,
                round_no=round_no,
                symbol=symbol,
                decision=decision,
                snapshot=self._execution_state_manager.get_state(symbol),
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
            OrderExecutionState.submitted,
            cl_ord_id=result.cl_ord_id,
            broker_order_id=result.broker_order_id,
            requested_volume=requested_volume,
            filled_volume=0,
            remaining_volume=requested_volume,
            submit_accepted=True,
            submit_accepted_at=result.event_time,
            last_order_status="submitted",
            rejection_reason=None,
            avg_price=None,
            event_time=result.event_time,
            message=result.message,
        )
        self._emit_order_audit_event(
            event_type="submit_accepted",
            account_id=account_id,
            round_no=round_no,
            symbol=symbol,
            decision=decision,
            snapshot=self._execution_state_manager.get_state(symbol),
        )
        return True, None

    def _reconcile_open_orders(
        self,
        *,
        tracked_symbols: set[str],
        decision_by_symbol: dict[str, DecisionResult],
        decision_state_by_symbol: dict[str, DecisionPositionStateSnapshot],
        pending_change_tags: dict[str, tuple[str, ...]],
        deadline: float,
        now: datetime,
        account_id: str,
        round_no: int,
    ) -> list[SellExecutionDetail]:
        """对新单和已有在途单做 round 级批次轮询。"""
        details: list[SellExecutionDetail] = []
        pending_symbols = set(tracked_symbols)
        timed_out = False

        while pending_symbols and self._timer() < deadline:
            next_symbols: set[str] = set()
            for symbol in pending_symbols:
                detail = self._reconcile_trade_state(
                    symbol=symbol,
                    decision=decision_by_symbol[symbol],
                    decision_state=decision_state_by_symbol[symbol],
                    extra_change_tags=pending_change_tags.pop(symbol, ()),
                    now=now,
                    account_id=account_id,
                    round_no=round_no,
                )
                if detail is not None:
                    details.append(detail)
                current_snapshot = self._execution_state_manager.get_state(symbol)
                if self._execution_state_manager.has_open_order(symbol) or _should_wait_for_terminal_audit(current_snapshot):
                    next_symbols.add(symbol)

            if not next_symbols:
                return details

            remaining_seconds = max(deadline - self._timer(), 0.0)
            if remaining_seconds <= 0:
                timed_out = True
                pending_symbols = next_symbols
                break

            self._sleep(min(_RECONCILE_INTERVAL_SECONDS, remaining_seconds))
            pending_symbols = next_symbols

        if pending_symbols and (timed_out or self._timer() >= deadline):
            # 为什么 timeout 不产出 latency：没有终态时间点就无法计算终态耗时，避免生成误导性数据。
            for symbol in pending_symbols:
                snapshot = self._execution_state_manager.get_state(symbol)
                timeout_message = (
                    "terminal_audit_pending"
                    if _should_wait_for_terminal_audit(snapshot)
                    else "reconcile_timeout"
                )
                self._emit_order_audit_event(
                    event_type="reconcile_timeout",
                    account_id=account_id,
                    round_no=round_no,
                    symbol=symbol,
                    decision=decision_by_symbol[symbol],
                    snapshot=snapshot,
                    message=timeout_message,
                )

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
        symbol: str,
        decision: DecisionResult,
        decision_state: DecisionPositionStateSnapshot,
        extra_change_tags: tuple[str, ...],
        now: datetime,
        account_id: str,
        round_no: int,
    ) -> SellExecutionDetail | None:
        """把外部查询结果转换成内部事件，再驱动本地执行态更新。"""
        snapshot = self._execution_state_manager.get_state(symbol)
        if snapshot.cl_ord_id is None:
            if not extra_change_tags:
                return None
            return self._build_execution_detail(
                symbol=symbol,
                decision=decision,
                decision_state=decision_state,
                change_tags=extra_change_tags,
                now=now,
            )

        change_tags: list[str] = list(extra_change_tags)
        old_terminal_state_at = snapshot.terminal_state_at
        old_avg_price = snapshot.avg_price
        old_wait_for_terminal_audit = _should_wait_for_terminal_audit(snapshot)
        for event in self._build_query_events(
            cl_ord_id=snapshot.cl_ord_id,
            symbol=symbol,
            last_order_status=snapshot.last_order_status,
        ):
            self._apply_query_event(symbol=symbol, event=event)
            if isinstance(event, _OrderStatusQueryEvent):
                change_tags.append("order_status_updated")
            else:
                change_tags.append("execution_reports_updated")

        # 只在第一次观察到终态时间时产出审计事件，避免重复轮询导致重复写入。
        updated_snapshot = self._execution_state_manager.get_state(symbol)
        terminal_became_auditable = (
            old_wait_for_terminal_audit
            and not _should_wait_for_terminal_audit(updated_snapshot)
            and old_avg_price is None
            and updated_snapshot.avg_price is not None
        )
        should_emit_terminal = (
            updated_snapshot.terminal_state_at is not None
            and (
                (old_terminal_state_at is None and not _should_wait_for_terminal_audit(updated_snapshot))
                or terminal_became_auditable
            )
        )
        if should_emit_terminal:
            self._emit_order_audit_event(
                event_type="terminal_state_reached",
                account_id=account_id,
                round_no=round_no,
                symbol=symbol,
                decision=decision,
                snapshot=updated_snapshot,
            )

        if not change_tags:
            return None
        return self._build_execution_detail(
            symbol=symbol,
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
            avg_price=(
                event.avg_price if event.avg_price is not None else snapshot.avg_price
            ),
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
    ) -> SellBlockDetail:
        """把当前阻断事实投影成双状态详情。"""
        execution_snapshot = self._execution_state_manager.get_state(symbol)
        execution_state = (
            execution_snapshot.state.value
            if execution_snapshot.state is not OrderExecutionState.idle
            else None
        )
        return SellBlockDetail(
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
    ) -> SellExecutionDetail:
        """把当前执行态快照整理为对外双状态详情。"""
        snapshot = self._execution_state_manager.get_state(symbol)
        order_terminal_latency_ms = self._resolve_order_terminal_latency_ms(
            submit_accepted_at=snapshot.submit_accepted_at,
            terminal_state_at=snapshot.terminal_state_at,
        )
        return SellExecutionDetail(
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
            submit_started_at=snapshot.submit_started_at,
            submit_accepted_at=snapshot.submit_accepted_at,
            terminal_state_at=snapshot.terminal_state_at,
            order_terminal_latency_ms=order_terminal_latency_ms,
        )


def _map_execution_state(status: str) -> OrderExecutionState:
    """把查单状态映射为执行态状态机。"""
    if status in {"submitted", "pending_new"}:
        return OrderExecutionState.submitted
    if status == "partially_filled":
        return OrderExecutionState.partially_filled
    if status == "filled":
        return OrderExecutionState.filled
    if status in {"cancelled", "expired", "done_for_day", "stopped"}:
        return OrderExecutionState.cancelled
    if status == "rejected":
        return OrderExecutionState.failed
    return OrderExecutionState.submitted


def _resolve_remaining_volume(
    *,
    snapshot: OrderExecutionStateSnapshot,
    event: _OrderStatusQueryEvent,
) -> int:
    """对 pending_new 等早期状态保守保留已知剩余量，避免被缺字段快照误写成 0。"""
    if event.remaining_volume > 0:
        return event.remaining_volume

    if event.status in {
        "filled",
        "cancelled",
        "expired",
        "done_for_day",
        "stopped",
        "rejected",
    }:
        return 0

    if snapshot.remaining_volume > 0 and event.filled_volume <= snapshot.filled_volume:
        return snapshot.remaining_volume

    if snapshot.requested_volume > event.filled_volume:
        return snapshot.requested_volume - event.filled_volume

    return 0


def _resolve_filled_volume(
    *,
    snapshot: OrderExecutionStateSnapshot,
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


def _should_wait_for_terminal_audit(snapshot: OrderExecutionStateSnapshot) -> bool:
    """filled 已确认但成交回报尚未补齐时，继续等待一次，避免终态审计写出半成品。"""
    return (
        snapshot.state is OrderExecutionState.filled
        and snapshot.filled_volume > 0
        and snapshot.avg_price is None
    )


# 向后兼容别名：保留旧 M3 命名，避免未迁移调用方中断。
M3ExecutionService = AutoSellService

__all__ = [
    "AutoSellService",
    "M3ExecutionService",
]
