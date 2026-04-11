from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import CashSnapshot, PositionSnapshot, QuoteSnapshot
from gmtrade_live.services.m0_connectivity import ConnectivityCheckService
from gmtrade_live.session import TradingSessionState


class FakeTradeGateway:
    def connect(self, config: AppConfig) -> None:
        self.account_id = config.account_id

    def get_cash(self, account_id: str) -> CashSnapshot:
        return CashSnapshot(
            account_id=account_id,
            available_cash=Decimal("100000.00"),
            market_value=Decimal("12000.00"),
            total_asset=Decimal("112000.00"),
            update_time=datetime(2026, 4, 8, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SHSE.600000",
                exchange="SHSE",
                volume=100,
                available_volume=100,
                cost_price=Decimal("10.01"),
                last_update_time=datetime(
                    2026,
                    4,
                    8,
                    10,
                    1,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            )
        ]


class FakeMarketGateway:
    def connect(self, token: str) -> None:
        self.token = token

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        return [
            QuoteSnapshot(
                symbol=symbol,
                last_price=Decimal("10.15"),
                quote_time=datetime(2026, 4, 8, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
                source="gm.current",
            )
            for symbol in symbols
        ]


def test_connectivity_service_reads_cash_positions_and_quotes(tmp_path: Path) -> None:
    config = AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m0",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal("1.0"),
        market_session_mode="a_share",
        log_dir=tmp_path,
        timezone="Asia/Shanghai",
        gmtrade_endpoint="api.myquant.cn:9000",
    )
    logger = logging.getLogger("gmtrade-live-m0-test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())

    service = ConnectivityCheckService(
        trade_gateway=FakeTradeGateway(),
        market_gateway=FakeMarketGateway(),
        logger=logger,
    )

    report = service.run(config=config, session_state=TradingSessionState.TRADING)

    assert report.account_id == "demo-account"
    assert report.session_state == "trading"
    assert report.cash.available_cash == Decimal("100000.00")
    assert len(report.positions) == 1
    assert report.positions[0].symbol == "SHSE.600000"
    assert len(report.quotes) == 1
    assert report.quotes[0].last_price == Decimal("10.15")
