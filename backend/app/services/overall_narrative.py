"""Executive-summary paragraph for the Analysis step's overall-analysis
card (see routers/analysis.py's /overall endpoint) -- reused verbatim by the
Report step's summary slide (see report_generator.py), so the AI is only
ever asked to write this once per Analysis run, not again at export time.

Tries an LLM-written narrative first (via Groq -- see groq_client.py),
since synthesizing "what matters most" out of a pile of highlights reads
far more naturally in prose than a fixed template can produce; falls back
to a deterministic templated sentence -- built only from the highlights
already computed by overall_analysis.py -- if Groq isn't configured or the
call fails, so this never blocks the Analysis page from loading.

The AI never computes a number itself and is told not to invent one --
it only narrates highlights already computed. It also never decides WHICH
analyses/pivots exist; that's still 100% the uploaded Analysis Profile plus
whatever the user added manually.
"""
from app.schemas import OverallHighlight
from app.services import groq_client

MAX_NARRATIVE_HIGHLIGHTS = 3

SYSTEM_PROMPT = """You are a program manager writing the executive-summary \
paragraph for a recurring cold-chain shipment report. You've been given a \
list of already-computed headline numbers (rows analyzed, feature averages, \
top categories, and best/worst performers from the pivot tables below). Do \
NOT invent any number, name, or trend that isn't in the list given, and do \
NOT restate every bullet -- synthesize the 2-3 most report-worthy points \
into plain prose. Write exactly 2-4 plain-English sentences, no markdown, \
no bullet lists, no restating these instructions."""


def _highlights_block(highlights: list[OverallHighlight]) -> str:
    return "\n".join(f"- {h.label}: {h.value}" for h in highlights)


def _generate_ai_narrative(row_count: int, highlights: list[OverallHighlight]) -> str:
    user_prompt = f"Rows analyzed: {row_count}\n\n{_highlights_block(highlights)}\n\nWrite the executive summary now."
    return groq_client.chat_text(SYSTEM_PROMPT, user_prompt).strip()


def _generate_deterministic_narrative(row_count: int, highlights: list[OverallHighlight]) -> str:
    # highlights[0] is always "Total Rows Analyzed" (see overall_analysis.build_highlights)
    # -- already covered by the row-count sentence below, so it's skipped here.
    detail_highlights = highlights[1:]

    sentences = [f"This report covers {row_count:,} rows analyzed across the current dataset."]

    if not detail_highlights:
        sentences.append("No feature or analysis-table highlights are available yet.")
        return " ".join(sentences)

    shown = detail_highlights[:MAX_NARRATIVE_HIGHLIGHTS]
    detail = "; ".join(f"{h.label.lower()} is {h.value}" for h in shown)
    sentences.append(f"Notable figures include {detail}.")

    remaining = len(detail_highlights) - len(shown)
    if remaining > 0:
        sentences.append(f"{remaining} additional metric(s) are detailed in the highlights below.")

    return " ".join(sentences)


def generate_narrative(row_count: int, highlights: list[OverallHighlight]) -> str:
    try:
        narrative = _generate_ai_narrative(row_count, highlights)
        if narrative:
            return narrative
    except Exception:
        pass
    return _generate_deterministic_narrative(row_count, highlights)
