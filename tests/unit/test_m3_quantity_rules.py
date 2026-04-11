from __future__ import annotations

from decimal import Decimal

from gmtrade_live.services.m3_quantity_rules import build_sell_quantity_plan


def test_build_sell_quantity_plan_promotes_full_position_when_total_remainder_is_odd_lot() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.600036",
        total_volume=250,
        available_volume=250,
        sell_quantity_ratio=Decimal("0.804"),
    )

    assert plan.raw_target_volume == 201
    assert plan.final_target_volume == 250
    assert plan.promotion_type == "full_position"
    assert plan.block_reason is None


def test_build_sell_quantity_plan_keeps_target_when_full_position_is_not_currently_sellable() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.600036",
        total_volume=250,
        available_volume=201,
        sell_quantity_ratio=Decimal("0.80"),
    )

    assert plan.raw_target_volume == 200
    assert plan.final_target_volume == 200
    assert plan.promotion_type is None
    assert plan.block_reason is None


def test_build_sell_quantity_plan_blocks_when_final_target_exceeds_available() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.600036",
        total_volume=250,
        available_volume=201,
        sell_quantity_ratio=Decimal("1.0"),
    )

    assert plan.final_target_volume == 250
    assert plan.block_reason == "sell_quantity_exceeds_available"


def test_build_sell_quantity_plan_blocks_when_normalized_target_is_zero() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.600036",
        total_volume=250,
        available_volume=250,
        sell_quantity_ratio=Decimal("0.01"),
    )

    assert plan.final_target_volume == 0
    assert plan.block_reason == "sell_quantity_below_min_order"


def test_build_sell_quantity_plan_supports_star_market_non_multiple_of_two_hundred() -> None:
    plan = build_sell_quantity_plan(
        symbol="SHSE.688188",
        total_volume=10000,
        available_volume=10000,
        sell_quantity_ratio=Decimal("0.0201"),
    )

    assert plan.raw_target_volume == 201
    assert plan.final_target_volume == 201
    assert plan.block_reason is None
