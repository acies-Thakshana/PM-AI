"""
Deterministic dataset-wide summary. Rolls up the already-computed feature
stats/distributions and pivot results into a short list of headline
highlights -- no LLM involved, same rule as feature_engineering.py and
pivot_engine.py: the numbers a PM puts in a report need to be reliable, not
a plausible-sounding guess. overall_analysis_agent.py turns this list into
prose; it never adds a number that isn't already here.
"""
from app.schemas import FeatureResult, OverallHighlight, PivotResult

MAX_FEATURE_HIGHLIGHTS = 6


def _feature_highlights(features: list[FeatureResult]) -> list[OverallHighlight]:
    highlights: list[OverallHighlight] = []
    for f in features:
        if f.stats:
            mean = f.stats.get("mean")
            if mean is not None:
                highlights.append(OverallHighlight(label=f"Avg {f.name}", value=str(mean)))
        elif f.distribution:
            top_value, top_count = next(iter(f.distribution.items()), (None, None))
            if top_value is None:
                continue
            total = f.non_null_count or 1
            share = (top_count / total) * 100
            highlights.append(OverallHighlight(
                label=f"Most common {f.name}", value=f"{top_value} ({top_count} rows, {share:.0f}%)"
            ))
    return highlights[:MAX_FEATURE_HIGHLIGHTS]


def _pivot_highlights(pivots: list[PivotResult]) -> list[OverallHighlight]:
    highlights: list[OverallHighlight] = []
    for p in pivots:
        if not p.rows or not p.metric_labels:
            continue
        metric = p.metric_labels[0]
        scored = [r for r in p.rows if isinstance(r.get(metric), (int, float))]
        if not scored:
            continue

        best = max(scored, key=lambda r: r[metric])
        best_label = " / ".join(str(best.get(c)) for c in p.group_by)
        highlights.append(OverallHighlight(
            label=f"Highest {metric} ({p.name})", value=f"{best_label}: {best[metric]}"
        ))

        if len(scored) > 1:
            worst = min(scored, key=lambda r: r[metric])
            if worst is not best:
                worst_label = " / ".join(str(worst.get(c)) for c in p.group_by)
                highlights.append(OverallHighlight(
                    label=f"Lowest {metric} ({p.name})", value=f"{worst_label}: {worst[metric]}"
                ))
    return highlights


def build_highlights(row_count: int, features: list[FeatureResult], pivots: list[PivotResult]) -> list[OverallHighlight]:
    highlights = [OverallHighlight(label="Total Rows Analyzed", value=f"{row_count:,}")]
    highlights += _feature_highlights(features)
    highlights += _pivot_highlights(pivots)
    return highlights
