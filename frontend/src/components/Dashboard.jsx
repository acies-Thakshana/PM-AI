import { AnswerCard } from "./AnswerCard.jsx";
import { Bars } from "./Viz.jsx";
import { LOGO } from "../logo.js";
import { formatValue } from "../format.js";

export function Dashboard({ hidden, domain, domainLabel, detail, dashboard, error, onAsk }) {
  const empty = !dashboard.kpis.length && !dashboard.charts.length && !dashboard.answers.length;
  let lede = "Pick or upload a domain to begin.";
  if (detail) {
    lede =
      detail.tables.length +
      " table(s), " +
      detail.counts.metrics +
      " certified metric(s). Figures below come from this domain's starter questions.";
  }
  return (
    <section id="dashboard" className="dashboard" hidden={hidden}>
      <header className="dash-head">
        <div>
          <p className="eyebrow">Carrier · Semantic analytics</p>
          <h1>{domainLabel}</h1>
          <p className="dash-lede">{lede}</p>
        </div>
        <img className="carrier-logo" alt="Carrier" src={LOGO} />
      </header>
      <div className="dash-kpis">
        {error && <p className="dash-note">{error}</p>}
        {!error && empty && (
          <p className="dash-note">
            {!domain
              ? "No domain selected."
              : detail && !dashboard.pending
                ? "This domain has no starter questions yet. Run onboarding from Upload data, or ask a question."
                : "Running this domain's starter questions…"}
          </p>
        )}
        {dashboard.kpis.map((kpi, i) => (
          <article className="kpi-card" key={i}>
            <span>{kpi.label}</span>
            <strong>{formatValue(kpi.value, kpi.unit)}</strong>
            {kpi.note && <em>{kpi.note}</em>}
          </article>
        ))}
      </div>
      <div className="dash-charts">
        {dashboard.charts.map((chart, i) => (
          <article className="dash-card" key={i}>
            <h2>{chart.title}</h2>
            {chart.note && <p className="dash-note">{chart.note}</p>}
            <Bars items={chart.items} unit={chart.unit} />
          </article>
        ))}
      </div>
      <div className="answer-stack">
        {dashboard.answers.map((item, i) => (
          <AnswerCard key={i} data={item} />
        ))}
      </div>
      <button className="dash-ask" type="button" onClick={onAsk}>
        Ask a question about these numbers
      </button>
    </section>
  );
}
