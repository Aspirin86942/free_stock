"""掘金行情网关适配。"""

from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any

from gmtrade_live.errors import ServiceError
from gmtrade_live.models import QuoteSnapshot
from gmtrade_live.precision import normalize_price


class GMCurrentQuoteGateway:
    """读取当前行情并转换为内部行情快照。"""

    def __init__(self, api_module: Any | None = None) -> None:
        self._api = api_module or importlib.import_module("gm.api")

    def connect(self, token: str) -> None:
        """设置行情接口 token。"""
        self._api.set_token(token)

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        """批量拉取标的最新价格。"""
        if not symbols:
            return []

        rows = self._api.current(symbols=symbols, fields="symbol,price,created_at")
        results: list[QuoteSnapshot] = []
        for row in rows:
            if "symbol" not in row or "price" not in row or "created_at" not in row:
                raise ServiceError(
                    code="gm.invalid_quote_payload",
                    message="行情快照字段缺失",
                    retryable=True,
                    context={"payload": str(row)},
                )
            results.append(
                QuoteSnapshot(
                    symbol=str(row["symbol"]),
                    last_price=normalize_price(row["price"]),
                    quote_time=_as_datetime(row["created_at"], field_name="created_at"),
                    source="gm.current",
                )
            )
        return results


def _as_datetime(value: Any, *, field_name: str) -> datetime:
    """校验行情时间字段格式。"""
    if isinstance(value, datetime):
        return value
    raise ServiceError(
        code="gm.invalid_datetime",
        message="行情时间字段格式不合法",
        retryable=True,
        context={"field": field_name, "value": str(value)},
    )
