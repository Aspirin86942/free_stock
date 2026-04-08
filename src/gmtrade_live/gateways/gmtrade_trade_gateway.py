from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import importlib
from typing import Any

from gmtrade_live.config import AppConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.models import CashSnapshot, PositionSnapshot
from gmtrade_live.precision import normalize_amount, normalize_price


class GMTradeQueryGateway:
    def __init__(self, api_module: Any | None = None) -> None:
        self._api = api_module or _import_trade_api()
        self._account_object: Any | None = None

    def connect(self, config: AppConfig) -> None:
        self._api.set_token(config.token)
        if _supports_gmtrade_login(self._api):
            if hasattr(self._api, "set_endpoint"):
                self._api.set_endpoint(config.gmtrade_endpoint)
            self._account_object = self._api.account(
                account_id=config.account_id,
                account_alias=config.strategy_name,
            )
            self._api.login(self._account_object)
            return

        if hasattr(self._api, "set_serv_addr"):
            self._api.set_serv_addr(config.gmtrade_endpoint)
        if hasattr(self._api, "set_account_id"):
            self._api.set_account_id(config.account_id)

    def get_cash(self, account_id: str) -> CashSnapshot:
        raw = self._get_cash_payload(account_id)
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
            market_value=normalize_amount(_pick(raw, "market_value", "market_value_long")),
            total_asset=normalize_amount(_pick(raw, "nav", "balance")),
            update_time=_as_datetime(
                _pick(raw, "updated_at", "created_at"),
                field_name="updated_at",
            ),
        )

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        rows = self._get_positions_payload(account_id)
        results: list[PositionSnapshot] = []
        for row in rows:
            row = _coerce_record(row)
            symbol = str(_pick(row, "symbol"))
            volume = int(_pick(row, "volume"))
            available_volume = int(_pick(row, "available", "available_now", "available_volume"))
            cost_per_share = _resolve_cost_per_share(row, volume)
            results.append(
                PositionSnapshot(
                    symbol=symbol,
                    exchange=symbol.split(".", maxsplit=1)[0] if "." in symbol else "",
                    volume=volume,
                    available_volume=available_volume,
                    cost_price=normalize_price(cost_per_share),
                    last_update_time=_as_datetime(
                        _pick(row, "updated_at", "created_at"),
                        field_name="updated_at",
                    ),
                )
            )
        return results

    def _get_cash_payload(self, account_id: str) -> Any:
        if _supports_gmtrade_login(self._api):
            try:
                return self._api.get_cash(account=self._account_object)
            except TypeError:
                return self._api.get_cash(account_id=account_id)
        return self._api.get_cash(account_id=account_id)

    def _get_positions_payload(self, account_id: str) -> list[Any]:
        if _supports_gmtrade_login(self._api) and hasattr(self._api, "get_positions"):
            try:
                return self._api.get_positions(account=self._account_object) or []
            except TypeError:
                return self._api.get_positions(account_id=account_id) or []
        if hasattr(self._api, "get_position"):
            return self._api.get_position(account_id=account_id) or []
        raise ServiceError(
            code="gmtrade.unsupported_api",
            message="未找到可用的持仓查询接口",
            retryable=False,
            context={"api_module": str(self._api)},
        )


def _import_trade_api() -> Any:
    try:
        return importlib.import_module("gmtrade.api")
    except ModuleNotFoundError:
        return importlib.import_module("gm.api")


def _supports_gmtrade_login(api_module: Any) -> bool:
    return all(
        hasattr(api_module, name)
        for name in ("set_endpoint", "account", "login")
    )


def _pick(payload: dict[str, Any], *keys: str) -> Any:
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
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise ServiceError(
        code="gmtrade.invalid_payload",
        message="掘金返回对象不是可映射记录",
        retryable=True,
        context={"value_type": type(value).__name__},
    )


def _resolve_cost_per_share(row: dict[str, Any], volume: int) -> Decimal:
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
    if isinstance(value, datetime):
        return value
    raise ServiceError(
        code="gmtrade.invalid_datetime",
        message="掘金返回的时间字段格式不合法",
        retryable=True,
        context={"field": field_name, "value": str(value)},
    )
