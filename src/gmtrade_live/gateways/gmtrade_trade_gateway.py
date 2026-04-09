"""掘金交易网关的适配实现。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import importlib
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from gm.enum import OrderSide_Sell, OrderType_Limit, OrderType_Market, PositionEffect_Close

from gmtrade_live.config import AppConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.models import (
    CashSnapshot,
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    OrderSubmitResult,
    PositionSnapshot,
)
from gmtrade_live.precision import normalize_amount, normalize_price

if TYPE_CHECKING:
    from gmtrade_live.gateways.callback_handler import CallbackHandler


class GMTradeQueryGateway:
    """负责交易、查单、查成交和回调注册的统一入口。"""

    def __init__(
        self,
        api_module: Any | None = None,
        account_id: str | None = None,
    ) -> None:
        self._api = api_module or importlib.import_module("gm.api")
        self._account_id = account_id
        self._callback_handler: CallbackHandler | None = None
        self._callback_runtime_ready = False

    def connect(self, config: AppConfig) -> None:
        """绑定 token、服务地址和账户上下文。"""
        self._api.set_token(config.token)
        if hasattr(self._api, "set_serv_addr") and config.gmtrade_endpoint:
            self._api.set_serv_addr(config.gmtrade_endpoint)
        if self._account_id is None:
            self._account_id = config.account_id

    def get_cash(self, account_id: str) -> CashSnapshot:
        """读取账户资金并转换为内部快照。"""
        raw = self._api.get_cash(account_id=account_id)
        if not raw:
            raise ServiceError(
                code="gmtrade.empty_cash",
                message="掘金未返回资金对象",
                retryable=True,
                context={"account_id": account_id},
            )
        raw = _coerce_record(raw)

        return CashSnapshot(
            account_id=str(_pick(raw, "account_id")),
            available_cash=normalize_amount(_pick(raw, "available", "balance")),
            market_value=normalize_amount(
                _pick(raw, "market_value", "market_value_long")
            ),
            total_asset=normalize_amount(_pick(raw, "nav", "balance")),
            update_time=_as_datetime_or_now(raw, field_name="updated_at"),
        )

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        """读取持仓列表并标准化价格、时间和可卖数量。"""
        rows = self._api.get_position(account_id=account_id) or []
        results: list[PositionSnapshot] = []
        for row in rows:
            row = _coerce_record(row)
            symbol = str(_pick(row, "symbol"))
            volume = int(_pick(row, "volume"))
            available_volume = int(
                _pick(row, "available", "available_now", "available_volume")
            )
            cost_per_share = _resolve_cost_per_share(row, volume)
            results.append(
                PositionSnapshot(
                    symbol=symbol,
                    exchange=symbol.split(".", maxsplit=1)[0] if "." in symbol else "",
                    volume=volume,
                    available_volume=available_volume,
                    cost_price=normalize_price(cost_per_share),
                    last_update_time=_as_datetime_or_now(row, field_name="updated_at"),
                )
            )
        return results

    def set_callback_handler(self, handler: CallbackHandler) -> None:
        """优先走显式 setter，真实 gm SDK 则退回到全局 context 注册。"""
        self._callback_handler = handler

        registered = False
        if hasattr(self._api, "set_order_callback"):
            self._api.set_order_callback(handler.on_order_status)
            registered = True
        if hasattr(self._api, "set_execution_report_callback"):
            self._api.set_execution_report_callback(handler.on_execution_report)
            registered = True

        if registered:
            return

        _register_gm_callbacks(handler)
        self._callback_runtime_ready = True

    def submit_order(self, request: OrderRequest) -> OrderSubmitResult:
        """提交卖单并把掘金原始返回转换为内部提交结果。"""
        if self._account_id is None:
            raise ServiceError(
                code="gmtrade.missing_account_id",
                message="交易网关尚未绑定账户，无法提交委托",
                retryable=False,
            )
        if request.side != "sell":
            raise ServiceError(
                code="gmtrade.unsupported_side",
                message="M1 仅支持手动卖单验证",
                retryable=False,
                context={"side": request.side},
            )
        if request.volume <= 0:
            raise ServiceError(
                code="gmtrade.invalid_volume",
                message="委托数量必须大于 0",
                retryable=False,
                context={"volume": str(request.volume)},
            )

        order_type = _resolve_order_type(request.price_type)
        order_price = _resolve_submit_price(request)
        raw_result = self._api.order_volume(
            symbol=request.symbol,
            volume=request.volume,
            side=OrderSide_Sell,
            order_type=order_type,
            position_effect=PositionEffect_Close,
            price=order_price,
            account=self._account_id,
        )
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
            symbol=str(_read_optional(row, "symbol", default=request.symbol)),
            message=message,
            raw_status=raw_status,
            event_time=_as_datetime_or_now(row, field_name="created_at"),
        )

    def query_order_status(self, cl_ord_id: str, symbol: str) -> OrderStatusSnapshot | None:
        """按内部委托号查单，确认最终委托状态。"""
        if self._account_id is None:
            raise ServiceError(
                code="gmtrade.missing_account_id",
                message="交易网关尚未绑定账户，无法查询委托状态",
                retryable=False,
            )

        rows = _fetch_orders(
            api_module=self._api,
            account_id=self._account_id,
            cl_ord_id=cl_ord_id,
            symbol=symbol,
        )
        rows = [
            row
            for row in rows
            if str(_read_optional(row, "cl_ord_id", default="")) == cl_ord_id
        ]
        if not rows:
            return None

        row = _coerce_record(rows[0])
        status_code = int(_read_optional(row, "status", default=0))
        filled_volume = int(_read_optional(row, "filled_volume", default=0))
        total_volume = int(_read_optional(row, "volume", default=filled_volume))
        remaining_volume = max(total_volume - filled_volume, 0)
        rejection_reason = _read_optional(
            row,
            "ord_rej_reason_detail",
            "status_msg",
            "message",
        )

        return OrderStatusSnapshot(
            cl_ord_id=str(_read_optional(row, "cl_ord_id", default=cl_ord_id)),
            broker_order_id=_as_optional_str(_read_optional(row, "order_id")),
            symbol=str(_read_optional(row, "symbol", default=symbol)),
            status=_map_order_status(status_code),
            filled_volume=filled_volume,
            remaining_volume=remaining_volume,
            rejection_reason=str(rejection_reason) if rejection_reason else None,
            event_time=_as_datetime_or_now(row, field_name="updated_at"),
        )

    def query_execution_reports(self, cl_ord_id: str) -> tuple[OrderExecutionSnapshot, ...]:
        """按内部委托号查询成交回报。"""
        if self._account_id is None:
            raise ServiceError(
                code="gmtrade.missing_account_id",
                message="交易网关尚未绑定账户，无法查询成交回报",
                retryable=False,
            )

        rows = _fetch_execution_reports(
            account_id=self._account_id,
            cl_ord_id=cl_ord_id,
        )
        snapshots: list[OrderExecutionSnapshot] = []
        for row in rows:
            payload = _coerce_record(row)
            if str(_read_optional(payload, "cl_ord_id", default="")) != cl_ord_id:
                continue
            filled_volume = int(_read_optional(payload, "volume", "filled_volume", default=0))
            snapshots.append(
                OrderExecutionSnapshot(
                    cl_ord_id=str(_read_optional(payload, "cl_ord_id", default=cl_ord_id)),
                    broker_order_id=_as_optional_str(_read_optional(payload, "order_id")),
                    symbol=str(_read_optional(payload, "symbol", default="")),
                    filled_volume=filled_volume,
                    avg_price=normalize_price(
                        _read_optional(payload, "filled_vwap", "price", default=0)
                    ),
                    event_time=_as_datetime_or_now(payload, field_name="created_at"),
                )
            )
        return tuple(snapshots)

    def poll_callbacks(self) -> None:
        """仅在注册了 gm 原生回调轮询时驱动回调通道。"""
        if not self._callback_runtime_ready:
            return
        _poll_gm_callbacks()


GMTradeGateway = GMTradeQueryGateway


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    """读取必填字段；缺失时抛出结构化错误。"""
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    raise ServiceError(
        code="gmtrade.missing_field",
        message="掘金返回字段缺失",
        retryable=True,
        context={"keys": ",".join(keys), "payload": str(payload)},
    )


def _coerce_record(value: Any) -> dict[str, Any]:
    """把 dict、映射对象或普通对象统一转换为字典。"""
    if isinstance(value, dict):
        return value
    if hasattr(value, "items"):
        return dict(value.items())
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise ServiceError(
        code="gmtrade.invalid_payload",
        message="掘金返回对象不是可映射记录",
        retryable=True,
        context={"value_type": type(value).__name__},
    )


def _resolve_cost_per_share(row: dict[str, Any], volume: int) -> Decimal:
    """按字段优先级推导持仓成本价。"""
    if "vwap" in row and row["vwap"] is not None:
        return Decimal(str(row["vwap"]))
    if "cost" in row and row["cost"] is not None:
        total_cost = Decimal(str(row["cost"]))
        return total_cost / Decimal(volume) if volume > 0 else Decimal("0")
    if "amount" in row and row["amount"] is not None:
        total_amount = Decimal(str(row["amount"]))
        return total_amount / Decimal(volume) if volume > 0 else Decimal("0")
    return Decimal("0")


def _as_datetime(value: Any, *, field_name: str) -> datetime:
    """校验时间字段是否已被 SDK 解析为 datetime。"""
    if isinstance(value, datetime):
        return value
    raise ServiceError(
        code="gmtrade.invalid_datetime",
        message="掘金返回的时间字段格式不合法",
        retryable=True,
        context={"field": field_name, "value": str(value)},
    )


def _as_datetime_or_now(payload: dict[str, Any], *, field_name: str) -> datetime:
    """尝试从 payload 提取时间字段，如果不存在则返回当前时间"""
    for key in ("updated_at", "created_at"):
        if key in payload and payload[key] is not None:
            value = payload[key]
            if isinstance(value, datetime):
                return value

    # gm.api 返回的数据可能没有时间字段，使用当前时间
    return datetime.now(tz=ZoneInfo("Asia/Shanghai"))


def _resolve_order_type(price_type: str) -> int:
    """把内部委托类型映射到掘金常量。"""
    if price_type == "market":
        return OrderType_Market
    if price_type == "limit":
        return OrderType_Limit
    raise ServiceError(
        code="gmtrade.invalid_price_type",
        message="仅支持 market 或 limit 委托类型",
        retryable=False,
        context={"price_type": price_type},
    )


def _resolve_submit_price(request: OrderRequest) -> float:
    """生成提交给 SDK 的价格字段。"""
    if request.price_type == "market":
        return 0
    if request.price is None:
        raise ServiceError(
            code="gmtrade.missing_limit_price",
            message="限价单缺少价格",
            retryable=False,
            context={"symbol": request.symbol},
        )
    return float(normalize_price(request.price))


def _extract_first_record(raw_result: Any) -> dict[str, Any]:
    """兼容 SDK 返回单对象或单元素列表两种提交结果格式。"""
    if isinstance(raw_result, (list, tuple)):
        if not raw_result:
            raise ServiceError(
                code="gmtrade.empty_order_submit",
                message="掘金未返回委托提交结果",
                retryable=True,
            )
        return _coerce_record(raw_result[0])
    return _coerce_record(raw_result)


def _read_optional(payload: dict[str, Any], *keys: str, default: Any | None = None) -> Any:
    """读取可选字段；缺失时返回默认值。"""
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _is_submit_accepted(*, order_id: Any, raw_status: str) -> bool:
    """根据委托号和状态码判断提交是否被柜台接受。"""
    if order_id in (None, ""):
        return False
    try:
        return int(raw_status) != 8
    except (TypeError, ValueError):
        return True


def _map_order_status(status_code: int) -> str:
    """把掘金状态码映射为内部状态文本。"""
    status_map = {
        0: "unknown",
        1: "submitted",
        2: "partially_filled",
        3: "filled",
        4: "done_for_day",
        5: "cancelled",
        6: "pending_cancel",
        7: "stopped",
        8: "rejected",
        9: "suspended",
        10: "pending_new",
        11: "calculated",
        12: "expired",
        13: "accepted_for_bidding",
        14: "pending_replace",
    }
    return status_map.get(status_code, f"unknown_{status_code}")


def _fetch_orders(
    *,
    api_module: Any,
    account_id: str,
    cl_ord_id: str,
    symbol: str,
) -> list[dict[str, Any]]:
    """优先调用高层 API，缺失时回退到底层 protobuf 查单。"""
    if hasattr(api_module, "get_orders_mm"):
        rows = api_module.get_orders_mm(
            symbol=symbol,
            order_ids=cl_ord_id,
            account_id=account_id,
        )
        return [_coerce_record(row) for row in rows or []]

    from gm.csdk.c_sdk import c_status_fail, py_gmi_get_orders
    from gm.model import DictLikeOrderMM
    from gm.pb.account_pb2 import Orders
    from gm.pb.trade_pb2 import GetOrdersReq
    from gm.pb_to_dict import protobuf_to_dict

    req = GetOrdersReq(
        account_id=account_id,
        symbols=[symbol] if symbol else None,
        cl_ord_ids=[cl_ord_id],
    ).SerializeToString()
    status, res = py_gmi_get_orders(req)
    if c_status_fail(status, "get_orders_mm"):
        return []
    if not res:
        return []

    rsp = Orders()
    rsp.ParseFromString(res)
    return [
        protobuf_to_dict(
            order,
            including_default_value_fields=True,
            dcls=DictLikeOrderMM,
        )
        for order in rsp.data
    ]


def _fetch_execution_reports(*, account_id: str, cl_ord_id: str) -> list[dict[str, Any]]:
    """通过底层 API 查询成交回报。"""
    from gm.csdk.c_sdk import c_status_fail, py_gmi_get_execution_reports
    from gm.pb.account_pb2 import ExecRpts
    from gm.pb.trade_pb2 import GetExecrptsReq
    from gm.pb_to_dict import protobuf_to_dict

    req = GetExecrptsReq(
        account_id=account_id,
        cl_ord_id=cl_ord_id,
    ).SerializeToString()
    status, res = py_gmi_get_execution_reports(req)
    if c_status_fail(status, "py_gmi_get_execution_reports"):
        return []
    if not res:
        return []

    rsp = ExecRpts()
    rsp.ParseFromString(res)
    return [
        protobuf_to_dict(
            report,
            including_default_value_fields=True,
        )
        for report in rsp.data
    ]


def _as_optional_str(value: Any) -> str | None:
    """把空字符串和 None 统一收敛为 None。"""
    if value in (None, ""):
        return None
    return str(value)


def _register_gm_callbacks(handler: CallbackHandler) -> None:
    """在真实 gm 运行时里注册订单和成交回调。"""
    try:
        from gm.callback import callback_controller
        from gm.csdk.c_sdk import (
            gmi_init,
            gmi_set_mode,
            py_gmi_set_data_callback,
            py_gmi_set_strategy_id,
        )
        from gm.api._errors import check_gm_status
        from gm.enum import MODE_LIVE
        from gm.model.storage import context as gm_context
    except ImportError as exc:
        raise ServiceError(
            code="gmtrade.callback_registration_failed",
            message="无法注册掘金回调函数",
            retryable=False,
            context={"reason": str(exc)},
        ) from exc

    # 直接把回调挂到 gm 全局 context，保证真实终端回报能进入本项目队列。
    gm_context.on_order_status_fun = handler.on_order_status
    gm_context.on_execution_report_fun = handler.on_execution_report
    gm_context.mode = MODE_LIVE
    gm_context.strategy_id = "m1_manual_trade"
    py_gmi_set_strategy_id(b"m1_manual_trade")
    gmi_set_mode(MODE_LIVE)
    py_gmi_set_data_callback(callback_controller)
    check_gm_status(gmi_init())


def _poll_gm_callbacks() -> None:
    """驱动 gm 底层回调轮询。"""
    try:
        from gm.csdk.c_sdk import gmi_poll
    except ImportError as exc:
        raise ServiceError(
            code="gmtrade.callback_poll_failed",
            message="无法轮询掘金回调通道",
            retryable=False,
            context={"reason": str(exc)},
        ) from exc

    gmi_poll()
