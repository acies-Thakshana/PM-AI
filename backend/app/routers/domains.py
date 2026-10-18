"""Read access to domains, plus batch runs and evaluation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.config import BATCH_MAX_QUESTIONS
from app.routers.deps import ContextDep, CurrentUser, SettingsDep, UserDomain, may_access
from app.routers.files import read_limited, records
from app.schemas import (
    BatchResponse,
    CheckResult,
    ColumnInfo,
    DomainDetail,
    DomainSummary,
    EvaluateResponse,
    TableInfo,
)
from app.services.ask.batch import run_batch
from app.services.ask.checks import check_domain
from app.services.ask.domain_view import resolve_domain
from app.services.data.tabular import read_table_bytes
from app.services.evaluation.scoring import score_results

router = APIRouter(prefix="/api/domains", tags=["domains"])

QuestionFile = Annotated[UploadFile, File(description="CSV or Excel file with a 'question' column.")]


@router.get("", response_model=list[DomainSummary])
def list_domains(user: CurrentUser, ctx: ContextDep, settings: SettingsDep) -> list[DomainSummary]:
    """The domains the caller may use: those with uploaded or bundled data, and those with a baseline package."""
    baseline = set(ctx.semantic.list_domains())
    names = sorted(baseline | set(ctx.source.list_domains()))
    return [
        DomainSummary(id=name, tables=ctx.source.list_tables(name), has_baseline_package=name in baseline)
        for name in names
        if may_access(user, name, settings)
    ]


@router.get("/{domain}", response_model=DomainDetail)
def domain_detail(domain: UserDomain, ctx: ContextDep) -> DomainDetail:
    view = resolve_domain(ctx, domain)
    pkg = view.pkg
    restricted = {name.lower() for name in pkg.restricted_columns()}
    tables = []
    for name, frame in view.raw.items():
        entity = pkg.entity_for_dataset(name)
        specs = {c.name.lower(): c for c in entity.columns} if entity else {}
        tables.append(
            TableInfo(
                name=name,
                rows=int(len(frame)),
                columns=[
                    ColumnInfo(
                        name=str(column),
                        dtype=str(frame[column].dtype),
                        role=specs[str(column).lower()].role if str(column).lower() in specs else "attribute",
                        restricted=str(column).lower() in restricted,
                    )
                    for column in frame.columns
                ],
            )
        )
    return DomainDetail(
        id=domain,
        has_baseline_package=ctx.semantic.exists(domain),
        tables=tables,
        counts={
            "entities": len(pkg.entities),
            "metrics": len(pkg.metrics),
            "joins": len(pkg.joins),
            "glossary_terms": len(pkg.glossary),
            "rules": len(pkg.rules),
            "validated_queries": len(pkg.validated_sql),
        },
        starter_questions=ctx.followups.starter_questions(pkg),
    )


@router.get("/{domain}/catalog")
def domain_catalog(domain: UserDomain, ctx: ContextDep) -> dict:
    """Table and column metadata saved by the last onboarding run (restricted columns carry no samples)."""
    return ctx.catalogs.load(domain)


@router.get("/{domain}/checks", response_model=list[CheckResult])
def domain_checks(domain: UserDomain, ctx: ContextDep) -> list[CheckResult]:
    return [CheckResult(**check.to_dict()) for check in check_domain(ctx, domain)]


@router.post("/{domain}/batch", response_model=BatchResponse)
def batch(domain: UserDomain, file: QuestionFile, ctx: ContextDep, settings: SettingsDep) -> BatchResponse:
    """Answer every question in an uploaded table. Capped at ``BATCH_MAX_QUESTIONS`` per request."""
    questions = read_table_bytes(file.filename or "questions.csv", read_limited(file, settings.upload_max_bytes))
    results = run_batch(
        questions, context=ctx, domain=domain, persist=settings.persist_episodes, max_questions=BATCH_MAX_QUESTIONS
    )
    return BatchResponse(questions=len(results), rows=records(results))


@router.post("/{domain}/evaluate", response_model=EvaluateResponse)
def evaluate(domain: UserDomain, file: QuestionFile, ctx: ContextDep, settings: SettingsDep) -> EvaluateResponse:
    """Run questions that carry an ``Expected_SQL_Query`` column and score the answers against it."""
    questions = read_table_bytes(file.filename or "questions.csv", read_limited(file, settings.upload_max_bytes))
    results = run_batch(questions, context=ctx, domain=domain, persist=False, max_questions=BATCH_MAX_QUESTIONS)
    executor = ctx.new_executor()
    try:
        detail, summary = score_results(results, resolve_domain(ctx, domain).tables, executor)
    finally:
        executor.close()
    return EvaluateResponse(summary=summary, detail=records(detail))
