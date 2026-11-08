from io import BytesIO
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from azure.core.exceptions import ClientAuthenticationError
import pytest

from backend.app import app_service_identity as identity


STORAGE = "https://storage.azure.com/.default"
OPENAI = "https://cognitiveservices.azure.com/.default"


@pytest.fixture
def credential(monkeypatch):
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://127.0.0.1/identity?existing=1")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")
    return identity.AppServiceCredential()


def reply(payload):
    response = BytesIO(json.dumps(payload).encode())
    response.status = 200
    return response


def test_token_request_and_cache_by_resource_until_refresh(credential, monkeypatch):
    clock = [1000]
    requests = []

    def open_token(request, *, timeout):
        assert request.get_method() == "GET"
        assert request.get_header("X-identity-header") == "test-header"
        assert timeout == identity.TOKEN_TIMEOUT
        query = parse_qs(urlsplit(request.full_url).query)
        assert query["api-version"] == ["2019-08-01"]
        assert query["existing"] == ["1"]
        requests.append(query["resource"][0])
        return reply({"access_token": f"test-token-{len(requests)}", "expires_on": "1300"})

    monkeypatch.setattr(identity, "time", lambda: clock[0])
    monkeypatch.setattr(credential._opener, "open", open_token)
    storage_token = credential.get_token(STORAGE)
    assert storage_token.expires_on == 1300
    assert credential.get_token_info(STORAGE).token == storage_token.token
    assert credential.get_token(OPENAI).token != storage_token.token
    clock[0] = 1180
    assert credential.get_token(STORAGE).token != storage_token.token
    assert requests == ["https://storage.azure.com", "https://cognitiveservices.azure.com",
                        "https://storage.azure.com"]


@pytest.mark.parametrize("payload", [
    {"access_token": "invalid-example", "expires_on": "999"},
    {"access_token": "invalid-example", "expires_on": "invalid"},
    {"access_token": "", "expires_on": "1300"},
    {},
])
def test_invalid_responses_are_not_cached_or_exposed(credential, monkeypatch, payload):
    monkeypatch.setattr(identity, "time", lambda: 1000)
    monkeypatch.setattr(credential._opener, "open", lambda *a, **kw: reply(payload))
    with pytest.raises(ClientAuthenticationError, match="^App Service token request failed\\.$"):
        credential.get_token(STORAGE)
    monkeypatch.setattr(credential._opener, "open",
                        lambda *a, **kw: reply({"access_token": "test-recovery", "expires_on": "1300"}))
    assert credential.get_token(STORAGE).token == "test-recovery"


@pytest.mark.parametrize("failure, message", [
    (TimeoutError("sensitive diagnostic text"), "timed out"),
    (HTTPError("http://127.0.0.1", 403, "sensitive diagnostic text", {}, None), "failed"),
])
def test_transport_failures_are_sanitized_and_not_retried(credential, monkeypatch, failure, message):
    requests = []

    def fail(*args, **kwargs):
        requests.append(args)
        raise failure

    monkeypatch.setattr(credential._opener, "open", fail)
    with pytest.raises(ClientAuthenticationError, match=f"^App Service token request {message}\\.$"):
        credential.get_token(STORAGE)
    assert len(requests) == 1


def test_missing_identity_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("IDENTITY_HEADER", raising=False)
    with pytest.raises(ClientAuthenticationError, match="not configured"):
        identity.AppServiceCredential()
