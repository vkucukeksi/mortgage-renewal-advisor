from decimal import Decimal

import pytest

from backend.app.calculations.mortgage import (
    calculate_equity,
    calculate_ltv,
    calculate_monthly_payment,
    calculate_overpayment_to_target_ltv,
)


def test_calculate_ltv():
    result = calculate_ltv(
        Decimal("325000"),
        Decimal("500000"),
    )

    assert result == Decimal("65.00")


def test_calculate_equity():
    result = calculate_equity(
        Decimal("325000"),
        Decimal("500000"),
    )

    assert result == Decimal("175000.00")


def test_calculate_overpayment_to_target_ltv():
    result = calculate_overpayment_to_target_ltv(
        Decimal("325000"),
        Decimal("500000"),
        Decimal("60"),
    )

    assert result == Decimal("25000.00")


def test_no_overpayment_needed_when_already_below_target_ltv():
    result = calculate_overpayment_to_target_ltv(
        Decimal("275000"),
        Decimal("500000"),
        Decimal("60"),
    )

    assert result == Decimal("0.00")


def test_calculate_monthly_payment():
    result = calculate_monthly_payment(
        Decimal("325000"),
        Decimal("1.89"),
        240,
    )

    assert result == Decimal("1627.24")


@pytest.mark.parametrize(("balance", "rate", "months", "expected"), [
    ("100000", "5", 300, "584.59"),
    ("200000", "4.5", 360, "1013.37"),
    ("200000", "4.5", 240, "1265.30"),
    ("120000", "0", 240, "500.00"),
    ("0", "4.5", 240, "0.00"),
])
def test_repayment_estimates(balance, rate, months, expected):
    assert calculate_monthly_payment(Decimal(balance), Decimal(rate), months) == Decimal(expected)


@pytest.mark.parametrize(("balance", "rate"), [("-1", "5"), ("100000", "-1")])
def test_repayment_rejects_negative_balance_or_rate(balance, rate):
    with pytest.raises(ValueError):
        calculate_monthly_payment(Decimal(balance), Decimal(rate), 240)


def test_invalid_property_value():
    with pytest.raises(ValueError):
        calculate_ltv(
            Decimal("325000"),
            Decimal("0"),
        )


def test_invalid_mortgage_balance():
    with pytest.raises(ValueError):
        calculate_equity(
            Decimal("-1"),
            Decimal("500000"),
        )


def test_invalid_target_ltv():
    with pytest.raises(ValueError):
        calculate_overpayment_to_target_ltv(
            Decimal("325000"),
            Decimal("500000"),
            Decimal("0"),
        )


def test_invalid_remaining_term():
    with pytest.raises(ValueError):
        calculate_monthly_payment(
            Decimal("325000"),
            Decimal("1.89"),
            0,
        )
