"""Per-session cache of Feature Agent results that already passed
validation once, keyed by entry id. It lives INSIDE the feature's own record in the session's
`FEATURES` document (key `cache`), next to the feature's definition and `source`, so one read
gives the definition, status and final code (see services/common/entry_store.py).

Every recompute (e.g. accepting one more AI suggestion re-runs the WHOLE
approved set, not just the new entry -- see feature_engineering.apply_
features) would otherwise call Think/Code/Validate again for every entry,
including ones that already succeeded. Code generation has some sampling
variance, so a feature that validated fine once can occasionally come out
different -- and fail -- on a later recompute for no reason tied to
anything the PM did. Caching the exact winning plan+code the first time an
entry validates makes recomputation idempotent: a proven-correct entry
just replays its own code from then on, instead of being regenerated (and
re-risked) every time.

The cache is invalidated automatically if the entry's own calculation
basis changes (a re-uploaded KPI Profile with a different formula for the
same id, say) -- see `get`.
"""
from datetime import datetime, timezone

from app.services.common.entry_store import FEATURES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get(session_id: str, entry: dict) -> dict | None:
    """Returns the cached {"plan_text", "generated_code"} for this entry if
    one exists and the entry's calculation basis (its formula if it has
    one, else its calculation_intent) and output column haven't changed
    since it was cached. None otherwise, so the caller computes fresh."""
    cached = FEATURES.get_cache(session_id, entry["id"])
    if not cached:
        return None
    basis = entry.get("formula") or entry["calculation_intent"]
    if cached.get("basis") != basis or cached.get("output_column") != entry["output_column"]:
        return None
    return cached


def set(session_id: str, entry: dict, plan_text: str | None, generated_code: str) -> None:
    FEATURES.set_cache(session_id, entry, {
        "basis": entry.get("formula") or entry["calculation_intent"],
        "output_column": entry["output_column"],
        "plan_text": plan_text,
        "generated_code": generated_code,
        "cached_at": _now(),
    })


def invalidate(session_id: str, entry_id: str) -> None:
    FEATURES.drop_cache(session_id, entry_id)
