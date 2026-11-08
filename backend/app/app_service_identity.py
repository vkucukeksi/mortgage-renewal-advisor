"""TokenCredential for the local Azure App Service managed identity endpoint."""
from functools import lru_cache
import json
import os
from threading import Lock
from time import time
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from azure.core.credentials import AccessToken, AccessTokenInfo
from azure.core.exceptions import ClientAuthenticationError


TOKEN_TIMEOUT = 15
REFRESH_MARGIN = 120
MAX_TOKEN_RESPONSE = 64 * 1024
RESOURCES = {"https://storage.azure.com", "https://cognitiveservices.azure.com"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AppServiceCredential:
    def __init__(self):
        self._endpoint = os.getenv("IDENTITY_ENDPOINT", "")
        self._header = os.getenv("IDENTITY_HEADER", "")
        endpoint = urlsplit(self._endpoint)
        if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
                or endpoint.username is not None or endpoint.fragment or not self._header):
            raise ClientAuthenticationError("App Service managed identity is not configured.")
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._tokens = {}
        self._locks = {resource: Lock() for resource in RESOURCES}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        # The process-scoped credential owns the shared in-memory cache.
        return None

    def get_token(self, *scopes, **kwargs):
        if len(scopes) != 1 or not scopes[0].endswith("/.default") or kwargs.get("claims"):
            raise ClientAuthenticationError("Unsupported App Service token request.")
        resource = scopes[0].removesuffix("/.default")
        if resource not in RESOURCES:
            raise ClientAuthenticationError("Unsupported App Service token resource.")
        lock = self._locks[resource]
        if not lock.acquire(timeout=TOKEN_TIMEOUT):
            raise ClientAuthenticationError("App Service token refresh timed out.")
        try:
            cached = self._tokens.get(resource)
            if cached is not None and cached.expires_on > time() + REFRESH_MARGIN:
                return cached
            token = self._request_token(resource)
            self._tokens[resource] = token
            return token
        finally:
            lock.release()

    def get_token_info(self, *scopes, options=None):
        token = self.get_token(*scopes, **(options or {}))
        return AccessTokenInfo(token.token, token.expires_on)

    def _request_token(self, resource):
        try:
            query = urlencode({"resource": resource, "api-version": "2019-08-01"})
            separator = "&" if urlsplit(self._endpoint).query else "?"
            request = Request(self._endpoint + separator + query,
                              headers={"X-IDENTITY-HEADER": self._header})
            with self._opener.open(request, timeout=TOKEN_TIMEOUT) as response:
                body = response.read(MAX_TOKEN_RESPONSE + 1)
                if response.status != 200 or len(body) > MAX_TOKEN_RESPONSE:
                    raise ValueError()
                payload = json.loads(body)
            value = payload["access_token"]
            expires = int(payload["expires_on"])
            if (not isinstance(value, str) or not value or any(c.isspace() for c in value)
                    or expires <= time()):
                raise ValueError()
            return AccessToken(value, expires)
        except TimeoutError:
            raise ClientAuthenticationError("App Service token request timed out.") from None
        except Exception:
            # HTTP and parse exceptions may contain endpoint details or token material.
            raise ClientAuthenticationError("App Service token request failed.") from None


@lru_cache(maxsize=1)
def app_service_credential():
    return AppServiceCredential()
