"""Pydantic contracts for a domain package. Every field is loaded from storage files."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Steward(BaseModel):
    role: str
    team: str
    contact: str = ""


ColumnRole = Literal["key", "foreign_key", "measure", "attribute", "timestamp", "flag", "degenerate"]


class ColumnSpec(BaseModel):
    name: str
    data_type: str
    role: ColumnRole
    description: str = ""
    pii_tag: Literal["none", "restricted", "masked"] = "none"
    sensitive: bool = False


class EntityRegistration(BaseModel):
    """Configuration-only mapping of a logical entity onto a physical dataset."""

    logical_entity: str
    source_system: Literal["salesforce", "sap", "servicenow", "snowflake", "other"]
    source_object: str
    physical_dataset: str
    data_product_id: str
    grain: str
    primary_keys: list[str] = Field(min_length=1)
    entity_kind: Literal["master", "transactional", "bridge"]
    columns: list[ColumnSpec] = Field(min_length=1)
    is_custom_object: bool = False
    notes: str = ""


class JoinKey(BaseModel):
    left_entity: str
    left_column: str
    right_entity: str
    right_column: str


class RegisteredJoin(BaseModel):
    id: str
    left_entity: str
    right_entity: str
    join_type: Literal["inner", "left", "right"]
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    keys: list[JoinKey] = Field(min_length=1)
    condition: str
    grain_note: str = ""
    allowed_for_nlq: bool = True
    approved_by: str = ""
    inferred: bool = False


class DictionaryEntity(BaseModel):
    logical_entity: str
    business_definition: str
    hierarchy: list[str] = Field(default_factory=list)


class DictionaryKpi(BaseModel):
    family: str
    name: str
    business_definition: str
    formula_hint: str
    grain: str
    owner: str
    synonyms: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=lambda: ["global"])


class DataDictionary(BaseModel):
    domain: str
    entities: list[DictionaryEntity] = Field(default_factory=list)
    kpis: list[DictionaryKpi] = Field(min_length=1)
    hierarchies: list[list[str]] = Field(default_factory=list)
    synonyms: list[dict[str, str]] = Field(default_factory=list)


class Contract(BaseModel):
    domain: str
    source_system: str
    historical_from: str
    historical_to: str
    extracts: list[str] = Field(min_length=1)
    master_entities: list[str] = Field(min_length=1)
    transactional_entities: list[str] = Field(min_length=1)
    owner: Steward
    notes: str = ""

    @field_validator("extracts")
    @classmethod
    def extracts_not_empty(cls, value: list[str]) -> list[str]:
        if not all(v.strip() for v in value):
            raise ValueError("extract names must be non-empty")
        return value


class GlossaryTerm(BaseModel):
    term: str
    kind: Literal["synonym", "acronym", "domain_term", "business_phrase"]
    maps_to_kind: Literal["metric_family", "metric", "entity", "dimension", "filter_value"]
    maps_to_id: str
    locale: str = "en"
    canonical_value: str = ""


class HarvestedMetric(BaseModel):
    name: str
    source_dashboard: str
    calculation: str
    business_questions: list[str] = Field(default_factory=list)
    drill_path: list[str] = Field(default_factory=list)


class BiHarvest(BaseModel):
    domain: str
    purpose: Literal["harvest_semantic_assets"] = "harvest_semantic_assets"
    metrics: list[HarvestedMetric] = Field(min_length=1)


class MetricVersion(BaseModel):
    """One KPI definition. Scope variants are siblings, not prompt forks."""

    id: str
    family: str
    name: str
    scope: str
    default_for_family: bool = False
    version: str
    status: Literal["proposed", "certified", "deprecated"] = "proposed"
    data_product_id: str
    grain: str
    aggregation: Literal["sum", "avg", "count", "count_distinct", "min", "max", "formula"]
    sql_expression: str
    filter_sql: str | None = None
    compute: dict = Field(default_factory=dict)
    synonyms: list[str] = Field(default_factory=list)
    owner: str = ""
    unit: str = ""


class BusinessUnitContext(BaseModel):
    code: str
    name: str
    description: str = ""
    currency: str = ""
    fiscal_year_start_month: int = 1
    default_filters: dict[str, str] = Field(default_factory=dict)
    scope_aliases: dict[str, str] = Field(default_factory=dict)
    owners: list[str] = Field(default_factory=list)
    notes: str = ""


class BusinessRule(BaseModel):
    id: str
    description: str
    rule_type: Literal["definition", "filter", "display", "restriction", "calculation"]
    applies_to: list[str] = Field(default_factory=list)
    sql_hint: str = ""
    keywords: list[str] = Field(default_factory=list)


class QueryExample(BaseModel):
    question: str
    intent: str = ""
    metric_ids: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    notes: str = ""


class ValidatedSql(BaseModel):
    id: str
    question: str
    sql: str
    datasets: list[str] = Field(default_factory=list)
    validated_by: str = ""
    validated_at: str = ""
    expected_result: str = ""


class DomainPackage(BaseModel):
    contract: Contract
    dictionary: DataDictionary
    entities: list[EntityRegistration] = Field(min_length=1)
    joins: list[RegisteredJoin] = Field(default_factory=list)
    glossary: list[GlossaryTerm] = Field(default_factory=list)
    harvest: BiHarvest | None = None
    metrics: list[MetricVersion] = Field(default_factory=list)
    pii_tags: list[dict] = Field(default_factory=list)
    business_unit: BusinessUnitContext | None = None
    rules: list[BusinessRule] = Field(default_factory=list)
    query_examples: list[QueryExample] = Field(default_factory=list)
    validated_sql: list[ValidatedSql] = Field(default_factory=list)
    visuals: list[dict] = Field(default_factory=list)
    drills: dict = Field(default_factory=dict)
    explainability: dict = Field(default_factory=dict)
    inferred: bool = False

    @property
    def domain(self) -> str:
        return self.contract.domain

    def entity_for_dataset(self, dataset: str) -> EntityRegistration | None:
        key = dataset.lower()
        for entity in self.entities:
            if entity.physical_dataset.lower() == key or entity.logical_entity.lower() == key:
                return entity
        return None

    def entity_for_product(self, data_product_id: str) -> EntityRegistration | None:
        return next((e for e in self.entities if e.data_product_id == data_product_id), None)

    def restricted_columns(self) -> set[str]:
        names: set[str] = set()
        for entity in self.entities:
            for col in entity.columns:
                if col.pii_tag == "restricted" or col.sensitive:
                    names.add(col.name)
        for tag in self.pii_tags:
            if tag.get("action") in {"deny", "restricted"}:
                names.add(str(tag.get("column") or ""))
        return {n for n in names if n}
