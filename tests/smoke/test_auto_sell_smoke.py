"""基础 smoke 门禁，确保决策观测与自动卖出在本地可跑并生成关键日志。"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gmtrade_live import app_runner
from gmtrade_live.models import (
    OrderExecutionSnapshot,
    OrderRequest,
    OrderStatusSnapshot,
    OrderSubmitResult,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.session import TradingSessionState

BASE_TIME = datetime(2026, 4, 13, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class FakeTimer:
    """保证观测/卖出计算调用间隔时使用可控值，避免依赖真实系统时间。"""

    def __init__(self, *, start: float = 0.0) -> None:
        self._value = start

    def __call__(self) -> float:
        return self._value

    def advance(self, amount: float) -> None:
        self._value += amount


class FakeTradeGateway:
    def __init__(
        self,
        positions: tuple[PositionSnapshot, ...],
        submit_result: OrderSubmitResult,
        order_status: OrderStatusSnapshot,
        execution_reports: tuple[OrderExecutionSnapshot, ...],
    ) -> None:
        self._positions = positions
        self._submit_result = submit_result
        self._order_status = order_status
        self._execution_reports = execution_reports
        self.account_id: str | None = None
        self._submitted_request: OrderRequest | None = None

    def connect(self, config) -> None:
        self.account_id = config.account_id

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        assert self.account_id == account_id
        return list(self._positions)

    def submit_order(self, request: OrderRequest) -> OrderSubmitResult:
        assert request.symbol == self._submit_result.symbol
        assert request.side == "sell"
        assert request.volume == self._order_status.filled_volume
        self._submitted_request = request
        return self._submit_result

    def query_order_status(
        self,
        cl_ord_id: str,
        symbol: str,
    ) -> OrderStatusSnapshot | None:
        assert self._submitted_request is not None
        assert cl_ord_id == self._submit_result.cl_ord_id
        assert cl_ord_id == self._order_status.cl_ord_id
        assert symbol == self._submitted_request.symbol
        assert symbol == self._order_status.symbol
        return self._order_status

    def query_execution_reports(self, cl_ord_id: str) -> tuple[OrderExecutionSnapshot, ...]:
        assert self._submitted_request is not None
        assert cl_ord_id == self._submit_result.cl_ord_id
        assert all(report.cl_ord_id == cl_ord_id for report in self._execution_reports)
        return self._execution_reports


class FakeMarketGateway:
    def __init__(self, quotes: tuple[QuoteSnapshot, ...]) -> None:
        self._quotes = quotes

    def connect(self, token: str) -> None:
        self.token = token

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        return [quote for quote in self._quotes if quote.symbol in symbols]


def _write_smoke_config(tmp_path: Path, log_dir: Path) -> Path:
    """
    生成独立配置，确保 log_dir 可控且不和主线测试冲突。
    """

    config_path = tmp_path / f"auto_sell_smoke_{log_dir.name}.yaml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            account_id: smoke_account
            token: smoke_token
            strategy_name: gmtrade-live-auto-sell
            poll_interval_seconds: 1
            take_profit_ratio: 0.05
            stop_loss_ratio: 0.03
            sell_quantity_ratio: 1.0
            market_session_mode: a_share
            log_dir: {log_dir.as_posix()}
            timezone: Asia/Shanghai
            gmtrade_endpoint: 127.0.0.1:7001
            """
        ).strip(),
        encoding="utf-8",
    )
    return config_path


def _patch_decision_service(monkeypatch, *, clock, timer: FakeTimer) -> None:
    """替换 SellCandidatePipeline，稳定 clock/timer 输出，便于 smoke 在任意时间快速重复跑。

    注意：当前 run_decision_observer() 的接线是 SellCandidatePipeline + DecisionObserverService，
    smoke 只需要在新的接线点注入稳定时间即可，不应恢复旧 dry-run API。
    """

    class StablePipeline(app_runner.SellCandidatePipeline):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("clock", clock)
            kwargs.setdefault("timer", timer)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(app_runner, "SellCandidatePipeline", StablePipeline)


def _patch_auto_sell_service(monkeypatch, *, clock, timer: FakeTimer, sleep) -> None:
    """替换 M3ExecutionService，稳定 clock/timer/sleep，避免莫名的等待或跳动。"""

    class StablePipeline(app_runner.SellCandidatePipeline):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("clock", clock)
            kwargs.setdefault("timer", timer)
            super().__init__(*args, **kwargs)

    class StableM3Service(app_runner.M3ExecutionService):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("clock", clock)
            kwargs.setdefault("timer", timer)
            kwargs.setdefault("sleep", sleep)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(app_runner, "SellCandidatePipeline", StablePipeline)
    monkeypatch.setattr(app_runner, "M3ExecutionService", StableM3Service)


def _patch_sess_state(monkeypatch) -> None:
    """让 smoke 固定会话态为 TRADING，避免运行时依赖真实时间。"""

    monkeypatch.setattr(
        app_runner,
        "_resolve_current_session_state",
        lambda config: TradingSessionState.TRADING,
    )


def _build_position() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="SHSE.600000",
        exchange="SHSE",
        volume=100,
        available_volume=100,
        cost_price=Decimal("10"),
        last_update_time=BASE_TIME,
    )


def _build_quote() -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol="SHSE.600000",
        last_price=Decimal("20"),
        quote_time=BASE_TIME,
        source="smoke",
    )


def _build_order_submit_result() -> OrderSubmitResult:
    return OrderSubmitResult(
        accepted=True,
        cl_ord_id="cl-smoke-1",
        broker_order_id="broker-smoke-1",
        symbol="SHSE.600000",
        message="accepted",
        raw_status="1",
        event_time=BASE_TIME,
    )


def _build_order_status_snapshot() -> OrderStatusSnapshot:
    return OrderStatusSnapshot(
        cl_ord_id="cl-smoke-1",
        broker_order_id="broker-smoke-1",
        symbol="SHSE.600000",
        status="filled",
        filled_volume=100,
        remaining_volume=0,
        rejection_reason=None,
        event_time=BASE_TIME + timedelta(seconds=1),
    )


def _build_order_execution_snapshots() -> tuple[OrderExecutionSnapshot, ...]:
    snapshot = OrderExecutionSnapshot(
        cl_ord_id="cl-smoke-1",
        broker_order_id="broker-smoke-1",
        symbol="SHSE.600000",
        filled_volume=100,
        avg_price=Decimal("12"),
        event_time=BASE_TIME + timedelta(seconds=1),
    )
    return (snapshot,)


def _filter_execution_details(output: str) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    for raw_line in output.splitlines():
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if payload.get("kind") == "sell_execution_detail":
            details.append(payload)
    return details


def _load_json_lines(raw_text: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for raw_line in raw_text.splitlines():
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _find_terminal_detail(details: list[dict[str, object]]) -> dict[str, object] | None:
    for detail in details:
        terminal_state_at = detail.get("terminal_state_at")
        if isinstance(terminal_state_at, str) and terminal_state_at:
            return detail
    return None


@pytest.mark.usefixtures("tmp_path")
def test_local_decision_observer_smoke_emits_summary_and_runtime_log(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    log_dir = tmp_path / "logs_decision"
    config_path = _write_smoke_config(tmp_path, log_dir)
    _patch_sess_state(monkeypatch)
    timer = FakeTimer()
    _patch_decision_service(monkeypatch, clock=lambda: BASE_TIME, timer=timer)

    trade_gateway = FakeTradeGateway(
        positions=( _build_position(), ),
        submit_result=_build_order_submit_result(),
        order_status=_build_order_status_snapshot(),
        execution_reports=_build_order_execution_snapshots(),
    )
    market_gateway = FakeMarketGateway(quotes=(_build_quote(),))

    monkeypatch.setattr(app_runner, "GMTradeGateway", lambda *args, **kwargs: trade_gateway)
    monkeypatch.setattr(
        app_runner,
        "GMCurrentQuoteGateway",
        lambda *args, **kwargs: market_gateway,
    )

    exit_code = app_runner.run_decision_observer(
        config_path=config_path,
        once=True,
        max_rounds=None,
    )
    captured = capsys.readouterr()
    runtime_log = (log_dir / "runtime.log").read_text(encoding="utf-8")

    assert exit_code == 0
    assert "decision_round_summary" in captured.out
    assert "round_started entry=decision_observer" in runtime_log
    assert "round_completed entry=decision_observer" in runtime_log


@pytest.mark.usefixtures("tmp_path")
def test_local_auto_sell_smoke_emits_audit_log_and_latency(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    log_dir = tmp_path / "logs_auto_sell"
    config_path = _write_smoke_config(tmp_path, log_dir)
    _patch_sess_state(monkeypatch)
    timer = FakeTimer()
    _patch_auto_sell_service(
        monkeypatch,
        clock=lambda: BASE_TIME,
        timer=timer,
        sleep=lambda _: timer.advance(0.001),
    )

    trade_gateway = FakeTradeGateway(
        positions=( _build_position(), ),
        submit_result=_build_order_submit_result(),
        order_status=_build_order_status_snapshot(),
        execution_reports=_build_order_execution_snapshots(),
    )
    market_gateway = FakeMarketGateway(quotes=(_build_quote(),))

    monkeypatch.setattr(app_runner, "GMTradeGateway", lambda *args, **kwargs: trade_gateway)
    monkeypatch.setattr(
        app_runner,
        "GMCurrentQuoteGateway",
        lambda *args, **kwargs: market_gateway,
    )

    exit_code = app_runner.run_auto_sell(
        config_path=config_path,
        once=True,
        max_rounds=None,
        reconcile_timeout_seconds=3,
    )
    captured = capsys.readouterr()
    details = _filter_execution_details(captured.out)
    terminal_detail = _find_terminal_detail(details)
    runtime_log = (log_dir / "runtime.log").read_text(encoding="utf-8")
    order_audit = (log_dir / "order_audit.log").read_text(encoding="utf-8")
    audit_events = _load_json_lines(order_audit)
    submit_events = [
        event for event in audit_events if event.get("event_type") == "submit_accepted"
    ]
    terminal_events = [
        event
        for event in audit_events
        if event.get("event_type") == "terminal_state_reached"
    ]

    assert exit_code == 0
    assert "auto_sell_round_summary" in captured.out
    assert details, "期待至少有一个 sell_execution_detail"
    assert terminal_detail is not None, "期待终态 detail 暴露 terminal_state_at"
    assert terminal_detail["order_terminal_latency_ms"] == 1000
    assert submit_events, "期待 order_audit.log 包含 submit_accepted 事件"
    assert terminal_events, "期待 order_audit.log 包含 terminal_state_reached 事件"
    assert terminal_events[0]["order_terminal_latency_ms"] == 1000
    assert "round_started entry=auto_sell" in runtime_log
    assert "round_completed entry=auto_sell" in runtime_log
