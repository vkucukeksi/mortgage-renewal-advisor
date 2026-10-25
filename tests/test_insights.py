
from decimal import Decimal

import pytest

from backend.app.scenarios.insights import generate_scenario_insights
from backend.app.scenarios.overpayments import (
    generate_renewal_overpayment_scenarios,
)


def test_identifies_smallest_overpayment_reaching_target():
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

    insights = generate_scenario_insights(
        scenarios,
        target_ltv_percent=Decimal("40"),
    )

    assert len(insights) == 1
    assert insights[0].kind == "target_reached"
    assert insights[0].overpayment == Decimal("100")
    assert insights[0].projected_ltv_percent == Decimal("35.85")
    assert insights[0].cash_remaining == Decimal("0")
    assert (
        insights[0].balance_reduction_vs_no_overpayment
        == Decimal("102.01")
    )


def test_identifies_target_already_reached_without_overpayment():
    scenarios = generate_renewal_overpayment_scenarios(
        mortgage_balance=Decimal("500"),
        property_value=Decimal("1000"),
        available_cash=Decimal("100"),
        annual_interest_rate_percent=Decimal("0"),
        monthly_payment=Decimal("0"),
        months_until_renewal=1,
        overpayment_options=[Decimal("0"), Decimal("50")],
    )

    insights = generate_scenario_insights(
        scenarios,
        target_ltv_percent=Decimal("60"),
    )

    assert insights[0].kind == "target_already_reached"
    assert insights[0].overpayment == Decimal("0")
    assert insights[0].projected_ltv_percent == Decimal("50.00")


def test_explains_when_none_of_the_options_reaches_target():
    scenarios = generate_renewal_overpayment_scenarios(
        mortgage_balance=Decimal("1800"),
        property_value=Decimal("2000"),
        available_cash=Decimal("10"),
        annual_interest_rate_percent=Decimal("0"),
        monthly_payment=Decimal("0"),
        months_until_renewal=1,
        overpayment_options=[Decimal("0"), Decimal("10")],
    )

    insights = generate_scenario_insights(
        scenarios,
        target_ltv_percent=Decimal("60"),
    )

    assert insights[0].kind == "target_not_reached"
    assert insights[0].overpayment == Decimal("10")
    assert insights[0].projected_ltv_percent == Decimal("89.50")


def test_rejects_empty_scenarios():
    with pytest.raises(ValueError):
        generate_scenario_insights([])


def test_rejects_invalid_target_ltv():
    scenarios = generate_renewal_overpayment_scenarios(
        mortgage_balance=Decimal("1000"),
        property_value=Decimal("2000"),
        available_cash=Decimal("100"),
        annual_interest_rate_percent=Decimal("0"),
        monthly_payment=Decimal("0"),
        months_until_renewal=1,
        overpayment_options=[Decimal("0")],
    )

    with pytest.raises(ValueError):
        generate_scenario_insights(
            scenarios,
            target_ltv_percent=Decimal("0"),
        )
