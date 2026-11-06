import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi import Request
from fastapi.testclient import TestClient
import pytest

from backend.app import main
from backend.app.ai import AIUnavailable
from backend.app.ai_guard import (
    GuardUnavailable, Limits, QuotaGuard, Throttled, get_guard, visitor_key,
)
from backend.app.body_limit import AIBodyLimit
from conftest import MemoryStateStore


SMALL = dict(mortgage_balance=1000, property_value=2000, available_cash=100,
             annual_interest_rate_percent=12, monthly_payment=100,
             months_until_renewal=2, overpayment_options=[0, 100])


def test_minute_and_daily_quotas():
    clock = [1767225600.0]
    guard = QuotaGuard(MemoryStateStore(), clock=lambda: clock[0])
    for index in range(20):
        if index and index % 3 == 0:
            clock[0] += 61
        ticket = guard.reserve('visitor')
        guard.release(ticket)
        if index < 18 and index % 3 == 2:
            with pytest.raises(Throttled) as error:
                guard.reserve('visitor')
            assert 1 <= error.value.retry_after <= 60
    with pytest.raises(Throttled, match='daily'):
        guard.reserve('visitor')
    assert guard.store.state.used == 20


def test_global_daily_quota_across_visitors_and_reset():
    clock = [1767225600.0]
    guard = QuotaGuard(MemoryStateStore(), Limits(daily=2), clock=lambda: clock[0])
    for name in ('one', 'two'):
        guard.release(guard.reserve(name))
    with pytest.raises(Throttled, match="Today's"):
        guard.reserve('three')
    clock[0] += 86400
    guard.release(guard.reserve('three'))
    assert guard.store.state.used == 1


def test_one_concurrent_request_and_stale_release():
    clock = [1767225600.0]
    guard = QuotaGuard(MemoryStateStore(), clock=lambda: clock[0])
    first = guard.reserve('one')
    with pytest.raises(Throttled, match='Another'):
        guard.reserve('two')
    clock[0] += 301
    second = guard.reserve('two')
    guard.release(first)
    assert second in guard.store.state.active
    assert guard.store.state.used == 2


def test_minute_and_concurrency_survive_midnight():
    clock = [1767311999.0]
    guard = QuotaGuard(MemoryStateStore(), clock=lambda: clock[0])
    for _ in range(2):
        guard.release(guard.reserve('one'))
    first = guard.reserve('one')
    clock[0] += 2
    with pytest.raises(Throttled, match='Another'):
        guard.reserve('two')
    guard.release(first)
    with pytest.raises(Throttled, match='minute'):
        guard.reserve('one')


def test_heartbeat_renews_live_reservation_and_stops():
    guard = QuotaGuard(MemoryStateStore(), Limits(heartbeat_seconds=.01))
    called = threading.Event()
    original = guard.renew
    def renew(ticket):
        original(ticket)
        called.set()
    guard.renew = renew
    with guard.admission('one'):
        assert called.wait(2)
        with pytest.raises(Throttled):
            guard.reserve('two')
    assert not guard.store.state.active


def test_conflicting_updates_retry_without_double_admission():
    store = MemoryStateStore()
    guards = [QuotaGuard(store) for _ in range(8)]
    barrier = threading.Barrier(8)
    def attempt(guard):
        barrier.wait()
        try:
            return guard.reserve('same-visitor')
        except (Throttled, GuardUnavailable):
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        tickets = list(pool.map(attempt, guards))
    assert len([ticket for ticket in tickets if ticket]) == 1
    assert store.state.used == 1


def test_exhausted_cas_conflicts_fail_closed():
    store = MemoryStateStore()
    store.write = lambda *args: False
    with pytest.raises(GuardUnavailable):
        QuotaGuard(store).reserve('one')


def test_provider_error_counts_attempt_and_releases_slot(quota_guard, monkeypatch):
    def fail(*args):
        raise AIUnavailable('Provider unavailable')
    monkeypatch.setattr(main, 'explain_results', fail)
    client = TestClient(main.app, client=('192.0.2.1', 50000))
    assert client.post('/api/ai/explain', json=SMALL).status_code == 503
    assert quota_guard.store.state.used == 1
    assert quota_guard.store.state.active == {}


def test_store_unavailable_never_calls_model_or_breaks_calculator(quota_guard, monkeypatch):
    def fail():
        raise GuardUnavailable()
    quota_guard.store.read = fail
    calls = []
    monkeypatch.setattr(main, 'explain_results', lambda *args: calls.append(args))
    client = TestClient(main.app, client=('192.0.2.1', 50000))
    response = client.post('/api/ai/explain', json=SMALL)
    assert response.status_code == 503
    assert calls == []
    assert client.post('/api/scenarios', json=SMALL).status_code == 200


def test_unconfigured_store_has_no_in_memory_fallback(monkeypatch):
    get_guard.cache_clear()
    monkeypatch.delenv('AI_QUOTA_CONTAINER', raising=False)
    with pytest.raises(GuardUnavailable):
        get_guard()


def ip_request(peer, forwarded=None):
    return Request({'type':'http', 'client':(peer, 1234),
                    'headers':[] if forwarded is None else [(b'x-forwarded-for', forwarded.encode())]})


def test_ip_hash_and_untrusted_headers(quota_guard):
    direct = visitor_key(ip_request('192.0.2.1'))
    assert direct == visitor_key(ip_request('192.0.2.1', '198.51.100.1'))
    assert direct == visitor_key(ip_request('::ffff:192.0.2.1'))
    assert len(direct) == 64 and '192.0.2.1' not in direct


def test_forwarded_client_ports_normalize(quota_guard, monkeypatch):
    monkeypatch.setenv('AI_TRUSTED_PROXY_CIDRS', '10.0.0.2/32')
    assert visitor_key(ip_request('10.0.0.2', '192.0.2.1:12345')) == visitor_key(ip_request('192.0.2.1'))
    assert visitor_key(ip_request('10.0.0.2', '[2001:db8::1]:443')) == visitor_key(ip_request('2001:db8::1'))


def test_missing_hash_secret_fails_closed(quota_guard, monkeypatch):
    monkeypatch.delenv('AI_VISITOR_HASH_KEY')
    with pytest.raises(GuardUnavailable):
        visitor_key(ip_request('192.0.2.1'))


def test_ambiguous_admission_write_does_not_call_model(quota_guard, monkeypatch):
    original = quota_guard.store.write
    def ambiguous(state, etag):
        original(state, etag)
        raise GuardUnavailable()
    quota_guard.store.write = ambiguous
    calls = []
    monkeypatch.setattr(main, 'explain_results', lambda *args: calls.append(args))
    result = TestClient(main.app, client=('192.0.2.1', 1)).post('/api/ai/explain', json=SMALL)
    assert result.status_code == 503
    assert not calls
    assert quota_guard.store.state.used == 1
    assert len(quota_guard.store.state.active) == 1


def test_release_failure_keeps_usage_and_reservation(quota_guard, monkeypatch):
    def model(*args):
        def fail(*args):
            raise GuardUnavailable()
        quota_guard.store.write = fail
        return 'Explanation'
    monkeypatch.setattr(main, 'explain_results', model)
    result = TestClient(main.app, client=('192.0.2.1', 1)).post('/api/ai/explain', json=SMALL)
    assert result.status_code == 200
    assert quota_guard.store.state.used == 1
    assert len(quota_guard.store.state.active) == 1


def test_failed_heartbeat_does_not_return_success():
    guard = QuotaGuard(MemoryStateStore(), Limits(heartbeat_seconds=.01))
    attempted = threading.Event()
    def fail(ticket):
        attempted.set()
        raise GuardUnavailable()
    guard.renew = fail
    with pytest.raises(GuardUnavailable):
        with guard.admission('one'):
            assert attempted.wait(2)
    assert guard.store.state.used == 1


def test_visitor_http_429_headers_and_no_extra_model_call(quota_guard, monkeypatch):
    calls = []
    monkeypatch.setattr(main, 'explain_results', lambda *args: calls.append(args) or 'Explanation')
    client = TestClient(main.app, client=('192.0.2.1', 1))
    for _ in range(3):
        assert client.post('/api/ai/explain', json=SMALL).status_code == 200
    denied = client.post('/api/ai/explain', json=SMALL)
    assert denied.status_code == 429
    assert 1 <= int(denied.headers['Retry-After']) <= 60
    assert len(calls) == 3


def test_trusted_proxy_ignores_spoofed_prefix(quota_guard, monkeypatch):
    monkeypatch.setenv('AI_TRUSTED_PROXY_CIDRS', '10.0.0.2/32')
    monkeypatch.setenv('WEBSITE_SITE_NAME', 'production')
    key = visitor_key(ip_request('10.0.0.2', '192.0.2.1'))
    assert key == visitor_key(ip_request('10.0.0.2', '198.51.100.7, 192.0.2.1'))
    assert key == visitor_key(ip_request('10.0.0.2', '192.0.2.1, 10.0.0.2'))
    with pytest.raises(GuardUnavailable):
        visitor_key(ip_request('10.0.0.3', '192.0.2.1'))
    for value in (None, 'not-an-ip', '10.0.0.2'):
        with pytest.raises(GuardUnavailable):
            visitor_key(ip_request('10.0.0.2', value))


@pytest.mark.parametrize('changes', [dict(overpayment_options=list(range(11))),
    dict(target_ltv_percentages=[10,20,30,40,50,60]), dict(extra='ignored?'),
    dict(mortgage_balance='1e100'), dict(property_value='0.001'),
    dict(annual_interest_rate_percent=26)])
def test_paid_endpoint_validation_prevents_calls(changes, quota_guard, monkeypatch):
    calls = []
    monkeypatch.setattr(main, 'explain_results', lambda *args: calls.append(args))
    response = TestClient(main.app).post('/api/ai/explain', json=SMALL | changes)
    assert response.status_code == 422
    assert quota_guard.store.state.used == 0
    assert not calls


def test_exact_ai_boundaries_and_calculator_keeps_its_limits(quota_guard, monkeypatch):
    monkeypatch.setattr(main, 'explain_results', lambda *args: 'Explanation')
    client = TestClient(main.app, client=('192.0.2.1', 50000))
    assert client.post('/api/ai/explain', json=SMALL | dict(
        overpayment_options=list(range(10)), target_ltv_percentages=[10,20,30,40,50])).status_code == 200
    assert client.post('/api/scenarios', json=SMALL | dict(overpayment_options=list(range(100)))).status_code == 200


@pytest.mark.parametrize('declared', [None, b'1', b'16385'])
def test_body_limit_before_parser_with_chunked_or_false_length(declared):
    reached = []
    async def app(*args):
        reached.append(True)
    async def exercise():
        chunks = iter([{'type':'http.request', 'body':b'x'*8192, 'more_body':True},
                       {'type':'http.request', 'body':b'x'*8193, 'more_body':False}])
        async def receive():
            return next(chunks)
        sent = []
        async def send(message):
            sent.append(message)
        headers = [] if declared is None else [(b'content-length', declared)]
        await AIBodyLimit(app)({'type':'http','method':'POST','path':'/api/ai/explain',
                                'headers':headers}, receive, send)
        assert sent[0]['status'] == 413
    asyncio.run(exercise())
    assert not reached


def test_body_boundary_replayed_and_compressed_rejected(quota_guard, monkeypatch):
    import json
    monkeypatch.setattr(main, 'explain_results', lambda *args: 'Explanation')
    client = TestClient(main.app, client=('192.0.2.1', 50000))
    body = json.dumps(SMALL).encode()
    body += b' ' * (16384 - len(body))
    assert client.post('/api/ai/explain', content=body, headers={'Content-Type':'application/json'}).status_code == 200
    assert client.post('/api/ai/explain', content=body + b' ').status_code == 413
    assert client.post('/api/ai/explain', content=body, headers={'Content-Encoding':'gzip'}).status_code == 415


def test_api_second_inflight_request_is_429_without_provider_call(quota_guard, monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    calls = []
    def model(*args):
        calls.append(True)
        entered.set()
        assert finish.wait(5)
        return 'Explanation'
    monkeypatch.setattr(main, 'explain_results', model)
    def first():
        return TestClient(main.app, client=('192.0.2.1', 1)).post('/api/ai/explain', json=SMALL)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(first)
        assert entered.wait(3)
        try:
            result = TestClient(main.app, client=('192.0.2.2', 1)).post('/api/ai/explain', json=SMALL)
            assert result.status_code == 429
            assert int(result.headers['Retry-After']) > 0
            assert len(calls) == 1
        finally:
            finish.set()
        assert future.result().status_code == 200
