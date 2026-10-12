from decimal import Decimal

from .mortgage import round_money


def project_mortgage_balance(
    mortgage_balance: Decimal,
    annual_interest_rate_percent: Decimal,
    monthly_payment: Decimal,
    months: int,
) -> Decimal:
    """Estimate the mortgage balance after regular monthly payments."""

    if mortgage_balance < 0:
        raise ValueError("Mortgage balance cannot be negative.")

    if annual_interest_rate_percent < 0:
        raise ValueError("Interest rate cannot be negative.")

    if monthly_payment < 0:
        raise ValueError("Monthly payment cannot be negative.")

    if months < 0:
        raise ValueError("Months cannot be negative.")

    balance = round_money(mortgage_balance)

    monthly_rate = (
        annual_interest_rate_percent
        / Decimal("100")
        / Decimal("12")
    )

    for _ in range(months):
        interest = round_money(balance * monthly_rate)

        balance = round_money(
            balance + interest - monthly_payment
        )

        # A mortgage balance cannot fall below zero.
        if balance <= 0:
            return Decimal("0.00")

    return balance