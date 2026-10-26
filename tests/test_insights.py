
from decimal import Decimal

import pytest

from backend.app.scenarios.insights import generate_scenario_insights
from backend.app.scenarios.overpayments import (
    generate_renewal_overpayment_scenarios,
)


def make_scenarios(
    balance="1000",
    property_value="2000",
    available_cash="100",
    interest_rate="12",
    monthly_payment="100",
    months=2,
    options=None,
):
    if options is None:
        options = [
            Decimal("0"),
            Decimal("100"),
        ]

    return generate_renewal_overpayment_scenarios(
        mortgage_balance=Decimal(balance),
        property_value=Decimal(property_value),
        available_cash=Decimal(available_cash),
        annual_interest_rate_percent=Decimal(interest_rate),
        monthly_payment=Decimal(monthly_payment),
        months_until_renewal=months,
        overpayment_options=options,
    )


def test_identifies_smallest_overpayment_reaching_target():
    scenarios = make_scenarios()

    insights = generate_scenario_insights(
        scenarios,
        [Decimal("40")],
    )

    target_insight = next(
        insight for insight in insights
        if insight.kind == "target_reached"
    )

    assert target_insight.overpayment == Decimal("100")
    assert target_insight.projected_ltv_percent == Decimal("35.85")
    assert target_insight.cash_remaining == Decimal("0")
    assert target_insight.balance_reduction_vs_baseline == Decimal("102.01")


def test_identifies_target_already_reached_without_overpayment():
    scenarios = make_scenarios(
        balance="500",
        property_value="1000",
        interest_rate="0",
        monthly_payment="0",
        months=1,
    )

    insights = generate_scenario_insights(
        scenarios,
        [Decimal("60")],
    )

    target_insight = next(
        insight for insight in insights
        if insight.kind == "target_already_reached"
    )

    assert target_insight.overpayment == Decimal("0")
    assert target_insight.projected_ltv_percent == Decimal("50.00")


def test_explains_when_no_tested_option_reaches_target():
    scenarios = make_scenarios(
        balance="1800",
        property_value="2000",
        available_cash="10",
        interest_rate="0",
        monthly_payment="0",
        months=1,
        options=[Decimal("0"), Decimal("10")],
    )

    insights = generate_scenario_insights(
        scenarios,
        [Decimal("60")],
    )

    target_insight = next(
        insight for insight in insights
        if insight.kind == "target_not_reached"
    )

    assert target_insight.overpayment == Decimal("10")
    assert target_insight.projected_ltv_percent == Decimal("89.50")


def test_generates_multiple_milestones_and_cash_tradeoff():
    scenarios = make_scenarios(
        balance="325000",
        property_value="500000",
        available_cash="50000",
        interest_rate="1.89",
        monthly_payment="1800",
        months=6,
        options=[
            Decimal("0"),
            Decimal("10000"),
            Decimal("20000"),
            Decimal("25000"),
            Decimal("30000"),
            Decimal("50000"),
        ],
    )

    insights = generate_scenario_insights(scenarios)

    reached_60 = next(
        insight for insight in insights
        if insight.kind == "target_reached"
        and insight.target_ltv_percent == Decimal("60")
    )

    reached_55 = next(
        insight for insight in insights
        if insight.kind == "target_reached"
        and insight.target_ltv_percent == Decimal("55")
    )

    not_reached_50 = next(
        insight for insight in insights
        if insight.kind == "target_not_reached"
        and insight.target_ltv_percent == Decimal("50")
    )

    tradeoff = next(
        insight for insight in insights
        if insight.kind == "cash_tradeoff"
    )

    assert reached_60.overpayment == Decimal("20000")
    assert reached_55.overpayment == Decimal("50000")
    assert not_reached_50.overpayment == Decimal("50000")
    assert tradeoff.overpayment == Decimal("50000")
    assert tradeoff.cash_remaining == Decimal("0")
    assert tradeoff.balance_reduction_vs_baseline == Decimal("50474.36")
        # Check that LTV percentages display correctly.
    assert reached_60.title == "Your 60% LTV milestone"
    assert reached_55.title == "Your 55% LTV milestone"
    assert not_reached_50.title == "50% LTV milestone not reached"


def test_rejects_empty_scenarios():
    with pytest.raises(ValueError):
        generate_scenario_insights([])


def test_rejects_invalid_target_ltv():
    scenarios = make_scenarios()

    with pytest.raises(ValueError):
        generate_scenario_insights(
            scenarios,
            [Decimal("0")],
        )


def test_rejects_duplicate_targets():
    scenarios = make_scenarios()

    with pytest.raises(ValueError):
        generate_scenario_insights(
            scenarios,
            [Decimal("60"), Decimal("60")],
        )
