"""Cross-process AI admission control. No financial inputs or raw IPs are stored."""
from contextlib import contextmanager
from contextvars import copy_context
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
import hashlib
import hmac
import ipaddress
import json
import math
import os
import threading
import time
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .ai_diagnostics import ai_stage, azure_credential


class GuardUnavailable(Exception):
    pass


class Throttled(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = max(1, math.ceil(retry_after))


class Visitor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    count: int = Field(default=0, ge=0)
    times: list[float] = Field(default_factory=list, max_length=3)


class State(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: int = Field(default=1, ge=1, le=1)
    day: str
    used: int = Field(default=0, ge=0)
    visitors: dict[str, Visitor] = Field(default_factory=dict)
    active: dict[str, float] = Field(default_factory=dict)
    cooldown: float = Field(default=0, ge=0)

    @field_validator("day")
    @classmethod
    def valid_day(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Invalid quota date")
        return value


@dataclass(frozen=True)
class Limits:
    daily: int = 50
    reservation_seconds: int = 300
    heartbeat_seconds: float = 30


class BlobStateStore:
    """Only conditional writes; never overwrite counters after a lost race."""
    def __init__(self, blob):
        self.blob = blob

    def read(self):
        try:
            with ai_stage("quota.blob.read"):
                download = self.blob.download_blob()
                if download.properties.size > 128 * 1024:
                    raise GuardUnavailable()
                raw = download.readall()
            with ai_stage("quota.state.validate"):
                if set(json.loads(raw)) != set(State.model_fields):
                    raise ValueError("Incomplete quota state")
                return State.model_validate_json(raw), download.properties.etag
        except Exception as exc:
            # Missing/corrupt state is NOT initialized at runtime: that could
            # silently reset daily quotas after deletion or configuration errors.
            raise GuardUnavailable("AI quota store is unavailable.") from exc

    def write(self, state, etag):
        from azure.core import MatchConditions
        from azure.core.exceptions import HttpResponseError
        try:
            with ai_stage("quota.blob.write"):
                try:
                    self.blob.upload_blob(state.model_dump_json(), overwrite=True,
                                          etag=etag, match_condition=MatchConditions.IfNotModified)
                except HttpResponseError as exc:
                    if exc.status_code == 412:
                        return False
                    raise
            return True
        except Exception as exc:
            # An ambiguous write may have committed. Do not admit a provider
            # call or refund/retry a reservation when the outcome is unknown.
            raise GuardUnavailable("AI quota store is unavailable.") from exc


class _StorageCredential:
    def __init__(self, credential):
        self.credential = credential

    def get_token(self, *scopes, **kwargs):
        with ai_stage("quota.identity.token"):
            return self.credential.get_token(*scopes, **kwargs)

    def get_token_info(self, *scopes, **kwargs):
        with ai_stage("quota.identity.token"):
            return self.credential.get_token_info(*scopes, **kwargs)


def _day(now):
    return datetime.fromtimestamp(now, timezone.utc).date().isoformat()


class QuotaGuard:
    def __init__(self, store, limits=Limits(), clock=time.time):
        self.store, self.limits, self.clock = store, limits, clock

    def _change(self, change):
        for _ in range(8):
            state, etag = self.store.read()
            result = change(state, self.clock())
            if self.store.write(state, etag):
                return result
        raise GuardUnavailable("AI quota store is busy.")

    def reserve(self, visitor):
        ticket = uuid4().hex

        def admit(state, now):
            today = _day(now)
            # Keep concurrency and cooldown across midnight. Minute limits
            # also cross midnight; only UTC daily counters reset.
            if state.day > today:
                raise GuardUnavailable("AI quota clock is inconsistent.")
            if state.day != today:
                state.day, state.used = today, 0
                state.visitors = {
                    key: Visitor(times=[t for t in value.times if t > now - 60])
                    for key, value in state.visitors.items()
                    if any(t > now - 60 for t in value.times)
                }
            midnight = (int(now // 86400) + 1) * 86400
            if state.cooldown > now:
                raise Throttled("AI is temporarily busy. Please wait before trying again.", state.cooldown - now)
            if state.used >= self.limits.daily:
                raise Throttled("Today's AI allowance has been reached. Mortgage calculations are still available.", midnight - now)
            record = state.visitors.get(visitor, Visitor())
            if record.count >= 20:
                raise Throttled("You have reached your daily AI allowance. Please try again tomorrow.", midnight - now)
            record.times = [t for t in record.times if t > now - 60]
            if len(record.times) >= 3:
                raise Throttled("You can request three AI explanations per minute. Please wait.", record.times[0] + 60 - now)
            state.active = {key: expiry for key, expiry in state.active.items() if expiry > now}
            if state.active:
                raise Throttled("Another AI explanation is being prepared. Please try again shortly.", 5)
            record.count += 1
            record.times.append(now)
            state.visitors[visitor] = record
            state.used += 1
            state.active[ticket] = now + self.limits.reservation_seconds
            return ticket

        return self._change(admit)

    def renew(self, ticket):
        def extend(state, now):
            if state.active.get(ticket, 0) <= now:
                raise GuardUnavailable("AI reservation expired.")
            state.active[ticket] = now + self.limits.reservation_seconds
        self._change(extend)

    def release(self, ticket, cooldown=0):
        def finish(state, now):
            # An old worker must not clear a newer worker's reservation.
            state.active.pop(ticket, None)
            state.cooldown = max(state.cooldown, now + cooldown)
        self._change(finish)

    @contextmanager
    def admission(self, visitor):
        with ai_stage("quota.reserve"):
            ticket = self.reserve(visitor)
        stop, failed = threading.Event(), threading.Event()
        cooldown = 0

        def heartbeat():
            while not stop.wait(self.limits.heartbeat_seconds):
                try:
                    self.renew(ticket)
                except GuardUnavailable:
                    failed.set()
                    # Keep trying to renew while the provider is still running;
                    # never release an in-flight call on a transient failure.

        thread = threading.Thread(target=copy_context().run, args=(heartbeat,), daemon=True)
        thread.start()
        try:
            yield
            if failed.is_set():
                raise GuardUnavailable("AI reservation could not be maintained.")
        except Throttled as exc:
            cooldown = exc.retry_after
            raise
        finally:
            stop.set()
            thread.join(timeout=12)
            try:
                self.release(ticket, cooldown)
            except GuardUnavailable:
                # Keep the reservation until expiry and do not refund usage.
                # New requests fail closed if storage remains unavailable.
                pass


def _ip(value):
    value = value.strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        # App Service can append an observed client port. Normalize it away.
        if value.startswith("["):
            host, port = value[1:].split("]:", 1)
        else:
            host, port = value.rsplit(":", 1)
            ipaddress.IPv4Address(host)
        if not port.isdigit() or not 0 <= int(port) <= 65535:
            raise ValueError("Invalid client port")
        address = ipaddress.ip_address(host)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address


def visitor_key(request: Request):
    """Requires Uvicorn --no-proxy-headers: this code owns proxy trust."""
    secret = os.getenv("AI_VISITOR_HASH_KEY", "")
    if len(secret.encode()) < 32:
        raise GuardUnavailable("AI visitor identification is not configured.")
    try:
        peer = _ip(request.client.host)
        networks = [ipaddress.ip_network(value.strip()) for value in
                    os.getenv("AI_TRUSTED_PROXY_CIDRS", "").split(",") if value.strip()]
        trusted = lambda address: any(address in network for network in networks)
        if trusted(peer):
            values = request.headers.getlist("x-forwarded-for")
            if len(values) != 1 or len(values[0]) > 1024:
                raise ValueError()
            chain = [_ip(value) for value in values[0].split(",")]
            if not chain or len(chain) > 10:
                raise ValueError()
            # Proxies append the observed source on the right. Ignore
            # attacker-controlled prefixes to the left of the first client.
            address = next(value for value in reversed(chain) if not trusted(value))
        else:
            if os.getenv("WEBSITE_SITE_NAME"):
                raise ValueError()  # unknown production proxy: fail closed
            address = peer  # direct development requests ignore all IP headers
        return hmac.new(secret.encode(), address.compressed.encode(), hashlib.sha256).hexdigest()
    except (ValueError, AttributeError, StopIteration):
        raise GuardUnavailable("AI visitor identification is unavailable.") from None


@lru_cache(maxsize=1)
def get_guard():
    try:
        with ai_stage("quota.blob.import"):
            from azure.storage.blob import BlobClient
        options = dict(connection_timeout=3, read_timeout=5, retry_total=0, logging_enable=False,
                       api_version="2023-11-03")
        daily = int(os.getenv("AI_GLOBAL_DAILY_LIMIT", "50"))
        if not 1 <= daily <= 1000:
            raise ValueError()
        container = os.environ["AI_QUOTA_CONTAINER"]
        blob_name = os.getenv("AI_QUOTA_BLOB", "ai-usage.json")
        connection = os.getenv("AI_QUOTA_CONNECTION_STRING")
        if connection:
            if os.getenv("WEBSITE_SITE_NAME"):
                raise ValueError("Production requires managed identity")
            blob = BlobClient.from_connection_string(connection, container, blob_name, **options)
        else:
            endpoint = os.environ["AI_QUOTA_ACCOUNT_URL"]
            if not endpoint.startswith("https://"):
                raise ValueError()
            with ai_stage("quota.identity.configure"):
                credential = _StorageCredential(azure_credential())
            blob = BlobClient(endpoint, container, blob_name, credential=credential, **options)
        return QuotaGuard(BlobStateStore(blob), Limits(daily=daily))
    except Exception:
        raise GuardUnavailable("AI quota protection is not configured.") from None
