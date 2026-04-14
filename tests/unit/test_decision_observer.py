from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    CandidateRoundSummary,
    CandidateRound,
    DecisionChangeEvent,
    DecisionObservationReport,
    DecisionPositionStateSnapshot,
    DecisionRoundSummary,
    SellCandidate,
)
from gmtrade_live.services.decision_observer import DecisionObserverService


def _now() -> datetime:
    return datetime(2026, 4, 9, 14, 20, tzinfo=ZoneInfo("Asia/Shanghai"))


def _config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-decision-observer",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        sell_quantity_ratio=Decimal("1.0"),
        market_session_mode="a_share",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="127.0.0.1:7001",
    )


class FakePipeline:
    def __init__(self, result: CandidateRound) -> None:
        self._result = result
        self.last_round_no: int | None = None
        self.last_account_id: str | None = None

    def run_round(self, *, config: AppConfig, round_no: int) -> CandidateRound:
        self.last_round_no = round_no
        self.last_account_id = config.account_id
        return self._result


def test_observer_service_consumes_pipeline_output() -> None:
    pipeline_result = CandidateRound(
        summary=CandidateRoundSummary(
            round_no=1,
            session_state="trading",
            position_count=0,
            watching_count=0,
            tombstone_count=0,
            should_sell_count=0,
            can_submit_sell_count=0,
            changed_symbol_count=0,
            duration_ms=0,
        ),
        candidates=(),
        tombstones=(),
        change_events=(),
    )
    expected = DecisionObservationReport(
        summary=DecisionRoundSummary(
            round_no=1,
            session_state="trading",
            position_count=0,
            watching_count=0,
            tombstone_count=0,
            should_sell_count=0,
            can_submit_sell_count=0,
            changed_symbol_count=0,
            duration_ms=0,
        ),
        candidates=(),
        tombstones=(),
        change_events=(),
    )
    pipeline = FakePipeline(pipeline_result)
    service = DecisionObserverService(
        pipeline=pipeline,
        logger=logging.getLogger("test"),
    )

    report = service.run_round(config=_config(), round_no=1)

    assert report == expected
    assert pipeline.last_round_no == 1
    assert pipeline.last_account_id == "demo-account"
