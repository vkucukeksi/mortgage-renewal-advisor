from decimal import Decimal

import pytest

from backend.app.calculations.projections import (
    project_mortgage_balance,
)


def test_projects_balance_with_interest():
    result = project_mortgage_balance(
        Decimal("1000"),
        Decimal("12"),
        Decimal("100"),
        2,
    )

    assert result == Decimal("819.10")


def test_projects_balance_with_zero_interest():
    result = project_mortgage_balance(
        Decimal("1000"),
        Decimal("0"),
        Decimal("100"),
        3,
    )

    assert result == Decimal("700.00")


def test_balance_cannot_fall_below_zero():
    result = project_mortgage_balance(
        Decimal("100"),
        Decimal("12"),
        Decimal("200"),
        1,
    )

    assert result == Decimal("0.00")


def test_zero_months_preserves_balance():
    result = project_mortgage_balance(
        Decimal("1000"),
        Decimal("12"),
        Decimal("100"),
        0,
    )

    assert result == Decimal("1000.00")


def test_rejects_negative_mortgage_balance():
    with pytest.raises(ValueError):
        project_mortgage_balance(
            Decimal("-1"),
            Decimal("5"),
            Decimal("100"),
            12,
        )


def test_rejects_negative_interest_rate():
    with pytest.raises(ValueError):
        project_mortgage_balance(
            Decimal("1000"),
            Decimal("-1"),
            Decimal("100"),
            12,
        )


def test_rejects_negative_monthly_payment():
    with pytest.raises(ValueError):
        project_mortgage_balance(
            Decimal("1000"),
            Decimal("5"),
            Decimal("-100"),
            12,
        )


def test_rejects_negative_months():
    with pytest.raises(ValueError):
        project_mortgage_balance(
            Decimal("1000"),
            Decimal("5"),
            Decimal("100"),
            -1,
        )