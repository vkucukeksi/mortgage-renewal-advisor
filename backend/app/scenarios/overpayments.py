from dataclasses import dataclass
from decimal import Decimal

from ..calculations.mortgage import (
    calculate_equity,
    calculate_ltv,
)


@dataclass(frozen=True)
class OverpaymentScenario:
    """Results for one mortgage overpayment scenario."""

    overpayment: Decimal
    mortgage_balance_after: Decimal
    ltv_percent: Decimal
    equity: Decimal
    cash_remaining: Decimal


def generate_overpayment_scenarios(
    mortgage_balance: Decimal,
    property_value: Decimal,
    available_cash: Decimal,
    overpayment_options: list[Decimal],
) -> list[OverpaymentScenario]:
    """Generate mortgage scenarios for different overpayment options."""

    if mortgage_balance < 0:
        raise ValueError("Mortgage balance cannot be negative.")

    if property_value <= 0:
        raise ValueError("Property value must be greater than zero.")

    if available_cash < 0:
        raise ValueError("Available cash cannot be negative.")

    if not overpayment_options:
        raise ValueError("At least one overpayment option is required.")

    if any(amount < 0 for amount in overpayment_options):
        raise ValueError("Overpayments cannot be negative.")

    if len(set(overpayment_options)) != len(overpayment_options):
        raise ValueError("Overpayment options must be unique.")

    scenarios = []

    for overpayment in overpayment_options:
        if overpayment > available_cash:
            raise ValueError(
                "Overpayment cannot exceed available cash."
            )

        if overpayment > mortgage_balance:
            raise ValueError(
                "Overpayment cannot exceed the mortgage balance."
            )

        balance_after = mortgage_balance - overpayment

        scenario = OverpaymentScenario(
            overpayment=overpayment,
            mortgage_balance_after=balance_after,
            ltv_percent=calculate_ltv(
                balance_after,
                property_value,
            ),
            equity=calculate_equity(
                balance_after,
                property_value,
            ),
            cash_remaining=available_cash - overpayment,
        )

        scenarios.append(scenario)

    return scenarios