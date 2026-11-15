"""Project a fixed-rate period using the repayment engine and a penny ledger."""
from dataclasses import dataclass
from decimal import Decimal

from .mortgage import calculate_equity, calculate_ltv, calculate_monthly_payment, round_money


@dataclass(frozen=True)
class DealProjection:
    estimated_monthly_payment: Decimal
    balance_at_start: Decimal
    ending_balance: Decimal
    ending_equity: Decimal
    ending_ltv_percent: Decimal
    total_payments: Decimal
    interest_paid: Decimal
    principal_repaid: Decimal
    cash_after_upfront_fee: Decimal


def project_deal(
    balance: Decimal, property_value: Decimal, cash: Decimal, rate: Decimal,
    term_months: int, deal_months: int, fee: Decimal, fee_financed: bool,
) -> DealProjection:
    if not 1 <= deal_months <= term_months:
        raise ValueError("The new mortgage deal period cannot exceed the remaining repayment term.")

    # A paid-off mortgage does not need a new product or incur a product fee.
    fee = fee if balance else Decimal(0)
    upfront = Decimal(0) if fee_financed else fee
    start = round_money(balance + (fee if fee_financed else Decimal(0)))
    payment = calculate_monthly_payment(start, rate, term_months)
    monthly_rate = rate / 1200
    remaining, total, interest = start, Decimal("0.00"), Decimal("0.00")
    for month in range(1, deal_months + 1):
        if not remaining:
            break
        accrued = round_money(remaining * monthly_rate)
        due = remaining + accrued
        paid = due if month == term_months else min(payment, due)
        remaining = due - paid
        total += paid
        interest += accrued

    return DealProjection(
        payment, start, remaining, calculate_equity(remaining, property_value),
        calculate_ltv(remaining, property_value), total, interest, start - remaining,
        round_money(cash - upfront),
    )
