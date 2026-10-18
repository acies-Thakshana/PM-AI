"""Deterministic plan and SQL used when no model is configured or the model fails.

Everything it knows comes from the domain package and the live tables:
certified metrics, glossary filter values, business rules, stored members,
and registered joins. It never invents a join or a formula.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.services.common.text import content_tokens, phrase_in, quote_ident, slug, sql_literal
from app.services.semantic.models import DomainPackage, MetricVersion, RegisteredJoin
from app.services.semantic.store import SemanticStore, scope_filter_value

_RANKING = re.compile(r"\b(top|rank|ranking|highest|lowest|best|worst|most|least|bottom|largest|smallest)\b")
_COMPARISON = re.compile(r"\b(compare|comparison|versus|vs\.?|against)\b")
_TREND = re.compile(
    r"\b(trend|over time|monthly|weekly|daily|quarterly|yearly|"
    r"per (?:month|week|day|quarter|year)|by (?:month|week|day|quarter|year))\b"
)
_BREAKDOWN = re.compile(r"\b(by|per|each|across|split|breakdown|break down)\b")
_ASCENDING = re.compile(r"\b(lowest|least|bottom|smallest|fewest|minimum)\b")
_COUNT = re.compile(r"\b(how many|count|number of)\b")
_AVG = re.compile(r"\b(average|avg|mean)\b")
_MAX = re.compile(r"\b(maximum|max|peak)\b")
_MIN = re.compile(r"\b(minimum|min)\b")
_TOP_N = re.compile(
    r"\b(?:top|bottom|first)\s+(\d{1,3})\b|\b(\d{1,3})\s+(?:best|worst|highest|lowest|largest|smallest)\b"
)
_SINGULAR_WHICH = re.compile(r"\bwhich\b[^?]*\b(has|is|had|was)\b")
_AGG_SQL = {"avg": "AVG", "sum": "SUM", "min": "MIN", "max": "MAX", "count": "COUNT"}
_TIME_FORMATS = (
    ("quarter", "strftime('%Y', {c}) || '-Q' || ((CAST(strftime('%m', {c}) AS INTEGER) + 2) / 3)"),
    ("week", "strftime('%Y-%W', {c})"),
    ("daily", "strftime('%Y-%m-%d', {c})"),
    ("day", "strftime('%Y-%m-%d', {c})"),
    ("year", "strftime('%Y', {c})"),
)
_COL = re.compile(r"@@(.+?)@@")
_MAX_FILTER_CARDINALITY = 200


def col(name: str) -> str:
    """Placeholder for a column; rendered with or without a table alias."""
    return f"@@{name}@@"


def detect_intent(question: str) -> str:
    q = question.lower()
    if _RANKING.search(q):
        return "ranking"
    if _COMPARISON.search(q):
        return "comparison"
    if _TREND.search(q):
        return "trend"
    if _BREAKDOWN.search(q):
        return "breakdown"
    return "aggregation"


def _is_measure(series: pd.Series, name: str) -> bool:
    if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return False
    lowered = name.lower()
    return not (lowered == "id" or lowered.endswith("_id") or lowered.endswith(" id"))


def _spoken(name: str) -> str:
    return re.sub(r"[_\s]+", " ", name).strip().lower()


def _mentions(question: str, phrase: str) -> bool:
    """Phrase or its simple plural appears in the question."""
    return phrase_in(question, phrase) or phrase_in(question, phrase + "s") or phrase_in(question, phrase + "es")


def _keyword_hit(question: str, keyword: str) -> int:
    """Length of a keyword match, ignoring matches negated by a leading 'non'."""
    text = question.lower()
    key = keyword.strip().lower()
    if not key:
        return 0
    for match in re.finditer(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text):
        before = text[: match.start()]
        if re.search(r"\bnon[\s-]*$", before) and not key.startswith("non"):
            continue
        return len(key)
    return 0


@dataclass
class Dimension:
    table: str
    alias: str
    expression: str


@dataclass
class LocalQuery:
    intent: str
    base_table: str
    value_expr: str
    value_alias: str
    metric: dict[str, Any]
    confidence: float
    dims: list[Dimension] = field(default_factory=list)
    filters: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    joins: list[tuple[RegisteredJoin, str]] = field(default_factory=list)
    order: str = ""
    limit: int | None = None
    having_not_null: bool = False
    rationale: list[str] = field(default_factory=list)
    columns_used: list[str] = field(default_factory=list)
    clarification: str = ""

    @property
    def tables(self) -> list[str]:
        return [self.base_table, *[table for _, table in self.joins]]


class LocalPlanner:
    def __init__(self, store: SemanticStore) -> None:
        self.store = store

    # ----- public -----------------------------------------------------------

    def draft(
        self, question: str, pkg: DomainPackage, frames: dict[str, pd.DataFrame]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        query = self.build(question, pkg, frames)
        sql = self.render_sql(query, pkg)
        return self._plan_payload(pkg, query), {
            "sql_query": sql,
            "datasets_used": query.tables,
            "columns_used": sorted(set(query.columns_used) | {c for _, c in query.filters}),
            "rationale": "local structured planner: " + "; ".join(query.rationale),
        }

    def build(self, question: str, pkg: DomainPackage, frames: dict[str, pd.DataFrame]) -> LocalQuery:
        intent = detect_intent(question)
        metric = self.store.resolve_metric(question, pkg)
        query = self._metric_query(question, pkg, frames, metric, intent) if metric else None
        if query is None:
            query = self._measure_query(question, pkg, frames, intent)
        if query.clarification:
            return query
        reachable = self._reachable_tables(pkg, frames, query.base_table)
        self._add_filters(question, pkg, frames, query, reachable)
        self._add_dimensions(question, pkg, frames, query, reachable)
        self._finish_order(question, query)
        return query

    # ----- measure selection ------------------------------------------------

    def _metric_query(
        self,
        question: str,
        pkg: DomainPackage,
        frames: dict[str, pd.DataFrame],
        metric: MetricVersion,
        intent: str,
    ) -> LocalQuery | None:
        entity = pkg.entity_for_product(metric.data_product_id)
        if entity is None or entity.physical_dataset not in frames:
            return None
        frame = frames[entity.physical_dataset]
        scope = scope_filter_value(metric)
        if scope and len(self._values_for_column(question, pkg, frame, scope[0])) > 1:
            metric = next((m for m in pkg.metrics if m.family == metric.family and m.default_for_family), metric)
            scope = scope_filter_value(metric)
        expression = self._metric_expression(metric, frame)
        if expression is None:
            return None
        query = LocalQuery(
            intent=intent,
            base_table=entity.physical_dataset,
            value_expr=expression,
            value_alias=slug(metric.name) or "value",
            metric={
                "id": metric.id,
                "name": metric.name,
                "calculation": metric.sql_expression,
                "sql_expression": _COL.sub(lambda m: quote_ident(m.group(1)), expression),
                "grain": metric.grain,
                "scope": metric.scope,
                "version": metric.version,
                "unit": metric.unit,
            },
            confidence=0.85,
        )
        query.rationale.append(f"certified metric {metric.id} v{metric.version}")
        compute = metric.compute or {}
        query.columns_used.extend(str(compute[k]) for k in ("start_column", "end_column", "column") if compute.get(k))
        query.columns_used.extend(
            str(column)
            for column in frame.columns
            if str(column) not in query.columns_used
            and (
                quote_ident(str(column)) in metric.sql_expression
                or re.search(rf"(?<![A-Za-z0-9_]){re.escape(str(column))}(?![A-Za-z0-9_])", metric.sql_expression)
            )
        )
        if scope:
            query.filters[(entity.physical_dataset, scope[0])] = [scope[1]]
            query.columns_used.append(scope[0])
        return query

    @staticmethod
    def _metric_expression(metric: MetricVersion, frame: pd.DataFrame) -> str | None:
        compute = metric.compute or {}
        aggregation = str(compute.get("aggregation") or metric.aggregation)
        kind = compute.get("kind")
        if kind == "duration_hours":
            start, end = compute.get("start_column"), compute.get("end_column")
            if start not in frame.columns or end not in frame.columns:
                return None
            inner = f"(julianday({col(end)}) - julianday({col(start)})) * 24.0"
        elif compute.get("column"):
            if compute["column"] not in frame.columns:
                return None
            inner = col(compute["column"])
        elif aggregation == "count":
            return "COUNT(*)"
        else:
            expression = metric.sql_expression
            matched = False
            for column in sorted(map(str, frame.columns), key=len, reverse=True):
                placeholder = col(column)
                quoted = quote_ident(column)
                if quoted in expression:
                    expression = expression.replace(quoted, placeholder)
                    matched = True
                elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", column):
                    expression, count = re.subn(
                        rf"(?<![A-Za-z0-9_]){re.escape(column)}(?![A-Za-z0-9_])",
                        placeholder,
                        expression,
                    )
                    matched = matched or bool(count)
            return expression if matched or expression.strip().upper() == "COUNT(*)" else None
        if aggregation == "count_distinct":
            return f"COUNT(DISTINCT {inner})"
        fn = _AGG_SQL.get(aggregation)
        return f"{fn}({inner})" if fn else None

    def _measure_query(
        self, question: str, pkg: DomainPackage, frames: dict[str, pd.DataFrame], intent: str
    ) -> LocalQuery:
        q = question.lower()
        words = content_tokens(question)
        preferred = self._rule_preferred_columns(question, pkg)
        best: tuple[float, str, str] | None = None
        grounded = False
        for table, frame in frames.items():
            for column in map(str, frame.columns):
                if not _is_measure(frame[column], column):
                    continue
                overlap = len(words & content_tokens(_spoken(column)))
                score = overlap * 2.0 + preferred.get(column, 0.0) - float(frame[column].isna().mean())
                if best is None or score > best[0]:
                    best = (score, table, column)
                    grounded = bool(overlap or column in preferred)
        if not _COUNT.search(q) and not grounded and self._mentioned_table(question, pkg, frames) is None:
            query = LocalQuery(
                intent="clarification_needed",
                base_table=self._table_for_question(question, pkg, frames),
                value_expr="COUNT(*)",
                value_alias="row_count",
                metric={},
                confidence=0.0,
            )
            query.clarification = self._clarification(pkg, frames)
            query.rationale.append("no metric, measure, or dataset matched the question")
            return query
        if best is None or _COUNT.search(q):
            base = self._table_for_question(question, pkg, frames)
            query = LocalQuery(
                intent=intent,
                base_table=base,
                value_expr="COUNT(*)",
                value_alias="row_count",
                metric={
                    "name": f"Number of {base.replace('_', ' ')}",
                    "calculation": "COUNT(*)",
                    "sql_expression": "COUNT(*)",
                    "grain": "row",
                },
                confidence=0.5 if _COUNT.search(q) else 0.3,
            )
            query.rationale.append("row count" if _COUNT.search(q) else "row count: no measure columns")
            return query
        score, table, column = best
        aggregation = "avg" if _AVG.search(q) else "max" if _MAX.search(q) else "min" if _MIN.search(q) else "sum"
        expression = f"{_AGG_SQL[aggregation]}({col(column)})"
        query = LocalQuery(
            intent=intent,
            base_table=table,
            value_expr=expression,
            value_alias=slug(f"{aggregation} {column}") or "value",
            metric={
                "name": column,
                "calculation": f"{aggregation.upper()}({column})",
                "sql_expression": f"{_AGG_SQL[aggregation]}({quote_ident(column)})",
                "grain": "as stored",
            },
            confidence=0.55 if score > 0 else 0.35,
        )
        query.columns_used.append(column)
        query.rationale.append(
            f"measure {column} matched the question" if score > 0 else f"defaulted to measure {column}"
        )
        return query

    @staticmethod
    def _clarification(pkg: DomainPackage, frames: dict[str, pd.DataFrame]) -> str:
        names = [m.name for m in pkg.metrics if m.status == "certified"]
        if not names:
            names = [k.name for k in pkg.dictionary.kpis]
        if not names:
            names = [str(c) for frame in frames.values() for c in frame.columns if _is_measure(frame[c], str(c))]
        choices = ", ".join(dict.fromkeys(names[:5])) or "a dataset and a measure"
        return f"Which metric do you mean? Available: {choices}."

    @staticmethod
    def _rule_preferred_columns(question: str, pkg: DomainPackage) -> dict[str, float]:
        """Columns named by matching business rules. Longer keyword matches weigh more."""
        preferred: dict[str, float] = {}
        for rule in pkg.rules:
            if rule.rule_type not in {"definition", "calculation"}:
                continue
            hit = max((_keyword_hit(question, k) for k in rule.keywords), default=0) if rule.keywords else 1
            if not hit:
                continue
            for column in rule.applies_to:
                preferred[column] = max(preferred.get(column, 0.0), 1.0 + 0.1 * hit)
        return preferred

    @staticmethod
    def _mentioned_table(question: str, pkg: DomainPackage, frames: dict[str, pd.DataFrame]) -> str | None:
        for entity in pkg.entities:
            if entity.physical_dataset not in frames:
                continue
            names = {entity.logical_entity, entity.physical_dataset, entity.logical_entity.replace("_", " ")}
            if any(_mentions(question, n) for n in names):
                return entity.physical_dataset
        return None

    @classmethod
    def _table_for_question(cls, question: str, pkg: DomainPackage, frames: dict[str, pd.DataFrame]) -> str:
        mentioned = cls._mentioned_table(question, pkg, frames)
        if mentioned:
            return mentioned
        for entity in pkg.entities:
            if entity.entity_kind == "transactional" and entity.physical_dataset in frames:
                return entity.physical_dataset
        return next(iter(frames))

    # ----- filters and dimensions ------------------------------------------

    @staticmethod
    def _reachable_tables(
        pkg: DomainPackage, frames: dict[str, pd.DataFrame], base: str
    ) -> dict[str, RegisteredJoin | None]:
        """The base table plus tables one registered join away."""
        reachable: dict[str, RegisteredJoin | None] = {base: None}
        base_entity = pkg.entity_for_dataset(base)
        if base_entity is None:
            return reachable
        for join in pkg.joins:
            if not join.allowed_for_nlq or base_entity.logical_entity not in {join.left_entity, join.right_entity}:
                continue
            other_name = join.right_entity if join.left_entity == base_entity.logical_entity else join.left_entity
            other = next((e for e in pkg.entities if e.logical_entity == other_name), None)
            if other and other.physical_dataset in frames and other.physical_dataset not in reachable:
                reachable[other.physical_dataset] = join
        return reachable

    @staticmethod
    def _values_for_column(question: str, pkg: DomainPackage, frame: pd.DataFrame, column: str) -> list[str]:
        if column not in frame.columns:
            return []
        stored = {str(v) for v in frame[column].dropna().unique()}
        found: list[str] = []
        for term in pkg.glossary:
            if term.maps_to_kind != "filter_value" or term.maps_to_id.split(".")[-1] != column:
                continue
            value = term.canonical_value or term.term
            if phrase_in(question, term.term) and value in stored and value not in found:
                found.append(value)
        for value in sorted(stored, key=len, reverse=True):
            if len(value) >= 2 and phrase_in(question, value) and value not in found:
                found.append(value)
        return found

    def _add_filters(
        self,
        question: str,
        pkg: DomainPackage,
        frames: dict[str, pd.DataFrame],
        query: LocalQuery,
        reachable: dict[str, RegisteredJoin | None],
    ) -> None:
        claimed = {v.lower() for values in query.filters.values() for v in values}
        for table in reachable:
            frame = frames[table]
            for column in map(str, frame.columns):
                if (table, column) in query.filters:
                    continue
                series = frame[column]
                if _is_measure(series, column) or series.nunique(dropna=True) > _MAX_FILTER_CARDINALITY:
                    continue
                values = [v for v in self._values_for_column(question, pkg, frame, column) if v.lower() not in claimed]
                if not values:
                    continue
                query.filters[(table, column)] = values
                claimed.update(v.lower() for v in values)
                self._use_table(query, reachable, table)

    def _add_dimensions(
        self,
        question: str,
        pkg: DomainPackage,
        frames: dict[str, pd.DataFrame],
        query: LocalQuery,
        reachable: dict[str, RegisteredJoin | None],
    ) -> None:
        if query.intent == "trend":
            self._add_time_dimension(question, pkg, frames, query)
            return
        if query.intent == "aggregation":
            return
        for (table, column), values in query.filters.items():
            if len(values) > 1:
                self._add_dim(query, Dimension(table, column, col(column)))
        base_entity = pkg.entity_for_dataset(query.base_table)
        base_names = {query.base_table.lower(), query.base_table.lower().rstrip("s")}
        if base_entity:
            base_names.add(base_entity.logical_entity.replace("_", " ").lower())
        q = question.lower()
        for table in reachable:
            entity = pkg.entity_for_dataset(table)
            roles = {c.name: c.role for c in entity.columns} if entity else {}
            for column in map(str, frames[table].columns):
                if _is_measure(frames[table][column], column) or roles.get(column) == "timestamp":
                    continue
                if table == query.base_table and column in query.columns_used:
                    continue
                spoken = _spoken(column)
                trimmed = re.sub(r"\s+(name|id|c|code)$", "", spoken)
                if (
                    trimmed != spoken
                    and trimmed in base_names
                    and not re.search(rf"\b(by|per|each|every)\s+{re.escape(trimmed)}", q)
                    and not _mentions(question, spoken)
                ):
                    continue
                if _mentions(question, spoken) or (trimmed != spoken and _mentions(question, trimmed)):
                    self._add_candidate(query, reachable, table, column)
            if entity and table != query.base_table and _mentions(question, entity.logical_entity.replace("_", " ")):
                label = next(
                    (str(c) for c in frames[table].columns if "name" in str(c).lower()), entity.primary_keys[0]
                )
                self._add_candidate(query, reachable, table, label)

    def _add_candidate(
        self, query: LocalQuery, reachable: dict[str, RegisteredJoin | None], table: str, column: str
    ) -> None:
        if any(d.alias == column for d in query.dims):
            return
        single = query.filters.get((table, column))
        if single and len(single) == 1:
            return
        self._add_dim(query, Dimension(table, column, col(column)))
        self._use_table(query, reachable, table)

    def _add_time_dimension(
        self, question: str, pkg: DomainPackage, frames: dict[str, pd.DataFrame], query: LocalQuery
    ) -> None:
        entity = pkg.entity_for_dataset(query.base_table)
        frame = frames[query.base_table]
        q = question.lower()
        period_columns = [
            str(c)
            for c in frame.columns
            if any(word in q and word in str(c).lower() for word in ("quarter", "month", "week", "year", "period"))
        ]
        if period_columns:
            self._add_dim(query, Dimension(query.base_table, "period", col(period_columns[0])))
            return
        timestamps = (
            [c.name for c in entity.columns if c.role == "timestamp" and c.name in frame.columns] if entity else []
        )
        if not timestamps:
            timestamps = [str(c) for c in frame.columns if re.search(r"(date|_at$|time)", str(c).lower())]
        if not timestamps:
            query.intent = "aggregation"
            query.rationale.append("no time column for a trend")
            return
        column = next((c for c in query.columns_used if c in timestamps), timestamps[0])
        template = "strftime('%Y-%m', {c})"
        for word, fmt in _TIME_FORMATS:
            if word in q:
                template = fmt
                break
        self._add_dim(query, Dimension(query.base_table, "period", template.format(c=col(column))))

    @staticmethod
    def _add_dim(query: LocalQuery, dim: Dimension) -> None:
        if not any(d.alias == dim.alias for d in query.dims):
            query.dims.append(dim)

    @staticmethod
    def _use_table(query: LocalQuery, reachable: dict[str, RegisteredJoin | None], table: str) -> None:
        join = reachable.get(table)
        if join is not None and all(t != table for _, t in query.joins):
            query.joins.append((join, table))

    @staticmethod
    def _finish_order(question: str, query: LocalQuery) -> None:
        q = question.lower()
        if not query.dims:
            return
        if query.intent == "trend":
            query.order = "period ASC"
            return
        query.order = f"{quote_ident(query.value_alias)} {'ASC' if _ASCENDING.search(q) else 'DESC'}"
        if query.intent == "ranking":
            query.having_not_null = True
            match = _TOP_N.search(q)
            if match:
                query.limit = int(match.group(1) or match.group(2))
            elif _SINGULAR_WHICH.search(q):
                query.limit = 1
            else:
                query.limit = 5

    # ----- rendering --------------------------------------------------------

    @staticmethod
    def render_sql(query: LocalQuery, pkg: DomainPackage) -> str:
        aliased = bool(query.joins)
        aliases = {table: f"t{index}" for index, table in enumerate(query.tables)}

        def render(expression: str, table: str) -> str:
            prefix = f"{aliases[table]}." if aliased else ""
            return _COL.sub(lambda m: prefix + quote_ident(m.group(1)), expression)

        select = [f"{render(d.expression, d.table)} AS {quote_ident(d.alias)}" for d in query.dims]
        value = render(query.value_expr, query.base_table)
        select.append(f"{value} AS {quote_ident(query.value_alias)}")
        sql = "SELECT " + ", ".join(select) + f" FROM {quote_ident(query.base_table)}"
        if aliased:
            sql += " AS t0"
            base_entity = pkg.entity_for_dataset(query.base_table)
            for join, table in query.joins:
                other_entity = pkg.entity_for_dataset(table)
                by_entity = {
                    base_entity.logical_entity if base_entity else query.base_table: query.base_table,
                    other_entity.logical_entity if other_entity else table: table,
                }
                conditions = [
                    f"{aliases[by_entity[key.left_entity]]}.{quote_ident(key.left_column)} = "
                    f"{aliases[by_entity[key.right_entity]]}.{quote_ident(key.right_column)}"
                    for key in join.keys
                    if key.left_entity in by_entity and key.right_entity in by_entity
                ]
                kind = (
                    join.join_type.upper() if base_entity and join.left_entity == base_entity.logical_entity else "LEFT"
                )
                sql += f" {kind} JOIN {quote_ident(table)} AS {aliases[table]} ON " + " AND ".join(conditions)
        where = []
        for (table, column), values in query.filters.items():
            target = render(col(column), table)
            if len(values) == 1:
                where.append(f"{target} = {sql_literal(values[0])}")
            else:
                where.append(f"{target} IN ({', '.join(sql_literal(v) for v in values)})")
        if where:
            sql += " WHERE " + " AND ".join(where)
        if query.dims:
            sql += " GROUP BY " + ", ".join(render(d.expression, d.table) for d in query.dims)
        if query.having_not_null:
            sql += f" HAVING {value} IS NOT NULL"
        if query.order:
            sql += f" ORDER BY {query.order}"
        if query.limit:
            sql += f" LIMIT {query.limit}"
        return sql

    @staticmethod
    def _plan_payload(pkg: DomainPackage, query: LocalQuery) -> dict[str, Any]:
        entities = []
        for table in query.tables:
            entity = pkg.entity_for_dataset(table)
            entities.append(entity.logical_entity if entity else table)
        filters = {column: values for (_, column), values in query.filters.items()}
        described = str(query.metric.get("name") or "value")
        if filters:
            described += " where " + "; ".join(f"{c} in {', '.join(v)}" for c, v in filters.items())
        if query.dims:
            described += " by " + ", ".join(d.alias for d in query.dims)
        return {
            "intent": query.intent,
            "interpreted_question": described,
            "entities": entities,
            "metrics": [query.metric],
            "dimensions": [d.alias for d in query.dims],
            "filters": filters,
            "calculations": [
                {
                    "name": query.value_alias,
                    "formula": _COL.sub(lambda m: quote_ident(m.group(1)), query.value_expr),
                    "rationale": "; ".join(query.rationale),
                }
            ],
            "new_terms": [],
            "confidence": query.confidence,
            "clarification_question": query.clarification,
        }
