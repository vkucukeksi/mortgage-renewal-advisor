
from dataclasses import dataclass
from decimal import Decimal

from ..calculations.mortgage import round_money
from .overpayments import RenewalOverpaymentScenario


DEFAULT_TARGET_LTV_PERCENTAGES = [
    Decimal("60"),
    Decimal("55"),
    Decimal("50"),
]


@dataclass(frozen=True)
class ScenarioInsight:
    """A plain-language insight derived from renewal scenarios."""

    kind: str
    title: str
    message: str
    target_ltv_percent: Decimal | None = None
    overpayment: Decimal | None = None
    projected_ltv_percent: Decimal | None = None
    cash_remaining: Decimal | None = None
    balance_reduction_vs_baseline: Decimal | None = None


def _format_money(amount: Decimal) -> str:
    """Format an amount as whole pounds."""
    return f"£{amount:,.0f}"


def _format_percent(value: Decimal) -> str:
    """Format a percentage without unnecessary decimal places."""
    formatted = format(value, "f")

    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")

    return formatted


def _meets_target(scenario: RenewalOverpaymentScenario, target: Decimal) -> bool:
    # Use the original value, not the display-rounded LTV or equity.
    return (
        scenario.projected_mortgage_balance * Decimal("100")
        <= target * scenario.property_value
    )


def generate_scenario_insights(
    scenarios: list[RenewalOverpaymentScenario],
    target_ltv_percentages: list[Decimal] | None = None,
) -> list[ScenarioInsight]:
    """Explain LTV milestones and cash-versus-mortgage trade-offs."""

    if not scenarios:
        raise ValueError("At least one scenario is required.")

    targets = (
        DEFAULT_TARGET_LTV_PERCENTAGES
        if target_ltv_percentages is None
        else target_ltv_percentages
    )

    if not targets:
        raise ValueError("At least one LTV target is required.")

    if any(target <= 0 or target > 100 for target in targets):
        raise ValueError("Target LTV must be greater than 0 and at most 100.")

    if len(set(targets)) != len(targets):
        raise ValueError("LTV targets must be unique.")

    # Compare from the lowest tested overpayment as the baseline.
    baseline = min(scenarios, key=lambda item: item.overpayment)

    insights: list[ScenarioInsight] = []

    for target in targets:
        target_text = _format_percent(target)

        # The lowest-overpayment option already meets this target.
        if _meets_target(baseline, target):
            if baseline.overpayment == 0:
                message = (
                    f"Your no-overpayment scenario is already projected "
                    f"to reach {target_text}% LTV or lower by renewal. "
                    "An overpayment is not needed to reach this particular "
                    "milestone under these assumptions."
                )
            else:
                message = (
                    f"Your lowest tested overpayment of "
                    f"{_format_money(baseline.overpayment)} is already "
                    f"projected to reach {target_text}% LTV or lower. "
                    "Consider this alongside the other options you tested."
                )

            insights.append(
                ScenarioInsight(
                    kind="target_already_reached",
                    title=f"{target_text}% LTV milestone already reached",
                    message=message,
                    target_ltv_percent=target,
                    overpayment=baseline.overpayment,
                    projected_ltv_percent=baseline.projected_ltv_percent,
                    cash_remaining=baseline.cash_remaining,
                )
            )
            continue

        qualifying = [
            scenario
            for scenario in scenarios
            if _meets_target(scenario, target)
        ]

        # Find the smallest tested overpayment that reaches the target.
        if qualifying:
            option = min(qualifying, key=lambda item: item.overpayment)

            balance_reduction = round_money(
                baseline.projected_mortgage_balance
                - option.projected_mortgage_balance
            )

            if baseline.overpayment == 0:
                comparison = "Compared with making no overpayment"
            else:
                comparison = (
                    "Compared with your lowest-overpayment option"
                )

            message = (
                f"{_format_money(option.overpayment)} is the smallest "
                f"of your tested overpayments that projects your mortgage "
                f"to {target_text}% LTV or lower by renewal. It leaves "
                f"{_format_money(option.cash_remaining)} in cash. "
                f"{comparison}, the projected mortgage balance is "
                f"{_format_money(balance_reduction)} lower."
            )

            insights.append(
                ScenarioInsight(
                    kind="target_reached",
                    title=f"Your {target_text}% LTV milestone",
                    message=message,
                    target_ltv_percent=target,
                    overpayment=option.overpayment,
                    projected_ltv_percent=option.projected_ltv_percent,
                    cash_remaining=option.cash_remaining,
                    balance_reduction_vs_baseline=balance_reduction,
                )
            )
            continue

        # No tested option reaches the target.
        lowest_ltv_option = min(
            scenarios,
            key=lambda item: item.projected_ltv_percent,
        )

        balance_reduction = round_money(
            baseline.projected_mortgage_balance
            - lowest_ltv_option.projected_mortgage_balance
        )

        message = (
            f"None of your tested options reaches {target_text}% LTV "
            "or lower by renewal. The lowest projected LTV is "
            f"{_format_percent(lowest_ltv_option.projected_ltv_percent)}% "
            f"with a {_format_money(lowest_ltv_option.overpayment)} "
            f"overpayment, leaving "
            f"{_format_money(lowest_ltv_option.cash_remaining)} in cash."
        )

        insights.append(
            ScenarioInsight(
                kind="target_not_reached",
                title=f"{target_text}% LTV milestone not reached",
                message=message,
                target_ltv_percent=target,
                overpayment=lowest_ltv_option.overpayment,
                projected_ltv_percent=(
                    lowest_ltv_option.projected_ltv_percent
                ),
                cash_remaining=lowest_ltv_option.cash_remaining,
                balance_reduction_vs_baseline=balance_reduction,
            )
        )

    # Compare the options that preserve the most cash and pay down the
    # most mortgage principal among the scenarios supplied.
    highest_overpayment = max(
        scenarios,
        key=lambda item: item.overpayment,
    )

    if highest_overpayment.overpayment > baseline.overpayment:
        balance_reduction = round_money(
            baseline.projected_mortgage_balance
            - highest_overpayment.projected_mortgage_balance
        )

        if balance_reduction > 0:
            balance_comparison = (
                f"the projected mortgage balance is "
                f"{_format_money(balance_reduction)} lower at renewal"
            )
        else:
            balance_comparison = (
                "there is no further reduction in the projected "
                "mortgage balance under these assumptions"
            )

        message = (
            f"Your lowest-overpayment option "
            f"({_format_money(baseline.overpayment)}) leaves "
            f"{_format_money(baseline.cash_remaining)} in cash. "
            f"Your highest tested overpayment "
            f"({_format_money(highest_overpayment.overpayment)}) leaves "
            f"{_format_money(highest_overpayment.cash_remaining)} in cash; "
            f"{balance_comparison}. This comparison does not account for "
            "emergency savings needs, other uses for your cash, or any "
            "lender overpayment charges."
        )

        insights.append(
            ScenarioInsight(
                kind="cash_tradeoff",
                title="Cash in hand versus mortgage balance",
                message=message,
                overpayment=highest_overpayment.overpayment,
                projected_ltv_percent=(
                    highest_overpayment.projected_ltv_percent
                ),
                cash_remaining=highest_overpayment.cash_remaining,
                balance_reduction_vs_baseline=balance_reduction,
            )
        )

    return insights
