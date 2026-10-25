
from dataclasses import dataclass
from decimal import Decimal

from ..calculations.mortgage import round_money
from .overpayments import RenewalOverpaymentScenario


@dataclass(frozen=True)
class ScenarioInsight:
    """A plain-language insight derived from renewal scenarios."""

    kind: str
    title: str
    message: str
    target_ltv_percent: Decimal
    overpayment: Decimal | None = None
    projected_ltv_percent: Decimal | None = None
    cash_remaining: Decimal | None = None
    balance_reduction_vs_no_overpayment: Decimal | None = None


def _format_money(amount: Decimal) -> str:
    """Format an amount as whole pounds for an insight message."""
    return f"£{amount:,.0f}"


def _format_percent(value: Decimal) -> str:
    """Format a percentage without unnecessary decimal places."""
    formatted = format(value, "f")

    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")

    return formatted


def generate_scenario_insights(
    scenarios: list[RenewalOverpaymentScenario],
    target_ltv_percent: Decimal = Decimal("60"),
) -> list[ScenarioInsight]:
    """Explain which tested overpayment options reach an LTV milestone."""

    if not scenarios:
        raise ValueError("At least one scenario is required.")

    if target_ltv_percent <= 0 or target_ltv_percent > 100:
        raise ValueError("Target LTV must be greater than 0 and at most 100.")

    baseline = next(
        (
            scenario
            for scenario in scenarios
            if scenario.overpayment == 0
        ),
        None,
    )

    qualifying_scenarios = [
        scenario
        for scenario in scenarios
        if scenario.projected_ltv_percent <= target_ltv_percent
    ]

    target_text = _format_percent(target_ltv_percent)

    # The no-overpayment scenario already meets the target.
    if (
        baseline is not None
        and baseline.projected_ltv_percent <= target_ltv_percent
    ):
        insight = ScenarioInsight(
            kind="target_already_reached",
            title=f"{target_text}% LTV milestone already reached",
            message=(
                "Your no-overpayment scenario is already projected "
                f"to reach {target_text}% LTV or lower by renewal. "
                "An overpayment is not required to reach this particular "
                "milestone under the assumptions used."
            ),
            target_ltv_percent=target_ltv_percent,
            overpayment=Decimal("0"),
            projected_ltv_percent=baseline.projected_ltv_percent,
            cash_remaining=baseline.cash_remaining,
        )

        return [insight]

    # Find the smallest tested overpayment that reaches the target.
    if qualifying_scenarios:
        best_threshold_option = min(
            qualifying_scenarios,
            key=lambda scenario: scenario.overpayment,
        )

        balance_reduction = None

        if baseline is not None:
            balance_reduction = round_money(
                baseline.projected_mortgage_balance
                - best_threshold_option.projected_mortgage_balance
            )

            message = (
                f"{_format_money(best_threshold_option.overpayment)} "
                f"is the smallest of your tested overpayments that "
                f"projects your mortgage to {target_text}% LTV or lower "
                "by renewal. It leaves "
                f"{_format_money(best_threshold_option.cash_remaining)} "
                "in cash. Compared with no overpayment, the projected "
                "mortgage balance is "
                f"{_format_money(balance_reduction)} lower."
            )
        else:
            message = (
                f"{_format_money(best_threshold_option.overpayment)} "
                f"is the smallest of the options you tested that "
                f"projects your mortgage to {target_text}% LTV or lower "
                "by renewal. It leaves "
                f"{_format_money(best_threshold_option.cash_remaining)} "
                "in cash. Include a £0 overpayment scenario to compare "
                "this option directly with making no overpayment."
            )

        return [
            ScenarioInsight(
                kind="target_reached",
                title=f"Your {target_text}% LTV milestone",
                message=message,
                target_ltv_percent=target_ltv_percent,
                overpayment=best_threshold_option.overpayment,
                projected_ltv_percent=(
                    best_threshold_option.projected_ltv_percent
                ),
                cash_remaining=best_threshold_option.cash_remaining,
                balance_reduction_vs_no_overpayment=balance_reduction,
            )
        ]

    # None of the tested options reaches the target.
    lowest_ltv_scenario = min(
        scenarios,
        key=lambda scenario: scenario.projected_ltv_percent,
    )

    message = (
        f"None of the overpayment options you tested reaches "
        f"{target_text}% LTV or lower by renewal. The lowest projected "
        f"LTV is {_format_percent(lowest_ltv_scenario.projected_ltv_percent)}% "
        f"with a {_format_money(lowest_ltv_scenario.overpayment)} "
        f"overpayment, leaving "
        f"{_format_money(lowest_ltv_scenario.cash_remaining)} in cash."
    )

    return [
        ScenarioInsight(
            kind="target_not_reached",
            title=f"{target_text}% LTV milestone not reached",
            message=message,
            target_ltv_percent=target_ltv_percent,
            overpayment=lowest_ltv_scenario.overpayment,
            projected_ltv_percent=lowest_ltv_scenario.projected_ltv_percent,
            cash_remaining=lowest_ltv_scenario.cash_remaining,
        )
    ]
