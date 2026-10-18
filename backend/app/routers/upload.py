"""Bringing datasets into a domain. Stewards only: uploads change what every question runs on."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.routers.deps import ContextDep, SettingsDep, StewardDomain
from app.routers.files import read_limited
from app.schemas import UploadedDataset, UploadRequest, UploadTargetResponse

router = APIRouter(prefix="/api/domains/{domain}", tags=["upload"])


@router.get("/datasets", response_model=list[str])
def list_datasets(domain: StewardDomain, ctx: ContextDep) -> list[str]:
    return ctx.uploads.tables(domain)


@router.post("/uploads", response_model=UploadTargetResponse)
def create_upload(domain: StewardDomain, body: UploadRequest, ctx: ContextDep) -> UploadTargetResponse:
    """Where to send one file. On AWS this is a short-lived S3 form (the file bypasses the API);
    locally it says to use ``POST .../datasets``. Either way, finish with ``POST .../uploads/complete``
    when the file went straight to storage."""
    target = ctx.uploads.create(domain, body.filename)
    return UploadTargetResponse(
        mode=target.mode,
        table=target.table,
        filename=target.filename,
        url=target.url,
        fields=target.fields,
        max_bytes=target.max_bytes,
    )


@router.post("/uploads/complete", response_model=UploadedDataset)
def complete_upload(domain: StewardDomain, body: UploadRequest, ctx: ContextDep) -> UploadedDataset:
    """Check a file that was sent straight to storage. An unreadable file is removed."""
    return UploadedDataset(**ctx.uploads.complete(domain, body.filename))


@router.post("/datasets", response_model=UploadedDataset, status_code=201)
def upload_dataset(
    domain: StewardDomain,
    file: Annotated[UploadFile, File(description="CSV, TSV, Excel, Parquet or JSON file.")],
    ctx: ContextDep,
    settings: SettingsDep,
) -> UploadedDataset:
    """Send a file through the API. Fine for local use and small files."""
    data = read_limited(file, settings.upload_max_bytes)
    return UploadedDataset(**ctx.uploads.save_direct(domain, file.filename or "", data))
