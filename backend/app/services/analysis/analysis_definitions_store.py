"""Holds the analysis-definitions JSON uploaded to the "Analysis Profile" slot, stored per user
(see services/common/profile_store.py). There is no bundled backend default -- if
nothing has been uploaded, `store.definitions` is None and the Analysis
page simply shows zero `predefined` entries (never a hard error). Same
interface as feature_definitions_store.py.

Deliberately looser than the old pivot-table JSON schema: no group_by/
metrics/agg vocabulary, since the Analysis Agent now derives the
aggregation itself from a plain-English `calculation_intent`.
"""
from app.services.common import profile_store, request_context


class AnalysisDefinitionsStore:
    def _profile(self) -> dict | None:
        return profile_store.load(request_context.user_id(), profile_store.ANALYSIS)

    @property
    def filename(self) -> str | None:
        return (self._profile() or {}).get("filename")

    @property
    def definitions(self) -> list[dict] | None:
        return (self._profile() or {}).get("definitions")

    def set(self, filename: str, definitions: list[dict]) -> None:
        profile_store.save(request_context.user_id(), profile_store.ANALYSIS, filename, definitions)

    def clear(self) -> None:
        profile_store.clear(request_context.user_id(), profile_store.ANALYSIS)


store = AnalysisDefinitionsStore()


def validate(payload: dict) -> list[dict]:
    """Raises ValueError with a clear message on anything malformed;
    returns the validated list of analysis specs."""
    if not isinstance(payload, dict) or "analyses" not in payload:
        raise ValueError("Expected a JSON object with a top-level 'analyses' array.")
    analyses = payload["analyses"]
    if not isinstance(analyses, list) or not analyses:
        raise ValueError("'analyses' must be a non-empty array.")

    required = {"id", "name", "description", "calculation_intent"}

    for i, spec in enumerate(analyses):
        if not isinstance(spec, dict):
            raise ValueError(f"Analysis #{i + 1} is not an object.")
        missing = required - set(spec.keys())
        if missing:
            raise ValueError(f"Analysis #{i + 1} ('{spec.get('id', '?')}') is missing: {', '.join(sorted(missing))}.")

    return analyses
