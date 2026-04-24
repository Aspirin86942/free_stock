from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    CashSnapshot,
    ConnectivityReport,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.session import TradingSessionState
from tools.debug import check_connectivity
from tools.debug.check_connectivity import build_connectivity_summary, run_connectivity_check


def test_ensure_local_src_on_path_adds_repo_src_when_package_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name == "gmtrade_live" else object())
    monkeypatch.setattr(sys, "path", ["C:\\dummy"])

    check_connectivity._ensure_local_src_on_path()

    assert sys.path[0] == str(Path(check_connectivity.__file__).resolve().parents[2] / "src")


def test_build_connectivity_summary_returns_payload() -> None:
    report = ConnectivityReport(
        account_id="demo-account",
        session_state="trading",
        cash=CashSnapshot(
            account_id="demo-account",
            available_cash=Decimal("100.00"),
            market_value=Decimal("200.00"),
            total_asset=Decimal("300.00"),
            update_time=datetime(2026, 4, 10, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        ),
        positions=(
            PositionSnapshot(
                symbol="SHSE.600000",
                exchange="SHSE",
                volume=100,
                available_volume=100,
                cost_price=Decimal("10.00"),
                last_update_time=datetime(
                    2026,
                    4,
                    10,
                    9,
                    30,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            ),
        ),
        quotes=(
            QuoteSnapshot(
                symbol="SHSE.600000",
                last_price=Decimal("10.10"),
                quote_time=datetime(2026, 4, 10, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
                source="gm.current",
            ),
        ),
    )

    payload = build_connectivity_summary(report)

    assert payload["account_id"] == "demo-account"
    assert payload["position_count"] == 1
    assert payload["quote_count"] == 1


def test_run_connectivity_check_calls_gateways_and_filters_symbols() -> None:
    class FakeTradeGateway:
        def __init__(self) -> None:
            self.connect_called = False
            self.account_id = None

        def connect(self, config: AppConfig) -> None:
            self.connect_called = True
            self.account_id = config.account_id

        def get_cash(self, account_id: str) -> CashSnapshot:
            return CashSnapshot(
                account_id=account_id,
                available_cash=Decimal("100.00"),
                market_value=Decimal("200.00"),
                total_asset=Decimal("300.00"),
                update_time=datetime(2026, 4, 10, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            )

        def get_positions(self, account_id: str) -> list[PositionSnapshot]:
            return [
                PositionSnapshot(
                    symbol="SHSE.600000",
                    exchange="SHSE",
                    volume=100,
                    available_volume=100,
                    cost_price=Decimal("10.00"),
                    last_update_time=datetime(
                        2026,
                        4,
                        10,
                        9,
                        30,
                        tzinfo=ZoneInfo("Asia/Shanghai"),
                    ),
                ),
                PositionSnapshot(
                    symbol="SHSE.600001",
                    exchange="SHSE",
                    volume=100,
                    available_volume=0,
                    cost_price=Decimal("10.00"),
                    last_update_time=datetime(
                        2026,
                        4,
                        10,
                        9,
                        30,
                        tzinfo=ZoneInfo("Asia/Shanghai"),
                    ),
                ),
            ]

    class FakeMarketGateway:
        def __init__(self) -> None:
            self.connect_called = False
            self.last_symbols = None

        def connect(self, token: str) -> None:
            self.connect_called = True

        def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
            self.last_symbols = list(symbols)
            return [
                QuoteSnapshot(
                    symbol=symbols[0],
                    last_price=Decimal("10.10"),
                    quote_time=datetime(
                        2026,
                        4,
                        10,
                        9,
                        31,
                        tzinfo=ZoneInfo("Asia/Shanghai"),
                    ),
                    source="gm.current",
                )
            ]

    config = AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-auto-sell",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal("1.0"),
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )
    logger = SimpleNamespace(info=lambda *a, **k: None)
    trade_gateway = FakeTradeGateway()
    market_gateway = FakeMarketGateway()

    report = run_connectivity_check(
        config=config,
        session_state=TradingSessionState.TRADING,
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        logger=logger,
    )

    assert trade_gateway.connect_called is True
    assert market_gateway.connect_called is True
    assert market_gateway.last_symbols == ["SHSE.600000"]
    assert report.account_id == "demo-account"
