
from decimal import Decimal

import pytest

from backend.app.scenarios.overpayments import (
    generate_overpayment_scenarios,
    generate_renewal_overpayment_scenarios,
)


def test_generate_overpayment_scenarios():
    scenarios = generate_overpayment_scenarios(
        mortgage_balance=Decimal("325000"),
        property_value=Decimal("500000"),
        available_cash=Decimal("50000"),
        overpayment_options=[
            Decimal("0"),
            Decimal("10000"),
            Decimal("20000"),
            Decimal("25000"),
            Decimal("30000"),
            Decimal("50000"),
        ],
    )

    assert len(scenarios) == 6

    # Check the mortgage balance after each overpayment.
    assert [
        scenario.mortgage_balance_after
        for scenario in scenarios
    ] == [
        Decimal("325000"),
        Decimal("315000"),
        Decimal("305000"),
        Decimal("300000"),
        Decimal("295000"),
        Decimal("275000"),
    ]

    # Check the resulting loan-to-value percentages.
    assert [
        scenario.ltv_percent
        for scenario in scenarios
    ] == [
        Decimal("65.00"),
        Decimal("63.00"),
        Decimal("61.00"),
        Decimal("60.00"),
        Decimal("59.00"),
        Decimal("55.00"),
    ]


def test_scenario_calculates_equity_and_remaining_cash():
    scenarios = generate_overpayment_scenarios(
        mortgage_balance=Decimal("325000"),
        property_value=Decimal("500000"),
        available_cash=Decimal("50000"),
        overpayment_options=[Decimal("25000")],
    )

    scenario = scenarios[0]

    assert scenario.equity == Decimal("200000.00")
    assert scenario.cash_remaining == Decimal("25000")


def test_no_overpayment_preserves_available_cash():
    scenarios = generate_overpayment_scenarios(
        mortgage_balance=Decimal("325000"),
        property_value=Decimal("500000"),
        available_cash=Decimal("50000"),
        overpayment_options=[Decimal("0")],
    )

    assert scenarios[0].cash_remaining == Decimal("50000")


def test_rejects_negative_mortgage_balance():
    with pytest.raises(ValueError):
        generate_overpayment_scenarios(
            Decimal("-1"),
            Decimal("500000"),
            Decimal("50000"),
            [Decimal("0")],
        )


def test_rejects_invalid_property_value():
    with pytest.raises(ValueError):
        generate_overpayment_scenarios(
            Decimal("325000"),
            Decimal("0"),
            Decimal("50000"),
            [Decimal("0")],
        )


def test_rejects_negative_available_cash():
    with pytest.raises(ValueError):
        generate_overpayment_scenarios(
            Decimal("325000"),
            Decimal("500000"),
            Decimal("-1"),
            [Decimal("0")],
        )


def test_rejects_empty_overpayment_options():
    with pytest.raises(ValueError):
        generate_overpayment_scenarios(
            Decimal("325000"),
            Decimal("500000"),
            Decimal("50000"),
            [],
        )


def test_rejects_negative_overpayment():
    with pytest.raises(ValueError):
        generate_overpayment_scenarios(
            Decimal("325000"),
            Decimal("500000"),
            Decimal("50000"),
            [Decimal("-1000")],
        )


def test_rejects_duplicate_overpayment_options():
    with pytest.raises(ValueError):
        generate_overpayment_scenarios(
            Decimal("325000"),
            Decimal("500000"),
            Decimal("50000"),
            [
                Decimal("10000"),
                Decimal("10000"),
            ],
        )


def test_rejects_overpayment_exceeding_available_cash():
    with pytest.raises(ValueError):
        generate_overpayment_scenarios(
            Decimal("325000"),
            Decimal("500000"),
            Decimal("20000"),
            [Decimal("25000")],
        )


def test_rejects_overpayment_exceeding_mortgage_balance():
    with pytest.raises(ValueError):
        generate_overpayment_scenarios(
            Decimal("325000"),
            Decimal("500000"),
            Decimal("400000"),
            [Decimal("350000")],
        )


def test_projects_overpayment_scenarios_to_renewal():
    scenarios = generate_renewal_overpayment_scenarios(
        mortgage_balance=Decimal("1000"),
        property_value=Decimal("2000"),
        available_cash=Decimal("100"),
        annual_interest_rate_percent=Decimal("12"),
        monthly_payment=Decimal("100"),
        months_until_renewal=2,
        overpayment_options=[
            Decimal("0"),
            Decimal("100"),
        ],
    )

    assert [
        scenario.projected_mortgage_balance
        for scenario in scenarios
    ] == [
        Decimal("819.10"),
        Decimal("717.09"),
    ]

    assert [
        scenario.projected_ltv_percent
        for scenario in scenarios
    ] == [
        Decimal("40.96"),
        Decimal("35.85"),
    ]

    assert [
        scenario.cash_remaining
        for scenario in scenarios
    ] == [
        Decimal("100"),
        Decimal("0"),
    ]


def test_zero_months_preserves_balance_after_overpayment():
    scenarios = generate_renewal_overpayment_scenarios(
        mortgage_balance=Decimal("1000"),
        property_value=Decimal("2000"),
        available_cash=Decimal("100"),
        annual_interest_rate_percent=Decimal("12"),
        monthly_payment=Decimal("100"),
        months_until_renewal=0,
        overpayment_options=[Decimal("100")],
    )

    assert (
        scenarios[0].projected_mortgage_balance
        == Decimal("900.00")
    )


def test_renewal_scenarios_reject_negative_months():
    with pytest.raises(ValueError):
        generate_renewal_overpayment_scenarios(
            Decimal("1000"),
            Decimal("2000"),
            Decimal("100"),
            Decimal("5"),
            Decimal("100"),
            -1,
            [Decimal("0")],
        )


def test_renewal_scenarios_reject_negative_monthly_payment():
    with pytest.raises(ValueError):
        generate_renewal_overpayment_scenarios(
            Decimal("1000"),
            Decimal("2000"),
            Decimal("100"),
            Decimal("5"),
            Decimal("-100"),
            6,
            [Decimal("0")],
        )


def test_renewal_scenarios_reject_overpayment_above_available_cash():
    with pytest.raises(ValueError):
        generate_renewal_overpayment_scenarios(
            Decimal("1000"),
            Decimal("2000"),
            Decimal("100"),
            Decimal("5"),
            Decimal("100"),
            6,
            [Decimal("101")],
        )
