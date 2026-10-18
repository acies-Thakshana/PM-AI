"""Error types shared by services and routers.

Every error carries a stable ``code`` and the ``http_status`` the API reports for it, so the
HTTP layer maps errors in exactly one place (see ``app.main``).
"""

from __future__ import annotations


class AI4BIError(Exception):
    """Base class. ``code`` is stable and safe to show to callers."""

    code = "ai4bi_error"
    http_status = 500


class ConfigError(AI4BIError):
    """The server is misconfigured. Callers get a generic message; details go to the log."""

    code = "config_error"
    http_status = 500


class AuthenticationError(AI4BIError):
    """No valid sign-in token was presented."""

    code = "unauthenticated"
    http_status = 401


class ForbiddenError(AI4BIError):
    """The caller is signed in but not allowed to do this."""

    code = "forbidden"
    http_status = 403


class DomainNotFoundError(AI4BIError):
    code = "domain_not_found"
    http_status = 404


class DataNotFoundError(AI4BIError):
    code = "data_not_found"
    http_status = 404


class InvalidInputError(AI4BIError):
    """The request is well formed but its content is not acceptable (bad file, bad name, ...)."""

    code = "invalid_input"
    http_status = 422


class ConflictError(AI4BIError):
    """A conditional write lost a race, or the requested change conflicts with stored state."""

    code = "conflict"
    http_status = 409


class LlmError(AI4BIError):
    """The model call failed or returned an unusable answer."""

    code = "llm_error"
    http_status = 502
