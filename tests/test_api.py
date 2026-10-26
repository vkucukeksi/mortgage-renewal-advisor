
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


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
