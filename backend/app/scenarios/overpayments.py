
from dataclasses import dataclass
from decimal import Decimal

from ..calculations.mortgage import (
    calculate_equity,
    calculate_ltv,
)
from ..calculations.projections import project_mortgage_balance


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
    """Generate scenarios for different overpayment options."""

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


@dataclass(frozen=True)
class RenewalOverpaymentScenario:
    """Results for an overpayment scenario at renewal."""

    overpayment: Decimal
    mortgage_balance_after_overpayment: Decimal
    projected_mortgage_balance: Decimal
    projected_ltv_percent: Decimal
    projected_equity: Decimal
    cash_remaining: Decimal


def generate_renewal_overpayment_scenarios(
    mortgage_balance: Decimal,
    property_value: Decimal,
    available_cash: Decimal,
    annual_interest_rate_percent: Decimal,
    monthly_payment: Decimal,
    months_until_renewal: int,
    overpayment_options: list[Decimal],
) -> list[RenewalOverpaymentScenario]:
    """Project mortgage balances for different overpayments at renewal."""

    if mortgage_balance < 0:
        raise ValueError("Mortgage balance cannot be negative.")

    if property_value <= 0:
        raise ValueError("Property value must be greater than zero.")

    if available_cash < 0:
        raise ValueError("Available cash cannot be negative.")

    if annual_interest_rate_percent < 0:
        raise ValueError("Interest rate cannot be negative.")

    if monthly_payment < 0:
        raise ValueError("Monthly payment cannot be negative.")

    if months_until_renewal < 0:
        raise ValueError("Months until renewal cannot be negative.")

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

        balance_after_overpayment = mortgage_balance - overpayment

        projected_balance = project_mortgage_balance(
            balance_after_overpayment,
            annual_interest_rate_percent,
            monthly_payment,
            months_until_renewal,
        )

        scenario = RenewalOverpaymentScenario(
            overpayment=overpayment,
            mortgage_balance_after_overpayment=(
                balance_after_overpayment
            ),
            projected_mortgage_balance=projected_balance,
            projected_ltv_percent=calculate_ltv(
                projected_balance,
                property_value,
            ),
            projected_equity=calculate_equity(
                projected_balance,
                property_value,
            ),
            cash_remaining=available_cash - overpayment,
        )

        scenarios.append(scenario)

    return scenarios
