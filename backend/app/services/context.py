"""Wire settings, stores, adapters and services into one object.

``build_context`` chooses the implementations: local files when AWS storage is not configured,
S3 and DynamoDB when it is. Tests and notebooks replace single pieces through keyword arguments.
Everything on the context is safe to share between requests except the SQL executor, which holds
a SQLite connection: get a fresh one per request with ``new_executor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.services.common.llm import LlmClient, get_llm_client
from app.services.data.cache import DataCache
from app.services.data.local_files import LocalFileSource
from app.services.data.s3_source import S3Source
from app.services.data.source import ChainedSource, DatasetSource
from app.services.data.uploads import DatasetStorage, LocalDatasetStorage, S3DatasetStorage, UploadService
from app.services.guardrails.sql_policy import SqlPolicy
from app.services.knowledge.graph_store import DynamoGraphStore, GraphStore, LocalGraphStore
from app.services.knowledge.history_store import DynamoHistoryStore, HistoryStore, LocalHistoryStore
from app.services.onboarding.catalog_store import CatalogStore, LocalCatalogStore, S3CatalogStore
from app.services.onboarding.job_store import DynamoJobStore, JobStore, LocalJobStore
from app.services.onboarding.jobs import JobRunner
from app.services.output.answers import AnswerGenerator
from app.services.output.followups import FollowupGenerator
from app.services.output.visualization import VisualizationBuilder
from app.services.semantic.registry_store import DynamoRegistryStore, LocalRegistryStore, RegistryStore
from app.services.semantic.store import SemanticStore
from app.services.sql.executor import SqliteFrameExecutor
from app.services.sql.generator import SqlGenerator
from app.services.sql.validator import SqlValidator


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    semantic: SemanticStore
    registry: RegistryStore
    graphs: GraphStore
    history: HistoryStore
    catalogs: CatalogStore
    source: DatasetSource
    cache: DataCache
    uploads: UploadService
    runner: JobRunner
    llm: LlmClient
    policy: SqlPolicy
    validator: SqlValidator
    generator: SqlGenerator
    answers: AnswerGenerator
    followups: FollowupGenerator
    visuals: VisualizationBuilder

    def new_executor(self) -> SqliteFrameExecutor:
        """A SQL executor for one request. Close it when the request is done."""
        return SqliteFrameExecutor(self.policy)


@dataclass(frozen=True)
class _Storage:
    registry: RegistryStore
    graphs: GraphStore
    history: HistoryStore
    catalogs: CatalogStore
    jobs: JobStore
    source: DatasetSource
    datasets: DatasetStorage


def _local_storage(settings: Settings) -> _Storage:
    state = settings.local_state_root
    return _Storage(
        registry=LocalRegistryStore(state / "registry"),
        graphs=LocalGraphStore(state / "knowledge_graph", settings.graph_max_episodes),
        history=LocalHistoryStore(state / "history"),
        catalogs=LocalCatalogStore(state / "metadata"),
        jobs=LocalJobStore(state / "jobs"),
        source=ChainedSource([LocalFileSource(settings.datasets_root), LocalFileSource(settings.samples_root)]),
        datasets=LocalDatasetStorage(settings.datasets_root),
    )


def _aws_storage(settings: Settings) -> _Storage:
    return _Storage(
        registry=DynamoRegistryStore(settings.ddb_registry),
        graphs=DynamoGraphStore(settings.ddb_kg, settings.graph_max_episodes, settings.record_ttl_days),
        history=DynamoHistoryStore(settings.ddb_history, settings.record_ttl_days),
        catalogs=S3CatalogStore(settings.s3_bucket),
        jobs=DynamoJobStore(settings.ddb_jobs, settings.record_ttl_days),
        source=ChainedSource([S3Source(settings.s3_bucket), LocalFileSource(settings.samples_root)]),
        datasets=S3DatasetStorage(
            settings.s3_bucket, expiry_seconds=settings.presign_expiry_seconds, max_bytes=settings.upload_max_bytes
        ),
    )


def build_context(
    settings: Settings | None = None,
    *,
    source: DatasetSource | None = None,
    llm: LlmClient | None = None,
    registry: RegistryStore | None = None,
    graphs: GraphStore | None = None,
) -> AppContext:
    settings = settings or get_settings()
    storage = _aws_storage(settings) if settings.use_aws_storage else _local_storage(settings)
    source = source or storage.source
    client = llm or get_llm_client(settings)
    semantic = SemanticStore(settings.semantic_root)
    policy = SqlPolicy.from_settings(settings)
    cache = DataCache(source, ttl_seconds=settings.data_cache_seconds, max_entries=settings.data_cache_max_entries)
    return AppContext(
        settings=settings,
        semantic=semantic,
        registry=registry or storage.registry,
        graphs=graphs or storage.graphs,
        history=storage.history,
        catalogs=storage.catalogs,
        source=source,
        cache=cache,
        uploads=UploadService(storage.datasets, source, cache, max_bytes=settings.upload_max_bytes),
        runner=JobRunner(storage.jobs, workers=settings.job_workers),
        llm=client,
        policy=policy,
        validator=SqlValidator(policy),
        generator=SqlGenerator(client, semantic),
        answers=AnswerGenerator(client),
        followups=FollowupGenerator(list(settings.followup_templates), settings.followup_max),
        visuals=VisualizationBuilder(settings.visual_templates_path),
    )


@lru_cache(maxsize=1)
def get_context() -> AppContext:
    """The process-wide context, built on first use. ``get_context.cache_clear()`` resets it in tests."""
    return build_context()
