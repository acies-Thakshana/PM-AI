"""
Agent 2: Report Composer.

Single responsibility: assemble the final .pptx by calling the deterministic
`pptx_tools` builder functions in the fixed order defined by
`report_template.SLIDE_SEQUENCE`. The LLM chooses *what to say* (narrative
phrasing, which recommendation is highest priority) but never touches PPTX
internals -- every tool call is executed by plain Python in pptx_tools.py.

Numeric slides (KPIs, tables) are handed EXACT pre-formatted values to copy
into the tool call, so a fluent-but-wrong number can't slip into the deck --
the agent's discretion there is limited to headings/labels, not the figures.
"""
import json
from datetime import datetime
from pathlib import Path

from app.agents.groq_client import chat_with_tools
from app.agents.pptx_tools import TOOL_SCHEMAS, PptxBuilder
from app.config import REPORTS_DIR
from app.services import ingestion
from app.services.report_template import PROGRAM_TITLE, SLIDE_SEQUENCE
from app.services.trip_analytics import FLAG_INFO

SYSTEM_PROMPT = f"""You are the report composer for the {PROGRAM_TITLE}. You assemble a \
PowerPoint deck by calling the tools you've been given -- you never write PPTX content \
any other way. You must call tools in EXACTLY this order, one call per entry, no extra \
slides, no skipped slides:

{json.dumps(SLIDE_SEQUENCE, indent=2)}

Rules:
- For add_kpi_slide and add_table_slide: use the EXACT values provided to you in the \
  "EXACT_DATA_FOR_NUMERIC_SLIDES" section of the user message. Do not alter, round \
  differently, or invent any number or row. You may only choose the slide heading text.
- For add_title_slide, add_narrative_slide and add_recommendations_slide: base the \
  content on the "ANALYST_INSIGHTS" section -- you may tighten the prose for a slide \
  (concise, presentation-appropriate) but must preserve every factual claim, trip ID, \
  product, and causal mechanism mentioned there. Do not add generic filler.
- Call the 7 tools in order and then stop.
"""


def _format_kpi_cards(kpis: dict, bloom_risk: list[dict], business_rules: dict | None) -> list[dict]:
    standard = {k["name"]: k for k in (business_rules or {}).get("standard_kpis", [])}
    customer_kpis = {k["name"]: k for k in (business_rules or {}).get("customer_kpis", [])}
    temp_target = standard.get("% Time In Spec", {}).get("target_pct", 95)
    bloom_target = customer_kpis.get("Bloom Risk Score", {}).get("target_max", 15)

    compliance = kpis.get("avg_compliance_pct")
    avg_bloom = round(sum(b["BloomRiskScore"] for b in bloom_risk) / len(bloom_risk), 1) if bloom_risk else None

    cards = [
        dict(label="Trips Loaded", value=str(kpis["trips_loaded"]), target="-", status="on_target"),
        dict(label="Avg % Time In Spec", value=f"{compliance}%" if compliance is not None else "-",
             target=f">= {temp_target}%",
             status="at_risk" if compliance is not None and compliance < temp_target else "on_target"),
        dict(label="Flagged Trips", value=str(kpis["flagged_trip_count"]), target="0",
             status="at_risk" if kpis["flagged_trip_count"] > 0 else "on_target"),
        dict(label="Should Be Closed", value=str(kpis["likely_arrived_count"]), target="0",
             status="at_risk" if kpis["likely_arrived_count"] > 0 else "on_target"),
        dict(label="Stuck - Needs Investigation", value=str(kpis["stuck_trip_count"]), target="0",
             status="at_risk" if kpis["stuck_trip_count"] > 0 else "on_target"),
    ]
    if avg_bloom is not None:
        cards.append(dict(label="Avg Bloom Risk Score", value=str(avg_bloom), target=f"<= {bloom_target}",
                           status="at_risk" if avg_bloom > bloom_target else "on_target"))
    return cards


def _flagged_trips_table(records: list[dict]):
    columns = ["Trip", "Source", "Product", "Destination", "Issue", "% In Spec"]
    rows = [[
        str(r["TripID"]), str(r["Source"]), str(r["Product"]), str(r["Destination"]),
        FLAG_INFO.get(r["Flag"], {}).get("label", r["Flag"]),
        str(r["CompliancePct"]) if r["CompliancePct"] is not None else "-",
    ] for r in records]
    return columns, rows


def _product_bloom_table(product_risk: list[dict], bloom_risk: list[dict]):
    bloom_by_product = {b["Product"]: b for b in bloom_risk}
    columns = ["Product", "Trips", "Avg % In Spec", "Flagged", "Bloom Risk Score"]
    rows = []
    for p in product_risk:
        bloom = bloom_by_product.get(p["Product"], {})
        rows.append([str(p["Product"]), str(p["TripCount"]), str(p["AvgCompliancePct"]), str(p["FlaggedCount"]),
                     str(bloom.get("BloomRiskScore", "-"))])
    return columns, rows


def compose_report(insights: dict) -> tuple[Path, list]:
    data = insights["_data"]
    business_rules = ingestion.store.business_rules
    kpi_cards = _format_kpi_cards(data["program_kpis"], data["bloom_risk_by_product"], business_rules)
    flagged_cols, flagged_rows = _flagged_trips_table(data["flagged_trips"])
    product_cols, product_rows = _product_bloom_table(data["product_risk"], data["bloom_risk_by_product"])

    builder = PptxBuilder()

    def tool_executor(name: str, args: dict) -> dict:
        method = getattr(builder, name, None)
        if method is None:
            return {"status": "error", "message": f"unknown tool {name}"}
        try:
            return method(**args)
        except TypeError as e:
            return {"status": "error", "message": str(e)}

    user_prompt = (
        "ANALYST_INSIGHTS (from Agent 1, use for narrative/recommendation slides):\n"
        f"{json.dumps({k: v for k, v in insights.items() if k != '_data'}, indent=2)}\n\n"
        "EXACT_DATA_FOR_NUMERIC_SLIDES (use verbatim for add_kpi_slide / add_table_slide):\n"
        f"{json.dumps({'kpi_cards': kpi_cards, 'flagged_trips_table': {'columns': flagged_cols, 'rows': flagged_rows}, 'product_bloom_table': {'columns': product_cols, 'rows': product_rows}}, indent=2, default=str)}\n\n"
        f"Reporting period context: report generated {datetime.now():%d %B %Y} for {data['customer']}, "
        "covering all SensiWatch and ColdStream trips currently loaded.\n\n"
        "Now call the 7 tools in order as instructed."
    )

    calls = chat_with_tools(SYSTEM_PROMPT, user_prompt, TOOL_SCHEMAS, tool_executor)

    if builder.slide_count == 0:
        raise RuntimeError("Report Composer agent made no tool calls -- no slides were generated.")

    filename = f"belvoire_cold_chain_report_{datetime.now():%Y%m%d_%H%M%S}.pptx"
    output_path = REPORTS_DIR / filename
    builder.save(output_path)
    return output_path, calls
