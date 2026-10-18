"""ASGI middleware. Written as plain ASGI (not ``BaseHTTPMiddleware``) so the request id it binds
is visible to every handler and worker thread that runs for the request."""

from __future__ import annotations

import re
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.common import request_context

HEADER = "x-request-id"
_VALID_ID = re.compile(r"^[A-Za-z0-9\-_.]{8,64}$")


class RequestIdMiddleware:
    """Give every request an id, bind it for logging, and return it in the ``X-Request-ID`` header.

    A caller-supplied id is kept when it is well formed, so a gateway's id can be traced end to end.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = dict(scope["headers"]).get(HEADER.encode(), b"").decode("latin-1")
        request_id = supplied if _VALID_ID.match(supplied) else str(uuid.uuid4())

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        with request_context.request_scope(request_id):
            await self.app(scope, receive, send_with_id)
