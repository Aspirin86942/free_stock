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


class FakeGMTradeApi:
    def __init__(self) -> None:
        self.token = None
        self.endpoint = None
        self.logged_in_account = None

    def set_token(self, token: str) -> None:
        self.token = token

    def set_endpoint(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def account(self, account_id: str, account_alias: str) -> dict[str, str]:
        return {"account_id": account_id, "account_alias": account_alias}

    def login(self, account_object: dict[str, str]) -> None:
        self.logged_in_account = account_object

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


class FakeGMTradeOfficialApi:
    def __init__(self) -> None:
        self.token = None
        self.endpoint = None
        self.logged_in_account = None

    def set_token(self, token: str) -> None:
        self.token = token

    def set_endpoint(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def account(self, account_id: str, account_alias: str) -> dict[str, str]:
        return {"account_id": account_id, "account_alias": account_alias}

    def login(self, account_object: dict[str, str]) -> None:
        self.logged_in_account = account_object

    def get_cash(self, account: dict[str, str] | None = None) -> dict[str, object]:
        return {
            "account_id": account["account_id"] if account else "unknown",
            "available": 12345.67,
            "market_value": 6543.21,
            "nav": 18888.88,
            "updated_at": datetime(2026, 4, 8, 10, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        }

    def get_positions(self, account: dict[str, str] | None = None) -> list[dict[str, object]]:
        return [
            {
                "symbol": "SHSE.600519",
                "volume": 10,
                "available": 10,
                "cost": 15000.0,
                "updated_at": datetime(
                    2026,
                    4,
                    8,
                    10,
                    7,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
        ]


class FakeGMTradeEmptyCashApi(FakeGMTradeOfficialApi):
    def get_cash(self, account: dict[str, str] | None = None) -> None:
        return None


class FakeGMApi:
    def __init__(self) -> None:
        self.token = None

    def set_token(self, token: str) -> None:
        self.token = token

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


class FakeGMApiTrade:
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
            "available": 8888.8,
            "market_value": 1111.2,
            "nav": 10000.0,
            "updated_at": datetime(2026, 4, 8, 10, 6, tzinfo=ZoneInfo("Asia/Shanghai")),
        }

    def get_position(self, account_id: str | None = None) -> list[dict[str, object]]:
        return [
            {
                "symbol": "SZSE.000001",
                "volume": 200,
                "available": 120,
                "cost": 2460.0,
                "updated_at": datetime(
                    2026,
                    4,
                    8,
                    10,
                    6,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
        ]


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


def test_gmtrade_gateway_connects_and_maps_query_objects() -> None:
    api = FakeGMTradeApi()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)
    cash = gateway.get_cash(config.account_id)
    positions = gateway.get_positions(config.account_id)

    assert api.token == "demo-token"
    assert api.endpoint == "api.myquant.cn:9000"
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


def test_gmtrade_gateway_supports_real_gmtrade_method_shapes() -> None:
    api = FakeGMTradeOfficialApi()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)
    cash = gateway.get_cash(config.account_id)
    positions = gateway.get_positions(config.account_id)

    assert api.logged_in_account == {
        "account_id": "demo-account",
        "account_alias": "gmtrade-live-m0",
    }
    assert cash.total_asset == Decimal("18888.88")
    assert positions[0].symbol == "SHSE.600519"
    assert positions[0].cost_price == Decimal("1500.000")


def test_gmtrade_gateway_supports_gm_api_query_backend() -> None:
    api = FakeGMApiTrade()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)
    cash = gateway.get_cash(config.account_id)
    positions = gateway.get_positions(config.account_id)

    assert api.token == "demo-token"
    assert api.account_id == "demo-account"
    assert cash.available_cash == Decimal("8888.80")
    assert cash.total_asset == Decimal("10000.00")
    assert positions[0].symbol == "SZSE.000001"
    assert positions[0].available_volume == 120
    assert positions[0].cost_price == Decimal("12.300")


def test_gmtrade_gateway_raises_empty_cash_when_sdk_returns_none() -> None:
    api = FakeGMTradeEmptyCashApi()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)

    with pytest.raises(ServiceError) as exc_info:
        gateway.get_cash(config.account_id)

    assert exc_info.value.code == "gmtrade.empty_cash"
