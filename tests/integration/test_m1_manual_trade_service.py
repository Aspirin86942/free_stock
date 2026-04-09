from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from threading import Thread
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.callback_handler import CallbackHandler
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway
from gmtrade_live.services.m1_manual_trade import ManualTradeService


class FakeGMApi:
    def __init__(self) -> None:
        self.token = None
        self.serv_addr = None
        self.account_id = None
        self.order_callback = None
        self.execution_report_callback = None

    def set_token(self, token: str) -> None:
        self.token = token

    def set_serv_addr(self, addr: str) -> None:
        self.serv_addr = addr

    def set_account_id(self, account_id: str) -> None:
        self.account_id = account_id

    def set_order_callback(self, callback) -> None:
        self.order_callback = callback

    def set_execution_report_callback(self, callback) -> None:
        self.execution_report_callback = callback

    def order_volume(self, **kwargs: object) -> list[SimpleNamespace]:
        def emit_callbacks() -> None:
            time.sleep(0.05)
            assert self.order_callback is not None
            self.order_callback(
                SimpleNamespace(
                    cl_ord_id="ORDER_1",
                    symbol=kwargs["symbol"],
                    status=3,
                    filled_volume=kwargs["volume"],
                    volume=kwargs["volume"],
                    ord_rej_reason_detail="",
                    created_at=datetime(
                        2026,
                        4,
                        9,
                        10,
                        30,
                        tzinfo=ZoneInfo("Asia/Shanghai"),
                    ),
                )
            )
            time.sleep(0.05)
            assert self.execution_report_callback is not None
            self.execution_report_callback(
                SimpleNamespace(
                    cl_ord_id="ORDER_1",
                    symbol=kwargs["symbol"],
                    volume=kwargs["volume"],
                    price=10.45,
                    created_at=datetime(
                        2026,
                        4,
                        9,
                        10,
                        30,
                        tzinfo=ZoneInfo("Asia/Shanghai"),
                    ),
                )
            )

        Thread(target=emit_callbacks, daemon=True).start()
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


def test_m1_manual_trade_fake_sdk_integration() -> None:
    api = FakeGMApi()
    gateway = GMTradeQueryGateway(api_module=api, account_id="demo-account")
    callback_handler = CallbackHandler(logging.getLogger("test"))
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=callback_handler,
        logger=logging.getLogger("test"),
    )
    config = _build_config()

    gateway.connect(config)
    gateway.set_callback_handler(callback_handler)
    report = service.run(
        config=config,
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    assert report.verification_passed is True
    assert report.order_event_received is True
    assert report.execution_event_received is True
    assert report.filled_volume == 100
    assert report.avg_price == Decimal("10.450")
