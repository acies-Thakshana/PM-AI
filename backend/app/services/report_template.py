"""
The "Gold Standard" report template spec: brand styling + the fixed slide
order/structure the Report Composer agent must follow. Keeping this as data
(not agent-authored) is what guarantees the deck always matches the required
format regardless of what the LLM decides to write in each placeholder.
"""

BRAND = dict(
    primary_hex="1B5E20",       # deep cold-chain green
    secondary_hex="0D47A1",     # accent blue
    accent_hex="F9A825",        # warning amber (used for risk callouts)
    dark_text_hex="1A1A1A",
    light_bg_hex="F5F7F5",
    font_heading="Calibri",
    font_body="Calibri",
)

PROGRAM_TITLE = "Cold Chain Post-Harvest Assessment Report"

# The fixed slide sequence. Agent 2 (Report Composer) must call exactly one
# pptx_tools function per entry, in this order, using content sourced from
# Agent 1's insight JSON -- it cannot reorder, skip, or invent extra slides.
SLIDE_SEQUENCE = [
    dict(slide_type="title", tool="add_title_slide",
         purpose="Program name, reporting period, subtitle"),
    dict(slide_type="kpi", tool="add_kpi_slide",
         purpose="Executive summary KPI cards vs. program targets"),
    dict(slide_type="narrative", tool="add_narrative_slide",
         purpose="Cold chain performance overview narrative"),
    dict(slide_type="narrative", tool="add_narrative_slide",
         purpose="Root-cause / deductive analysis: correlate temperature excursions to green-life loss, name specific commodities/facilities"),
    dict(slide_type="table", tool="add_table_slide",
         purpose="Top at-risk shipments deep-dive table"),
    dict(slide_type="table", tool="add_table_slide",
         purpose="Facility performance ranking table"),
    dict(slide_type="recommendations", tool="add_recommendations_slide",
         purpose="Prioritized, root-cause-matched corrective actions"),
]
