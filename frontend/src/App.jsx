import { useCallback, useEffect, useRef, useState } from "react";
import { askQuestion, getDomain, getDomains, getInfo } from "./api.js";
import { dashboardQuestions, pretty } from "./format.js";
import { TopBar, Sidebar } from "./components/Shell.jsx";
import { Dashboard } from "./components/Dashboard.jsx";
import { Ask } from "./components/Ask.jsx";
import { Upload } from "./components/Upload.jsx";

const newSession = () => "web-" + Math.random().toString(36).slice(2, 10);
const EMPTY_DASHBOARD = { kpis: [], charts: [], answers: [], pending: false };

export default function App() {
  const [view, setView] = useState("upload");
  const [domains, setDomains] = useState([]);
  const [domain, setDomain] = useState("");
  const [detail, setDetail] = useState(null);
  const [dashboard, setDashboard] = useState(EMPTY_DASHBOARD);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Connecting to the backend…");
  const [recent, setRecent] = useState([]);
  const [chatKey, setChatKey] = useState(0);
  const [sessionId, setSessionId] = useState(newSession);
  const [pendingQuestion, setPendingQuestion] = useState("");
  const runRef = useRef(0);

  const domainLabel = domain ? pretty(domain) : "No domain";

  const loadDomain = useCallback((id) => {
    const run = ++runRef.current;
    setDomain(id);
    setDetail(null);
    setError("");
    setDashboard(EMPTY_DASHBOARD);
    if (!id) {
      setStatus("No domains yet. Upload data to begin.");
      return Promise.resolve();
    }
    setStatus("Loading " + id + "…");
    return getDomain(id)
      .then(async (d) => {
        if (run !== runRef.current) return;
        setDetail(d);
        setStatus(d.tables.length + " table(s) · " + (d.has_baseline_package ? "baseline package" : "inferred package"));
        const questions = dashboardQuestions(d);
        if (!questions.length) return;
        setDashboard({ ...EMPTY_DASHBOARD, pending: true });
        // One at a time: the backend builds the domain's data once and caches it.
        for (const question of questions) {
          if (run !== runRef.current) return;
          try {
            const view = await askQuestion(question, id, null);
            if (run !== runRef.current) return;
            setDashboard((dash) => {
              const next = { ...dash, answers: [...dash.answers, view] };
              if (view.ok && view.viz.kind === "number") {
                next.kpis = [...dash.kpis, { label: view.viz.label, value: view.viz.value, unit: view.viz.unit, note: question }];
              } else if (view.ok && view.viz.kind === "bars") {
                next.charts = [
                  ...dash.charts,
                  { title: (view.chart && view.chart.title) || question, note: question, items: view.viz.items, unit: view.viz.unit }
                ];
              }
              return next;
            });
          } catch {
            /* one failing question must not blank the dashboard */
          }
        }
        if (run === runRef.current) setDashboard((dash) => ({ ...dash, pending: false }));
      })
      .catch((e) => {
        if (run !== runRef.current) return;
        setStatus(e.message || String(e));
        setError(e.message || String(e));
      });
  }, []);

  const loadDomains = useCallback(
    (preferred) =>
      getDomains().then((list) => {
        setDomains(list || []);
        return preferred && (list || []).some((d) => d.id === preferred) ? preferred : list && list.length ? list[0].id : "";
      }),
    []
  );

  useEffect(() => {
    getInfo()
      .then((info) => loadDomains(info.default_domain))
      .then((id) => loadDomain(id))
      .catch((e) => {
        setStatus(e.message || String(e));
        setError(e.message || String(e));
      });
  }, [loadDomains, loadDomain]);

  function changeDomain(id) {
    setChatKey((k) => k + 1);
    setSessionId(newSession());
    loadDomain(id);
  }

  function newConversation() {
    setChatKey((k) => k + 1);
    setSessionId(newSession());
  }

  function onAsked(question) {
    setRecent((r) => [question, ...r.filter((q) => q !== question)].slice(0, 8));
  }

  function askFromRecent(text) {
    setView("ask");
    setPendingQuestion(text);
  }

  const suggestions = dashboardQuestions(detail);

  return (
    <div className="workspace-shell">
      <TopBar view={view} setView={setView} domainLabel={domainLabel} />
      <div className="shell">
        <Sidebar
          view={view}
          setView={setView}
          domainLabel={domainLabel}
          domains={domains}
          domain={domain}
          onDomain={changeDomain}
          detail={detail}
          recent={recent}
          onRecent={askFromRecent}
          onNewChat={newConversation}
          status={status}
        />
        <div className="main">
          <Dashboard
            hidden={view !== "dashboard"}
            domain={domain}
            domainLabel={domainLabel}
            detail={detail}
            dashboard={dashboard}
            error={error}
            onAsk={() => setView("ask")}
          />
          <Ask
            key={domain + ":" + chatKey}
            hidden={view !== "ask"}
            domain={domain}
            domainLabel={domainLabel}
            suggestions={suggestions}
            sessionId={sessionId}
            onAsked={onAsked}
            pendingQuestion={pendingQuestion}
            clearPending={() => setPendingQuestion("")}
          />
          <Upload
            hidden={view !== "upload"}
            domains={domains}
            activeDomain={domain}
            onFinished={(id, open) =>
              loadDomains(id)
                .then(() => (open || id !== domain ? loadDomain(id) : null))
                .then(() => {
                  if (open) setView("dashboard");
                })
            }
            onSkip={() => setView("dashboard")}
          />
        </div>
      </div>
    </div>
  );
}
