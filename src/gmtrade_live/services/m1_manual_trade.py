"""M1 手动卖单验证服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from queue import Empty
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.models import (
    ExecutionEvent,
    OrderEvent,
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    OrderSubmitResult,
    TradeReport,
)

if TYPE_CHECKING:
    from gmtrade_live.gateways.callback_handler import CallbackHandler
    from gmtrade_live.gateways.protocols import TradeGateway


_RECONCILE_INTERVAL_SECONDS = 0.5
_TERMINAL_ORDER_STATUSES = {"rejected", "cancelled", "expired", "done_for_day", "stopped"}


@dataclass(slots=True)
class _CollectedEvents:
    """聚合回调与主动查询得到的订单状态。"""

    order_event_received: bool = False
    execution_event_received: bool = False
    callback_chain_closed: bool = False
    order_status_confirmed: bool = False
    execution_status_confirmed: bool = False
    broker_order_id: str | None = None
    last_order_status: str | None = None
    rejection_reason: str | None = None
    filled_volume: int = 0
    avg_price: Decimal | None = None


class ManualTradeService:
    """负责一次 M1 手动卖单验证的完整收口。"""

    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        callback_handler: CallbackHandler,
        logger: logging.Logger,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._callback_handler = callback_handler
        self._logger = logger

    def run(
        self,
        *,
        config: AppConfig,
        symbol: str,
        volume: int,
        price_type: str,
        price: Decimal | None,
        timeout_seconds: int,
    ) -> TradeReport:
        """提交卖单、等待回报，并在超时前主动查单收口。"""
        self._validate_inputs(
            symbol=symbol,
            volume=volume,
            price_type=price_type,
            price=price,
            timeout_seconds=timeout_seconds,
        )
        started_at = self._now(config.timezone)
        self._logger.info(
            "m1_manual_trade_starting account_id=%s symbol=%s volume=%s price_type=%s timeout_seconds=%s",
            config.account_id,
            symbol,
            volume,
            price_type,
            timeout_seconds,
        )

        request = OrderRequest(
            symbol=symbol,
            volume=volume,
            side="sell",
            price_type=price_type,
            price=price,
        )
        self._callback_handler.clear_queue()
        self._logger.info(
            "order_submit_request account_id=%s symbol=%s volume=%s price_type=%s",
            config.account_id,
            symbol,
            volume,
            price_type,
        )

        try:
            submit_result = self._trade_gateway.submit_order(request)
        except Exception as exc:
            self._logger.error(
                "m1_manual_trade_failed account_id=%s symbol=%s reason=%s",
                config.account_id,
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
                "m1_manual_trade_failed account_id=%s symbol=%s reason=%s",
                config.account_id,
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
        collected = self._wait_for_events(
            request=request,
            submit_result=submit_result,
            deadline=deadline,
            timezone_name=config.timezone,
        )
        if submit_result.broker_order_id is not None:
            collected.broker_order_id = submit_result.broker_order_id
        # SDK 回调可能丢失，离开等待循环前再主动查一次，确保终态尽量可确认。
        if not (collected.order_event_received and collected.execution_event_received):
            self._reconcile_trade_state(
                request=request,
                submit_result=submit_result,
                collected=collected,
            )

        callback_success = collected.order_event_received and collected.execution_event_received
        collected.callback_chain_closed = callback_success
        verification_passed = _is_verification_success(
            submit_result=submit_result,
            collected=collected,
        )
        finished_at = self._now(config.timezone)

        if verification_passed and callback_success:
            self._logger.info(
                "m1_manual_trade_success account_id=%s cl_ord_id=%s filled_volume=%s",
                config.account_id,
                submit_result.cl_ord_id,
                collected.filled_volume,
            )
            return self._build_report(
                config=config,
                request=request,
                submit_result=submit_result,
                collected=collected,
                verification_passed=True,
                message="M1 verification completed successfully",
                started_at=started_at,
                finished_at=finished_at,
            )

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
                message="交易状态已确认，但回调链路未闭环",
                started_at=started_at,
                finished_at=finished_at,
            )

        message = _resolve_failure_message(collected)
        log_method = self._logger.warning if collected.order_status_confirmed else self._logger.error
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

    def _wait_for_events(
        self,
        *,
        request: OrderRequest,
        submit_result: OrderSubmitResult,
        deadline: datetime,
        timezone_name: str,
    ) -> _CollectedEvents:
        """等待订单回报，并定期主动查询作为兜底。"""
        collected = _CollectedEvents()
        next_reconcile_at = self._now(timezone_name)

        while self._now(timezone_name) < deadline:
            self._trade_gateway.poll_callbacks()
            remaining_seconds = max((deadline - self._now(timezone_name)).total_seconds(), 0.0)
            timeout = min(0.2, remaining_seconds)
            try:
                event = self._callback_handler.event_queue.get(timeout=timeout)
            except Empty:
                if collected.order_event_received and collected.execution_event_received:
                    return collected
            else:
                if not hasattr(event, "order_id"):
                    self._logger.warning("unknown_trade_event event_type=%s", type(event).__name__)
                    continue
                # 队列里可能混入其他历史订单事件，必须按 cl_ord_id 严格过滤。
                if event.order_id != submit_result.cl_ord_id:
                    self._logger.info(
                        "trade_event_ignored expected_order_id=%s actual_order_id=%s",
                        submit_result.cl_ord_id,
                        event.order_id,
                    )
                    continue

                if isinstance(event, OrderEvent):
                    collected.order_event_received = True
                    collected.last_order_status = event.status
                    self._logger.info(
                        "order_event_matched order_id=%s status=%s filled_volume=%s remaining_volume=%s",
                        event.order_id,
                        event.status,
                        event.filled_volume,
                        event.remaining_volume,
                    )
                elif isinstance(event, ExecutionEvent):
                    collected.execution_event_received = True
                    collected.filled_volume += event.filled_volume
                    collected.avg_price = event.avg_price
                    self._logger.info(
                        "execution_event_matched order_id=%s filled_volume=%s avg_price=%s",
                        event.order_id,
                        event.filled_volume,
                        event.avg_price,
                    )

            now = self._now(timezone_name)
            if now >= next_reconcile_at:
                self._reconcile_trade_state(
                    request=request,
                    submit_result=submit_result,
                    collected=collected,
                )
                if _is_verification_success(
                    submit_result=submit_result,
                    collected=collected,
                ):
                    return collected
                next_reconcile_at = now + timedelta(seconds=_RECONCILE_INTERVAL_SECONDS)

        return collected

    def _reconcile_trade_state(
        self,
        *,
        request: OrderRequest,
        submit_result: OrderSubmitResult,
        collected: _CollectedEvents,
    ) -> None:
        """用主动查询结果补齐回调缺失的委托和成交状态。"""
        if submit_result.cl_ord_id is None:
            return

        order_snapshot = self._trade_gateway.query_order_status(
            submit_result.cl_ord_id,
            request.symbol,
        )
        if order_snapshot is not None:
            self._apply_order_snapshot(collected=collected, snapshot=order_snapshot)

        # 只有出现成交相关状态时才查成交，避免对拒单、撤单做无意义查询。
        if collected.last_order_status in {"filled", "partially_filled"}:
            execution_snapshots = self._trade_gateway.query_execution_reports(
                submit_result.cl_ord_id
            )
            if execution_snapshots:
                self._apply_execution_snapshots(
                    collected=collected,
                    snapshots=execution_snapshots,
                )

    def _apply_order_snapshot(
        self,
        *,
        collected: _CollectedEvents,
        snapshot: OrderStatusSnapshot,
    ) -> None:
        """把查单结果并入当前聚合状态。"""
        collected.order_status_confirmed = True
        collected.last_order_status = snapshot.status
        collected.rejection_reason = snapshot.rejection_reason
        collected.broker_order_id = snapshot.broker_order_id or collected.broker_order_id
        collected.filled_volume = max(collected.filled_volume, snapshot.filled_volume)
        self._logger.info(
            "order_status_reconciled cl_ord_id=%s status=%s broker_order_id=%s rejection_reason=%s",
            snapshot.cl_ord_id,
            snapshot.status,
            snapshot.broker_order_id,
            snapshot.rejection_reason,
        )

    def _apply_execution_snapshots(
        self,
        *,
        collected: _CollectedEvents,
        snapshots: tuple[OrderExecutionSnapshot, ...],
    ) -> None:
        """把成交查询结果并入当前聚合状态。"""
        collected.execution_status_confirmed = True
        collected.filled_volume = sum(snapshot.filled_volume for snapshot in snapshots)
        collected.avg_price = snapshots[-1].avg_price
        for snapshot in snapshots:
            if snapshot.broker_order_id is not None:
                collected.broker_order_id = snapshot.broker_order_id
        self._logger.info(
            "execution_status_reconciled cl_ord_id=%s executions=%s filled_volume=%s avg_price=%s",
            snapshots[0].cl_ord_id,
            len(snapshots),
            collected.filled_volume,
            collected.avg_price,
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
            symbol=request.symbol,
            requested_volume=request.volume,
            price_type=request.price_type,
            submit_accepted=submit_result.accepted if submit_result is not None else False,
            cl_ord_id=submit_result.cl_ord_id if submit_result is not None else None,
            broker_order_id=collected.broker_order_id,
            order_event_received=collected.order_event_received,
            execution_event_received=collected.execution_event_received,
            callback_chain_closed=collected.callback_chain_closed,
            order_status_confirmed=(
                collected.order_event_received or collected.order_status_confirmed
            ),
            execution_status_confirmed=(
                collected.execution_event_received or collected.execution_status_confirmed
            ),
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
        symbol: str,
        volume: int,
        price_type: str,
        price: Decimal | None,
        timeout_seconds: int,
    ) -> None:
        """校验 M1 请求参数，避免把非法请求送到柜台。"""
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


def _timeout_message(collected: _CollectedEvents) -> str:
    """根据缺失的回调类型生成超时原因。"""
    if not collected.order_event_received and not collected.execution_event_received:
        return "missing_both_events"
    if not collected.order_event_received:
        return "missing_order_event"
    return "missing_execution_event"


def _resolve_failure_message(collected: _CollectedEvents) -> str:
    """把当前已知状态翻译为更具体的失败说明。"""
    order_status_confirmed = collected.order_event_received or collected.order_status_confirmed
    execution_status_confirmed = (
        collected.execution_event_received or collected.execution_status_confirmed
    )
    if order_status_confirmed and collected.last_order_status is not None:
        if collected.last_order_status == "filled" and not execution_status_confirmed:
            return "委托已成交，但成交明细未确认"
        if collected.last_order_status not in _TERMINAL_ORDER_STATUSES:
            return f"委托状态已确认但尚未到终态: {collected.last_order_status}"
        return "交易状态已确认，但回调链路未闭环"
    if execution_status_confirmed:
        return "成交明细已确认，但委托状态未确认"
    return _timeout_message(collected)


def _is_verification_success(
    *,
    submit_result: OrderSubmitResult | None,
    collected: _CollectedEvents,
) -> bool:
    """判断当前信息是否足以确认订单已到可接受的终态。"""
    if submit_result is None or not submit_result.accepted:
        return False

    if collected.order_event_received and collected.execution_event_received:
        return True

    order_status_confirmed = collected.order_event_received or collected.order_status_confirmed
    execution_status_confirmed = (
        collected.execution_event_received or collected.execution_status_confirmed
    )
    if not order_status_confirmed or collected.last_order_status is None:
        return False

    # 以查询结果为准收口 M1：已拒绝、已撤销、已过期等终态不再要求成交回报。
    if collected.last_order_status in _TERMINAL_ORDER_STATUSES:
        return True

    # 成交完成必须能确认成交数据，避免只知道“已成交”却拿不到数量和价格。
    if collected.last_order_status == "filled":
        return execution_status_confirmed

    return False
