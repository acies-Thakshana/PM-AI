"""Error types shared by every entry point."""

from __future__ import annotations


class AI4BIError(Exception):
    """Base class. ``code`` is stable and safe to show to callers."""

    code = "ai4bi_error"


class ConfigError(AI4BIError):
    code = "config_error"


class DomainNotFoundError(AI4BIError):
    code = "domain_not_found"


class DataNotFoundError(AI4BIError):
    code = "data_not_found"


class GuardrailViolation(AI4BIError):
    code = "guardrail_violation"

    def __init__(self, message: str, *, status: str = "refuse_unsupported") -> None:
        super().__init__(message)
        self.status = status


class SqlValidationError(AI4BIError, PermissionError):
    code = "sql_validation_failed"


class SqlExecutionError(AI4BIError):
    code = "sql_execution_failed"


class LlmError(AI4BIError):
    code = "llm_error"
