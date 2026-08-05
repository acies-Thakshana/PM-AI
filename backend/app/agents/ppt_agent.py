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
from app.services.report_template import PROGRAM_TITLE, SLIDE_SEQUENCE

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
  (concise, presentation-appropriate) but must preserve every factual claim, shipment ID, \
  facility name, and causal mechanism mentioned there. Do not add generic filler.
- Call the 7 tools in order and then stop.
"""


def _format_kpi_cards(kpis: dict) -> list[dict]:
    targets = kpis.get("targets", {})
    temp_target = targets.get("Temperature Compliance Rate", 95)
    spoil_target = targets.get("Maximum Acceptable Spoilage", 8)
    life_target = targets.get("Minimum Green Life Retention", 70)

    return [
        dict(label="Temperature Compliance", value=f"{kpis['avg_temperature_compliance_pct']}%",
             target=f"{temp_target}%",
             status="on_target" if kpis["avg_temperature_compliance_pct"] >= temp_target else "at_risk"),
        dict(label="Avg Arrival Spoilage", value=f"{kpis['avg_spoilage_pct']}%",
             target=f"<= {spoil_target}%",
             status="at_risk" if kpis["avg_spoilage_pct"] > spoil_target else "on_target"),
        dict(label="Avg Green Life Retention", value=f"{kpis['avg_green_life_retention_pct']}%",
             target=f">= {life_target}%",
             status="at_risk" if kpis["avg_green_life_retention_pct"] < life_target else "on_target"),
        dict(label="At-Risk Shipments", value=str(kpis["at_risk_shipment_count"]), target="0",
             status="at_risk" if kpis["at_risk_shipment_count"] > 0 else "on_target"),
        dict(label="Shipments Assessed", value=str(kpis["shipments_assessed"]), target="-", status="on_target"),
    ]


def _top_risk_table(records: list[dict]):
    # the add_table_slide tool schema requires string cells -- stringify here so the
    # exact values in the prompt already match what the model is allowed to pass back
    columns = ["Shipment", "Commodity", "Facility", "Spoilage %", "Green Life Left (d)", "Excursion (deg-hrs)"]
    rows = [[str(r["ShipmentID"]), str(r["Commodity"]), str(r["DestinationFacility"]), str(r["SpoilagePct"]),
             str(r["GreenLifeRemainingDays"]), str(r["ExcursionDegHours"])] for r in records]
    return columns, rows


def _facility_table(records: list[dict]):
    columns = ["Facility", "Type", "Refrigeration", "Install Yr", "Avg Compliance %", "Avg Spoilage %"]
    rows = [[str(r["DestinationFacility"]), str(r["FacilityType"]), str(r["RefrigerationSystemType"]), str(r["InstallYear"]),
             str(r["AvgCompliancePct"]), str(r["AvgSpoilagePct"])] for r in records]
    return columns, rows


def compose_report(insights: dict) -> Path:
    data = insights["_data"]
    kpi_cards = _format_kpi_cards(data["program_kpis"])
    top_risk_cols, top_risk_rows = _top_risk_table(data["top_risk_shipments"])
    facility_cols, facility_rows = _facility_table(data["facility_ranking"])

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
        f"{json.dumps({'kpi_cards': kpi_cards, 'top_risk_table': {'columns': top_risk_cols, 'rows': top_risk_rows}, 'facility_table': {'columns': facility_cols, 'rows': facility_rows}}, indent=2, default=str)}\n\n"
        f"Reporting period context: report generated {datetime.now():%d %B %Y}, "
        "covering shipments dispatched over the preceding 30 days.\n\n"
        "Now call the 7 tools in order as instructed."
    )

    calls = chat_with_tools(SYSTEM_PROMPT, user_prompt, TOOL_SCHEMAS, tool_executor)

    if builder.slide_count == 0:
        raise RuntimeError("Report Composer agent made no tool calls -- no slides were generated.")

    filename = f"cold_chain_report_{datetime.now():%Y%m%d_%H%M%S}.pptx"
    output_path = REPORTS_DIR / filename
    builder.save(output_path)
    return output_path, calls
