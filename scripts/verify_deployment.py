"""CLI verification of frontend, API contract, and independently known answers."""
import json
import sys
from decimal import Decimal
from urllib.request import Request, urlopen

base = sys.argv[1].rstrip("/")


def fetch(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=60) as response:
        return response.read().decode()


assert 'id="root"' in fetch("/")
assert json.loads(fetch("/health"))["status"] == "healthy"
payload = dict(mortgage_balance=1000, property_value=2000, available_cash=100,
               annual_interest_rate_percent=12, monthly_payment=100,
               months_until_renewal=2, overpayment_options=[0, 100],
               target_ltv_percentages=[40])
result = json.loads(fetch("/api/scenarios", payload))
# Month 1: 1000 + 10 - 100 = 910. Month 2: 910 + 9.10 - 100 = 819.10.
assert Decimal(result["scenarios"][0]["projected_mortgage_balance"]) == Decimal("819.10")
assert Decimal(result["scenarios"][1]["projected_mortgage_balance"]) == Decimal("717.09")
assert result["insights"][0]["kind"] == "target_reached"
payload.update(mortgage_balance=600.01, property_value=1000, months_until_renewal=0,
               overpayment_options=[0], target_ltv_percentages=[60])
assert json.loads(fetch("/api/scenarios", payload))["insights"][0]["kind"] == "target_not_reached"
print(f"PASS: {base}: frontend, health, monthly interest, overpayment, exact LTV boundary")
