"""Real Blob CAS tests. Set AI_AZURITE_TESTS=1 and run local Azurite first."""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
import threading
from uuid import uuid4

from azure.storage.blob import BlobServiceClient, BlobClient
import pytest

from backend.app.ai_guard import BlobStateStore, GuardUnavailable, Limits, QuotaGuard, State, Throttled


# Supply local configuration through the environment, never through Git.
CONNECTION = os.getenv('AI_AZURITE_CONNECTION_STRING', '')
OPTIONS = dict(api_version='2023-11-03', retry_total=0, connection_timeout=2, read_timeout=3)
pytestmark = pytest.mark.skipif(os.getenv('AI_AZURITE_TESTS') != '1', reason='Local Azurite opt-in')


def blob_for(container):
    parts = dict(item.split('=', 1) for item in CONNECTION.split(';') if '=' in item)
    if (parts.get('BlobEndpoint') != 'http://127.0.0.1:10000/devstoreaccount1'
            or parts.get('AccountName') != 'devstoreaccount1'
            or parts.get('DefaultEndpointsProtocol') != 'http'
            or any(key not in {'DefaultEndpointsProtocol', 'AccountName', 'AccountKey', 'BlobEndpoint'} for key in parts)):
        raise ValueError('Tests require an explicit loopback-only Azurite connection string')
    return BlobClient.from_connection_string(CONNECTION, container, 'state.json', **OPTIONS)


@pytest.mark.parametrize('connection', ['',
    'DefaultEndpointsProtocol=https;AccountName=production;BlobEndpoint=https://example.blob.core.windows.net;',
    'DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;SharedAccessSignature=not-allowed;'])
def test_test_configuration_cannot_target_azure(monkeypatch, connection):
    import sys
    monkeypatch.setattr(sys.modules[__name__], 'CONNECTION', connection)
    with pytest.raises(ValueError, match='loopback-only'):
        blob_for('validation-only')


@pytest.fixture
def container():
    # Validate before even creating a service client or deleting test data.
    blob_for('validation-only').close()
    service = BlobServiceClient.from_connection_string(CONNECTION, **OPTIONS)
    name = 'guard-test-' + uuid4().hex
    service.create_container(name)
    blob_for(name).upload_blob(State(day='2026-01-01').model_dump_json())
    try:
        yield name
    finally:
        service.delete_container(name)
        service.close()


def test_real_conditional_write_rejects_stale_etag(container):
    store = BlobStateStore(blob_for(container))
    first, etag = store.read()
    second, same_etag = store.read()
    first.used = 1
    assert store.write(first, etag)
    second.used = 2
    assert not store.write(second, same_etag)
    assert store.read()[0].used == 1


def test_independent_clients_cannot_overreserve(container):
    guards = [QuotaGuard(BlobStateStore(blob_for(container))) for _ in range(6)]
    barrier = threading.Barrier(len(guards))
    def attempt(guard):
        barrier.wait()
        try:
            return guard.reserve('one-shared-visitor')
        except (Throttled, GuardUnavailable):
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        tickets = list(pool.map(attempt, guards))
    assert sum(ticket is not None for ticket in tickets) == 1
    state, _ = guards[0].store.read()
    assert state.used == 1
    assert len(state.active) == 1


def test_real_minute_daily_and_global_limits(container):
    clock = [1767225600.0]
    guards = [QuotaGuard(BlobStateStore(blob_for(container)), Limits(daily=21), lambda: clock[0])
              for _ in range(2)]
    for index in range(20):
        guard = guards[index % 2]
        if index and index % 3 == 0:
            with pytest.raises(Throttled, match='minute'):
                guard.reserve('same')
            clock[0] += 61
        guard.release(guard.reserve('same'))
    with pytest.raises(Throttled, match='daily'):
        guards[1].reserve('same')
    guards[1].release(guards[1].reserve('other'))
    with pytest.raises(Throttled, match="Today's"):
        guards[0].reserve('third')
    assert guards[0].store.read()[0].used == 21


def test_real_stale_reservation_and_old_owner_release(container):
    clock = [1767225600.0]
    one = QuotaGuard(BlobStateStore(blob_for(container)), clock=lambda: clock[0])
    two = QuotaGuard(BlobStateStore(blob_for(container)), clock=lambda: clock[0])
    first = one.reserve('first')
    clock[0] += 290
    one.renew(first)
    clock[0] += 20
    with pytest.raises(Throttled):
        two.reserve('second')
    clock[0] += 301
    second = two.reserve('second')
    one.release(first)
    assert second in two.store.read()[0].active


@pytest.mark.parametrize('content', [b'broken-json', b'{"day":"2026-01-01","used":-1}',
                                   b'{"day":"2026-01-01","version":2}',
                                   b'{"day":"2026-01-01"}'])
def test_corrupt_blob_fails_closed(container, content):
    blob = blob_for(container)
    blob.upload_blob(content, overwrite=True)
    with pytest.raises(GuardUnavailable):
        QuotaGuard(BlobStateStore(blob)).reserve('one')


def test_missing_blob_is_not_reinitialized(container):
    blob = BlobClient.from_connection_string(CONNECTION, container, 'missing.json', **OPTIONS)
    with pytest.raises(GuardUnavailable):
        QuotaGuard(BlobStateStore(blob)).reserve('one')
    assert not blob.exists()


def _api_worker(container_name, entered, finish, result, hold):
    """Separate Python processes, each with its own FastAPI app and SDK client."""
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from backend.app import main
    os.environ['AI_VISITOR_HASH_KEY'] = 'azurite-test-secret-identical-in-both-workers'
    os.environ.pop('WEBSITE_SITE_NAME', None)
    os.environ.pop('AI_TRUSTED_PROXY_CIDRS', None)
    guard = QuotaGuard(BlobStateStore(blob_for(container_name)))
    def model(*args):
        entered.set()
        if hold and not finish.wait(15):
            raise RuntimeError('Test timeout')
        return 'Mock explanation'
    payload = dict(mortgage_balance=1000, property_value=2000, available_cash=100,
                   annual_interest_rate_percent=12, monthly_payment=100,
                   months_until_renewal=2, overpayment_options=[0,100])
    with patch.object(main, 'get_guard', return_value=guard), patch.object(main, 'explain_results', side_effect=model) as mocked:
        response = TestClient(main.app, client=('192.0.2.1',50000)).post('/api/ai/explain', json=payload)
        result.put((response.status_code, mocked.call_count, response.headers.get('Retry-After')))


def test_two_process_api_concurrency_with_mocked_model(container):
    context = multiprocessing.get_context('spawn')
    entered, finish, result = context.Event(), context.Event(), context.Queue()
    first = context.Process(target=_api_worker, args=(container, entered, finish, result, True))
    second = context.Process(target=_api_worker, args=(container, entered, finish, result, False))
    first.start()
    try:
        assert entered.wait(10)
        second.start()
        rejected = result.get(timeout=10)
        assert rejected[0] == 429 and rejected[1] == 0 and int(rejected[2]) > 0
        finish.set()
        accepted = result.get(timeout=10)
        assert accepted[:2] == (200, 1)
        first.join(5)
        second.join(5)
        assert first.exitcode == second.exitcode == 0
        state, _ = BlobStateStore(blob_for(container)).read()
        assert state.used == 1 and state.active == {}
    finally:
        finish.set()
        for process in (first, second):
            if process.pid and process.is_alive():
                process.terminate()
                process.join(5)
