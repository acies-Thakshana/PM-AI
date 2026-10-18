"""Application factory. ``uvicorn app.main:app`` serves it."""

from __future__ import annotations

import logging
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.errors import AI4BIError, ConfigError
from app.logging_config import setup_logging
from app.middleware import RequestIdMiddleware
from app.routers import ask, domains, onboard, registry, system, upload
from app.services.common import request_context
from app.services.context import get_context

LOGGER = logging.getLogger(__name__)

_LOCALHOST_ORIGIN = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

# The dashboard UI lives next to the backend folder. When present it is served at /app/ so one
# process runs everything locally.
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _error(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    body = {"code": code, "message": message, "request_id": request_context.current_request_id.get(), **extra}
    return JSONResponse(status_code=status, content={"error": body})


async def _ai4bi_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AI4BIError)
    if isinstance(exc, ConfigError):
        # Configuration details (resource names, paths) are for the operator, not the caller.
        LOGGER.error("Configuration error: %s", exc)
        return _error(exc.http_status, exc.code, "The service is misconfigured. Contact the administrator.")
    return _error(exc.http_status, exc.code, str(exc))


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"field": ".".join(str(part) for part in error["loc"][1:]), "message": error["msg"]} for error in exc.errors()
    ]
    return _error(422, "invalid_request", "The request is not valid.", details=details)


async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    LOGGER.exception("Unhandled error", exc_info=exc)
    return _error(500, "internal_error", "Something went wrong. Quote the request id when reporting it.")


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    settings = get_settings()
    setup_logging(settings.log_level, json_format=settings.log_json)
    settings.validate()  # refuse to start misconfigured, rather than fail on the first request
    context = get_context()
    LOGGER.info(
        "Started AI4BI %s: storage=%s llm=%s auth=%s",
        __version__,
        settings.storage_backend,
        settings.llm_mode,
        "entra" if settings.auth_enabled else "off",
    )
    yield
    context.runner.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI4BI",
        version=__version__,
        description="Ask business questions of your data in plain language.",
        lifespan=_lifespan,
        # Interactive docs are a development aid; they stay off when the service runs on AWS.
        docs_url=None if settings.use_aws_storage else "/docs",
        redoc_url=None,
        openapi_url=None if settings.use_aws_storage else "/openapi.json",
    )
    app.add_exception_handler(AI4BIError, _ai4bi_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=_LOCALHOST_ORIGIN if settings.cors_allow_localhost else None,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    for module in (system, ask, domains, registry, upload, onboard):
        app.include_router(module.router)

    if _FRONTEND_DIR.is_dir():
        app.mount("/app", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")

        @app.get("/", include_in_schema=False)
        def _home() -> RedirectResponse:
            return RedirectResponse("/app/")

    return app


app = create_app()
