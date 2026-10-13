"""Local Streamlit host: light command dashboard + Ask Business Data."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from frontend.app.services import backend  # noqa: E402

ACCENT = "#0B6E99"
ALERT = "#C23B3B"
OK = "#1F8A5B"
WARN = "#B7791F"
PURPLE = "#6B5B95"
CARD_ACCENTS = [ACCENT, WARN, OK, PURPLE, "#C45C7A", "#3A7CA5"]

st.set_page_config(
    page_title="Enterprise AI for BI — Local Command",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #F4F8FC 0%, #EAF1F8 45%, #F7FAFD 100%);
            color: #1B2A3A;
        }
        .block-container {padding-top: 1.0rem; padding-bottom: 2rem; max-width: 1500px;}
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #FFFFFF 0%, #F3F7FB 100%);
            border-right: 1px solid #D5E0EB;
        }
        .hero {
            background: linear-gradient(135deg, #FFFFFF 0%, #EEF5FB 55%, #E4F0F7 100%);
            border: 1px solid #D0DCE8; border-radius: 16px;
            padding: 1.05rem 1.35rem 1.15rem 1.35rem; margin-bottom: 0.85rem;
            box-shadow: 0 6px 18px rgba(27, 42, 58, 0.06);
        }
        .hero h1 {margin: 0; font-size: 1.7rem; color: #132433;}
        .hero p {margin: 0.35rem 0 0 0; color: #5A6F84; font-size: 0.95rem;}
        .hero .pill {
            display: inline-block; margin-top: 0.55rem; margin-right: 0.35rem;
            padding: 0.18rem 0.55rem; border-radius: 999px;
            background: rgba(11,110,153,0.10); border: 1px solid #9FCBDD;
            color: #0B6E99; font-size: 0.72rem; letter-spacing: 0.03em;
        }
        .kpi-card {
            background: #FFFFFF; border: 1px solid #D5E0EB;
            border-radius: 14px; padding: 0.85rem 1rem 0.95rem 1rem;
            min-height: 132px; box-shadow: 0 6px 16px rgba(27, 42, 58, 0.05);
        }
        .kpi-card.accent-0 {border-top: 3px solid #0B6E99;}
        .kpi-card.accent-1 {border-top: 3px solid #B7791F;}
        .kpi-card.accent-2 {border-top: 3px solid #1F8A5B;}
        .kpi-card.accent-3 {border-top: 3px solid #6B5B95;}
        .kpi-label {color: #5A6F84; font-size: 0.74rem; letter-spacing: 0.04em; text-transform: uppercase;}
        .kpi-value {color: #132433; font-size: 1.35rem; font-weight: 700; line-height: 1.25; margin-top: 0.25rem;}
        .kpi-sub {color: #7A8FA3; font-size: 0.76rem; margin-top: 0.25rem;}
        .panel {
            background: rgba(255,255,255,0.92); border: 1px solid #D5E0EB;
            border-radius: 14px; padding: 0.9rem 1rem; margin-bottom: 0.75rem;
        }
        .panel h3 {margin: 0 0 0.35rem 0; color: #132433; font-size: 1.05rem;}
        .panel p {margin: 0; color: #5A6F84; font-size: 0.88rem;}
        .chip {
            display: inline-block; margin: 0.15rem 0.3rem 0.15rem 0;
            padding: 0.2rem 0.55rem; border-radius: 999px;
            background: #FFFFFF; border: 1px solid #C9D7E6; color: #334E63;
            font-size: 0.75rem;
        }
        .chip.ok {border-color: #8BC9A8; color: #1F8A5B; background: rgba(31,138,91,0.08);}
        .chip.warn {border-color: #E2C48A; color: #B7791F; background: rgba(183,121,31,0.08);}
        .chip.alert {border-color: #E2A0A0; color: #C23B3B; background: rgba(194,59,59,0.08);}
        div[data-testid="stMetric"] {
            background: #FFFFFF; border: 1px solid #D5E0EB; border-radius: 12px;
            padding: 0.55rem 0.75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def style_fig(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=48, b=10),
        font=dict(color="#1B2A3A"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def kpi_card_html(label: str, value: str, sub: str, accent_idx: int = 0) -> None:
    st.markdown(
        f'<div class="kpi-card accent-{accent_idx % 4}">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


inject_css()

bootstrap_users = backend.get_bootstrap("local.cross_bu")["users"]
user_ids = [u["user_id"] for u in bootstrap_users] or ["local.cross_bu"]

st.sidebar.markdown("### Session")
default_idx = user_ids.index("local.cross_bu") if "local.cross_bu" in user_ids else 0
user_id = st.sidebar.selectbox("Local user", user_ids, index=default_idx)
boot = backend.get_bootstrap(user_id)
user = boot["user"]
catalog = boot.get("filter_catalog") or {}

st.sidebar.caption(f"**{user['display_name']}**")
st.sidebar.caption(f"Roles: {', '.join(user.get('roles') or []) or 'none'}")
st.sidebar.caption(
    f"BU scope: {', '.join(user.get('authorized_bu_codes') or ['cross-BU / all'])}"
)
st.sidebar.caption(f"Semantic `{boot.get('semantic_version')}` · `{boot.get('model_id')}`")

st.sidebar.divider()
st.sidebar.markdown("### Global filters")
st.sidebar.caption("Affects dashboard charts only (Ask is independent unless you opt in).")

bu_opts = catalog.get("business_units") or user.get("authorized_bu_codes") or []
# Cross-BU users default to ALL BUs; BU-scoped users get their authorized list.
_default_bus = (
    list(bu_opts)
    if user.get("can_query_cross_bu")
    else (list(user.get("authorized_bu_codes") or bu_opts[:1]))
)
selected_bus = st.sidebar.multiselect(
    "Business unit",
    options=bu_opts,
    default=[b for b in _default_bus if b in bu_opts] or (bu_opts[:1] if bu_opts else []),
)
selected_pillars = st.sidebar.multiselect(
    "Pillar type",
    options=catalog.get("pillars") or ["Direct", "Indirect", "Logistics"],
    default=catalog.get("pillars") or ["Direct", "Indirect", "Logistics"],
)
c_y, c_q = st.sidebar.columns(2)
with c_y:
    year_opts = catalog.get("years") or ["2025"]
    selected_years = st.multiselect("Year", options=year_opts, default=year_opts[:1])
with c_q:
    q_opts = catalog.get("quarters") or ["Q1", "Q2", "Q3", "Q4"]
    selected_quarters = st.multiselect("Quarter", options=q_opts, default=q_opts)

selected_months = st.sidebar.multiselect(
    "Month", options=catalog.get("months") or [], default=[]
)
selected_regions = st.sidebar.multiselect(
    "Region", options=catalog.get("regions") or [], default=[]
)
selected_categories = st.sidebar.multiselect(
    "Category (L1)", options=catalog.get("categories") or [], default=[]
)

st.sidebar.divider()
st.sidebar.markdown("### Display options")
view_mode = st.sidebar.selectbox(
    "Dashboard view",
    options=catalog.get("view_modes") or ["Overview", "Trend", "Comparison", "Variance", "Ranking"],
    index=0,
)
chart_type = st.sidebar.selectbox(
    "Preferred chart",
    options=catalog.get("chart_types") or ["Auto", "Bar", "Line", "Grouped bar", "Treemap"],
    index=0,
)
currency = st.sidebar.selectbox(
    "Currency", options=catalog.get("currencies") or ["USD"], index=0
)
unit = st.sidebar.selectbox(
    "Unit", options=catalog.get("units") or ["Currency amount"], index=0
)
compare_basis = st.sidebar.selectbox(
    "Comparison basis",
    options=["Prior period", "Target / forecast", "Peer BU", "Same quarter last year"],
    index=1,
)
show_targets = st.sidebar.toggle("Show target overlays", value=True)
show_freshness = st.sidebar.toggle("Show freshness strip", value=True)

active_filters = {
    "business_units": selected_bus,
    "pillars": selected_pillars,
    "years": selected_years,
    "quarters": selected_quarters,
    "months": selected_months,
    "regions": selected_regions,
    "categories": selected_categories,
    "currency": currency,
    "unit": unit,
    "view_mode": view_mode,
    "chart_type": chart_type,
    "compare_basis": compare_basis,
    "show_targets": show_targets,
}

dash = backend.get_dashboard(user_id, active_filters)
summary = dash.get("summary") or {}
cards = dash.get("kpi_cards") or []
by_pillar = pd.DataFrame(dash.get("by_pillar") or [])
by_bu = pd.DataFrame(dash.get("by_bu") or [])
by_quarter = pd.DataFrame(dash.get("by_quarter") or [])
by_region = pd.DataFrame(dash.get("by_region") or [])

st.sidebar.divider()
st.sidebar.markdown("### Active selection")
st.sidebar.markdown(
    f'<span class="chip">{view_mode}</span>'
    f'<span class="chip">{chart_type}</span>'
    f'<span class="chip">{currency}</span>'
    f'<span class="chip">{unit}</span>',
    unsafe_allow_html=True,
)
if selected_bus:
    st.sidebar.caption(
        "BUs: " + ", ".join(selected_bus[:3]) + ("…" if len(selected_bus) > 3 else "")
    )
st.sidebar.caption(f"{summary.get('row_count', 0):,} KPI rows in current filter")

st.markdown(
    f"""
    <div class="hero">
      <h1>Enterprise AI for BI — Local Command</h1>
      <p>Live KPI cube numbers · governed semantic metrics · Ask Business Data stays dashboard-independent</p>
      <span class="pill">LOCAL</span>
      <span class="pill">SEMANTIC {boot.get('semantic_version')}</span>
      <span class="pill">{boot.get('model_id')}</span>
      <span class="pill">{view_mode.upper()}</span>
      <span class="pill">{summary.get('row_count', 0):,} ROWS</span>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_dash, tab_explore, tab_chat, tab_meta = st.tabs(
    [
        "Executive overview",
        "Explore & compare",
        "Ask Business Data",
        "Metric definitions",
    ]
)

with tab_dash:
    st.markdown(
        '<div class="panel"><h3>Authorized KPI cards</h3>'
        "<p>Values are computed from the curated KPI_data cube with your filters and BU scope applied.</p></div>",
        unsafe_allow_html=True,
    )

    if not cards:
        st.warning("No authorized KPI cards for this user/role.")
    else:
        cols = st.columns(min(4, len(cards)))
        for i, card in enumerate(cards):
            with cols[i % len(cols)]:
                kpi_card_html(
                    card["title"],
                    card.get("display_value") or "n/a",
                    f"{card['metric_id']} · {summary.get('row_count', 0):,} rows",
                    accent_idx=i,
                )

    if show_freshness:
        st.markdown("#### Data freshness")
        chips = []
        as_of = summary.get("as_of")
        if as_of:
            chips.append(f'<span class="chip ok">KPI cube as-of {as_of}</span>')
        for item in boot.get("freshness") or []:
            behavior = (item.get("stale_behavior") or "warn").lower()
            klass = "ok" if behavior == "warn" else ("alert" if behavior == "block" else "warn")
            chips.append(
                f'<span class="chip {klass}">{item.get("data_product_id")} · '
                f'SLA {item.get("sla_hours")}h · {behavior}</span>'
            )
        if chips:
            st.markdown(" ".join(chips), unsafe_allow_html=True)

    st.markdown("#### Actual productivity by quarter")
    if by_quarter.empty:
        st.info("No quarterly rows for the current filters.")
    else:
        qdf = by_quarter.rename(columns={"value": "Actual productivity"})
        order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
        qcol = by_quarter.columns[0]
        qdf["_ord"] = qdf[qcol].map(lambda x: order.get(str(x), 99))
        qdf = qdf.sort_values("_ord")
        if chart_type in {"Line", "Auto"}:
            fig = px.line(
                qdf,
                x=qcol,
                y="Actual productivity",
                markers=True,
                color_discrete_sequence=CARD_ACCENTS,
            )
        else:
            fig = px.bar(
                qdf,
                x=qcol,
                y="Actual productivity",
                color_discrete_sequence=CARD_ACCENTS,
            )
        if show_targets and summary.get("forecast_productivity"):
            fig.add_hline(
                y=summary["forecast_productivity"] / max(len(qdf), 1),
                line_dash="dot",
                line_color=WARN,
                annotation_text="avg target/quarter (approx)",
            )
        st.plotly_chart(style_fig(fig, 400), use_container_width=True)

with tab_explore:
    left, right = st.columns(2)
    with left:
        st.markdown("#### Comparison by pillar")
        if by_pillar.empty:
            st.info("No pillar data for current filters.")
        else:
            pdf = by_pillar.rename(columns={"value": "Actual productivity"})
            fig = px.bar(
                pdf,
                x=pdf.columns[0],
                y="Actual productivity",
                color=pdf.columns[0],
                color_discrete_sequence=CARD_ACCENTS,
            )
            st.plotly_chart(style_fig(fig, 360), use_container_width=True)
    with right:
        st.markdown("#### Actual vs target (filter totals)")
        vs = pd.DataFrame(
            [
                {"Metric": "Actual", "Value": summary.get("actual_productivity") or 0},
                {"Metric": "Target", "Value": summary.get("forecast_productivity") or 0},
                {"Metric": "Prob-weighted", "Value": summary.get("agg_productivity") or 0},
            ]
        )
        fig = px.bar(
            vs,
            x="Metric",
            y="Value",
            color="Metric",
            color_discrete_sequence=CARD_ACCENTS,
        )
        st.plotly_chart(style_fig(fig, 360), use_container_width=True)

    st.markdown("#### Ranking by business unit")
    if by_bu.empty:
        st.info("No BU ranking for current filters.")
    else:
        rdf = by_bu.rename(columns={"value": "Actual productivity"}).head(12)
        fig = px.bar(
            rdf,
            x="Actual productivity",
            y=rdf.columns[0],
            orientation="h",
            color="Actual productivity",
            color_continuous_scale="Teal",
        )
        st.plotly_chart(style_fig(fig, 360), use_container_width=True)

    if not by_region.empty:
        st.markdown("#### By region")
        reg = by_region.rename(columns={"value": "Actual productivity"}).head(12)
        fig = px.bar(
            reg,
            x=reg.columns[0],
            y="Actual productivity",
            color_discrete_sequence=CARD_ACCENTS,
        )
        st.plotly_chart(style_fig(fig, 320), use_container_width=True)

    st.markdown("#### Applied filters")
    st.json(active_filters)

with tab_chat:
    st.markdown(
        '<div class="panel"><h3>Ask Business Data</h3>'
        "<p>Semantic KPI executor first (certified metrics on KPI_data). Falls back to NL-to-SQL only when needed.</p></div>",
        unsafe_allow_html=True,
    )

    suggestions = boot.get("suggested_questions") or []
    c1, c2 = st.columns([2, 1])
    with c1:
        pick = st.selectbox("Suggested questions", [""] + suggestions) if suggestions else ""
        question = st.text_area("Your question", value=pick or "", height=110)
    with c2:
        st.markdown("##### Context sent as UI hint only")
        st.caption("Not a security boundary")
        apply_dash_filters = st.checkbox(
            "Apply dashboard filters to Ask",
            value=False,
            help="Off by default so questions can span all authorized BUs.",
        )
        st.write(f"View: **{view_mode}**")
        st.write(f"Currency: **{currency}**")
        st.write(f"Compare: **{compare_basis}**")
        st.write(f"BUs: **{', '.join(selected_bus) or 'default scope'}**")

    ask_clicked = st.button("Ask", type="primary", use_container_width=False)

    if ask_clicked and question.strip():
        with st.spinner("Planning + querying curated data products..."):
            result = backend.ask(
                question.strip(),
                user_id=user_id,
                visible_metric_ids=[c["metric_id"] for c in cards],
                filters=active_filters,
                apply_dashboard_filters=apply_dash_filters,
            )
        st.session_state["last_result"] = result

    result = st.session_state.get("last_result")
    if result:
        status = result.get("status")
        if status == "success":
            st.markdown(f'<span class="chip ok">{status}</span>', unsafe_allow_html=True)
        elif status in {"clarification_needed"}:
            st.markdown(f'<span class="chip warn">{status}</span>', unsafe_allow_html=True)
        else:
            st.markdown(f'<span class="chip alert">{status}</span>', unsafe_allow_html=True)
        st.caption(f"request `{result.get('request_id')}`")

        if result.get("clarification"):
            st.warning(result["clarification"])
            if result.get("suggested_questions"):
                st.write("Try:")
                for s in result["suggested_questions"]:
                    st.write(f"- {s}")
        if result.get("answer"):
            st.success(result["answer"])
        table = result.get("table") or {}
        if table.get("rows"):
            st.dataframe(pd.DataFrame(table["rows"]), use_container_width=True)
        if result.get("sql_query"):
            with st.expander("SQL (semantic / validated path)"):
                st.code(result["sql_query"], language="sql")
        if result.get("chart_spec"):
            with st.expander("Chart spec"):
                st.json(result["chart_spec"])
        with st.expander("Semantic query plan"):
            st.json(result.get("plan") or {})
        with st.expander("Response metadata"):
            st.json(
                {
                    "metric_ids": result.get("metric_ids"),
                    "data_products": result.get("data_products"),
                    "bu_scope": result.get("bu_scope"),
                    "warnings": result.get("warnings"),
                    "freshness": result.get("freshness"),
                    "ui_filters": active_filters,
                }
            )

with tab_meta:
    st.markdown(
        '<div class="panel"><h3>Metric definitions</h3>'
        "<p>Authorized cards and shared dimensions from the loaded semantic model.</p></div>",
        unsafe_allow_html=True,
    )
    for i, card in enumerate(cards):
        with st.expander(f"{card['title']} — {card['metric_id']}", expanded=(i == 0)):
            st.write(card.get("description"))
            st.write(f"Live value: **{card.get('display_value')}**")
            st.write(f"Status: **{card.get('definition_status')}**")
            st.write(f"Unit: `{card.get('unit_id')}`")
            st.write(f"Data products: `{', '.join(card.get('data_product_ids') or [])}`")
            st.write(f"Synonyms: {', '.join(card.get('synonyms') or [])}")
            st.write(f"Semantic version: `{card.get('semantic_version')}`")

    st.markdown("#### Dimensions")
    for dim in boot.get("dimensions") or []:
        st.markdown(
            f'<span class="chip">{dim.get("name")} · {dim.get("id")}</span>',
            unsafe_allow_html=True,
        )
        st.caption(dim.get("description") or "")
