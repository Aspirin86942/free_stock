from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gmtrade_live.config import AppConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway


class FakeGMApi:
    def __init__(self) -> None:
        self.token = None
        self.account_id = None

    def set_token(self, token: str) -> None:
        self.token = token

    def set_account_id(self, account_id: str) -> None:
        self.account_id = account_id

    def get_cash(self, account_id: str | None = None) -> dict[str, object]:
        return {
            "account_id": account_id,
            "available": 20000.0,
            "market_value": 5000.0,
            "nav": 25000.0,
            "updated_at": datetime(2026, 4, 8, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
        }

    def get_position(self, account_id: str | None = None) -> list[dict[str, object]]:
        return [
            {
                "symbol": "SHSE.600000",
                "volume": 100,
                "available": 100,
                "cost": 1000.0,
                "updated_at": datetime(
                    2026,
                    4,
                    8,
                    10,
                    5,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
        ]

    def current(self, symbols: list[str], fields: str = "") -> list[dict[str, object]]:
        return [
            {
                "symbol": symbol,
                "price": 10.25,
                "created_at": datetime(
                    2026,
                    4,
                    8,
                    10,
                    5,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
            for symbol in symbols
        ]


class FakeGMApiEmptyCash(FakeGMApi):
    def get_cash(self, account_id: str | None = None) -> None:
        return None


def _build_config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m0",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        trade_session_start="09:30:00",
        trade_session_end="15:00:00",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="api.myquant.cn:9000",
    )


def test_gm_api_gateway_connects_and_maps_query_objects() -> None:
    api = FakeGMApi()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)
    cash = gateway.get_cash(config.account_id)
    positions = gateway.get_positions(config.account_id)

    assert api.token == "demo-token"
    assert api.account_id == "demo-account"
    assert cash.total_asset == Decimal("25000.00")
    assert cash.available_cash == Decimal("20000.00")
    assert cash.market_value == Decimal("5000.00")
    assert positions[0].symbol == "SHSE.600000"
    assert positions[0].available_volume == 100
    assert positions[0].cost_price == Decimal("10.000")


def test_gm_market_gateway_reads_quotes_from_current() -> None:
    api = FakeGMApi()
    gateway = GMCurrentQuoteGateway(api_module=api)

    gateway.connect("demo-token")
    quotes = gateway.get_quotes(["SHSE.600000"])

    assert api.token == "demo-token"
    assert quotes[0].symbol == "SHSE.600000"
    assert quotes[0].last_price == Decimal("10.250")
    assert quotes[0].source == "gm.current"


def test_gm_api_gateway_raises_empty_cash_when_sdk_returns_none() -> None:
    api = FakeGMApiEmptyCash()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)

    with pytest.raises(ServiceError) as exc_info:
        gateway.get_cash(config.account_id)

    assert exc_info.value.code == "gmtrade.empty_cash"
