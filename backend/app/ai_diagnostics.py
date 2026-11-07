"""Log AI stages without request data, SDK exception text or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import os
from time import monotonic
from uuid import uuid4


logger = logging.getLogger("uvicorn.error.mortgage_ai")
request_id = ContextVar("ai_request_id", default="-")


def log_ai_response(status):
    logger.info("AI trace=%s stage=request.response status=%d", request_id.get(), status)


@contextmanager
def ai_trace():
    token = request_id.set(uuid4().hex)
    try:
        yield
    finally:
        request_id.reset(token)


@contextmanager
def ai_stage(stage):
    trace = request_id.get()
    start = monotonic()
    logger.info("AI trace=%s stage=%s outcome=started", trace, stage)
    try:
        yield
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        level = logging.INFO if type(exc).__name__ == "Throttled" else logging.WARNING
        logger.log(level, "AI trace=%s stage=%s outcome=%s status=%s duration_ms=%d",
                   trace, stage, type(exc).__name__, status if isinstance(status, int) else "-",
                   (monotonic() - start) * 1000)
        raise
    else:
        logger.info("AI trace=%s stage=%s outcome=ok duration_ms=%d",
                    trace, stage, (monotonic() - start) * 1000)


def azure_credential():
    with ai_stage("identity.import"):
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

    # The SDK can log exception text from the identity endpoint. Emit only the
    # stage diagnostics above. Blob HTTP logging is disabled on its client.
    for name in ("azure.identity", "msal"):
        sdk_logger = logging.getLogger(name)
        sdk_logger.propagate = False
        if not sdk_logger.handlers:
            sdk_logger.addHandler(logging.NullHandler())
    client_id = os.getenv("AZURE_CLIENT_ID")
    if os.getenv("WEBSITE_SITE_NAME"):
        if not (os.getenv("IDENTITY_ENDPOINT") and os.getenv("IDENTITY_HEADER")):
            raise RuntimeError("App Service managed identity configuration is missing")
    elif not os.getenv("IDENTITY_ENDPOINT"):
        return DefaultAzureCredential(managed_identity_client_id=client_id)

    # Blob transport settings do not apply to the credential's token request.
    return ManagedIdentityCredential(client_id=client_id, connection_timeout=3,
                                     read_timeout=5, retry_total=0, use_env_settings=False)
