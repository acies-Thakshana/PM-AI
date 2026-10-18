"""SQL safety policy loaded from settings. Prompts are not a security boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings

DEFAULT_FORBIDDEN = (
    "insert",
    "update",
    "delete",
    "merge",
    "drop",
    "alter",
    "create",
    "truncate",
    "grant",
    "revoke",
    "attach",
    "detach",
    "pragma",
    "vacuum",
)


@dataclass(frozen=True)
class SqlPolicy:
    forbidden_keywords: tuple[str, ...] = DEFAULT_FORBIDDEN
    row_limit: int = 500
    max_execution_steps: int = 50_000_000
    allowed_starts: tuple[str, ...] = ("select", "with")
    restricted_columns: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_settings(cls, settings: Settings, restricted: set[str] | None = None) -> SqlPolicy:
        return cls(
            forbidden_keywords=tuple(settings.forbidden_keywords or DEFAULT_FORBIDDEN),
            row_limit=settings.row_limit,
            max_execution_steps=settings.max_execution_steps,
            restricted_columns=frozenset(c.lower() for c in (restricted or set())),
        )

    def with_restricted(self, restricted: set[str]) -> SqlPolicy:
        return SqlPolicy(
            forbidden_keywords=self.forbidden_keywords,
            row_limit=self.row_limit,
            max_execution_steps=self.max_execution_steps,
            allowed_starts=self.allowed_starts,
            restricted_columns=frozenset(c.lower() for c in restricted),
        )
