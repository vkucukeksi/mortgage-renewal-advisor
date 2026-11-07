"""Bound AI request bytes before FastAPI reads/parses a JSON document."""
from starlette.responses import JSONResponse
from .ai_diagnostics import ai_stage, ai_trace, log_ai_response


class AIBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST"
                or scope["path"].rstrip("/") != "/api/ai/explain"):
            return await self.app(scope, receive, send)
        async def report_status(message):
            if message["type"] == "http.response.start":
                log_ai_response(message["status"])
            await send(message)

        with ai_trace():
            await self._limited(scope, receive, report_status)

    async def _limited(self, scope, receive, send):
        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)

        headers = [(k.lower(), v) for k, v in scope["headers"]]
        if any(k == b"content-encoding" and v.lower() != b"identity" for k, v in headers):
            return await reject(415, "Compressed AI requests are not supported.")
        lengths = [v for k, v in headers if k == b"content-length"]
        try:
            if len(lengths) > 1 or (lengths and int(lengths[0]) < 0):
                raise ValueError()
            if lengths and int(lengths[0]) > 16384:
                return await reject(413, "AI requests must not exceed 16 KiB.")
        except ValueError:
            return await reject(400, "Invalid Content-Length.")
        body = bytearray()
        with ai_stage("request.body"):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > 16384:
                    return await reject(413, "AI requests must not exceed 16 KiB.")
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
