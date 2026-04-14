from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gmtrade_live.models import (
    AutoSellRoundReport,
    AutoSellRoundSummary,
    SellBlockDetail,
    SellExecutionDetail,
    SellQuantityPlan,
)


def _now() -> datetime:
    return datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_sell_quantity_plan_carries_final_target_and_promotion_type() -> None:
    plan = SellQuantityPlan(
        symbol="SHSE.600036",
        requested_ratio=Decimal("0.804"),
        total_volume=250,
        available_volume=250,
        raw_target_volume=201,
        final_target_volume=250,
        promotion_type="full_position",
        block_reason=None,
    )

    assert plan.final_target_volume == 250
    assert plan.promotion_type == "full_position"


def test_auto_sell_round_report_exposes_block_and_execution_details() -> None:
    report = AutoSellRoundReport(
        summary=AutoSellRoundSummary(
            round_no=1,
            session_state="trading",
            position_count=1,
            candidate_count=1,
            blocked_count=0,
            submitted_count=1,
            open_order_count=1,
            changed_symbol_count=1,
            duration_ms=10,
        ),
        block_details=(
            SellBlockDetail(
                symbol="SHSE.600036",
                decision_lifecycle_state="watching",
                decision_should_sell=True,
                decision_can_submit_sell=True,
                decision_trigger_reason="take_profit_triggered",
                decision_block_reason=None,
                execution_state="failed",
                execution_cl_ord_id="CL_OLD",
                execution_broker_order_id="BK_OLD",
                execution_last_order_status="rejected",
                requested_ratio=Decimal("0.80"),
                total_volume=250,
                available_volume=201,
                raw_target_volume=200,
                promotion_type=None,
                normalized_target_volume=200,
                block_reason="sell_quantity_exceeds_available",
                evaluated_at=_now(),
            ),
        ),
        execution_details=(
            SellExecutionDetail(
                symbol="SHSE.600036",
                change_tags=("submit_accepted",),
                decision_lifecycle_state="watching",
                decision_should_sell=True,
                decision_can_submit_sell=True,
                decision_trigger_reason="take_profit_triggered",
                decision_block_reason=None,
                execution_state="submitted",
                cl_ord_id="CL_1",
                broker_order_id="BK_1",
                requested_volume=200,
                filled_volume=0,
                remaining_volume=200,
                submit_accepted=True,
                last_order_status="submitted",
                rejection_reason=None,
                avg_price=None,
                event_time=_now(),
                message="accepted",
            ),
        ),
    )

    assert report.summary.submitted_count == 1
    assert report.block_details[0].decision_lifecycle_state == "watching"
    assert report.block_details[0].block_reason == "sell_quantity_exceeds_available"
    assert report.execution_details[0].decision_trigger_reason == "take_profit_triggered"
    assert report.execution_details[0].cl_ord_id == "CL_1"


def test_sell_execution_detail_exposes_timing_projection() -> None:
    moment = _now()

    detail = SellExecutionDetail(
        symbol="SHSE.600036",
        change_tags=("terminal_state_reached",),
        decision_lifecycle_state="watching",
        decision_should_sell=True,
        decision_can_submit_sell=True,
        decision_trigger_reason="take_profit_triggered",
        decision_block_reason=None,
        execution_state="filled",
        cl_ord_id="CL_1",
        broker_order_id="BK_1",
        requested_volume=200,
        filled_volume=200,
        remaining_volume=0,
        submit_accepted=True,
        last_order_status="filled",
        rejection_reason=None,
        avg_price=Decimal("10.80"),
        event_time=moment,
        message="filled",
        submit_started_at=moment,
        submit_accepted_at=moment,
        terminal_state_at=moment,
        order_terminal_latency_ms=1200,
    )

    assert detail.terminal_state_at == moment
    assert detail.order_terminal_latency_ms == 1200
