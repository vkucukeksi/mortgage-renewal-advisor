from decimal import Decimal

import pytest

from backend.app.calculations.deals import project_deal
from test_ai import EXAMPLE, client, provider
from test_follow_up import ask, choice


@pytest.mark.parametrize("months", [1, 17, 24, 36, 60, 120])
def test_zero_rate_projection_matches_an_independent_linear_schedule(months):
    deal = project_deal(Decimal("240000"), Decimal("400000"), Decimal("50000"),
                        Decimal(0), 240, months, Decimal(0), False)
    assert deal.estimated_monthly_payment == 1000
    assert deal.ending_balance == 240000 - 1000 * months
    assert deal.ending_equity == 160000 + 1000 * months
    assert deal.ending_ltv_percent == Decimal(240000 - 1000 * months) / 4000
    assert deal.total_payments == deal.principal_repaid == 1000 * months
    assert deal.interest_paid == 0


def test_comparison_uses_distinct_terms_rates_and_fees():
    data = EXAMPLE | dict(
        remaining_term_years=20, deal_duration_months=24, overpayment_options=[0, 20000],
        renewal_interest_rates_percent=[4],
        primary_deal_fee={"product_fee": 899, "fee_treatment": "upfront"},
        comparison_deals=[{"duration_months": 60, "annual_interest_rate_percent": 5,
                           "product_fee": 1499, "fee_treatment": "financed"}],
    )
    response = client.post("/api/scenarios", json=data)
    assert response.status_code == 200
    no_overpay, overpay = response.json()["scenarios"]
    primary, comparison = no_overpay["deal_projections"]
    assert primary["balance_at_start"] == no_overpay["projected_mortgage_balance"]
    assert Decimal(primary["cash_after_upfront_fee"]) == 49101
    assert Decimal(comparison["cash_after_upfront_fee"]) == 50000
    assert Decimal(comparison["balance_at_start"]) == Decimal(primary["balance_at_start"]) + 1499
    assert Decimal(comparison["estimated_monthly_payment"]) > Decimal(primary["estimated_monthly_payment"])
    assert overpay["deal_projections"][1]["ending_balance"] != comparison["ending_balance"]
    for deal in (primary, comparison):
        assert Decimal(deal["total_payments"]) == Decimal(deal["interest_paid"]) + Decimal(deal["principal_repaid"])
        assert Decimal(deal["ending_balance"]) + Decimal(deal["ending_equity"]) == 500000


def test_nonzero_rate_reference_and_different_repayment_terms():
    args = [Decimal("120000"), Decimal("300000"), Decimal("30000"), Decimal("6")]
    short = project_deal(*args, 120, 1, Decimal(0), False)
    long = project_deal(*args, 240, 1, Decimal(0), False)
    assert short.estimated_monthly_payment == Decimal("1332.25")
    assert long.estimated_monthly_payment == Decimal("859.72")
    assert short.interest_paid == long.interest_paid == 600
    assert short.ending_balance == Decimal("119267.75")
    assert long.ending_balance == Decimal("119740.28")


@pytest.mark.parametrize("balance, term, period, payment, total", [
    ("0.00", 12, 12, "0.00", "0.00"),
    ("0.07", 12, 10, "0.01", "0.07"),
    ("0.04", 12, 12, "0.00", "0.04"),
    ("12.05", 12, 12, "1.00", "12.05"),
])
def test_early_payoff_and_final_payment_rounding(balance, term, period, payment, total):
    deal = project_deal(Decimal(balance), Decimal(100), Decimal(20), Decimal(0),
                        term, period, Decimal(0), True)
    assert deal.estimated_monthly_payment == Decimal(payment)
    assert deal.total_payments == Decimal(total)
    assert deal.ending_balance == 0


def test_full_payoff_does_not_open_a_new_loan_or_charge_a_fee():
    deal = project_deal(Decimal(0), Decimal(100), Decimal(20), Decimal(5),
                        120, 24, Decimal(9), True)
    assert deal.ending_balance == deal.estimated_monthly_payment == 0
    assert deal.cash_after_upfront_fee == 20


@pytest.mark.parametrize("overrides", [
    {"deal_duration_months": 37}, {"deal_duration_months": 0}, {"deal_duration_months": 2.5},
    {"comparison_deals": [{"duration_months": 37, "annual_interest_rate_percent": 4}]},
    {"comparison_deals": [{"duration_months": 24, "annual_interest_rate_percent": 4, "product_fee": -1}]},
    {"primary_deal_fee": {"product_fee": 100, "fee_treatment": "deduct"}},
    {"remaining_term_years": None, "deal_duration_months": 24},
])
def test_invalid_deals_are_rejected(overrides):
    assert client.post("/api/scenarios", json=EXAMPLE | {"remaining_term_years": 3} | overrides).status_code == 422


def test_default_deal_for_existing_clients_respects_a_short_term():
    response = client.post("/api/scenarios", json=EXAMPLE | {"remaining_term_years": 1})
    assert response.json()["scenarios"][0]["deal_projections"][0]["duration_months"] == 12


def test_ai_returns_only_backend_deal_points_and_safe_trade_offs(provider):
    captured = provider(choice("1"))
    data = EXAMPLE | dict(remaining_term_years=20, deal_duration_months=24, overpayment_options=[0])
    response = client.post("/api/ai/explain", json=data)
    assert response.status_code == 200
    assert "24-month deal" in response.json()["explanation"]
    assert "unknown rates" in response.json()["explanation"]
    assert captured[0]["max_output_tokens"] == 128
    provider(choice("Invented 1% deal"))
    assert client.post("/api/ai/explain", json=data).status_code == 503


def test_deal_followup_keeps_calculated_results_when_ai_is_down(provider):
    provider(status=503)
    result = ask("What if my deal period is 5 years?", deal_duration_months=24)
    assert result.status_code == 200
    data = result.json()
    assert "60-month primary deal" in data["answer"]
    assert all("60-month deal" in point for point in data["figures"])
    assert data["explanation"] is None
    assert ask("deal period 121 months").status_code == 422


def test_upfront_fee_shortfall_does_not_change_the_loan():
    deal = project_deal(Decimal(100), Decimal(200), Decimal(1), Decimal(0),
                        12, 1, Decimal(9), False)
    assert deal.cash_after_upfront_fee == -8
    assert deal.balance_at_start == 100


def test_followup_reserve_discloses_upfront_product_fee(provider):
    provider(choice("1"))
    response = ask("keep £25", deal_duration_months=24,
                   primary_deal_fee={"product_fee": 50, "fee_treatment": "upfront"})
    assert response.status_code == 200
    assert "before any upfront product fees" in response.json()["answer"]
