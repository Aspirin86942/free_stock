from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
import gmtrade_live.gateways.gmtrade_trade_gateway as gateway_module
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway
from gmtrade_live.services.m1_manual_trade import ManualTradeService


class FakeGMApi:
    def __init__(self) -> None:
        self.token = None
        self.serv_addr = None

    def set_token(self, token: str) -> None:
        self.token = token

    def set_serv_addr(self, addr: str) -> None:
        self.serv_addr = addr

    def order_volume(self, **kwargs: object) -> list[SimpleNamespace]:
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
                    29,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            )
        ]

    def get_orders_mm(
        self,
        *,
        symbol: str,
        order_ids: str,
        account_id: str,
    ) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                cl_ord_id=order_ids,
                order_id="BROKER_1",
                symbol=symbol,
                status=3,
                filled_volume=100,
                volume=100,
                ord_rej_reason_detail="",
                updated_at=datetime(
                    2026,
                    4,
                    9,
                    10,
                    30,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            )
        ]


def _build_config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m1",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        trade_session_start="09:30:00",
        trade_session_end="15:00:00",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


def test_m1_manual_trade_fake_sdk_integration(monkeypatch) -> None:
    api = FakeGMApi()
    gateway = GMTradeQueryGateway(api_module=api, account_id="demo-account")
    monkeypatch.setattr(
        gateway_module,
        "_fetch_execution_reports",
        lambda *, account_id, cl_ord_id: [
            {
                "cl_ord_id": cl_ord_id,
                "order_id": "BROKER_1",
                "symbol": "SHSE.600036",
                "volume": 100,
                "price": Decimal("10.45"),
                "created_at": datetime(
                    2026,
                    4,
                    9,
                    10,
                    30,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
        ],
    )
    service = ManualTradeService(
        trade_gateway=gateway,
        logger=logging.getLogger("test"),
    )
    config = _build_config()

    gateway.connect(config)
    report = service.run(
        config=config,
        side="sell",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    assert report.verification_passed is True
    assert report.order_status_confirmed is True
    assert report.execution_status_confirmed is True
    assert report.filled_volume == 100
    assert report.avg_price == Decimal("10.450")


def test_m1_manual_trade_fake_sdk_buy_integration(monkeypatch) -> None:
    api = FakeGMApi()
    gateway = GMTradeQueryGateway(api_module=api, account_id="demo-account")
    monkeypatch.setattr(
        gateway_module,
        "_fetch_execution_reports",
        lambda *, account_id, cl_ord_id: [
            {
                "cl_ord_id": cl_ord_id,
                "order_id": "BROKER_1",
                "symbol": "SHSE.600036",
                "volume": 100,
                "price": Decimal("10.45"),
                "created_at": datetime(
                    2026,
                    4,
                    9,
                    10,
                    30,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
        ],
    )
    service = ManualTradeService(
        trade_gateway=gateway,
        logger=logging.getLogger("test"),
    )
    config = _build_config()

    gateway.connect(config)
    report = service.run(
        config=config,
        side="buy",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    assert report.side == "buy"
    assert report.verification_passed is True
    assert report.execution_status_confirmed is True
