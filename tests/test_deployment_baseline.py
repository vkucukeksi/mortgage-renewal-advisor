from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def payload(**changes):
    values = dict(mortgage_balance=600.01, property_value=1000, available_cash=100,
                  annual_interest_rate_percent=0, monthly_payment=0,
                  months_until_renewal=0, overpayment_options=[0],
                  target_ltv_percentages=[60])
    return values | changes


def test_ltv_rounding_cannot_qualify_balance_above_target():
    result = client.post('/api/scenarios', json=payload()).json()
    assert Decimal(result['scenarios'][0]['projected_ltv_percent']) == Decimal('60.00')
    assert result['insights'][0]['kind'] == 'target_not_reached'


def test_exact_target_qualifies():
    result = client.post('/api/scenarios', json=payload(mortgage_balance=600)).json()
    assert result['insights'][0]['kind'] == 'target_already_reached'


@pytest.mark.parametrize('changes', [dict(months_until_renewal=601),
                                    dict(overpayment_options=list(range(101))),
                                    dict(target_ltv_percentages=list(range(101)))])
def test_oversized_calculations_are_rejected(changes):
    assert client.post('/api/scenarios', json=payload(**changes)).status_code == 422
