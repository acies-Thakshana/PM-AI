"""
Agent 1: Insight Analyst.

Single responsibility: turn deterministic stats (from app.services.analytics)
plus retrieved domain knowledge (from app.services.knowledge_retriever) into
expert-level narrative and recommendations. It NEVER touches the Excel file
and NEVER invents numbers -- every figure it is allowed to cite is handed to
it in the prompt; its job is judgment and language, not arithmetic.

Output is validated JSON. Downstream (Agent 2 / pptx_tools) treats the numeric
tables from `analytics.py` as ground truth and only pulls narrative text from
here, so a hallucinated adjective can't corrupt a data cell in the deck.
"""
import json

from app.agents.groq_client import chat_json
from app.services import analytics
from app.services.knowledge_retriever import retrieve_for_shipments

SYSTEM_PROMPT = """You are a senior post-harvest cold chain analyst producing the \
analytical narrative for a Commercial & Industrial (C&I) Program Management report. \
You write like an experienced program manager, not a generic AI assistant: specific, \
deductive, and grounded in the technical reference material you are given.

Rules:
- Only cite numbers that appear in the "DATA" section below. Never invent or round \
  figures beyond what is given.
- Ground every causal claim in the "DOMAIN KNOWLEDGE" section (e.g. degree-hours, \
  Q10 respiration, chilling injury vs heat-driven spoilage, door-open effects). \
  Name the mechanism, not just the correlation.
- Name specific shipment IDs, commodities, and facility names from the DATA when \
  making a point -- never write generic filler like "some shipments experienced issues".
- Recommendations must each map to a specific root cause you identified, using the \
  corrective action catalog in the DOMAIN KNOWLEDGE, not generic advice.
- Return ONLY a JSON object matching this schema, no prose outside the JSON:
{
  "executive_summary": "2-4 sentences, headline numbers + overall verdict vs targets",
  "performance_overview_narrative": "1-2 short paragraphs on cold chain compliance performance",
  "root_cause_narrative": "1-2 short paragraphs deductively correlating specific temperature excursions to specific green-life/spoilage outcomes, naming the mechanism",
  "facility_ranking_narrative": "1 short paragraph on which facilities underperform and the likely equipment/process reason",
  "recommendations": [
    {"action": "...", "rationale": "...", "priority": "High|Medium|Low"}
  ]
}
"""


def generate_insights() -> dict:
    kpis = analytics.kpi_summary()
    alerts_df = analytics.excursion_alerts()
    facility_df = analytics.facility_ranking()
    commodity_df = analytics.commodity_risk()
    top_risk_df = analytics.top_risk_shipments(5)

    commodities = commodity_df["Commodity"].tolist() if not commodity_df.empty else []
    facility_names = facility_df["DestinationFacility"].tolist() if not facility_df.empty else []
    knowledge_context = retrieve_for_shipments(
        commodities, facility_names,
        extra_terms="excursion degree-hours chilling injury green life spoilage door open compliance",
    )

    data_payload = {
        "program_kpis": kpis,
        "excursion_alerts": analytics.to_records(alerts_df),
        "facility_ranking": analytics.to_records(facility_df),
        "commodity_risk": analytics.to_records(commodity_df),
        "top_risk_shipments": analytics.to_records(top_risk_df),
    }

    user_prompt = (
        "DATA (deterministic, already computed -- do not recompute or alter any figure):\n"
        f"{json.dumps(data_payload, indent=2, default=str)}\n\n"
        "DOMAIN KNOWLEDGE (retrieved reference material relevant to this data):\n"
        f"{knowledge_context}\n\n"
        "Produce the JSON object described in your instructions."
    )

    insights = chat_json(SYSTEM_PROMPT, user_prompt)

    # attach the ground-truth numeric tables so Agent 2 never has to re-derive them
    insights["_data"] = data_payload
    return insights
