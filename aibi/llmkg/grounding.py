"""Ground NL-to-SQL in the live table, for any question and any extract.

The model only sees columns that contain data, the real members of each
attribute, and the closest members to the words in the question. Filter
literals that are not stored values are rewritten to the unambiguous member.
Ranking queries drop null aggregates. Nothing here is tied to one question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

_STOP = frozenset(
    {"the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "you", "your"}
)
_AGG_FN = re.compile(r"\b(SUM|AVG|MIN|MAX|COUNT)\s*\(", re.I)


@dataclass
class ColumnProfile:
    name: str
    role: str
    dtype: str
    null_fraction: float
    nunique: int
    values: list[str] = field(default_factory=list)
    description: str = ""
    norm_to_exact: dict[str, str] = field(default_factory=dict)
    token_index: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        return self.null_fraction < 0.999 and self.nunique > 0


def profile_frame(
    frame: pd.DataFrame,
    *,
    notes: dict[str, str] | None = None,
) -> list[ColumnProfile]:
    """Profile any dataframe. Low-cardinality attributes keep every member."""
    notes = notes or {}
    profiles: list[ColumnProfile] = []
    for name in frame.columns:
        series = frame[name]
        null_fraction = float(series.isna().mean()) if len(series) else 1.0
        role = _role(str(name), series)
        values = _members(series) if role != "measure" else []
        profile = ColumnProfile(
            name=str(name),
            role=role,
            dtype=str(series.dtype),
            null_fraction=null_fraction,
            nunique=len(values) if values else int(series.nunique(dropna=True)),
            values=values,
            description=str(notes.get(str(name)) or "").strip(),
        )
        if role != "measure":
            _index_values(profile)
        profiles.append(profile)
    return profiles


def load_semantic_hints(roots: list[Path] | None = None) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Column notes and filter aliases from any semantic domain pack on disk.

    Aliases are ``(term, canonical_value)`` and are applied only when that
    value is actually stored. They are not question logic.
    """
    try:
        import yaml
    except Exception:
        return {}, []
    notes: dict[str, str] = {}
    aliases: list[tuple[str, str]] = []
    seen_alias: set[str] = set()
    for path in _semantic_files(roots or []):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for product in payload.get("data_products") or []:
            if not isinstance(product, dict):
                continue
            for column in product.get("columns") or []:
                if not isinstance(column, dict):
                    continue
                name = str(column.get("name") or "").strip()
                description = str(column.get("description") or "").strip()
                if name and description and name not in notes:
                    notes[name] = description
        for dim in payload.get("dimensions") or []:
            if not isinstance(dim, dict):
                continue
            description = str(dim.get("description") or dim.get("name") or "").strip()
            targets = [dim.get("key_column"), dim.get("label_column")]
            targets.extend(dim.get("attributes") or [])
            for target in targets:
                name = str(target or "").strip()
                if name and description and description.lower() not in notes.get(name, "").lower():
                    notes[name] = (notes.get(name, "") + " " + description).strip()
        for item in payload.get("synonyms") or []:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term") or "").strip()
            canonical = str(item.get("canonical_value") or "").strip()
            key = term.lower()
            if term and canonical and key not in seen_alias:
                seen_alias.add(key)
                aliases.append((term, canonical))
    aliases.sort(key=lambda pair: len(pair[0]), reverse=True)
    return notes, aliases


def schema_text(
    columns: list[ColumnProfile],
    question: str,
    *,
    table: str = "KPI_data",
    aliases: list[tuple[str, str]] | None = None,
) -> str:
    """Prompt catalog: usable columns, real members, and question hits."""
    lines = [
        f"SQLite table: {table}",
        "Rules:",
        "- Use only columns listed under Measures or Attributes. Omitted columns have no stored values.",
        "- When several measures could match, prefer the lowest null_fraction whose description matches the question.",
        "- Copy filter values exactly from the member lists or the closest matches. Do not paraphrase, pluralize, or shorten them.",
        "- Quote identifiers that contain spaces or punctuation with double quotes.",
        "- Additive amounts use SUM. Ratios and achievement use SUM(amount) / NULLIF(SUM(plan), 0) after GROUP BY, never an average of row ratios, and never a currency total compared with a bare percent.",
        "- Do not put IS NOT NULL or <> 0 on a summed measure in WHERE. SUM already skips nulls. A ratio test belongs in HAVING, after the sums.",
        "- Performance, achievement, and a stated percent are that ratio, not the larger dollar total and not an amount divided by spend.",
        "- Which group is highest or lowest, then the top N members inside it: filter to the winning group first. Do not LIMIT the cross-product of both groups.",
        "- Filter with the stored member that matches the whole phrase in the question, not a different member that only shares one word.",
        "- When the question contrasts two measures, use the two columns whose descriptions match those words.",
        "- Rankings must drop null aggregates (HAVING <aggregate> IS NOT NULL) and blank group labels. Lowest means ASC, highest means DESC.",
        "- \"Across all\" of a dimension means COUNT(DISTINCT that column) equals the number of members listed for it. Do not hardcode a member list the user did not require, and do not require the measure to be non-zero unless asked.",
        "- When an id column and a name column share a prefix, select and group by both.",
        "",
        "Measures:",
    ]
    measures = [c for c in columns if c.role == "measure" and c.has_data]
    if not measures:
        lines.append("- (none)")
    for column in measures:
        note = f" — {column.description}" if column.description else ""
        lines.append(
            f'- "{column.name}" null_fraction={column.null_fraction:.2f}{note}'
        )
    lines.append("")
    lines.append("Attributes:")
    for column in columns:
        if column.role == "measure" or not column.has_data:
            continue
        note = f" — {column.description}" if column.description else ""
        if column.nunique <= 80:
            rendered = ", ".join(_sql_literal(v) for v in column.values)
            lines.append(
                f'- "{column.name}" members ({column.nunique}){note}: {rendered}'
            )
        else:
            hits = candidate_values(column, question, limit=6)
            if hits:
                rendered = ", ".join(
                    f"{_sql_literal(value)} ({score:.2f})" for value, score in hits
                )
                lines.append(
                    f'- "{column.name}" {column.nunique} distinct{note}. Closest to this question: {rendered}'
                )
            else:
                lines.append(
                    f'- "{column.name}" {column.nunique} distinct{note}. No close member for this question; do not invent a filter on it.'
                )
    pairs = key_label_pairs(columns)
    if pairs:
        lines.append("")
        lines.append("Identifier pairs:")
        for key, label in pairs:
            lines.append(f'- "{key}" with "{label}"')
    glossary_lines = _glossary_lines(question, aliases or [], columns)
    if glossary_lines:
        lines.append("")
        lines.append("Glossary (use the stored value, not the user's shorthand):")
        lines.extend(glossary_lines)
    omitted = [c.name for c in columns if not c.has_data]
    if omitted:
        lines.append("")
        lines.append(
            f"{len(omitted)} columns have no stored values and are omitted. Do not reference them."
        )
    return "\n".join(lines)


def prepare_sql(
    sql: str,
    columns: list[ColumnProfile],
    question: str = "",
    *,
    aliases: list[tuple[str, str]] | None = None,
) -> str:
    """Bind filter literals and keep rankings from treating nulls as answers."""
    text = (sql or "").strip().rstrip(";")
    if not text:
        return text
    text = _bind_comparisons(text, columns)
    text = _bind_in_lists(text, columns)
    text = _align_filters_to_question(text, columns, question)
    text = _apply_glossary(text, question, aliases or [], columns)
    text = _strip_invented_scale(text, question)
    text = _strip_preaggregate_measure_filters(text, columns)
    text = _rewrite_contrast(text, columns, question)
    text = _fix_ratio_ordering(text, columns, question)
    if _is_simple_select(text):
        text = _drop_blank_groups(text, columns)
        text = _drop_null_aggregates(text)
        text = _rewrite_winner_then_top(text, columns, question)
    return text


def references_unavailable(sql: str, columns: list[ColumnProfile]) -> bool:
    """True when SQL reads a column that has no stored values."""
    return any(
        not column.has_data and _column_mentioned(sql, column.name)
        for column in columns
    )


def result_is_vacuous(frame: pd.DataFrame | None) -> bool:
    """True when the result cannot support a numeric or labeled answer."""
    if frame is None or frame.empty:
        return True
    numeric = frame.select_dtypes(include="number")
    if numeric.shape[1]:
        return bool(numeric.isna().all().all())
    for column in frame.columns:
        series = frame[column]
        if series.notna().any() and series.astype(str).str.strip().replace("None", "").ne("").any():
            return False
    return True


def diagnose(
    sql: str,
    columns: list[ColumnProfile],
    result: pd.DataFrame | None,
) -> str:
    """Tell the model why the result cannot be answered, using the live catalog."""
    parts: list[str] = []
    if result is None or result.empty:
        parts.append("The query returned no rows.")
    elif result_is_vacuous(result):
        parts.append("Every measure in the result is null.")
    empty = [
        column.name
        for column in columns
        if not column.has_data and _column_mentioned(sql, column.name)
    ]
    if empty:
        parts.append("These columns have no stored values: " + ", ".join(empty) + ".")
        usable = [
            f'"{column.name}"' + (f" ({column.description})" if column.description else "")
            for column in columns
            if column.role == "measure" and column.has_data
        ]
        if usable:
            parts.append("Populated measures: " + "; ".join(usable) + ".")
    for column_name, literal in _equality_literals(sql):
        column = _find_column(columns, column_name)
        if column is None or column.role == "measure" or not column.values:
            continue
        if _exact_member(column, literal):
            continue
        hits = _score_against(column, literal, limit=5)
        shown = ", ".join(_sql_literal(value) for value, score in hits if score >= 0.4) or "(none)"
        parts.append(
            f'Filter "{column.name}" = {_sql_literal(literal)} is not stored. Closest members: {shown}.'
        )
    if not parts:
        parts.append("The query did not return a usable result. Rewrite it from the catalog.")
    return "\n".join(parts)


def candidate_values(
    column: ColumnProfile, question: str, *, limit: int = 6
) -> list[tuple[str, float]]:
    """Members of one column that the question is actually referring to.

    A long phrase match wins over a one-word exact match. ``ALC Kennesaw``
    stays on ``ALC, Kennesaw, GA`` instead of the site named only ``KENNESAW``.
    """
    best: dict[str, float] = {}
    strong_width = 0
    for gram in _ngrams(question):
        width = len(gram.split())
        if strong_width and width < strong_width:
            break
        found_strong = False
        for value in _lookup(column, _tokens(gram)):
            score = _score(gram, value)
            if score < 0.9:
                continue
            found_strong = True
            if score > best.get(value, 0.0):
                best[value] = score
        if found_strong:
            strong_width = width
    if not best:
        for gram in _ngrams(question):
            for value in _lookup(column, _tokens(gram)):
                score = _score(gram, value)
                if score > best.get(value, 0.0):
                    best[value] = score
        for token in _tokens(_normalize(question)):
            if not 2 <= len(token) <= 5:
                continue
            for value in column.values:
                if _initials(value) == token and value not in best:
                    best[value] = 0.7
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    return [(value, score) for value, score in ranked if score >= 0.55][:limit]


def key_label_pairs(columns: list[ColumnProfile]) -> list[tuple[str, str]]:
    names = {column.name for column in columns if column.has_data}
    pairs: list[tuple[str, str]] = []
    for name in sorted(names):
        if not name.lower().endswith(" id"):
            continue
        prefix = name[:-3].rstrip()
        for suffix in (" name", " Name"):
            label = prefix + suffix
            if label in names:
                pairs.append((name, label))
                break
    return pairs


def _role(name: str, series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "time"
    if not pd.api.types.is_numeric_dtype(series):
        return "attribute"
    label = name.lower()
    distinct = int(series.nunique(dropna=True))
    # Low-cardinality numerics such as a reporting year are filters, not amounts.
    if distinct <= 30 and any(token in label for token in ("year", "quarter", "month", "flag", "code")):
        return "attribute"
    return "measure"


def _members(series: pd.Series) -> list[str]:
    if pd.api.types.is_datetime64_any_dtype(series):
        return []
    seen: list[str] = []
    known: set[str] = set()
    for raw in series.dropna().unique().tolist():
        text = _display(raw)
        if not text or text in known:
            continue
        known.add(text)
        seen.append(text)
        if len(seen) > 4000:
            break
    seen.sort(key=str.lower)
    return seen


def _display(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).replace("\xa0", " ").strip()
    if text.lower() in {"nan", "none", "<na>", "nat"}:
        return ""
    return text


def _index_values(column: ColumnProfile) -> None:
    for value in column.values:
        norm = _normalize(value)
        column.norm_to_exact.setdefault(norm, value)
        for token in _tokens(norm):
            if token in _STOP:
                continue
            bucket = column.token_index.setdefault(token, [])
            if len(bucket) < 400:
                bucket.append(value)


def _semantic_files(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root is None:
            continue
        base = Path(root)
        for folder in (base / "semantic" / "domains", base):
            if not folder.exists():
                continue
            for path in sorted(folder.glob("*.yaml")):
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                found.append(path)
    return found


def _glossary_lines(
    question: str, aliases: list[tuple[str, str]], columns: list[ColumnProfile]
) -> list[str]:
    lines: list[str] = []
    for term, canonical in aliases:
        if not _term_in(question, term):
            continue
        column = _column_for_value(columns, canonical)
        if column is None:
            continue
        exact = _exact_member(column, canonical) or canonical
        lines.append(f'- "{term}" -> "{column.name}" = {_sql_literal(exact)}')
    return lines


def _bind_value(column: ColumnProfile, literal: str) -> str | None:
    exact = _exact_member(column, literal)
    if exact:
        return exact
    if re.fullmatch(r"\d+\.0+", (literal or "").strip()):
        as_int = _exact_member(column, str(int(float(literal))))
        if as_int:
            return as_int
    hits = _score_against(column, literal, limit=2)
    if not hits:
        return None
    best_value, best_score = hits[0]
    second = hits[1][1] if len(hits) > 1 else 0.0
    if best_score >= 0.92 and best_score - second >= 0.05:
        return best_value
    return None


def _align_filters_to_question(sql: str, columns: list[ColumnProfile], question: str) -> str:
    """Prefer the member that matches the question phrase, even if another member is real."""
    if not question:
        return sql
    equality = re.compile(
        r"""(?P<col>`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>'(?:[^']|'')*'|"(?:[^"]|"")*")""",
        re.I,
    )

    def rewrite_eq(match: re.Match[str]) -> str:
        column = _find_column(columns, _unquote_ident(match.group("col")))
        literal = _unquote_literal(match.group("val"))
        if column is None:
            return match.group(0)
        better = _better_member(column, question, literal)
        if not better:
            return match.group(0)
        return f"{match.group('col')} = {_sql_literal(better)}"

    sql = _replace_spans(sql, equality, rewrite_eq)
    like = re.compile(
        r"""(?P<col>`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)\s+LIKE\s+'(?:%[^']*%|[^']*)'""",
        re.I,
    )

    def rewrite_like(match: re.Match[str]) -> str:
        column = _find_column(columns, _unquote_ident(match.group("col")))
        if column is None:
            return match.group(0)
        better = _better_member(column, question, "")
        if not better:
            return match.group(0)
        return f"{match.group('col')} = {_sql_literal(better)}"

    return _replace_spans(sql, like, rewrite_like)


def _better_member(column: ColumnProfile, question: str, current: str) -> str | None:
    hits = candidate_values(column, question, limit=3)
    if not hits or hits[0][1] < 0.92:
        return None
    best, score = hits[0]
    if len(hits) > 1 and hits[1][1] >= 0.9:
        return None
    if current and _normalize(best) == _normalize(current):
        return None
    if current:
        # Score the stored literal on the same long phrase that picked the winner.
        # A one-word overlap such as "Poland" must not keep "Sales Poland".
        current_score = _score_long_grams(question, current, _strong_width(question, best))
        if score - current_score < 0.08:
            return None
    return best


def _strong_width(question: str, value: str) -> int:
    for gram in _ngrams(question):
        if _score(gram, value) >= 0.9:
            return len(gram.split())
    return 1


def _score_long_grams(question: str, value: str, min_width: int) -> float:
    best = 0.0
    for gram in _ngrams(question):
        if len(gram.split()) < min_width:
            break
        best = max(best, _score(gram, value))
    return best


def _question_member_score(question: str, value: str) -> float:
    if not value:
        return 0.0
    best = 0.0
    for gram in _ngrams(question):
        best = max(best, _score(gram, value))
    return best


def _strip_invented_scale(sql: str, question: str) -> str:
    """Drop a million/billion multiplier the question did not ask for."""
    if re.search(r"\b(million|billion|thousand)\b", question or "", re.I):
        return sql
    return re.sub(r"\s*\*\s*(?:1000000|1000000000|1e6|1e9)\b", "", sql, flags=re.I)


def _strip_preaggregate_measure_filters(sql: str, columns: list[ColumnProfile]) -> str:
    """SUM already skips nulls. A row filter on a summed measure changes the other totals."""
    if not re.search(r"\b(sum|avg)\s*\(", sql, re.I):
        return sql
    aggregated = _aggregated_measure_names(sql, columns)
    if not aggregated:
        return sql
    where = _clause(sql, "where")
    if not where:
        return sql
    kept = [
        pred
        for pred in _split_and(where)
        if not _is_measure_null_test(pred, aggregated)
    ]
    return _replace_where(sql, kept)


def _aggregated_measure_names(sql: str, columns: list[ColumnProfile]) -> set[str]:
    found: set[str] = set()
    for column in columns:
        if column.role != "measure":
            continue
        ident = rf'(?:"{re.escape(column.name)}"|`{re.escape(column.name)}`)'
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column.name):
            ident += rf"|\b{re.escape(column.name)}\b"
        if re.search(rf"\b(SUM|AVG|MIN|MAX)\s*\(\s*(?:CAST\s*\(\s*)?(?:{ident})", sql, re.I):
            found.add(column.name)
    return found


def _is_measure_null_test(predicate: str, measures: set[str]) -> bool:
    mentioned = [name for name in measures if _column_mentioned(predicate, name)]
    if len(mentioned) != 1:
        return False
    if re.search(r"\b(and|or)\b", predicate, re.I):
        return False
    return bool(
        re.search(
            r"\bIS\s+(?:NOT\s+)?NULL\b|(?:!=|<>|=)\s*(?:0(?:\.0+)?|'0(?:\.0+)?'|\"0(?:\.0+)?\")",
            predicate,
            re.I,
        )
    )


def _replace_where(sql: str, predicates: list[str]) -> str:
    match = _keyword_at_depth0(sql, "where")
    if not match:
        return sql
    end = len(sql)
    for later in ("group by", "having", "order by", "limit"):
        found = _keyword_at_depth0(sql[match.end() :], later)
        if found:
            end = min(end, match.end() + found.start())
    prefix = sql[: match.start()].rstrip()
    suffix = sql[end:]
    if not predicates:
        return prefix + " " + suffix.lstrip()
    return prefix + " WHERE " + " AND ".join(predicates) + " " + suffix.lstrip()


def _split_and(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            buf.append(char)
            if char == quote:
                quote = None
            i += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            buf.append(char)
            i += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0 and text[i : i + 5].lower() == " and ":
            parts.append("".join(buf).strip())
            buf = []
            i += 5
            continue
        buf.append(char)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [part for part in parts if part]


def _amount_and_plan(
    columns: list[ColumnProfile],
    question: str = "",
) -> tuple[ColumnProfile | None, ColumnProfile | None]:
    """Default productivity amount and the plan that belongs to the same family.

    Probability-weighted amount is used only when the question says probability
    and does not say non-probability. A spend or gross plan does not replace
    the plan that shares the amount's wording.
    """
    measures = [column for column in columns if column.role == "measure" and column.has_data]
    amount: ColumnProfile | None = None
    plans: list[ColumnProfile] = []
    for column in measures:
        blob = _normalize(column.name + " " + column.description)
        name = _normalize(column.name)
        if "non probability" in blob or (
            "actual" in name and "plan" not in name and "forecast" not in name and "px" not in name
        ):
            if amount is None or "non probability" in blob:
                amount = column
        if ("plan" in name or "target" in name) and "px" not in name:
            plans.append(column)
    if _prefers_probability(question):
        for column in measures:
            blob = _normalize(column.name + " " + column.description)
            if "probability" in blob and "non" not in _tokens(blob):
                amount = column
                break
    return amount, _closest_plan(amount, plans)


def _prefers_probability(question: str) -> bool:
    tokens = set(_tokens(question))
    return "probability" in tokens and "non" not in tokens


def _closest_plan(
    amount: ColumnProfile | None, plans: list[ColumnProfile]
) -> ColumnProfile | None:
    if not plans:
        return None
    if amount is None or len(plans) == 1:
        return plans[0]
    amount_tokens = set(_tokens(amount.name + " " + amount.description)) - {
        "plan",
        "target",
        "forecast",
        "actual",
    }

    def score(column: ColumnProfile) -> int:
        tokens = set(_tokens(column.name + " " + column.description))
        return len(amount_tokens & tokens)

    return max(plans, key=score)


def _asks_ratio(question: str) -> bool:
    text = question or ""
    if re.search(
        r"\b(performance|achievement|achieved|against the target|of their target|of the target|versus target|vs target|of plan|of the plan|versus plan|vs plan)\b",
        text,
        re.I,
    ):
        return True
    if re.search(r"\bwithin\s+\d+(?:\.\d+)?\s*%", text, re.I):
        return True
    return bool(
        re.search(
            r"\b(achieve|achieved|productivity|performance)\b.{0,60}\d+(?:\.\d+)?\s*%"
            r"|\d+(?:\.\d+)?\s*%.{0,40}\b(achieve|achieved|productivity|performance|plan|target)\b",
            text,
            re.I,
        )
    )


def _fix_ratio_ordering(sql: str, columns: list[ColumnProfile], question: str) -> str:
    """Rank and filter on amount/plan after the sums, not on the raw amount."""
    if not _asks_ratio(question) or not _is_simple_select(sql):
        return sql
    amount, plan = _amount_and_plan(columns, question)
    if amount is None or plan is None:
        return sql
    scale = "100.0" if "%" in (question or "") else "1.0"
    ratio = (
        f'(SUM({_q(amount.name)}) * {scale} / NULLIF(SUM({_q(plan.name)}), 0))'
    )
    updated = _rewrite_plan_division(sql, amount, plan, ratio)
    updated = _rewrite_over_order(updated, ratio)
    order = _clause(updated, "order by")
    if (
        order
        and not _order_expression_is_ratio(updated)
        and not re.search(r"\bover\s*\(", updated, re.I)
    ):
        direction = (
            "ASC"
            if re.search(r"\b(lowest|worst|bottom|not achieved|have not|below|under)\b", question, re.I)
            else "DESC"
        )
        updated = _replace_clause(updated, "order by", f"{ratio} {direction}")
    return updated


def _rewrite_over_order(sql: str, ratio: str) -> str:
    match = re.search(r"\bOVER\s*\(", sql, re.I)
    if not match:
        return sql
    start = match.end()
    depth = 1
    index = start
    while index < len(sql) and depth:
        if sql[index] == "(":
            depth += 1
        elif sql[index] == ")":
            depth -= 1
        index += 1
    inner = sql[start : index - 1]
    if "/" in inner:
        return sql
    new_inner = re.sub(r"ORDER\s+BY\s+.+", f"ORDER BY {ratio} DESC", inner, count=1, flags=re.I | re.S)
    return sql[:start] + new_inner + sql[index - 1 :]


def _rewrite_plan_division(
    sql: str, amount: ColumnProfile, plan: ColumnProfile, ratio: str
) -> str:
    """A percent-of-plan question uses the described amount and plan, not a lookalike."""
    select = _clause_between(sql, "select", "from")
    if "/" not in select:
        return sql
    items = _split_csv(select)
    changed = False
    rewritten: list[str] = []
    for item in items:
        if (
            "/" in item
            and re.search(r"\b(SUM|AVG)\s*\(", item, re.I)
            and not (
                _column_mentioned(item, amount.name) and _column_mentioned(item, plan.name)
            )
        ):
            _expr, alias = _split_alias(item)
            rewritten.append(ratio + (f" AS {alias}" if alias else ""))
            changed = True
        else:
            rewritten.append(item)
    if not changed:
        return sql
    return _replace_select_list(sql, ", ".join(rewritten))


def _replace_select_list(sql: str, select_list: str) -> str:
    begin = _keyword_at_depth0(sql, "select")
    finish = _keyword_at_depth0(sql, "from")
    if not begin or not finish or finish.start() <= begin.end():
        return sql
    return sql[: begin.end()] + " " + select_list + " " + sql[finish.start() :]


def _order_expression_is_ratio(sql: str) -> bool:
    order = _clause(sql, "order by")
    if "/" in order:
        return True
    name = _normalize(_unquote_ident(_first_ident(order)))
    for item in _split_csv(_clause_between(sql, "select", "from")):
        if _normalize(_alias_of(item)) == name and "/" in item:
            return True
    return False


def _rewrite_contrast(sql: str, columns: list[ColumnProfile], question: str) -> str:
    """Difference questions use the two described measures, not a similarly named column."""
    pair = _contrast_pair(question, columns)
    if pair is None or not _is_simple_select(sql):
        return sql
    left, right = pair
    if _column_mentioned(sql, left.name) and _column_mentioned(sql, right.name):
        return sql
    if re.search(r"\b(group\s+by| by | per | each | split | across)\b", question, re.I):
        return sql
    table = _from_table(sql)
    where = _attribute_where(sql, columns)
    left_q, right_q = _q(left.name), _q(right.name)
    select = (
        f'SELECT SUM({left_q}) AS "{left.name}", SUM({right_q}) AS "{right.name}", '
        f"SUM({left_q}) - SUM({right_q}) AS difference FROM {table}"
    )
    if where:
        select += " WHERE " + where
    return select


def _contrast_pair(
    question: str, columns: list[ColumnProfile]
) -> tuple[ColumnProfile, ColumnProfile] | None:
    if not question or not re.search(r"\b(difference|versus|vs)\b", question, re.I):
        return None
    body = question
    between = re.search(r"\bbetween\b(.+)$", question, re.I)
    if between:
        body = between.group(1)
    parts = re.split(r"\band\b", body, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None
    measures = [column for column in columns if column.role == "measure" and column.has_data]
    picked: list[ColumnProfile] = []
    for part in parts:
        scored = sorted(
            (( _concept_score(part, column), column) for column in measures),
            key=lambda item: -item[0],
        )
        if not scored or scored[0][0] <= 0:
            return None
        picked.append(scored[0][1])
    if picked[0].name == picked[1].name:
        return None
    return picked[0], picked[1]


def _concept_score(side: str, column: ColumnProfile) -> float:
    blob = _normalize(column.name + " " + column.description)
    side_norm = _normalize(side)
    side_tokens = set(_tokens(side_norm))
    if not blob or not side_tokens:
        return 0.0
    blob_tokens = _tokens(blob)
    negated = "non" in side_tokens
    blob_negated = "non" in blob_tokens
    probable = _mentions(side_tokens, "probability")
    blob_probable = _mentions(blob_tokens, "probability")
    if negated != blob_negated and probable and blob_probable:
        return 0.0
    overlap = 0
    for token in side_tokens:
        if token in _STOP or token in {"non", "under", "weighted", "productivity"}:
            continue
        if any(_token_close(token, other) for other in blob_tokens):
            overlap += 1
    if negated and blob_negated:
        overlap += 2
    if not negated and not blob_negated and probable and blob_probable:
        overlap += 2
    name_tokens = set(_tokens(column.name))
    if re.search(r"\bpx\d*\b", blob) and not re.search(r"\bpx\d*\b", side_norm):
        overlap -= 5
    if probable and negated and "actual" in name_tokens and "agg" not in name_tokens:
        overlap += 3
    if probable and not negated and "agg" in name_tokens:
        overlap += 3
    return float(overlap)


def _mentions(tokens: set[str] | list[str], word: str) -> bool:
    return any(token == word or _token_close(token, word) for token in tokens)


def _rewrite_winner_then_top(sql: str, columns: list[ColumnProfile], question: str) -> str:
    """Which group wins, then the top N members inside that group."""
    parsed = _winner_request(question, columns)
    if parsed is None or not _is_simple_select(sql):
        return sql
    parent, child, limit, highest = parsed
    if not re.search(r"\bgroup\s+by\b", sql, re.I) or not re.search(r"\blimit\s+\d+\b", sql, re.I):
        return sql
    metric = _primary_aggregate(sql)
    if not metric:
        amount, _plan = _amount_and_plan(columns, question)
        if amount is None:
            return sql
        metric = f"SUM({_q(amount.name)})"
    table = _from_table(sql)
    outer_preds = _split_and(_clause(sql, "where"))
    shared = [
        pred
        for pred in outer_preds
        if not _column_mentioned(pred, parent.name) and not _column_mentioned(pred, child.name)
    ]
    direction = "DESC" if highest else "ASC"
    parent_q, child_q = _q(parent.name), _q(child.name)
    key = _pair_key(columns, child)
    key_select = f", {_q(key.name)}" if key else ""
    key_group = f", {_q(key.name)}" if key else ""
    parent_guard = f"{parent_q} IS NOT NULL AND TRIM({parent_q}) <> ''"
    winner = (
        f"SELECT {parent_q} FROM {table} WHERE {' AND '.join([*shared, parent_guard])} "
        f"GROUP BY {parent_q} HAVING {metric} IS NOT NULL "
        f"ORDER BY {metric} {direction} LIMIT 1"
    )
    child_preds = list(shared)
    child_preds.append(f"{parent_q} = ({winner})")
    child_preds.append(f"{child_q} IS NOT NULL AND TRIM({child_q}) <> ''")
    return (
        f"SELECT {child_q}{key_select}, {parent_q}, {metric} AS total_value "
        f"FROM {table} WHERE {' AND '.join(child_preds)} "
        f"GROUP BY {child_q}{key_group}, {parent_q} "
        f"HAVING {metric} IS NOT NULL "
        f"ORDER BY total_value {direction} LIMIT {limit}"
    )


def _winner_request(
    question: str, columns: list[ColumnProfile]
) -> tuple[ColumnProfile, ColumnProfile, int, bool] | None:
    which = re.search(
        r"\bwhich\s+(.+?)\s+(?:has|have|is|are|with)\b.+?\b(highest|lowest|best|worst)\b",
        question or "",
        re.I,
    )
    top = re.search(
        r"\btop\s+(\d+)\s+([a-z][a-z0-9-]+)(?:\s+(?!in\b|for\b|of\b|within\b|inside\b|from\b|that\b|with\b|by\b|under\b|during\b)([a-z][a-z0-9-]+))?",
        question or "",
        re.I,
    )
    if not which or not top:
        return None
    child_phrase = top.group(2) if not top.group(3) else f"{top.group(2)} {top.group(3)}"
    parent = _match_dimension(which.group(1), columns)
    child = _match_dimension(child_phrase, columns)
    if parent is None or child is None or parent.name == child.name:
        return None
    highest = which.group(2).lower() in {"highest", "best"}
    return parent, child, int(top.group(1)), highest


_DIM_HINTS = {
    "project": ("project", "initiative"),
    "projects": ("project", "initiative"),
    "initiative": ("initiative", "project"),
    "initiatives": ("initiative", "project"),
    "site": ("site",),
    "sites": ("site",),
    "bu": ("bu", "business"),
    "bus": ("bu", "business"),
    "business": ("bu", "business"),
    "unit": ("bu", "business"),
    "units": ("bu", "business"),
    "workstream": ("workstream",),
    "workstreams": ("workstream",),
    "pillar": ("pillar",),
    "pillars": ("pillar",),
}


def _match_dimension(phrase: str, columns: list[ColumnProfile]) -> ColumnProfile | None:
    tokens = _tokens(phrase)
    hints: set[str] = set(tokens)
    for token in tokens:
        hints.update(_DIM_HINTS.get(token, ()))
    labels = {label for _key, label in key_label_pairs(columns)}
    best: ColumnProfile | None = None
    best_score = 0
    for column in columns:
        if column.role == "measure" or not column.has_data:
            continue
        blob = set(_tokens(column.name + " " + column.description))
        score = 0
        for hint in hints:
            if any(_token_close(hint, other) or hint == other for other in blob):
                score += 2
        if column.name.lower() in {token.lower() for token in tokens}:
            score += 3
        prefer_label = (
            score == best_score
            and score > 0
            and column.name in labels
            and (best is None or best.name not in labels)
        )
        if score > best_score or prefer_label:
            best, best_score = column, score
    if best_score < 2:
        return None
    return best


def _pair_key(columns: list[ColumnProfile], label: ColumnProfile) -> ColumnProfile | None:
    for key, paired in key_label_pairs(columns):
        if paired == label.name:
            return _find_column(columns, key)
    return None


def _primary_aggregate(sql: str) -> str:
    select = _clause_between(sql, "select", "from")
    for item in _split_csv(select):
        expr = _expression_of(item)
        if _AGG_FN.search(expr):
            return expr
    return ""


def _attribute_where(sql: str, columns: list[ColumnProfile]) -> str:
    kept = []
    for pred in _split_and(_clause(sql, "where")):
        if any(
            column.role == "measure" and _column_mentioned(pred, column.name)
            for column in columns
        ):
            continue
        kept.append(pred)
    return " AND ".join(kept)


def _from_table(sql: str) -> str:
    match = re.search(r"\bfrom\s+([^\s]+)", sql, re.I)
    return match.group(1) if match else "KPI_data"


def _replace_clause(sql: str, keyword: str, body: str) -> str:
    match = _keyword_at_depth0(sql, keyword)
    if not match:
        return sql
    rest = sql[match.end() :]
    end = len(rest)
    for later in ("group by", "having", "order by", "limit"):
        if later == keyword:
            continue
        found = _keyword_at_depth0(rest, later)
        if found and found.start() < end:
            end = found.start()
    return sql[: match.start()] + keyword.upper() + " " + body + " " + rest[end:]


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _bind_comparisons(sql: str, columns: list[ColumnProfile]) -> str:
    pattern = re.compile(
        r"""(?P<col>`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>'(?:[^']|'')*'|"(?:[^"]|"")*")""",
        re.I,
    )
    return _replace_spans(sql, pattern, lambda match: _rewrite_equality(match, columns))


def _bind_in_lists(sql: str, columns: list[ColumnProfile]) -> str:
    pattern = re.compile(
        r"""(?P<col>`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)\s+in\s*\((?P<body>[^)]*)\)""",
        re.I,
    )

    def rewrite(match: re.Match[str]) -> str:
        column = _find_column(columns, _unquote_ident(match.group("col")))
        if column is None or not column.values:
            return match.group(0)
        parts = _split_csv(match.group("body"))
        rewritten: list[str] = []
        for part in parts:
            stripped = part.strip()
            if not stripped or stripped[0] not in {"'", '"'}:
                rewritten.append(stripped)
                continue
            literal = _unquote_literal(stripped)
            bound = _bind_value(column, literal)
            rewritten.append(_sql_literal(bound if bound else literal))
        return f"{match.group('col')} IN ({', '.join(rewritten)})"

    return _replace_spans(sql, pattern, rewrite)


def _rewrite_equality(match: re.Match[str], columns: list[ColumnProfile]) -> str:
    column = _find_column(columns, _unquote_ident(match.group("col")))
    literal = _unquote_literal(match.group("val"))
    if column is None or not column.values:
        return match.group(0)
    bound = _bind_value(column, literal)
    if not bound or bound == literal:
        return match.group(0)
    return f"{match.group('col')} = {_sql_literal(bound)}"


def _apply_glossary(
    sql: str,
    question: str,
    aliases: list[tuple[str, str]],
    columns: list[ColumnProfile],
) -> str:
    """Map a glossary term onto its stored member when the user did not type that member."""
    if not question or not aliases:
        return sql
    updated = sql
    applied: set[str] = set()
    for term, canonical in aliases:
        if not _term_in(question, term):
            continue
        column = _column_for_value(columns, canonical)
        if column is None or column.name in applied:
            continue
        exact = _exact_member(column, canonical)
        if not exact or _question_names_member(question, column):
            continue
        if _column_is_filtered(updated, column.name):
            updated = _replace_column_literal(updated, column.name, exact)
        elif _is_simple_select(updated):
            quoted = '"' + column.name.replace('"', '""') + '"'
            updated = _insert_before_clause(updated, f"{quoted} = {_sql_literal(exact)}")
        else:
            continue
        applied.add(column.name)
    return updated


def _question_names_member(question: str, column: ColumnProfile) -> bool:
    """True when the user already typed a stored member, so glossary must not override it."""
    for value in column.values:
        if len(value) >= 4 and _term_in(question, value):
            return True
    return False


def _column_is_filtered(sql: str, name: str) -> bool:
    quoted = rf'(?:`{re.escape(name)}`|"{re.escape(name)}"'
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        quoted += rf"|\b{re.escape(name)}\b"
    quoted += ")"
    return re.search(rf"{quoted}\s*(?:=|\bIN\b)", sql, re.I) is not None


def _replace_column_literal(sql: str, column_name: str, exact: str) -> str:
    pattern = re.compile(
        rf"""(?P<col>`{re.escape(column_name)}`|"{re.escape(column_name)}"|\b{re.escape(column_name)}\b)\s*=\s*(?P<val>'(?:[^']|'')*'|"(?:[^"]|"")*")""",
        re.I,
    )

    def rewrite(match: re.Match[str]) -> str:
        current = _unquote_literal(match.group("val"))
        if _normalize(current) == _normalize(exact):
            return f"{match.group('col')} = {_sql_literal(exact)}"
        return f"{match.group('col')} = {_sql_literal(exact)}"

    return _replace_spans(sql, pattern, rewrite)


def _drop_blank_groups(sql: str, columns: list[ColumnProfile]) -> str:
    group = _clause(sql, "group by")
    if not group:
        return sql
    predicates: list[str] = []
    for ident in _split_csv(group):
        name = _unquote_ident(ident.strip())
        column = _find_column(columns, name)
        if column is None or column.role == "measure":
            continue
        quoted = _quote_like(ident.strip(), name)
        predicate = f"{quoted} IS NOT NULL AND TRIM({quoted}) <> ''"
        if predicate.lower() in sql.lower():
            continue
        predicates.append(predicate)
    if not predicates:
        return sql
    return _insert_before_clause(sql, " AND ".join(predicates))


def _drop_null_aggregates(sql: str) -> str:
    if re.search(r"\bhaving\b", sql, re.I):
        return sql
    if not re.search(r"\bgroup\s+by\b", sql, re.I):
        return sql
    if not re.search(r"\border\s+by\b", sql, re.I):
        return sql
    expr = _ordered_aggregate(sql)
    if not expr:
        return sql
    having = f"HAVING {expr} IS NOT NULL"
    return _insert_keyword(sql, "order by", having)


def _ordered_aggregate(sql: str) -> str:
    order = _clause(sql, "order by")
    if not order:
        return ""
    token = _first_ident(order)
    name = _unquote_ident(token)
    select = _clause_between(sql, "select", "from")
    alias_map: dict[str, str] = {}
    for item in _split_csv(select):
        alias = _alias_of(item)
        expr = _expression_of(item)
        if re.search(r"\bover\s*\(", expr, re.I):
            continue
        if alias and _AGG_FN.search(expr):
            alias_map[_normalize(alias)] = expr
        elif _AGG_FN.search(expr):
            alias_map[_normalize(expr)] = expr
    mapped = alias_map.get(_normalize(name))
    if mapped:
        return mapped
    if _AGG_FN.search(order):
        return re.split(r"\s+(?:ASC|DESC)\b", order, maxsplit=1, flags=re.I)[0].strip()
    return ""


def _is_simple_select(sql: str) -> bool:
    lowered = f" {sql.lower()} "
    return lowered.count(" select ") == 1 and " join " not in lowered


def _insert_before_clause(sql: str, predicate: str) -> str:
    for keyword in ("group by", "order by", "limit"):
        match = _keyword_at_depth0(sql, keyword)
        if not match:
            continue
        prefix = sql[: match.start()]
        if re.search(r"\bwhere\b", prefix, re.I):
            glue = " AND "
        else:
            glue = " WHERE "
        return sql[: match.start()].rstrip() + glue + predicate + " " + sql[match.start() :]
    if re.search(r"\bwhere\b", sql, re.I):
        return sql.rstrip() + " AND " + predicate
    return sql.rstrip() + " WHERE " + predicate


def _insert_keyword(sql: str, keyword: str, insertion: str) -> str:
    match = _keyword_at_depth0(sql, keyword)
    if not match:
        return sql
    return sql[: match.start()].rstrip() + " " + insertion + " " + sql[match.start() :]


def _keyword_at_depth0(sql: str, keyword: str) -> re.Match[str] | None:
    depth = 0
    pattern = re.compile(rf"\b{keyword}\b", re.I)
    for match in pattern.finditer(sql):
        depth = sql[: match.start()].count("(") - sql[: match.start()].count(")")
        if depth == 0:
            return match
    return None


def _clause(sql: str, keyword: str) -> str:
    match = _keyword_at_depth0(sql, keyword)
    if not match:
        return ""
    rest = sql[match.end() :]
    end = len(rest)
    for later in ("group by", "having", "order by", "limit"):
        if later == keyword:
            continue
        found = _keyword_at_depth0(rest, later)
        if found and found.start() < end:
            end = found.start()
    return rest[:end].strip()


def _clause_between(sql: str, start: str, end: str) -> str:
    begin = _keyword_at_depth0(sql, start)
    finish = _keyword_at_depth0(sql, end)
    if not begin or not finish or finish.start() <= begin.end():
        return ""
    return sql[begin.end() : finish.start()].strip()


def _alias_of(select_item: str) -> str:
    _expr, alias = _split_alias(select_item)
    return _unquote_ident(alias)


def _expression_of(select_item: str) -> str:
    expr, _alias = _split_alias(select_item)
    return expr


def _split_alias(select_item: str) -> tuple[str, str]:
    """Split ``expr AS alias`` at depth 0. ``CAST(x AS FLOAT)`` is not an alias."""
    depth = 0
    quote: str | None = None
    cut: int | None = None
    index = 0
    while index < len(select_item):
        char = select_item[index]
        if quote:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0 and select_item[index : index + 4].lower() == " as ":
            cut = index
        index += 1
    if cut is None:
        return select_item.strip(), ""
    return select_item[:cut].strip(), select_item[cut + 4 :].strip()


def _equality_literals(sql: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"""(?P<col>`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>'(?:[^']|'')*'|"(?:[^"]|"")*")""",
        re.I,
    )
    found: list[tuple[str, str]] = []
    for match in pattern.finditer(sql or ""):
        found.append((_unquote_ident(match.group("col")), _unquote_literal(match.group("val"))))
    return found


def _column_mentioned(sql: str, name: str) -> bool:
    if re.search(rf'`{re.escape(name)}`|"{re.escape(name)}"', sql):
        return True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return re.search(rf"\b{re.escape(name)}\b", sql) is not None
    return False


def _find_column(columns: list[ColumnProfile], name: str) -> ColumnProfile | None:
    target = _normalize(name)
    for column in columns:
        if _normalize(column.name) == target:
            return column
    return None


def _column_for_value(columns: list[ColumnProfile], value: str) -> ColumnProfile | None:
    for column in columns:
        if _exact_member(column, value):
            return column
    return None


def _exact_member(column: ColumnProfile, literal: str) -> str | None:
    if literal in column.values:
        return literal
    return column.norm_to_exact.get(_normalize(literal))


def _score_against(
    column: ColumnProfile, literal: str, *, limit: int
) -> list[tuple[str, float]]:
    best: dict[str, float] = {}
    pool = _lookup(column, _tokens(literal)) or column.values[:300]
    for value in pool:
        score = _score(literal, value)
        if score > best.get(value, 0.0):
            best[value] = score
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:limit]


def _lookup(column: ColumnProfile, tokens: list[str]) -> list[str]:
    useful = [token for token in tokens if token not in _STOP and len(token) >= 3]
    if not useful:
        return []
    sets: list[set[str]] = []
    for token in useful:
        hits = set(column.token_index.get(token, []))
        if not hits:
            for key, values in column.token_index.items():
                if _token_close(token, key):
                    hits.update(values)
        if hits:
            sets.append(hits)
    if not sets:
        return []
    sets.sort(key=len)
    chosen = sets[0]
    for other in sets[1:]:
        shared = chosen & other
        if shared:
            chosen = shared
    return list(chosen)[:200]


def _score(query: str, value: str) -> float:
    left = _normalize(query)
    right = _normalize(value)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if right.startswith(left) or left.startswith(right):
        ratio = min(len(left), len(right)) / max(len(left), len(right))
        if ratio >= 0.84:
            return 0.9 + 0.09 * ratio
    q_tokens = [token for token in _tokens(left) if token not in _STOP]
    v_tokens = [token for token in _tokens(right) if token not in _STOP]
    if not q_tokens or not v_tokens:
        return 0.0
    covered = 0
    matched_values: set[str] = set()
    for token in q_tokens:
        close = next((item for item in v_tokens if _token_close(token, item)), "")
        if close:
            covered += 1
            matched_values.add(close)
    cover = covered / len(q_tokens)
    extra = max(0, len(v_tokens) - len(matched_values)) / len(v_tokens)
    return cover - 0.12 * extra


def _token_close(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) < 4 or len(right) < 4:
        return False
    if left.startswith(right) or right.startswith(left):
        return abs(len(left) - len(right)) <= 2
    if min(len(left), len(right)) >= 8 and abs(len(left) - len(right)) <= 1:
        return _one_edit(left, right)
    return False


def _one_edit(left: str, right: str) -> bool:
    if len(left) > len(right):
        left, right = right, left
    index = 0
    while index < len(left) and left[index] == right[index]:
        index += 1
    if len(left) == len(right):
        return left[index + 1 :] == right[index + 1 :]
    return left[index:] == right[index + 1 :]


def _normalize(text: str) -> str:
    cleaned = (text or "").replace("\xa0", " ").lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


def _tokens(text: str) -> list[str]:
    return [token for token in _normalize(text).split() if token]


def _ngrams(question: str) -> list[str]:
    tokens = [token for token in _tokens(question) if token not in _STOP]
    grams: list[str] = []
    for size in range(min(6, len(tokens)), 0, -1):
        for index in range(0, len(tokens) - size + 1):
            grams.append(" ".join(tokens[index : index + size]))
    return grams


def _initials(value: str) -> str:
    tokens = [token for token in _tokens(value) if token not in _STOP]
    return "".join(token[0] for token in tokens)


def _term_in(question: str, term: str) -> bool:
    if not question or not term:
        return False
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", question, re.I) is not None


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _unquote_literal(token: str) -> str:
    text = token.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        body = text[1:-1]
        return body.replace("''", "'").replace('""', '"')
    return text


def _first_ident(text: str) -> str:
    body = text.strip()
    if not body:
        return ""
    opener = body[0]
    if opener in {'`', '"'}:
        end = body.find(opener, 1)
        return body[: end + 1] if end > 0 else body.split()[0]
    if opener == "[":
        end = body.find("]")
        return body[: end + 1] if end > 0 else body.split()[0]
    return body.split()[0].rstrip(",")


def _unquote_ident(token: str) -> str:
    text = token.strip().rstrip(",")
    if len(text) >= 2 and text[0] in {'`', '"', "["} and text[-1] in {'`', '"', "]"}:
        return text[1:-1]
    return text


def _quote_like(original: str, name: str) -> str:
    token = original.strip().rstrip(",")
    if token.startswith("`"):
        return "`" + name.replace("`", "``") + "`"
    if token.startswith("["):
        return "[" + name + "]"
    return '"' + name.replace('"', '""') + '"'


def _split_csv(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote: str | None = None
    for char in text:
        if in_quote:
            buf.append(char)
            if char == in_quote:
                in_quote = None
            continue
        if char in {"'", '"', "`"}:
            in_quote = char
            buf.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(char)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _replace_spans(sql: str, pattern: re.Pattern[str], rewrite) -> str:
    matches = list(pattern.finditer(sql))
    if not matches:
        return sql
    updated = sql
    for match in reversed(matches):
        updated = updated[: match.start()] + rewrite(match) + updated[match.end() :]
    return updated
