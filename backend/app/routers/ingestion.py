"""Data Upload page endpoints: accepts the 4 source files (real upload or a
one-click sample load) and returns the triage summary immediately."""
from fastapi import APIRouter, HTTPException, UploadFile

from app.config import (
    BUSINESS_RULES_SAMPLE_PATH,
    COLDSTREAM_SAMPLE_PATH,
    CUSTOMER_PROFILE_SAMPLE_PATH,
    SENSIWATCH_SAMPLE_PATH,
)
from app.services import ingestion

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])


@router.post("/sensiwatch")
async def upload_sensiwatch(file: UploadFile):
    try:
        return ingestion.ingest_sensiwatch(await file.read())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not parse SensiWatch export: {exc}") from exc


@router.post("/sensiwatch/load-sample")
def load_sample_sensiwatch():
    return ingestion.ingest_sensiwatch(SENSIWATCH_SAMPLE_PATH.read_bytes())


@router.post("/coldstream")
async def upload_coldstream(file: UploadFile):
    try:
        return ingestion.ingest_coldstream(await file.read())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not parse ColdStream export: {exc}") from exc


@router.post("/coldstream/load-sample")
def load_sample_coldstream():
    return ingestion.ingest_coldstream(COLDSTREAM_SAMPLE_PATH.read_bytes())


@router.post("/customer-profile")
async def upload_customer_profile(file: UploadFile):
    try:
        text = (await file.read()).decode("utf-8")
        return ingestion.ingest_customer_profile(text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not read customer profile: {exc}") from exc


@router.post("/customer-profile/load-sample")
def load_sample_customer_profile():
    text = CUSTOMER_PROFILE_SAMPLE_PATH.read_text(encoding="utf-8")
    return ingestion.ingest_customer_profile(text)


@router.post("/business-rules")
async def upload_business_rules(file: UploadFile):
    try:
        return ingestion.ingest_business_rules(await file.read())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not parse business rules JSON: {exc}") from exc


@router.post("/business-rules/load-sample")
def load_sample_business_rules():
    return ingestion.ingest_business_rules(BUSINESS_RULES_SAMPLE_PATH.read_bytes())


@router.get("/status")
def ingest_status():
    return ingestion.get_status()
