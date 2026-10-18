"""Deterministic SQL checks: read-only, one statement, known tables, safe columns, registered joins."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.guardrails.sql_policy import SqlPolicy
from app.services.semantic.models import DomainPackage

_STRING = re.compile(r"'(?:[^']|'')*'")
_QUOTED_IDENT = re.compile(r'"(?:[^"]|"")*"|`[^`]*`|\[[^\]]*\]')
_BARE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IDENT = r'(?:"(?:[^"]|"")+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)'
_TABLE_REF = re.compile(rf"\b(from|join)\s+({_IDENT})", re.IGNORECASE)
_CTE = re.compile(rf"(?:\bwith\b|,)\s*(?:recursive\s+)?({_IDENT})\s+as\s*\(", re.IGNORECASE)
_COMMA_JOIN = re.compile(rf"\bfrom\s+{_IDENT}(?:\s+(?:as\s+)?{_IDENT})?\s*,\s*{_IDENT}", re.IGNORECASE)
_EQ_PAIR = re.compile(rf"(?:({_IDENT})\s*\.\s*)?({_IDENT})\s*=\s*(?:({_IDENT})\s*\.\s*)?({_IDENT})", re.IGNORECASE)
_ON_END = re.compile(
    r"\b(?:left|right|inner|full|cross|outer|natural|join|where|group|order|limit|having|union|except|intersect)\b",
    re.IGNORECASE,
)
_SQL_WORDS = frozenset(
    {
        "select",
        "from",
        "where",
        "and",
        "or",
        "not",
        "null",
        "is",
        "in",
        "as",
        "on",
        "group",
        "by",
        "order",
        "limit",
        "having",
        "case",
        "when",
        "then",
        "else",
        "end",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "distinct",
        "asc",
        "desc",
        "with",
        "union",
        "all",
        "like",
        "between",
        "cast",
        "over",
        "partition",
        "true",
        "false",
    }
)


def _unquote(token: str | None) -> str:
    text = (token or "").strip()
    if len(text) >= 2 and text[0] in '"`[' and text[-1] in '"`]':
        text = text[1:-1].replace('""', '"')
    return text


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


@dataclass
class ValidationResult:
    sql: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    joins_used: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)


class SqlValidator:
    def __init__(self, policy: SqlPolicy) -> None:
        self.policy = policy

    def validate(
        self,
        sql: str,
        pkg: DomainPackage,
        available_tables: list[str] | None = None,
    ) -> ValidationResult:
        text = (sql or "").strip().rstrip(";").strip()
        result = ValidationResult(sql=text)
        if not text:
            result.fail("Empty SQL is not allowed.")
            return result
        no_strings = _STRING.sub("''", text)
        no_idents = _QUOTED_IDENT.sub('"_"', no_strings)
        lowered = no_idents.lower()

        if ";" in lowered:
            result.fail("Multiple SQL statements are not allowed.")
        if "--" in lowered or "/*" in lowered:
            result.fail("SQL comments are not allowed.")
        first_word = _BARE.search(lowered)
        if first_word is None or first_word.group(0) not in self.policy.allowed_starts:
            result.fail("Only read-only SELECT queries are allowed.")
        for keyword in self.policy.forbidden_keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                result.fail(f"Keyword {keyword.upper()} is not allowed. Only read-only SELECT is allowed.")
        if re.search(r"\breplace\s+into\b", lowered):
            result.fail("REPLACE INTO is not allowed.")

        restricted = self.policy.restricted_columns | {c.lower() for c in pkg.restricted_columns()}
        identifiers = {m.lower() for m in _BARE.findall(no_strings)}
        identifiers |= {_unquote(m).lower() for m in _QUOTED_IDENT.findall(no_strings)}
        hits = sorted(c for c in restricted if c in identifiers)
        if hits:
            result.fail("Restricted columns cannot be selected or filtered: " + ", ".join(hits))

        ctes = {_unquote(m).lower() for m in _CTE.findall(no_strings)}
        tables: list[str] = []
        for _, token in _TABLE_REF.findall(no_strings):
            name = _unquote(token)
            if name.lower() in ctes or name.lower() in _SQL_WORDS:
                continue
            if name not in tables:
                tables.append(name)
        result.tables = tables
        if available_tables is not None:
            known = {t.lower() for t in available_tables}
            unknown = [t for t in tables if t.lower() not in known]
            if unknown:
                result.fail(
                    "Unknown tables: " + ", ".join(unknown) + ". Available: " + ", ".join(sorted(available_tables))
                )
        if _COMMA_JOIN.search(no_strings):
            result.fail("Comma joins are not allowed. Use JOIN ... ON with a registered join key.")
        self._check_joins(no_strings, pkg, result)
        return result

    # ----- joins ------------------------------------------------------------

    def _check_joins(self, sql: str, pkg: DomainPackage, result: ValidationResult) -> None:
        segments = re.split(r"\bjoin\b", sql, flags=re.IGNORECASE)
        if len(segments) == 1:
            return
        allowed = [j for j in pkg.joins if j.allowed_for_nlq]
        if not allowed:
            result.fail(
                "SQL contains JOIN but the domain has no registered joins. A steward must register the join first."
            )
            return
        conditions = {_norm(j.condition): j.id for j in allowed}
        pairs: dict[frozenset[str], str] = {}
        for join in allowed:
            for key in join.keys:
                pairs[frozenset({key.left_column.lower(), key.right_column.lower()})] = join.id
        normalized_sql = _norm(sql)
        for segment in segments[1:]:
            on_match = re.search(r"\bon\b(.*)", segment, flags=re.IGNORECASE | re.S)
            using = re.search(r"\busing\s*\(([^)]*)\)", segment, flags=re.IGNORECASE)
            matched: list[str] = []
            if on_match:
                clause = on_match.group(1)
                end = _ON_END.search(clause)
                clause = clause[: end.start()] if end else clause
                found = _EQ_PAIR.findall(clause)
                if not found:
                    result.fail("JOIN condition must be an equality on a registered key.")
                    continue
                for _, left_col, _, right_col in found:
                    key = frozenset({_unquote(left_col).lower(), _unquote(right_col).lower()})
                    join_id = pairs.get(key)
                    if join_id is None:
                        join_id = next(
                            (jid for cond, jid in conditions.items() if cond and cond in normalized_sql), None
                        )
                    if join_id is None:
                        result.fail(
                            f"JOIN on {_unquote(left_col)} = {_unquote(right_col)} is not registered. "
                            "A steward must register the relationship first; joins are never guessed."
                        )
                    else:
                        matched.append(join_id)
            elif using:
                for column in using.group(1).split(","):
                    name = _unquote(column.strip()).lower()
                    join_id = pairs.get(frozenset({name}))
                    if join_id is None:
                        result.fail(f"JOIN USING({name}) is not a registered join key.")
                    else:
                        matched.append(join_id)
            else:
                result.fail("JOIN without an ON condition is not allowed.")
            for join_id in matched:
                if join_id not in result.joins_used:
                    result.joins_used.append(join_id)
