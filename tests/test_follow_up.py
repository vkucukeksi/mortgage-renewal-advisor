import json

import pytest

from test_ai import SMALL, client, provider
from backend.app.main import follow_up_slot


def ask(question, **changes):
    scenario = SMALL | {"remaining_term_years": 10} | changes
    return client.post("/api/ai/follow-up", json={"question": question, "scenario": scenario})


def choice(value):
    return {"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": value}]},
    ]}


def test_renewal_rate_uses_projected_balances_and_only_calculated_points(provider):
    captured = provider(choice("2"))
    result = ask("What if my renewal interest rate increases to 5%?")
    assert result.status_code == 200
    result = result.json()
    assert "5%" in result["answer"]
    assert result["figures"] == [
        "With a £0.00 overpayment, your estimated monthly repayment is £8.69.",
        "With a £100.00 overpayment, your estimated monthly repayment is £7.61.",
    ]
    assert result["explanation"] == result["figures"][1]
    assert any("12%" in line and "£100.00" in line for line in result["assumptions"])
    assert any("5% renewal rate" in line and "10-year" in line for line in result["assumptions"])
    assert json.loads(captured[0]["input"]) == {"supporting_points": result["figures"]}
    assert captured[0]["max_output_tokens"] == 128
    assert captured[0]["store"] is False


def test_savings_reserve_recalculates_affordable_overpayment(provider):
    provider(choice("2"))
    result = ask("What if I keep £15,000.25 in savings?", mortgage_balance=120000,
                 property_value=200000, available_cash=20000, months_until_renewal=0)
    assert result.status_code == 200
    assert "£4,999.75" in result.json()["answer"]
    assert "£115,000.25" in result.json()["figures"][1]
    assert "£15,000.25 in savings" in result.json()["figures"][1]


@pytest.mark.parametrize("savings, expected", [
    (100, "£18.72"),
    (5, "£13.72 above your available budget"),
])
def test_ltv_search_targets_exact_balance_after_renewal(provider, savings, expected):
    provider(choice("1"))
    result = ask("How much would I need to overpay to reach 40% LTV?",
                 available_cash=savings, overpayment_options=[0])
    assert result.status_code == 200
    assert expected in result.json()["answer"]
    if savings == 100:
        assert "£800.00 at 40.00% LTV" in result.json()["figures"][1]
        lower = client.post("/api/scenarios", json=SMALL | {"overpayment_options": [18.71]})
        assert lower.json()["scenarios"][0]["projected_mortgage_balance"] == "800.01"


@pytest.mark.parametrize("question, changes, detail", [
    ("Recommend a mortgage lender", {}, "Ask one question"),
    ("renewal rate 5%", {"remaining_term_years": None}, "remaining term"),
    ("keep £500", {}, "exceed"),
    ("target 0% LTV", {}, "above 0%"),
    ("renewal rate 101%", {}, "between 0%"),
])
def test_unsupported_or_missing_inputs_never_call_ai(provider, question, changes, detail):
    captured = provider()
    result = ask(question, **changes)
    assert result.status_code == 422
    assert detail in result.json()["detail"]
    assert not captured


@pytest.mark.parametrize("options", [{"status": 503}, {"answer": choice("Invented £500 offer")}])
def test_provider_failure_returns_calculation_without_untrusted_text(provider, options):
    provider(**options)
    response = ask("keep £25")
    assert response.status_code == 200
    data = response.json()
    assert "£75.00" in data["answer"]
    assert data["figures"]
    assert data["assumptions"]
    assert data["explanation"] is None
    assert "Invented" not in response.text


def test_busy_worker_returns_retry_after_without_calling_provider(provider):
    captured = provider()
    assert follow_up_slot.acquire(blocking=False)
    try:
        response = ask("keep £25")
    finally:
        follow_up_slot.release()
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert not captured
