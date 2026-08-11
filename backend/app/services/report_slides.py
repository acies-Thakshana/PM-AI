"""Report-time slide list: an explicit, user-editable set of slides for the
downloaded report, decoupled from the Analysis page's pivot state. Each
slide independently recomputes its own pivot at report-build time using its
own filters (see report_generator.build_report), so nothing here ever
affects that pivot's computed rows/table.

Two-level hierarchy only: a top-level slide per pivot (one id per pivot,
deterministic so re-syncing never duplicates it), and any number of child
slides (created by duplicating a slide with "+") that explore the same pivot
with a different filter -- a child's `parent_id` always points at the
top-level slide, never at another child.
"""
from app.schemas import PivotResult, ReportSlide


def slide_id_for_pivot(pivot_id: str) -> str:
    return f"slide_{pivot_id}"


def sync_slides(
    pivots: list[PivotResult], existing: list[ReportSlide], pivot_filter_state: dict[str, list[dict]]
) -> list[ReportSlide]:
    """Keeps one top-level slide per CURRENT pivot -- creating any that are
    missing, seeded from that pivot's current Analysis-page filters -- and
    drops any slide (top-level or child) whose pivot no longer exists.
    Preserves already-existing slides' own titles/filters and children's
    relative order untouched."""
    by_id = {s.id: s for s in existing}
    children_by_pivot: dict[str, list[ReportSlide]] = {}
    for s in existing:
        if s.parent_id is not None:
            children_by_pivot.setdefault(s.pivot_id, []).append(s)

    synced: list[ReportSlide] = []
    for pivot in pivots:
        top_id = slide_id_for_pivot(pivot.id)
        top = by_id.get(top_id) or ReportSlide(
            id=top_id, title=pivot.name, pivot_id=pivot.id, filters=pivot_filter_state.get(pivot.id, [])
        )
        synced.append(top)
        synced.extend(children_by_pivot.get(pivot.id, []))
    return synced
