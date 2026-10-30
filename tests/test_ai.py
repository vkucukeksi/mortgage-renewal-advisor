import json
import sys
from types import ModuleType, SimpleNamespace
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import ai
from backend.app.main import app

client = TestClient(app)
SMALL = dict(mortgage_balance=1000, property_value=2000, available_cash=100,
             annual_interest_rate_percent=12, monthly_payment=100,
             months_until_renewal=2, overpayment_options=[0, 100], target_ltv_percentages=[40])
EXAMPLE = dict(mortgage_balance=325000, property_value=500000, available_cash=50000,
               annual_interest_rate_percent=1.89, monthly_payment=1800,
               months_until_renewal=6, overpayment_options=[0, 10000, 20000, 25000, 30000, 50000],
               target_ltv_percentages=[60, 55, 50])
ANSWER = {'status': 'completed', 'output': [
    {'type': 'message', 'content': [{'type': 'output_text', 'text': 'An explanation of the tested scenarios.'}]}]}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://example.openai.azure.com')
    monkeypatch.setenv('AZURE_OPENAI_DEPLOYMENT', 'test-deployment')
    monkeypatch.setattr(ai, '_access_token', lambda: 'test-token')
    original = httpx.Client
    captured = []

    def configure(answer=ANSWER, status=200, timeout=False):
        def respond(request):
            captured.append(json.loads(request.content))
            assert request.headers['Authorization'] == 'Bearer test-token'
            assert str(request.url) == 'https://example.openai.azure.com/openai/v1/responses'
            if timeout:
                raise httpx.ReadTimeout('private provider details', request=request)
            return httpx.Response(status, json=answer, request=request)
        monkeypatch.setattr(ai.httpx, 'Client', lambda **kwargs: original(
            **kwargs, transport=httpx.MockTransport(respond)))
        return captured
    return configure


@pytest.mark.parametrize('inputs', [SMALL, EXAMPLE])
def test_explanation_uses_engine_results(inputs, provider):
    captured = provider()
    expected = client.post('/api/scenarios', json=inputs).json()
    result = client.post('/api/ai/explain', json=inputs)
    assert result.status_code == 200
    assert result.json()['explanation'] == ANSWER['output'][0]['content'][0]['text']
    sent = captured[0]
    assert json.loads(sent['input'])['engine_results'] == expected
    assert sent['model'] == 'test-deployment'
    assert sent['store'] is False
    if inputs == SMALL:
        assert Decimal(expected['scenarios'][0]['projected_mortgage_balance']) == Decimal('819.10')
        assert Decimal(expected['scenarios'][1]['projected_mortgage_balance']) == Decimal('717.09')


@pytest.mark.parametrize('changes, status', [({'property_value': 0}, 422),
    ({'overpayment_options': [101]}, 400), ({'months_until_renewal': 601}, 422)])
def test_invalid_inputs_never_call_ai(changes, status, provider):
    captured = provider()
    assert client.post('/api/ai/explain', json=SMALL | changes).status_code == status
    assert captured == []


@pytest.mark.parametrize('kwargs', [dict(status=401), dict(status=429), dict(status=500),
    dict(timeout=True), dict(answer={'status': 'completed', 'output': []}),
    dict(answer={'status': 'incomplete', 'output': ANSWER['output']}),
    dict(answer={'output': 'invalid'}), dict(answer={'status': 'completed', 'output': [
        {'type': 'message', 'content': [{'type': 'refusal'}]}]})])
def test_provider_failure_keeps_calculations_available(kwargs, provider):
    provider(**kwargs)
    result = client.post('/api/ai/explain', json=SMALL)
    assert result.status_code == 503
    assert 'test-token' not in result.text
    assert 'private provider details' not in result.text
    assert client.post('/api/scenarios', json=SMALL).status_code == 200


def test_missing_config_does_not_require_identity(monkeypatch):
    monkeypatch.delenv('AZURE_OPENAI_ENDPOINT', raising=False)
    monkeypatch.delenv('AZURE_OPENAI_DEPLOYMENT', raising=False)
    result = client.post('/api/ai/explain', json=SMALL)
    assert result.status_code == 503
    assert 'not configured' in result.json()['detail']


def test_auth_failure_is_safe(provider, monkeypatch):
    provider()
    def fail():
        raise ai.AIUnavailable('AI authentication is unavailable.')
    monkeypatch.setattr(ai, '_access_token', fail)
    assert client.post('/api/ai/explain', json=SMALL).status_code == 503


@pytest.mark.parametrize('hosted', [False, True])
def test_identity_selection_and_token_scope(monkeypatch, hosted):
    used = []
    scopes = []
    class Credential:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            used.append('closed')
        def get_token(self, scope):
            scopes.append(scope)
            return SimpleNamespace(token='identity-token')
    identity = ModuleType('azure.identity')
    def managed(**kwargs):
        used.append(('managed', kwargs))
        return Credential()
    def default(**kwargs):
        used.append(('default', kwargs))
        return Credential()
    identity.ManagedIdentityCredential = managed
    identity.DefaultAzureCredential = default
    monkeypatch.setitem(sys.modules, 'azure', ModuleType('azure'))
    monkeypatch.setitem(sys.modules, 'azure.identity', identity)
    monkeypatch.setenv('AZURE_CLIENT_ID', 'identity-client-id')
    if hosted:
        monkeypatch.setenv('IDENTITY_ENDPOINT', 'http://localhost/identity')
    else:
        monkeypatch.delenv('IDENTITY_ENDPOINT', raising=False)
    assert ai._access_token() == 'identity-token'
    assert used[0] == (('managed', {'client_id': 'identity-client-id'}) if hosted
                       else ('default', {'managed_identity_client_id': 'identity-client-id'}))
    assert used[-1] == 'closed'
    assert scopes == ['https://cognitiveservices.azure.com/.default']


def test_ai_receives_exact_ltv_boundary_findings(provider):
    captured = provider()
    response = client.post('/api/ai/explain', json=SMALL | dict(
        mortgage_balance=600.01, property_value=1000, months_until_renewal=0,
        overpayment_options=[0], target_ltv_percentages=[60]))
    assert response.status_code == 200
    results = json.loads(captured[0]['input'])['engine_results']
    assert results['insights'][0]['kind'] == 'target_not_reached'
