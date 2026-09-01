import json

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import FeatureDefinitionsSummary, FeatureSuggestionsResponse, SuggestFeaturesRequest
from app.services import feature_definitions_store as defs_store
from app.services import feature_suggester
from app.routers._common import get_session_or_404

router = APIRouter(prefix="/api/features", tags=["features"])


@router.post("/definitions", response_model=FeatureDefinitionsSummary)
async def upload_feature_definitions(file: UploadFile = File(...)) -> FeatureDefinitionsSummary:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}") from exc

    try:
        features = defs_store.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = file.filename or "customer_kpi_profile.json"
    defs_store.store.set(filename, features)

    return FeatureDefinitionsSummary(
        filename=filename,
        feature_count=len(features),
        feature_names=[f["name"] for f in features],
    )


@router.get("/definitions", response_model=FeatureDefinitionsSummary)
def get_feature_definitions() -> FeatureDefinitionsSummary:
    if defs_store.store.definitions is None:
        raise HTTPException(status_code=404, detail="No Customer KPI Profile has been uploaded yet.")
    return FeatureDefinitionsSummary(
        filename=defs_store.store.filename,
        feature_count=len(defs_store.store.definitions),
        feature_names=[f["name"] for f in defs_store.store.definitions],
    )


@router.post("/suggest", response_model=FeatureSuggestionsResponse)
def suggest_features(body: SuggestFeaturesRequest) -> FeatureSuggestionsResponse:
    session = get_session_or_404(body.session_id)
    base_df = session.pre_feature_df if session.pre_feature_df is not None else session.df
    try:
        suggestions = feature_suggester.suggest_features(base_df)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature suggestion agent (Groq) is unavailable: {exc}") from exc
    return FeatureSuggestionsResponse(session_id=body.session_id, suggestions=suggestions)
