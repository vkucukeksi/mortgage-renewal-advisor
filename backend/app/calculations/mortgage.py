from decimal import Decimal, ROUND_HALF_UP


TWOPLACES = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    """Round a monetary value to the nearest penny."""
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def calculate_ltv(
    mortgage_balance: Decimal,
    property_value: Decimal,
) -> Decimal:
    """Calculate loan-to-value percentage."""
    if mortgage_balance < 0:
        raise ValueError("Mortgage balance cannot be negative.")

    if property_value <= 0:
        raise ValueError("Property value must be greater than zero.")

    ltv = (mortgage_balance / property_value) * Decimal("100")

    return ltv.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def calculate_equity(
    mortgage_balance: Decimal,
    property_value: Decimal,
) -> Decimal:
    """Calculate property equity."""
    if mortgage_balance < 0:
        raise ValueError("Mortgage balance cannot be negative.")

    if property_value < 0:
        raise ValueError("Property value cannot be negative.")

    return round_money(property_value - mortgage_balance)


def calculate_overpayment_to_target_ltv(
    mortgage_balance: Decimal,
    property_value: Decimal,
    target_ltv_percent: Decimal,
) -> Decimal:
    """Calculate the overpayment required to reach a target LTV."""
    if mortgage_balance < 0:
        raise ValueError("Mortgage balance cannot be negative.")

    if property_value <= 0:
        raise ValueError("Property value must be greater than zero.")

    if target_ltv_percent <= 0 or target_ltv_percent > 100:
        raise ValueError("Target LTV must be between 0 and 100.")

    target_balance = (
        property_value
        * target_ltv_percent
        / Decimal("100")
    )

    overpayment = mortgage_balance - target_balance

    if overpayment < 0:
        return Decimal("0.00")

    return round_money(overpayment)


def calculate_monthly_payment(
    mortgage_balance: Decimal,
    annual_interest_rate_percent: Decimal,
    remaining_term_months: int,
) -> Decimal:
    """Calculate the monthly repayment for a repayment mortgage."""
    if mortgage_balance <= 0:
        raise ValueError("Mortgage balance must be greater than zero.")

    if annual_interest_rate_percent < 0:
        raise ValueError("Interest rate cannot be negative.")

    if remaining_term_months <= 0:
        raise ValueError("Remaining term must be greater than zero.")

    monthly_rate = (
        annual_interest_rate_percent
        / Decimal("100")
        / Decimal("12")
    )

    if monthly_rate == 0:
        return round_money(
            mortgage_balance / Decimal(remaining_term_months)
        )

    repayment_factor = (Decimal("1") + monthly_rate) ** remaining_term_months

    monthly_payment = (
        mortgage_balance
        * monthly_rate
        * repayment_factor
        / (repayment_factor - Decimal("1"))
    )

    return round_money(monthly_payment)