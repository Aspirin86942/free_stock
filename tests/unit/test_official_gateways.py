from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from gm.enum import (
    OrderSide_Buy,
    OrderSide_Sell,
    PositionEffect_Close,
    PositionEffect_Open,
)

from gmtrade_live.config import AppConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway
from gmtrade_live.models import OrderRequest


class FakeGMApi:
    def __init__(self) -> None:
        self.token = None
        self.serv_addr = None
        self.account_id = None
        self.last_order_kwargs = None

    def set_token(self, token: str) -> None:
        self.token = token

    def set_serv_addr(self, addr: str) -> None:
        self.serv_addr = addr

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

    def order_volume(self, **kwargs: object) -> list[SimpleNamespace]:
        self.last_order_kwargs = kwargs
        return [
            SimpleNamespace(
                cl_ord_id="ORDER_1",
                symbol=kwargs["symbol"],
                status=1,
                ord_rej_reason_detail="",
                created_at=datetime(
                    2026,
                    4,
                    9,
                    10,
                    6,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            )
        ]


class FakeGMApiEmptyCash(FakeGMApi):
    def get_cash(self, account_id: str | None = None) -> None:
        return None


class FakeGMApiNoTimestamp(FakeGMApi):
    """模拟真实 gm.api 返回的数据（没有时间字段）"""

    def get_cash(self, account_id: str | None = None) -> dict[str, object]:
        return {
            "account_id": account_id,
            "available": 7575683.895145463,
            "balance": 7575683.895145463,
            "market_value": 2226796.0384368896,
            "nav": 9802479.933582352,
        }

    def get_position(self, account_id: str | None = None) -> list[dict[str, object]]:
        return [
            {
                "symbol": "SHSE.600839",
                "volume": 251900,
                "available": 251900,
                "vwap": 10.019,
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


def test_gm_api_gateway_connects_and_maps_query_objects() -> None:
    api = FakeGMApi()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)
    cash = gateway.get_cash(config.account_id)
    positions = gateway.get_positions(config.account_id)

    assert api.token == "demo-token"
    assert api.serv_addr == "api.myquant.cn:9000"
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


def test_gm_api_gateway_handles_missing_timestamp_fields() -> None:
    """测试真实 gm.api 返回数据（没有时间字段）"""
    api = FakeGMApiNoTimestamp()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)
    cash = gateway.get_cash(config.account_id)
    positions = gateway.get_positions(config.account_id)

    # 验证资金数据
    assert cash.account_id == "demo-account"
    assert cash.available_cash == Decimal("7575683.90")
    assert cash.market_value == Decimal("2226796.04")
    assert cash.total_asset == Decimal("9802479.93")
    assert cash.update_time is not None  # 应该使用当前时间

    # 验证持仓数据
    assert len(positions) == 1
    assert positions[0].symbol == "SHSE.600839"
    assert positions[0].volume == 251900
    assert positions[0].available_volume == 251900
    assert positions[0].cost_price == Decimal("10.019")
    assert positions[0].last_update_time is not None  # 应该使用当前时间


def test_gm_api_gateway_submits_order_via_query_driven_path() -> None:
    api = FakeGMApi()
    gateway = GMTradeQueryGateway(api_module=api, account_id="demo-account")
    config = _build_config()

    gateway.connect(config)
    result = gateway.submit_order(
        OrderRequest(
            symbol="SHSE.600036",
            volume=100,
            side="sell",
            price_type="market",
            price=None,
        )
    )

    assert api.token == "demo-token"
    assert api.serv_addr == "api.myquant.cn:9000"
    # connect() 不应在 M0/M1 查询链路里全局绑定账户，否则会把 gm SDK 全局状态带进后续调用。
    assert api.account_id is None
    assert api.last_order_kwargs is not None
    assert api.last_order_kwargs["symbol"] == "SHSE.600036"
    assert api.last_order_kwargs["volume"] == 100
    assert api.last_order_kwargs["account"] == "demo-account"
    assert api.last_order_kwargs["side"] == OrderSide_Sell
    assert api.last_order_kwargs["position_effect"] == PositionEffect_Close
    assert result.accepted is True
    assert result.cl_ord_id == "ORDER_1"
    assert result.broker_order_id is None


def test_gm_api_gateway_submits_buy_order_via_query_driven_path() -> None:
    api = FakeGMApi()
    gateway = GMTradeQueryGateway(api_module=api, account_id="demo-account")
    config = _build_config()

    gateway.connect(config)
    result = gateway.submit_order(
        OrderRequest(
            symbol="SHSE.600036",
            volume=100,
            side="buy",
            price_type="market",
            price=None,
        )
    )

    assert api.last_order_kwargs is not None
    assert api.last_order_kwargs["account"] == "demo-account"
    assert api.last_order_kwargs["side"] == OrderSide_Buy
    assert api.last_order_kwargs["position_effect"] == PositionEffect_Open
    assert result.accepted is True
    assert result.cl_ord_id == "ORDER_1"


def test_gm_api_gateway_filters_order_status_by_cl_ord_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = GMTradeQueryGateway(api_module=FakeGMApi(), account_id="demo-account")

    monkeypatch.setattr(
        "gmtrade_live.gateways.gmtrade_trade_gateway._fetch_orders",
        lambda **kwargs: [
            {
                "cl_ord_id": "OTHER_ORDER",
                "order_id": "BROKER_OLD",
                "symbol": "SHSE.600036",
                "status": 8,
                "filled_volume": 0,
                "volume": 100,
                "ord_rej_reason_detail": "old_rejected",
                "updated_at": datetime(
                    2026,
                    4,
                    9,
                    10,
                    7,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            },
            {
                "cl_ord_id": "ORDER_1",
                "order_id": "BROKER_1",
                "symbol": "SHSE.600036",
                "status": 3,
                "filled_volume": 100,
                "volume": 100,
                "ord_rej_reason_detail": "",
                "updated_at": datetime(
                    2026,
                    4,
                    9,
                    10,
                    8,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            },
        ],
    )

    snapshot = gateway.query_order_status("ORDER_1", "SHSE.600036")

    assert snapshot is not None
    assert snapshot.cl_ord_id == "ORDER_1"
    assert snapshot.broker_order_id == "BROKER_1"
    assert snapshot.status == "filled"
    assert snapshot.rejection_reason is None


def test_gm_api_gateway_filters_execution_reports_by_cl_ord_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = GMTradeQueryGateway(api_module=FakeGMApi(), account_id="demo-account")

    monkeypatch.setattr(
        "gmtrade_live.gateways.gmtrade_trade_gateway._fetch_execution_reports",
        lambda **kwargs: [
            {
                "cl_ord_id": "ORDER_1",
                "order_id": "BROKER_1",
                "symbol": "SHSE.600036",
                "volume": 100,
                "price": 10.45,
                "created_at": datetime(
                    2026,
                    4,
                    9,
                    10,
                    8,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            },
            {
                "cl_ord_id": "OTHER_ORDER",
                "order_id": "BROKER_OLD",
                "symbol": "SHSE.600839",
                "volume": 100,
                "price": 8.70,
                "created_at": datetime(
                    2026,
                    4,
                    9,
                    10,
                    7,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            },
        ],
    )

    snapshots = gateway.query_execution_reports("ORDER_1")

    assert len(snapshots) == 1
    assert snapshots[0].cl_ord_id == "ORDER_1"
    assert snapshots[0].broker_order_id == "BROKER_1"
    assert snapshots[0].symbol == "SHSE.600036"
    assert snapshots[0].filled_volume == 100
    assert snapshots[0].avg_price == Decimal("10.450")
