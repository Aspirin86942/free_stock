"""独立查询 smoke test：发起限价买单后，轮询查单与查成交确认最终状态。"""

from __future__ import annotations

from decimal import Decimal
import importlib
import logging
from pathlib import Path
import time

from gm.enum import OrderSide_Buy, OrderType_Limit, PositionEffect_Open

from gmtrade_live.config import load_config
from gmtrade_live.gateways.gmtrade_trade_gateway import (
    GMTradeGateway,
    _as_datetime_or_now,
    _extract_first_record,
    _is_submit_accepted,
    _read_optional,
)
from gmtrade_live.models import OrderStatusSnapshot, OrderSubmitResult
from gmtrade_live.precision import normalize_price

POLL_INTERVAL_SECONDS = 0.2
WAIT_TIMEOUT_SECONDS = 30
TERMINAL_ORDER_STATUSES = {"rejected", "cancelled", "expired", "done_for_day", "stopped"}

# 这里保持成脚本常量，方便直接改值重复做烟雾验证。
BUY_SYMBOL = "SHSE.600839"
BUY_VOLUME = 100
BUY_LIMIT_PRICE = Decimal("8.660")


def build_buy_order_kwargs(
    *,
    symbol: str,
    volume: int,
    limit_price: Decimal,
    account_id: str,
) -> dict[str, object]:
    """构造独立买入 smoke test 需要的下单参数。"""
    return {
        "symbol": symbol,
        "volume": volume,
        "side": OrderSide_Buy,
        "order_type": OrderType_Limit,
        "position_effect": PositionEffect_Open,
        "price": float(normalize_price(limit_price)),
        "account": account_id,
    }


def build_summary(
    *,
    submit_accepted: bool,
    query_order_status_confirmed: bool,
    query_execution_count: int,
    final_order_status: str | None,
    final_rejection_reason: str | None,
) -> dict[str, object]:
    """整理脚本最终输出，只保留查询视角的结果。"""
    return {
        "submit_accepted": submit_accepted,
        "query_order_status_confirmed": query_order_status_confirmed,
        "query_execution_count": query_execution_count,
        "final_order_status": final_order_status,
        "final_rejection_reason": final_rejection_reason,
    }


def _parse_submit_result(raw_result: object, *, symbol: str) -> OrderSubmitResult:
    """把 gm 原始下单返回转换成统一提交结果。"""
    row = _extract_first_record(raw_result)
    raw_status = str(_read_optional(row, "status", default=""))
    cl_ord_id = _read_optional(row, "cl_ord_id", "order_id")
    broker_order_id = _read_optional(row, "order_id")
    message = str(
        _read_optional(
            row,
            "ord_rej_reason_detail",
            "status_msg",
            "message",
            default="accepted" if cl_ord_id else "empty_submit_result",
        )
    )
    return OrderSubmitResult(
        accepted=_is_submit_accepted(order_id=cl_ord_id, raw_status=raw_status),
        cl_ord_id=str(cl_ord_id) if cl_ord_id is not None else None,
        broker_order_id=str(broker_order_id) if broker_order_id is not None else None,
        symbol=str(_read_optional(row, "symbol", default=symbol)),
        message=message,
        raw_status=raw_status,
        event_time=_as_datetime_or_now(row, field_name="created_at"),
    )


def _should_stop_wait(order_snapshot: OrderStatusSnapshot | None) -> bool:
    """已查到终态后结束轮询。"""
    if order_snapshot is None:
        return False
    return order_snapshot.status in ({"filled"} | TERMINAL_ORDER_STATUSES)


def _wait_for_order_status(
    *,
    gateway: GMTradeGateway,
    cl_ord_id: str,
    symbol: str,
) -> OrderStatusSnapshot | None:
    """在超时前轮询查单，直到确认终态或耗尽等待时间。"""
    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    last_snapshot: OrderStatusSnapshot | None = None

    while time.time() < deadline:
        last_snapshot = gateway.query_order_status(cl_ord_id, symbol)
        if last_snapshot is not None:
            print("query_order_status ...")
            print(last_snapshot)
        if _should_stop_wait(last_snapshot):
            return last_snapshot
        time.sleep(POLL_INTERVAL_SECONDS)

    return last_snapshot


def run_query_smoke_test(config_path: Path) -> dict[str, object]:
    """执行一次独立买入查询 smoke test。"""
    config = load_config(config_path)
    logger = logging.getLogger("query-smoke")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(logging.StreamHandler())

    api_module = importlib.import_module("gm.api")
    gateway = GMTradeGateway(api_module=api_module, account_id=config.account_id)

    gateway.connect(config)
    print("query smoke test started")

    raw_result = api_module.order_volume(
        **build_buy_order_kwargs(
            symbol=BUY_SYMBOL,
            volume=BUY_VOLUME,
            limit_price=BUY_LIMIT_PRICE,
            account_id=config.account_id,
        )
    )
    result = _parse_submit_result(raw_result, symbol=BUY_SYMBOL)
    print(result)

    if result.cl_ord_id is None:
        raise SystemExit("submit_result 缺少 cl_ord_id，无法继续查单")

    order_snapshot = _wait_for_order_status(
        gateway=gateway,
        cl_ord_id=result.cl_ord_id,
        symbol=result.symbol,
    )

    if order_snapshot is not None and order_snapshot.status in {"filled", "partially_filled"}:
        print("query_execution_reports ...")
        execution_snapshots = gateway.query_execution_reports(result.cl_ord_id)
        print(execution_snapshots)
    else:
        execution_snapshots = ()

    summary = build_summary(
        submit_accepted=result.accepted,
        query_order_status_confirmed=order_snapshot is not None,
        query_execution_count=len(execution_snapshots),
        final_order_status=order_snapshot.status if order_snapshot is not None else None,
        final_rejection_reason=(
            order_snapshot.rejection_reason if order_snapshot is not None else None
        ),
    )
    print(summary)
    return summary


def main() -> int:
    """脚本入口。"""
    run_query_smoke_test(Path("config/sim_account.yaml"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
