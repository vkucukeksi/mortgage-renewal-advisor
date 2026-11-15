"""Parse supported follow-ups and calculate an exact LTV threshold."""
from decimal import Decimal
import re

from ..calculations.projections import project_mortgage_balance


HELP = ("Ask one question about a renewal rate, savings to keep, or an LTV target. "
        "Use a suggested question as a starting point.")
PERCENT = r"(\d{1,3}(?:\.\d{1,4})?)\s*%"
MONEY = r"£?\s*((?:\d{1,12}|\d{1,3}(?:,\d{3}){1,3})(?:\.\d{1,2})?)"
PATTERNS = {
    "rate": rf"(?:what if (?:my )?)?(?:renewal (?:interest )?rate|interest rate at renewal)(?: (?:increases to|rises to|falls to|is|of|at))?\s*{PERCENT}",
    "savings": rf"(?:what if (?:i )?)?keep\s*{MONEY}(?: in savings)?",
    "ltv": rf"(?:how much (?:would|do) i need to overpay to reach |overpayment (?:to reach|for) |reach |target )?{PERCENT}\s*ltv",
}


def parse_question(question: str) -> tuple[str, Decimal]:
    normalized = " ".join(question.casefold().split()).removesuffix("?").rstrip()
    for kind, pattern in PATTERNS.items():
        match = re.fullmatch(pattern, normalized)
        if match:
            value = Decimal(match[1].replace(",", ""))
            if kind == "rate" and value > 100:
                raise ValueError("Enter a renewal rate between 0% and 100%.")
            if kind == "ltv" and not 0 < value <= 100:
                raise ValueError("Enter an LTV target above 0% and up to 100%.")
            return kind, value
    raise ValueError(HELP)


def minimum_overpayment(
    balance: Decimal,
    property_value: Decimal,
    current_rate: Decimal,
    payment: Decimal,
    months: int,
    target: Decimal,
) -> Decimal:
    """Find the first whole penny that meets the unrounded LTV target."""
    def meets(pennies: int) -> bool:
        projected = project_mortgage_balance(
            balance - Decimal(pennies) / 100, current_rate, payment, months,
        )
        return projected * 100 <= target * property_value

    low, high = 0, int(balance * 100)
    while low < high:
        middle = (low + high) // 2
        if meets(middle):
            high = middle
        else:
            low = middle + 1
    return Decimal(low) / 100
