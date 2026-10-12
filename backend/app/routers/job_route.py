"""A route class that can run any endpoint as a background job.

Routers declared with `APIRouter(route_class=JobRoute)` behave exactly as before, unless the request
carries the header `X-Run-As-Job: 1`. Then the endpoint's normal handler (dependencies, validation, the
function itself, error handling) runs in a background thread (services/common/jobs.py) and the request
is answered immediately with `202 {"job_id": ...}`. The real response is read later from
`GET /api/jobs/<id>/result`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.services.common import jobs, request_context

log = logging.getLogger(__name__)

HEADER = "x-run-as-job"


async def _error_response(request: Request, exc: Exception) -> Response:
    """The response the app would have sent for `exc` (its registered exception handler)."""
    for cls in type(exc).__mro__:
        handler = request.app.exception_handlers.get(cls)
        if handler is not None:
            result = handler(request, exc)
            return await result if asyncio.iscoroutine(result) else result
    log.error("unhandled error in a background job", exc_info=exc)
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)


class JobRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            if request.headers.get(HEADER) != "1":
                return await original(request)

            body = await request.body()
            scope = dict(request.scope)

            async def work() -> tuple[jobs.StoredResponse, str | None]:
                async def receive() -> dict:  # replays the request body to the real handler
                    return {"type": "http.request", "body": body, "more_body": False}

                replay = Request(scope, receive)
                try:
                    response = await original(replay)
                except Exception as exc:  # noqa: BLE001
                    response = await _error_response(replay, exc)
                # The sign-in dependency ran inside `original`, in this same task.
                owner = request_context.current_user_id.get()
                headers = {
                    k.decode("latin-1"): v.decode("latin-1")
                    for k, v in response.raw_headers
                    if k != b"content-length"
                }
                return jobs.StoredResponse(response.status_code, headers, bytes(response.body)), owner

            job = jobs.start(request.url.path, work)
            return JSONResponse({"job_id": job.id, "status": "running"}, status_code=202)

        return handler
