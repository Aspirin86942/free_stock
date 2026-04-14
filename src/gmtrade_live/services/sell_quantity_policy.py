"""自动卖出卖量规划规则。"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from gmtrade_live.models import SellQuantityPlan


def build_sell_quantity_plan(
    *,
    symbol: str,
    total_volume: int,
    available_volume: int,
    sell_quantity_ratio: Decimal,
) -> SellQuantityPlan:
    """按“总仓比例 -> odd-lot 整仓提升 -> 市场规则归整 -> available 校验”生成卖量。"""
    raw_target_volume = int(
        (Decimal(total_volume) * sell_quantity_ratio).to_integral_value(
            rounding=ROUND_DOWN
        )
    )
    minimum_lot = _minimum_lot_for_symbol(symbol)
    raw_remaining_total = total_volume - raw_target_volume

    if 0 < raw_remaining_total < minimum_lot and total_volume <= available_volume:
        # 这里优先整仓，是为了避免留下无法再卖的总仓残量。
        final_target_volume = total_volume
        promotion_type = "full_position"
    else:
        final_target_volume = _normalize_target_volume(
            symbol=symbol,
            total_volume=total_volume,
            target_volume=raw_target_volume,
        )
        promotion_type = None

    block_reason: str | None = None
    if final_target_volume <= 0:
        block_reason = "sell_quantity_below_min_order"
    elif final_target_volume > available_volume:
        block_reason = "sell_quantity_exceeds_available"

    return SellQuantityPlan(
        symbol=symbol,
        requested_ratio=sell_quantity_ratio,
        total_volume=total_volume,
        available_volume=available_volume,
        raw_target_volume=raw_target_volume,
        final_target_volume=final_target_volume,
        promotion_type=promotion_type,
        block_reason=block_reason,
    )


def _minimum_lot_for_symbol(symbol: str) -> int:
    """按市场规则返回最小申报单位。"""
    return 200 if _is_star_market(symbol) else 100


def _is_star_market(symbol: str) -> bool:
    """判断是否科创板标的。"""
    return symbol.startswith("SHSE.688")


def _normalize_target_volume(*, symbol: str, total_volume: int, target_volume: int) -> int:
    """按市场规则把目标卖量归整成可申报数量。"""
    if _is_star_market(symbol):
        return _normalize_star_market_sell_volume(
            total_volume=total_volume,
            target_volume=target_volume,
        )
    return _normalize_a_share_sell_volume(
        total_volume=total_volume,
        target_volume=target_volume,
    )


def _normalize_a_share_sell_volume(*, total_volume: int, target_volume: int) -> int:
    """A 股卖出支持整百，或一次性卖出后剩余为整百。"""
    for candidate in range(target_volume, 0, -1):
        if candidate % 100 == 0:
            return candidate
        if (total_volume - candidate) % 100 == 0:
            return candidate
    return 0


def _normalize_star_market_sell_volume(*, total_volume: int, target_volume: int) -> int:
    """科创板 200 股起，余股可一次性卖出。"""
    if total_volume < 200:
        return total_volume if target_volume >= total_volume else 0
    return target_volume if target_volume >= 200 else 0
