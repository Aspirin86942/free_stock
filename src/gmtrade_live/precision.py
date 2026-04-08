from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def normalize_price(value: float | Decimal) -> Decimal:
    """标准化价格为 3 位小数。"""
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def normalize_amount(value: float | Decimal) -> Decimal:
    """标准化金额为 2 位小数。"""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_ratio(value: float | Decimal) -> Decimal:
    """标准化比例为 4 位小数。"""
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
