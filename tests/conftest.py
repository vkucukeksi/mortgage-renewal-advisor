import threading

import pytest

from backend.app import main
from backend.app.ai_guard import QuotaGuard, State


class MemoryStateStore:
    """CAS fake for deterministic unit tests, never a production fallback."""
    def __init__(self, day="2026-01-01"):
        self.state = State(day=day)
        self.etag = 0
        self.lock = threading.Lock()

    def read(self):
        with self.lock:
            return self.state.model_copy(deep=True), self.etag

    def write(self, state, etag):
        with self.lock:
            if etag != self.etag:
                return False
            self.state = state.model_copy(deep=True)
            self.etag += 1
            return True


@pytest.fixture
def quota_guard(monkeypatch):
    store = MemoryStateStore()
    guard = QuotaGuard(store)
    monkeypatch.setattr(main, "get_guard", lambda: guard)
    monkeypatch.setenv("AI_VISITOR_HASH_KEY", "test-only-visitor-hmac-secret-32-bytes-long")
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    monkeypatch.delenv("AI_TRUSTED_PROXY_CIDRS", raising=False)
    return guard
