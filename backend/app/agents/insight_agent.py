"""
Agent 1: Insight Analyst.

Single responsibility: turn deterministic stats (from app.services.trip_analytics,
computed over the uploaded SensiWatch/ColdStream trip data -- see Data Upload page)
plus retrieved chocolate cold chain domain knowledge into expert-level narrative
and recommendations. It NEVER touches the raw trip data directly and NEVER
invents numbers -- every figure it is allowed to cite is handed to it in the
prompt; its job is judgment and language, not arithmetic.

Output is validated JSON. Downstream (Agent 2 / pptx_tools) treats the numeric
tables from `trip_analytics.py` as ground truth and only pulls narrative text
from here, so a hallucinated adjective can't corrupt a data cell in the deck.
"""
import json

from app.agents.groq_client import chat_json
from app.services import ingestion, trip_analytics
from app.services.knowledge_retriever import chocolate_knowledge

SYSTEM_PROMPT = """You are a senior cold chain program manager producing the analytical \
narrative for a chocolate/confectionery customer's cold chain performance report. You \
write like an experienced program manager, not a generic AI assistant: specific, \
deductive, and grounded in the technical reference material you are given.

Rules:
- Only cite numbers that appear in the "DATA" section below. Never invent or round \
  figures beyond what is given.
- Ground every causal claim in the "DOMAIN KNOWLEDGE" section (e.g. fat bloom vs sugar \
  bloom mechanisms, temperature vs humidity compliance, trip-closure process gaps vs \
  genuinely stalled trips, ColdStream data-quality issues). Name the mechanism, not just \
  the correlation.
- Name specific trip IDs, products, and origin/destination facilities from the DATA when \
  making a point -- never write generic filler like "some shipments experienced issues".
- Recommendations must each map to a specific root cause you identified, using the \
  corrective action catalog in the DOMAIN KNOWLEDGE, not generic advice.
- Return ONLY a JSON object matching this schema, no prose outside the JSON:
{
  "executive_summary": "2-4 sentences, headline numbers + overall verdict vs targets",
  "performance_overview_narrative": "1-2 short paragraphs on % time in spec, humidity compliance, and bloom risk score performance vs targets",
  "root_cause_narrative": "1-2 short paragraphs deductively correlating specific triage flags (trip closure gaps, stalled trips, ColdStream data-quality issues) and temperature/humidity excursions to specific bloom risk outcomes, naming the mechanism",
  "recommendations": [
    {"action": "...", "rationale": "...", "priority": "High|Medium|Low"}
  ]
}
"""


def generate_insights() -> dict:
    kpis = trip_analytics.kpi_summary()
    if kpis["trips_loaded"] == 0:
        raise RuntimeError("No trip data loaded yet -- load SensiWatch/ColdStream data on the Data Upload page first.")

    flagged_df = trip_analytics.flagged_trips()
    product_risk_df = trip_analytics.product_risk()
    destination_df = trip_analytics.destination_ranking()
    rca = trip_analytics.rca_summary()
    bloom_risk = trip_analytics.bloom_risk_by_product()

    products = product_risk_df["Product"].tolist() if not product_risk_df.empty else []
    destinations = destination_df["Destination"].tolist() if not destination_df.empty else []
    knowledge_context = chocolate_knowledge.retrieve_for(
        products + destinations,
        extra_terms="fat bloom sugar bloom trip closure gap stalled data quality excursion humidity",
    )

    customer = (ingestion.store.business_rules or {}).get("customer", "the customer")

    data_payload = {
        "customer": customer,
        "program_kpis": kpis,
        "flagged_trips": trip_analytics.to_records(flagged_df),
        "root_cause_categories": rca,
        "product_risk": trip_analytics.to_records(product_risk_df),
        "destination_ranking": trip_analytics.to_records(destination_df),
        "bloom_risk_by_product": bloom_risk,
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
