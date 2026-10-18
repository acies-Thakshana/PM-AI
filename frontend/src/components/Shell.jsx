import { LOGO } from "../logo.js";

const TITLES = { dashboard: "Dashboard", ask: "Ask Questions", upload: "Upload Data" };

export function TopBar({ view, setView, unlocked, domainLabel }) {
  const subtitles = { dashboard: domainLabel, ask: "Business analyst copilot", upload: "Step 1 · Add your data" };
  return (
    <header className="workspace-topbar">
      <div className="workspace-topbar-left">
        <div className="workspace-brand">
          <img className="workspace-logo" alt="Carrier" src={LOGO} />
          <div>
            <p className="workspace-brand-name">NL2SQL</p>
            <p className="workspace-brand-tag">AI CoE · Semantic analytics</p>
          </div>
        </div>
        <span className="topbar-divider" aria-hidden="true"></span>
        <div>
          <p className="topbar-title">{TITLES[view]}</p>
          <p className="topbar-subtitle">{subtitles[view]}</p>
        </div>
        <div className="dataset-chip">
          Current dataset: <strong>{domainLabel}</strong>
        </div>
      </div>
      <nav className="view-nav" aria-label="Views">
        {[
          ["upload", "Upload data"],
          ["dashboard", "Dashboard"],
          ["ask", "Ask"]
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={"view-btn" + (view === id ? " active" : "")}
            disabled={!unlocked && id !== "upload"}
            title={!unlocked && id !== "upload" ? "Upload data first" : undefined}
            onClick={() => setView(id)}
          >
            {label}
          </button>
        ))}
      </nav>
    </header>
  );
}

export function Sidebar({ view, setView, unlocked, domainLabel, domains, domain, onDomain, detail, recent, onRecent, onNewChat, status }) {
  const tables = (detail && detail.tables) || [];
  const columns = [];
  tables.forEach((table) =>
    table.columns.forEach((column) => {
      if (columns.length < 40) columns.push(table.name + "." + column.name + (column.restricted ? " (restricted)" : ""));
    })
  );
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <img id="side-logo" className="carrier-logo" alt="Carrier" src={LOGO} />
        <p className="product-name">NL2SQL</p>
        <p className="product-tag">
          {TITLES[view].split(" ")[0]} · {domainLabel}
        </p>
      </div>
      <div className="side-views">
        <button type="button" className={"side-view" + (view === "dashboard" ? " active" : "")} disabled={!unlocked} onClick={() => setView("dashboard")}>
          Dashboard
        </button>
        <button type="button" className={"side-view" + (view === "ask" ? " active" : "")} disabled={!unlocked} onClick={() => setView("ask")}>
          Ask
        </button>
        <button
          type="button"
          className={"side-view side-view-wide" + (view === "upload" ? " active" : "")}
          onClick={() => setView("upload")}
        >
          Upload data
        </button>
      </div>
      {unlocked && (
      <>
      <div className="sidebar-section">
        <p className="sidebar-label">Domain</p>
        <select className="domain-select" aria-label="Domain" value={domain} onChange={(e) => onDomain(e.target.value)}>
          {domains.map((d) => (
            <option key={d.id} value={d.id}>
              {d.id}
            </option>
          ))}
          {!domains.length && <option value="">No domains</option>}
        </select>
      </div>
      {view === "ask" && (
        <button className="new-chat" type="button" onClick={onNewChat}>
          <span className="icon-plus" aria-hidden="true"></span> New conversation
        </button>
      )}
      <div className="sidebar-section">
        <p className="sidebar-label">Tables</p>
        <ul className="table-list">
          {!tables.length && <li>No tables yet</li>}
          {tables.map((t) => (
            <li key={t.name}>
              {t.name}
              <span>{t.rows}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="sidebar-section">
        <p className="sidebar-label">Columns</p>
        <ul className="column-list">
          {columns.length ? columns.map((c) => <li key={c}>{c}</li>) : <li>Columns appear after the tables load</li>}
        </ul>
      </div>
      <div className="sidebar-section">
        <p className="sidebar-label">Recent</p>
        <ul className="recent-list">
          {recent.length ? (
            recent.map((text) => (
              <li key={text}>
                <button type="button" onClick={() => onRecent(text)}>
                  {text}
                </button>
              </li>
            ))
          ) : (
            <li>
              <p className="sidebar-empty">Questions you ask show up here.</p>
            </li>
          )}
        </ul>
      </div>
      </>
      )}
      <p className="sidebar-foot">{status}</p>
    </aside>
  );
}
