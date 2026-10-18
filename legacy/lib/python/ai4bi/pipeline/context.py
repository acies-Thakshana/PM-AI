"""Wire settings, stores, adapters, and services into one context object.

Platforms swap pieces through keyword arguments: a Dataiku recipe passes its
own data source, LLM client, and graph store; local runs use the defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai4bi.answers.generator import AnswerGenerator
from ai4bi.config.settings import Settings, load_settings
from ai4bi.data.local_files import LocalFileSource
from ai4bi.data.source import DatasetSource
from ai4bi.followups.generator import FollowupGenerator
from ai4bi.guardrails.sql_policy import SqlPolicy
from ai4bi.knowledge.history import HistoryStore
from ai4bi.knowledge.store import GraphStore, JsonGraphStore
from ai4bi.llm.client import LlmClient, get_llm_client
from ai4bi.logging.setup import setup_logging
from ai4bi.metadata.store import MetadataStore
from ai4bi.semantic.store import SemanticStore
from ai4bi.sql.executor import SqliteFrameExecutor, SqlExecutor
from ai4bi.sql.generator import SqlGenerator
from ai4bi.sql.validator import SqlValidator
from ai4bi.visualization.generator import VisualizationBuilder


@dataclass
class AppContext:
    settings: Settings
    semantic: SemanticStore
    graphs: GraphStore
    data: DatasetSource
    llm: LlmClient
    executor: SqlExecutor
    validator: SqlValidator
    generator: SqlGenerator
    answers: AnswerGenerator
    followups: FollowupGenerator
    visuals: VisualizationBuilder
    metadata: MetadataStore
    history: HistoryStore | None


def build_context(
    settings: Settings | None = None,
    *,
    data_source: DatasetSource | None = None,
    llm: LlmClient | None = None,
    graph_store: GraphStore | None = None,
    executor: SqlExecutor | None = None,
    history: bool = True,
    configure_logging: bool = True,
) -> AppContext:
    settings = settings or load_settings()
    if configure_logging:
        setup_logging(settings.logging_config_path, project_root=settings.project_root, level=settings.log_level)
    policy = SqlPolicy.from_settings(settings)
    semantic = SemanticStore(settings.semantic_root)
    client = llm or get_llm_client(settings)
    return AppContext(
        settings=settings,
        semantic=semantic,
        graphs=graph_store or JsonGraphStore(settings.knowledge_graph_root),
        data=data_source or LocalFileSource(settings.samples_root),
        llm=client,
        executor=executor or SqliteFrameExecutor(policy),
        validator=SqlValidator(policy),
        generator=SqlGenerator(client, semantic),
        answers=AnswerGenerator(client),
        followups=FollowupGenerator(settings.followup_templates, settings.followup_max),
        visuals=VisualizationBuilder(settings.visual_templates_path),
        metadata=MetadataStore(settings.metadata_root),
        history=HistoryStore(settings.history_root) if history else None,
    )
