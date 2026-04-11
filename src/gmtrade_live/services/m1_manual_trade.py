"""M1 手工交易验证服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import time
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.models import (
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    OrderSubmitResult,
    TradeReport,
)
from gmtrade_live.gateways.protocols import TradeGateway


_QUERY_INTERVAL_SECONDS = 0.5
_TERMINAL_ORDER_STATUSES = {
    "rejected",
    "cancelled",
    "expired",
    "done_for_day",
    "stopped",
}


@dataclass(frozen=True, slots=True)
class _OrderStatusQueryEvent:
    """把一次查单结果转换成内部事件。"""

    broker_order_id: str | None
    status: str
    filled_volume: int
    rejection_reason: str | None


@dataclass(frozen=True, slots=True)
class _ExecutionReportsQueryEvent:
    """把一次查成交结果转换成内部事件。"""

    broker_order_id: str | None
    filled_volume: int
    avg_price: Decimal | None


@dataclass(slots=True)
class _CollectedEvents:
    """聚合查询事件后的订单状态。"""

    order_status_confirmed: bool = False
    execution_status_confirmed: bool = False
    broker_order_id: str | None = None
    last_order_status: str | None = None
    rejection_reason: str | None = None
    filled_volume: int = 0
    avg_price: Decimal | None = None


class ManualTradeService:
    """负责一次 M1 手工交易验证的完整收口。"""

    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        logger: logging.Logger,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._logger = logger

    def run(
        self,
        *,
        config: AppConfig,
        side: str,
        symbol: str,
        volume: int,
        price_type: str,
        price: Decimal | None,
        timeout_seconds: int,
    ) -> TradeReport:
        """提交委托后轮询查询结果，并用内部事件收口最终状态。"""
        self._validate_inputs(
            side=side,
            symbol=symbol,
            volume=volume,
            price_type=price_type,
            price=price,
            timeout_seconds=timeout_seconds,
        )
        started_at = self._now(config.timezone)
        self._logger.info(
            "m1_manual_trade_starting account_id=%s side=%s symbol=%s volume=%s price_type=%s timeout_seconds=%s",
            config.account_id,
            side,
            symbol,
            volume,
            price_type,
            timeout_seconds,
        )

        request = OrderRequest(
            symbol=symbol,
            volume=volume,
            side=side,
            price_type=price_type,
            price=price,
        )
        self._logger.info(
            "order_submit_request account_id=%s side=%s symbol=%s volume=%s price_type=%s",
            config.account_id,
            side,
            symbol,
            volume,
            price_type,
        )

        try:
            submit_result = self._trade_gateway.submit_order(request)
        except Exception as exc:
            self._logger.error(
                "m1_manual_trade_failed account_id=%s side=%s symbol=%s reason=%s",
                config.account_id,
                side,
                symbol,
                str(exc),
                exc_info=True,
            )
            return self._build_report(
                config=config,
                request=request,
                submit_result=None,
                collected=_CollectedEvents(),
                verification_passed=False,
                message=str(exc),
                started_at=started_at,
                finished_at=self._now(config.timezone),
            )

        self._logger.info(
            "order_submit_result account_id=%s cl_ord_id=%s accepted=%s raw_status=%s",
            config.account_id,
            submit_result.cl_ord_id,
            submit_result.accepted,
            submit_result.raw_status,
        )
        if not submit_result.accepted or submit_result.cl_ord_id is None:
            self._logger.error(
                "m1_manual_trade_failed account_id=%s side=%s symbol=%s reason=%s",
                config.account_id,
                side,
                symbol,
                submit_result.message,
            )
            return self._build_report(
                config=config,
                request=request,
                submit_result=submit_result,
                collected=_CollectedEvents(),
                verification_passed=False,
                message=submit_result.message,
                started_at=started_at,
                finished_at=self._now(config.timezone),
            )

        deadline = started_at + timedelta(seconds=timeout_seconds)
        collected = self._poll_trade_state(
            request=request,
            submit_result=submit_result,
            deadline=deadline,
            timezone_name=config.timezone,
        )
        verification_passed = _is_verification_success(
            submit_result=submit_result,
            collected=collected,
        )
        finished_at = self._now(config.timezone)

        if verification_passed:
            self._logger.info(
                "m1_manual_trade_query_closed account_id=%s cl_ord_id=%s last_order_status=%s filled_volume=%s",
                config.account_id,
                submit_result.cl_ord_id,
                collected.last_order_status,
                collected.filled_volume,
            )
            return self._build_report(
                config=config,
                request=request,
                submit_result=submit_result,
                collected=collected,
                verification_passed=True,
                message="交易状态已确认",
                started_at=started_at,
                finished_at=finished_at,
            )

        message = _resolve_failure_message(collected)
        log_method = (
            self._logger.warning
            if collected.order_status_confirmed
            else self._logger.error
        )
        log_method(
            "m1_manual_trade_timeout account_id=%s cl_ord_id=%s message=%s",
            config.account_id,
            submit_result.cl_ord_id,
            message,
        )
        return self._build_report(
            config=config,
            request=request,
            submit_result=submit_result,
            collected=collected,
            verification_passed=False,
            message=message,
            started_at=started_at,
            finished_at=finished_at,
        )

    def _poll_trade_state(
        self,
        *,
        request: OrderRequest,
        submit_result: OrderSubmitResult,
        deadline: datetime,
        timezone_name: str,
    ) -> _CollectedEvents:
        """轮询柜台查询，并把查询结果先转成内部事件再更新聚合状态。"""
        # print(f"  开始轮询，cl_ord_id={submit_result.cl_ord_id}")
        collected = _CollectedEvents(broker_order_id=submit_result.broker_order_id)
        # print(collected)

        while True:
            self._reconcile_trade_state(
                request=request,
                submit_result=submit_result,
                collected=collected,
            )
            # print(collected)
            if _is_verification_success(
                submit_result=submit_result,
                collected=collected,
            ):
                return collected

            now = self._now(timezone_name)
            if now >= deadline:
                return collected
            remaining_seconds = max((deadline - now).total_seconds(), 0.0)
            time.sleep(min(_QUERY_INTERVAL_SECONDS, remaining_seconds))

    def _reconcile_trade_state(
        self,
        *,
        request: OrderRequest,
        submit_result: OrderSubmitResult,
        collected: _CollectedEvents,
    ) -> None:
        """把外部查询结果转换成内部事件，再驱动本地聚合状态更新。"""
        if submit_result.cl_ord_id is None:
            return

        for event in self._build_query_events(
            request=request,
            submit_result=submit_result,
            collected=collected,
        ):
            self._apply_query_event(collected=collected, event=event)

    def _build_query_events(
        self,
        *,
        request: OrderRequest,
        submit_result: OrderSubmitResult,
        collected: _CollectedEvents,
    ) -> tuple[_OrderStatusQueryEvent | _ExecutionReportsQueryEvent, ...]:
        """查询外部状态，并标准化成内部事件序列。"""
        if submit_result.cl_ord_id is None:
            return ()

        events: list[_OrderStatusQueryEvent | _ExecutionReportsQueryEvent] = []
        order_snapshot = self._trade_gateway.query_order_status(
            submit_result.cl_ord_id,
            request.symbol,
        )
        current_status = collected.last_order_status
        if order_snapshot is not None:
            current_status = order_snapshot.status
            events.append(self._to_order_status_event(order_snapshot))

        # 只有订单已经出现成交相关状态时才查成交，减少无意义查询。
        if current_status in {"filled", "partially_filled"}:
            execution_snapshots = self._trade_gateway.query_execution_reports(
                submit_result.cl_ord_id
            )
            if execution_snapshots:
                events.append(self._to_execution_reports_event(execution_snapshots))

        return tuple(events)

    def _apply_query_event(
        self,
        *,
        collected: _CollectedEvents,
        event: _OrderStatusQueryEvent | _ExecutionReportsQueryEvent,
    ) -> None:
        """如果当前收到的是查单事件，就按查单规则更新聚合状态；不然就按查成交规则更新聚合状态。"""
        if isinstance(event, _OrderStatusQueryEvent):
            self._apply_order_status_event(collected=collected, event=event)
            return
        self._apply_execution_reports_event(collected=collected, event=event)

    def _apply_order_status_event(
        self,
        *,
        collected: _CollectedEvents,
        event: _OrderStatusQueryEvent,
    ) -> None:
        """把查单事件并入当前聚合状态。"""
        collected.order_status_confirmed = True
        collected.last_order_status = event.status
        collected.rejection_reason = event.rejection_reason
        collected.broker_order_id = event.broker_order_id or collected.broker_order_id
        collected.filled_volume = max(collected.filled_volume, event.filled_volume)
        self._logger.info(
            "order_status_reconciled status=%s broker_order_id=%s rejection_reason=%s",
            event.status,
            event.broker_order_id,
            event.rejection_reason,
        )

    def _apply_execution_reports_event(
        self,
        *,
        collected: _CollectedEvents,
        event: _ExecutionReportsQueryEvent,
    ) -> None:
        """把查成交事件并入当前聚合状态。"""
        collected.execution_status_confirmed = True
        collected.filled_volume = event.filled_volume
        collected.avg_price = event.avg_price
        collected.broker_order_id = event.broker_order_id or collected.broker_order_id
        self._logger.info(
            "execution_status_reconciled broker_order_id=%s filled_volume=%s avg_price=%s",
            event.broker_order_id,
            event.filled_volume,
            event.avg_price,
        )

    def _to_order_status_event(
        self, snapshot: OrderStatusSnapshot
    ) -> _OrderStatusQueryEvent:
        """把查单快照标准化为内部订单事件。"""
        return _OrderStatusQueryEvent(
            broker_order_id=snapshot.broker_order_id,
            status=snapshot.status,
            filled_volume=snapshot.filled_volume,
            rejection_reason=snapshot.rejection_reason,
        )

    def _to_execution_reports_event(
        self,
        snapshots: tuple[OrderExecutionSnapshot, ...],
    ) -> _ExecutionReportsQueryEvent:
        """把成交快照列表聚合成一个内部成交事件。"""
        broker_order_id = None
        for snapshot in snapshots:
            if snapshot.broker_order_id is not None:
                broker_order_id = snapshot.broker_order_id

        return _ExecutionReportsQueryEvent(
            broker_order_id=broker_order_id,
            filled_volume=sum(snapshot.filled_volume for snapshot in snapshots),
            avg_price=snapshots[-1].avg_price if snapshots else None,
        )

    def _build_report(
        self,
        *,
        config: AppConfig,
        request: OrderRequest,
        submit_result: OrderSubmitResult | None,
        collected: _CollectedEvents,
        verification_passed: bool,
        message: str,
        started_at: datetime,
        finished_at: datetime,
    ) -> TradeReport:
        """把运行时聚合状态整理为对外报告。"""
        return TradeReport(
            account_id=config.account_id,
            side=request.side,
            symbol=request.symbol,
            requested_volume=request.volume,
            price_type=request.price_type,
            submit_accepted=(
                submit_result.accepted if submit_result is not None else False
            ),
            cl_ord_id=submit_result.cl_ord_id if submit_result is not None else None,
            broker_order_id=collected.broker_order_id,
            order_status_confirmed=collected.order_status_confirmed,
            execution_status_confirmed=collected.execution_status_confirmed,
            last_order_status=collected.last_order_status,
            rejection_reason=collected.rejection_reason,
            filled_volume=collected.filled_volume,
            avg_price=collected.avg_price,
            verification_passed=verification_passed,
            message=message,
            started_at=started_at,
            finished_at=finished_at,
        )

    def _validate_inputs(
        self,
        *,
        side: str,
        symbol: str,
        volume: int,
        price_type: str,
        price: Decimal | None,
        timeout_seconds: int,
    ) -> None:
        """校验 M1 请求参数，避免把非法请求送到柜台。"""
        if side not in {"buy", "sell"}:
            raise ServiceError(
                code="manual_trade.invalid_side",
                message="side 仅支持 buy 或 sell",
                retryable=False,
                context={"side": side},
            )
        if not symbol:
            raise ServiceError(
                code="manual_trade.invalid_symbol",
                message="symbol 不能为空",
                retryable=False,
            )
        if volume <= 0:
            raise ServiceError(
                code="manual_trade.invalid_volume",
                message="volume 必须大于 0",
                retryable=False,
                context={"volume": str(volume)},
            )
        if price_type not in {"market", "limit"}:
            raise ServiceError(
                code="manual_trade.invalid_price_type",
                message="price_type 仅支持 market 或 limit",
                retryable=False,
                context={"price_type": price_type},
            )
        if price_type == "limit" and (price is None or price <= Decimal("0")):
            raise ServiceError(
                code="manual_trade.invalid_limit_price",
                message="限价单必须提供大于 0 的价格",
                retryable=False,
                context={"price": str(price)},
            )
        if price_type == "market" and price is not None:
            raise ServiceError(
                code="manual_trade.invalid_market_price",
                message="市价单不应传入 price",
                retryable=False,
                context={"price": str(price)},
            )
        if timeout_seconds <= 0:
            raise ServiceError(
                code="manual_trade.invalid_timeout",
                message="timeout_seconds 必须大于 0",
                retryable=False,
                context={"timeout_seconds": str(timeout_seconds)},
            )

    def _now(self, timezone_name: str) -> datetime:
        return datetime.now(tz=ZoneInfo(timezone_name))


def _resolve_failure_message(collected: _CollectedEvents) -> str:
    """把当前已知状态翻译为更具体的失败说明。"""
    if collected.order_status_confirmed and collected.last_order_status is not None:
        if (
            collected.last_order_status == "filled"
            and not collected.execution_status_confirmed
        ):
            return "委托已成交，但成交明细未确认"
        if collected.last_order_status not in _TERMINAL_ORDER_STATUSES:
            return f"委托状态已确认但尚未到终态: {collected.last_order_status}"
        return "交易状态已确认"
    if collected.execution_status_confirmed:
        return "成交明细已确认，但委托状态未确认"
    return "委托状态未确认"


def _is_verification_success(
    *,
    submit_result: OrderSubmitResult | None,
    collected: _CollectedEvents,
) -> bool:
    """判断当前信息是否足以确认订单已到可接受的终态。"""
    if submit_result is None or not submit_result.accepted:
        return False

    if not collected.order_status_confirmed or collected.last_order_status is None:
        return False

    # 以查询结果为准收口 M1：拒单、撤单、过期等终态不再要求成交明细。
    if collected.last_order_status in _TERMINAL_ORDER_STATUSES:
        return True

    # 已成交必须确认成交明细，避免只知道“成交了”但拿不到数量和价格。
    if collected.last_order_status == "filled":
        return collected.execution_status_confirmed

    return False
