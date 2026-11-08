
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)

REPAYMENT_INPUTS = {
    "mortgage_balance": 325000,
    "property_value": 500000,
    "available_cash": 50000,
    "annual_interest_rate_percent": 1.89,
    "monthly_payment": 1800,
    "months_until_renewal": 6,
    "overpayment_options": [0, 20000],
    "remaining_term_years": 20,
}


def test_repayment_comparison_uses_the_projected_balance_and_default_rates():
    response = client.post("/api/scenarios", json=REPAYMENT_INPUTS)
    assert response.status_code == 200
    baseline, overpayment = response.json()["scenarios"]
    assert baseline["projected_mortgage_balance"] == "317240.76"
    assert overpayment["projected_mortgage_balance"] == "297051.01"
    assert overpayment["cash_remaining"] == "30000"
    for scenario, estimates, differences in [
        (baseline, ["1839.87", "2007.02", "2182.26"], ["39.87", "207.02", "382.26"]),
        (overpayment, ["1722.78", "1879.29", "2043.38"], ["-77.22", "79.29", "243.38"]),
    ]:
        comparisons = scenario["renewal_payments"]
        assert [row["annual_interest_rate_percent"] for row in comparisons] == ["3.5", "4.5", "5.5"]
        assert [row["estimated_monthly_payment"] for row in comparisons] == estimates
        assert [row["change_from_current_monthly_payment"] for row in comparisons] == differences


def test_zero_rate_and_balance_with_custom_term():
    response = client.post("/api/scenarios", json=REPAYMENT_INPUTS | {
        "mortgage_balance": 12000,
        "months_until_renewal": 0,
        "monthly_payment": 100,
        "overpayment_options": [0, 12000],
        "remaining_term_years": 10,
        "renewal_interest_rates_percent": [0, 6.125],
    })
    assert response.status_code == 200
    baseline, paid_off = response.json()["scenarios"]
    assert baseline["renewal_payments"][0] == {
        "annual_interest_rate_percent": "0",
        "estimated_monthly_payment": "100.00",
        "change_from_current_monthly_payment": "0.00",
    }
    assert Decimal(baseline["renewal_payments"][1]["estimated_monthly_payment"]) > 100
    assert all(row["estimated_monthly_payment"] == "0.00"
               and row["change_from_current_monthly_payment"] == "-100.00"
               for row in paid_off["renewal_payments"])


@pytest.mark.parametrize("changes", [
    {"remaining_term_years": 0},
    {"remaining_term_years": 51},
    {"remaining_term_years": 10.5},
    {"remaining_term_years": True},
    {"renewal_interest_rates_percent": []},
    {"renewal_interest_rates_percent": [3.5, "3.50"]},
    {"renewal_interest_rates_percent": [-0.1]},
    {"renewal_interest_rates_percent": [101]},
    {"renewal_interest_rates_percent": ["NaN"]},
    {"renewal_interest_rates_percent": ["0.00001"]},
    {"renewal_interest_rates_percent": list(range(11))},
])
def test_invalid_repayment_inputs_return_422(changes):
    response = client.post("/api/scenarios", json=REPAYMENT_INPUTS | changes)
    assert response.status_code == 422


def test_root_endpoint():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Mortgage Renewal Advisor API is running"
    }


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_create_renewal_scenarios():
    response = client.post(
        "/api/scenarios",
        json={
            "mortgage_balance": 1000,
            "property_value": 2000,
            "available_cash": 100,
            "annual_interest_rate_percent": 12,
            "monthly_payment": 100,
            "months_until_renewal": 2,
            "overpayment_options": [0, 100],
            "target_ltv_percentages": [60],
        },
    )

    assert response.status_code == 200

    data = response.json()
    scenarios = data["scenarios"]
    insights = data["insights"]

    assert len(scenarios) == 2
    assert len(insights) == 2
    assert all(scenario["renewal_payments"] == [] for scenario in scenarios)

    assert float(
        scenarios[0]["projected_mortgage_balance"]
    ) == pytest.approx(819.10)

    assert float(
        scenarios[1]["projected_mortgage_balance"]
    ) == pytest.approx(717.09)

    assert float(
        scenarios[0]["projected_ltv_percent"]
    ) == pytest.approx(40.96)

    assert insights[0]["kind"] == "target_already_reached"
    assert float(insights[0]["target_ltv_percent"]) == 60.0


def test_invalid_property_value_returns_422():
    response = client.post(
        "/api/scenarios",
        json={
            "mortgage_balance": 1000,
            "property_value": 0,
            "available_cash": 100,
            "annual_interest_rate_percent": 12,
            "monthly_payment": 100,
            "months_until_renewal": 2,
            "overpayment_options": [0],
        },
    )

    assert response.status_code == 422


def test_overpayment_above_available_cash_returns_400():
    response = client.post(
        "/api/scenarios",
        json={
            "mortgage_balance": 1000,
            "property_value": 2000,
            "available_cash": 50,
            "annual_interest_rate_percent": 12,
            "monthly_payment": 100,
            "months_until_renewal": 2,
            "overpayment_options": [100],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Overpayment cannot exceed available cash."
    )
