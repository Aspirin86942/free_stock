from __future__ import annotations

from datetime import datetime
import importlib
from typing import Any

from gmtrade_live.errors import ServiceError
from gmtrade_live.models import QuoteSnapshot
from gmtrade_live.precision import normalize_price


class GMCurrentQuoteGateway:
    def __init__(self, api_module: Any | None = None) -> None:
        self._api = api_module or importlib.import_module("gm.api")

    def connect(self, token: str) -> None:
        self._api.set_token(token)

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
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
    if isinstance(value, datetime):
        return value
    raise ServiceError(
        code="gm.invalid_datetime",
        message="行情时间字段格式不合法",
        retryable=True,
        context={"field": field_name, "value": str(value)},
    )
