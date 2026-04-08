from decimal import Decimal

from gmtrade_live.precision import normalize_amount, normalize_price, normalize_ratio


def test_normalize_price_rounds_to_three_decimals() -> None:
    assert normalize_price(10.123456) == Decimal("10.123")
    assert normalize_price(10.1235) == Decimal("10.124")
    assert normalize_price(Decimal("10.123456")) == Decimal("10.123")


def test_normalize_amount_rounds_to_two_decimals() -> None:
    assert normalize_amount(1000.5678) == Decimal("1000.57")
    assert normalize_amount(1000.565) == Decimal("1000.57")
    assert normalize_amount(Decimal("1000.5678")) == Decimal("1000.57")


def test_normalize_ratio_rounds_to_four_decimals() -> None:
    assert normalize_ratio(0.05) == Decimal("0.0500")
    assert normalize_ratio(0.123456) == Decimal("0.1235")
    assert normalize_ratio(Decimal("0.123456")) == Decimal("0.1235")
