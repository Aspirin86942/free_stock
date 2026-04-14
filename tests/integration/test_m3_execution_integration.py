from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    OrderExecutionSnapshot,
    OrderStatusSnapshot,
    OrderSubmitResult,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.services.m3_execution_service import M3ExecutionService
from gmtrade_live.services.m3_state_manager import (
    M3ExecutionState,
    M3PositionStateManager,
)
from gmtrade_live.services.position_decision_state import PositionDecisionStateStore
from gmtrade_live.services.sell_decision_engine import SellDecisionEngine


def _now() -> datetime:
    return datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config(*, ratio: str = "1.0") -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal(ratio),
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


def _position(symbol: str = "SZSE.002594") -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        exchange=symbol.split(".", maxsplit=1)[0],
        volume=200,
        available_volume=200,
        cost_price=Decimal("10.00"),
        last_update_time=_now(),
    )


def _quote(symbol: str = "SZSE.002594") -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        last_price=Decimal("10.80"),
        quote_time=_now(),
        source="fake",
    )


def _execution(
    filled_volume: int,
    *,
    symbol: str = "SZSE.002594",
) -> OrderExecutionSnapshot:
    return OrderExecutionSnapshot(
        cl_ord_id="CL_1",
        broker_order_id="BK_1",
        symbol=symbol,
        filled_volume=filled_volume,
        avg_price=Decimal("10.80"),
        event_time=_now(),
    )


class FakeTimer:
    def __init__(self, values: list[float]) -> None:
        self._values = values
        self._index = 0

    def __call__(self) -> float:
        if self._index < len(self._values):
            value = self._values[self._index]
            self._index += 1
            return value
        return self._values[-1]


class SequencedTradeGateway:
    def __init__(
        self,
        *,
        positions: tuple[PositionSnapshot, ...] | None = None,
        order_statuses: list[tuple[str, int, int, str | None]] | None = None,
        execution_reports: list[tuple[OrderExecutionSnapshot, ...]] | None = None,
    ) -> None:
        self.positions = positions or (_position(),)
        self.order_statuses = order_statuses or [("filled", 200, 0, "BK_1")]
        self.execution_reports = execution_reports or [(_execution(200),)]
        self.submit_calls = 0
        self.query_order_status_calls = 0
        self._last_query_index = 0

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return list(self.positions)

    def submit_order(self, request):
        self.submit_calls += 1
        return OrderSubmitResult(
            accepted=True,
            cl_ord_id="CL_1",
            broker_order_id="BK_1",
            symbol=request.symbol,
            message="accepted",
            raw_status="1",
            event_time=_now(),
        )

    def query_order_status(self, cl_ord_id: str, symbol: str):
        index = min(self.query_order_status_calls, len(self.order_statuses) - 1)
        self.query_order_status_calls += 1
        self._last_query_index = index
        status, filled_volume, remaining_volume, broker_order_id = self.order_statuses[
            index
        ]
        return OrderStatusSnapshot(
            cl_ord_id=cl_ord_id,
            broker_order_id=broker_order_id,
            symbol=symbol,
            status=status,
            filled_volume=filled_volume,
            remaining_volume=remaining_volume,
            rejection_reason=None,
            event_time=_now(),
        )

    def query_execution_reports(self, cl_ord_id: str):
        index = min(self._last_query_index, len(self.execution_reports) - 1)
        return self.execution_reports[index]


class FakeMarketGateway:
    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        return [_quote(symbol) for symbol in symbols]


def test_m3_once_round_keeps_polling_until_budget_exhausted_or_order_finishes() -> None:
    service = M3ExecutionService(
        trade_gateway=SequencedTradeGateway(
            order_statuses=[
                ("pending_new", 0, 0, "BK_1"),
                ("partially_filled", 100, 100, "BK_1"),
                ("filled", 200, 0, "BK_1"),
            ],
            execution_reports=[
                (),
                (_execution(100),),
                (_execution(200),),
            ],
        ),
        market_gateway=FakeMarketGateway(),
        decision_state_manager=PositionDecisionStateStore(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=SellDecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 0.2, 0.7, 0.8, 1.3, 1.4]),
        sleep=lambda seconds: None,
    )

    report = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=5)

    assert report.summary.submitted_count == 1
    assert report.summary.open_order_count == 0
    assert report.execution_details[-1].execution_state == "filled"
    assert report.execution_details[-1].decision_trigger_reason == "take_profit_triggered"


def test_open_order_continues_in_next_round_after_timeout() -> None:
    trade_gateway = SequencedTradeGateway(
        order_statuses=[
            ("pending_new", 0, 0, "BK_1"),
            ("filled", 200, 0, "BK_1"),
        ],
        execution_reports=[
            (),
            (_execution(200),),
        ],
    )
    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=FakeMarketGateway(),
        decision_state_manager=PositionDecisionStateStore(logging.getLogger("test")),
        execution_state_manager=M3PositionStateManager(logger=None),
        decision_engine=SellDecisionEngine(),
        logger=logging.getLogger("test"),
        clock=_now,
        timer=FakeTimer([0.0, 0.1, 1.2, 2.0, 2.1, 2.2]),
        sleep=lambda seconds: None,
    )

    first_round = service.run_round(config=_config(), round_no=1, reconcile_timeout_seconds=1)
    second_round = service.run_round(config=_config(), round_no=2, reconcile_timeout_seconds=5)

    assert first_round.summary.submitted_count == 1
    assert first_round.summary.open_order_count == 1
    assert second_round.summary.submitted_count == 0
    assert second_round.execution_details[-1].execution_state == "filled"
    assert second_round.execution_details[-1].filled_volume == 200
    assert trade_gateway.submit_calls == 1
    assert (
        service._execution_state_manager.get_state("SZSE.002594").state
        is M3ExecutionState.filled
    )
