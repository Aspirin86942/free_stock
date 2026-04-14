from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import (
    CashSnapshot,
    ConnectivityReport,
    PositionSnapshot,
    QuoteSnapshot,
)
from tools.debug.check_connectivity import build_connectivity_summary


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
