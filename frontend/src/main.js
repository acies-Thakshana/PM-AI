/* Live dashboard for the AI4BI backend (FastAPI).
 *
 * Talks to:  GET /api/info, GET /api/domains, GET /api/domains/{d}, POST /api/ask,
 *            POST /api/domains/{d}/datasets, POST /api/domains/{d}/onboard, GET /api/jobs/{id}
 * The dashboard has no stored answers of its own: it runs the domain's starter questions and shows
 * the results, so the numbers always come from the connected tables.
 */
import "./style.css";

(function () {
  // Empty in dev: Vite proxies /api to the backend (see vite.config.js). Set VITE_API_BASE to point elsewhere.
  var API = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");
  var DASHBOARD_QUESTIONS = 4;
  var STEPS = [
    "Understanding the question",
    "Matching tables and columns",
    "Writing the query",
    "Running it on the connected tables",
    "Writing the answer"
  ];

  var state = {
    domains: [],
    domain: "",
    detail: null,
    dashboard: { kpis: [], charts: [], answers: [] },
    sessionId: "web-" + Math.random().toString(36).slice(2, 10),
    dashboardRun: 0
  };

  var chat = document.getElementById("chat");
  var composer = document.getElementById("composer");
  var followInput = document.getElementById("follow-input");
  var recentList = document.getElementById("recent");
  var tableList = document.getElementById("tables");
  var columnList = document.getElementById("columns");
  var statusFoot = document.getElementById("status-foot");
  var domainSelect = document.getElementById("domain-select");
  var history = [];
  var recent = [];
  var busy = false;
  var started = false;

  var pageTitle = document.querySelector(".topbar-title");
  var pageSubtitle = document.querySelector(".topbar-subtitle");
  var productTag = document.querySelector(".product-tag");
  var brandLogo = document.querySelector(".workspace-logo");
  ["dash-logo", "side-logo"].forEach(function (id) {
    var node = document.getElementById(id);
    if (node && brandLogo) node.src = brandLogo.src;
  });

  // ---------------------------------------------------------------- helpers

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function setStatus(text) {
    if (statusFoot) statusFoot.textContent = text;
  }

  function pretty(name) {
    var text = String(name || "").replace(/[_\-.]+/g, " ").trim();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  function domainLabel() {
    return state.domain ? pretty(state.domain) : "No domain";
  }

  function number(value) {
    var n = Number(value);
    return isFinite(n) ? n : null;
  }

  function formatValue(value, unit) {
    if (value == null || value === "") return "—";
    var n = number(value);
    if (n == null) return String(value);
    var text;
    if (unit === "percent" || unit === "%") {
      if (Math.abs(n) <= 1) n = n * 100;
      return n.toLocaleString(undefined, { maximumFractionDigits: 1 }) + "%";
    }
    if (unit === "usd" || unit === "$" || unit === "currency") {
      return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
    }
    text = n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return unit ? text + " " + unit : text;
  }

  function fetchJson(path, options, timeoutMs) {
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, timeoutMs || 120000) : null;
    var opts = options || {};
    if (controller) opts.signal = controller.signal;
    return fetch(API + path, opts).then(function (response) {
      if (timer) clearTimeout(timer);
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var err = data && data.error;
          var message = (err && err.message) || (data && data.detail) || "The backend returned " + response.status;
          if (err && err.details && err.details.length) {
            message += " (" + err.details.map(function (d) { return d.field + ": " + d.message; }).join("; ") + ")";
          }
          throw new Error(message);
        }
        return data;
      });
    }).catch(function (error) {
      if (timer) clearTimeout(timer);
      if (error && error.name === "AbortError") throw new Error("The backend did not answer in time.");
      if (error instanceof TypeError) {
        throw new Error("Cannot reach the backend at " + (API || window.location.origin) + ". Is it running?");
      }
      throw error;
    });
  }

  function postJson(path, body, timeoutMs) {
    return fetchJson(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    }, timeoutMs);
  }

  // ---------------------------------------------------------------- views

  function showView(name) {
    var views = { dashboard: "dashboard", ask: "ask-view", upload: "upload-view" };
    Object.keys(views).forEach(function (key) {
      var node = document.getElementById(views[key]);
      if (node) node.hidden = key !== name;
    });
    document.querySelectorAll("[data-view]").forEach(function (button) {
      button.classList.toggle("active", button.getAttribute("data-view") === name);
    });
    var fresh = document.getElementById("new-chat");
    if (fresh) fresh.hidden = name !== "ask";
    var titles = { dashboard: "Dashboard", ask: "Ask Questions", upload: "Upload Data" };
    var subtitles = { dashboard: domainLabel(), ask: "Business analyst copilot", upload: "Add datasets and onboard them" };
    if (pageTitle) pageTitle.textContent = titles[name];
    if (pageSubtitle) pageSubtitle.textContent = subtitles[name];
    if (productTag) productTag.textContent = titles[name].split(" ")[0] + " · " + domainLabel();
    if (name === "ask" && composer && !composer.hidden && followInput) followInput.focus();
  }

  function applyChrome() {
    var chip = document.querySelector(".dataset-chip strong");
    if (chip) chip.textContent = domainLabel();
    var heading = document.querySelector(".dash-head h1");
    if (heading) heading.textContent = domainLabel();
    var lede = document.querySelector(".dash-lede");
    if (lede) {
      var d = state.detail;
      lede.textContent = d
        ? d.tables.length + " table(s), " + d.counts.metrics + " certified metric(s). Figures below come from this domain's starter questions."
        : "Pick or upload a domain to begin.";
    }
  }

  // ---------------------------------------------------------------- rendering

  function renderBars(host, items, unit) {
    host.innerHTML = "";
    var rows = items || [];
    if (!rows.length) {
      host.appendChild(el("p", "dash-note", "No grouped values."));
      return;
    }
    var max = 0;
    rows.forEach(function (item) { max = Math.max(max, Math.abs(number(item.value) || 0)); });
    var wrap = el("div", "bars");
    rows.forEach(function (item) {
      var row = el("div", "bar-row");
      row.appendChild(el("span", null, item.label));
      var track = el("div", "track");
      var fill = el("div", "fill");
      fill.style.width = (max ? Math.max(4, (Math.abs(number(item.value) || 0) / max) * 100) : 0) + "%";
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("span", "bar-value", formatValue(item.value, unit)));
      wrap.appendChild(row);
    });
    host.appendChild(wrap);
  }

  function renderTable(host, columns, rows) {
    host.innerHTML = "";
    var wrap = el("div", "table-wrap");
    var table = document.createElement("table");
    var thead = document.createElement("thead");
    var head = document.createElement("tr");
    (columns || []).forEach(function (column) { head.appendChild(el("th", null, column)); });
    thead.appendChild(head);
    table.appendChild(thead);
    var body = document.createElement("tbody");
    (rows || []).forEach(function (record) {
      var tr = document.createElement("tr");
      (columns || []).forEach(function (column) {
        var value = record[column];
        tr.appendChild(el("td", null, value == null ? "" : String(value)));
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    host.appendChild(wrap);
  }

  function renderViz(host, viz) {
    host.innerHTML = "";
    if (!viz || viz.kind === "empty") {
      host.appendChild(el("p", "dash-note", (viz && viz.note) || "No chart for this answer."));
    } else if (viz.kind === "number") {
      var row = el("div", "part-row");
      row.appendChild(el("span", null, viz.label || "Value"));
      row.appendChild(el("strong", "viz-number", formatValue(viz.value, viz.unit)));
      host.appendChild(row);
    } else if (viz.kind === "bars") {
      renderBars(host, viz.items, viz.unit);
    } else if (viz.kind === "table") {
      renderTable(host, viz.columns, viz.rows);
    }
  }

  function answerCard(data) {
    var card = el("article", "answer");
    if (data.question) card.appendChild(el("h3", null, data.question));
    var head = el("div", "answer-head");
    if (data.pathLabel) head.appendChild(el("span", "badge " + (data.ok ? "ok" : "warn"), data.pathLabel));
    if (data.confidence != null && data.confidence !== "") {
      var score = Number(data.confidence);
      head.appendChild(el("span", "badge " + (score >= 0.7 ? "ok" : "warn"), "Confidence " + Math.round(score * 100) + "%"));
    }
    if (head.childNodes.length) card.appendChild(head);
    card.appendChild(el("p", "section-label", "Explanation"));
    card.appendChild(el("p", "summary-text", data.explanation || ""));
    if (data.warnings && data.warnings.length) {
      var list = el("ul", "warn-list");
      data.warnings.forEach(function (w) { list.appendChild(el("li", null, w)); });
      card.appendChild(list);
    }
    card.appendChild(el("p", "section-label", "Visualization"));
    var vizHost = el("div", "viz-block");
    renderViz(vizHost, data.viz);
    card.appendChild(vizHost);
    card.appendChild(el("p", "section-label", "Reasoning"));
    card.appendChild(el("p", "reasoning-prose", data.reasoning || ""));
    card.appendChild(el("p", "section-label", "SQL"));
    card.appendChild(el("pre", "sql", data.sql || "No SQL was produced for this answer."));
    return card;
  }

  function renderDashboard() {
    applyChrome();
    var kpis = document.getElementById("dash-kpis");
    var charts = document.getElementById("dash-charts");
    var answers = document.getElementById("dash-answers");
    if (!kpis || !charts || !answers) return;
    kpis.innerHTML = "";
    charts.innerHTML = "";
    answers.innerHTML = "";
    var dash = state.dashboard;
    if (!dash.kpis.length && !dash.charts.length && !dash.answers.length) {
      kpis.appendChild(el("p", "dash-note", state.domain ? "Running this domain's starter questions…" : "No domain selected."));
    }
    dash.kpis.forEach(function (kpi) {
      var card = el("article", "kpi-card");
      card.appendChild(el("span", null, kpi.label));
      card.appendChild(el("strong", null, formatValue(kpi.value, kpi.unit)));
      if (kpi.note) card.appendChild(el("em", null, kpi.note));
      kpis.appendChild(card);
    });
    dash.charts.forEach(function (chart) {
      var article = el("article", "dash-card");
      article.appendChild(el("h2", null, chart.title));
      if (chart.note) article.appendChild(el("p", "dash-note", chart.note));
      var host = el("div");
      renderBars(host, chart.items, chart.unit);
      article.appendChild(host);
      charts.appendChild(article);
    });
    dash.answers.forEach(function (item) { answers.appendChild(answerCard(item)); });
  }

  function renderTables() {
    if (!tableList || !columnList) return;
    tableList.innerHTML = "";
    columnList.innerHTML = "";
    var tables = (state.detail && state.detail.tables) || [];
    if (!tables.length) tableList.appendChild(el("li", null, "No tables yet"));
    tables.forEach(function (table) {
      var item = el("li");
      item.appendChild(document.createTextNode(table.name));
      item.appendChild(el("span", null, String(table.rows)));
      tableList.appendChild(item);
    });
    var shown = 0;
    tables.forEach(function (table) {
      table.columns.forEach(function (column) {
        if (shown >= 40) return;
        var label = table.name + "." + column.name + (column.restricted ? " (restricted)" : "");
        columnList.appendChild(el("li", null, label));
        shown += 1;
      });
    });
    if (!shown) columnList.appendChild(el("li", null, "Columns appear after the tables load"));
  }

  function renderDomainSelect() {
    if (domainSelect) {
      domainSelect.innerHTML = "";
      state.domains.forEach(function (d) {
        var option = el("option", null, d.id);
        option.value = d.id;
        if (d.id === state.domain) option.selected = true;
        domainSelect.appendChild(option);
      });
      if (!state.domains.length) domainSelect.appendChild(el("option", null, "No domains"));
    }
    var options = document.getElementById("domain-options");
    if (options) {
      options.innerHTML = "";
      state.domains.forEach(function (d) {
        var option = document.createElement("option");
        option.value = d.id;
        options.appendChild(option);
      });
    }
  }

  function renderRecent() {
    if (!recentList) return;
    recentList.innerHTML = "";
    if (!recent.length) {
      var empty = document.createElement("li");
      empty.appendChild(el("p", "sidebar-empty", "Questions you ask show up here."));
      recentList.appendChild(empty);
      return;
    }
    recent.forEach(function (text) {
      var item = document.createElement("li");
      var button = el("button", null, text);
      button.type = "button";
      button.addEventListener("click", function () { ask(text); });
      item.appendChild(button);
      recentList.appendChild(item);
    });
  }

  function renderEmpty() {
    if (!chat || !composer) return;
    started = false;
    history = [];
    chat.classList.add("chat-empty-mode");
    chat.innerHTML = "";
    composer.hidden = true;
    var box = el("div", "claude-empty");
    box.appendChild(el("h2", null, "Ask " + domainLabel()));
    box.appendChild(el("p", null, "Questions run on the tables in this domain. Each answer includes an explanation, a chart, the reasoning, and the SQL."));
    var form = el("form", "hero-composer");
    var area = document.createElement("textarea");
    area.rows = 3;
    area.placeholder = "Ask a question about the connected tables…";
    var bar = el("div", "hero-composer-bar");
    var button = el("button", null, "↑");
    button.type = "submit";
    bar.appendChild(button);
    form.appendChild(area);
    form.appendChild(bar);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      ask(area.value);
    });
    area.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        ask(area.value);
      }
    });
    box.appendChild(form);
    var pills = el("div", "suggestion-pills");
    dashboardQuestions().forEach(function (text) {
      var pill = el("button", "sug-pill", text);
      pill.type = "button";
      pill.addEventListener("click", function () { ask(text); });
      pills.appendChild(pill);
    });
    box.appendChild(pills);
    chat.appendChild(box);
  }

  function thinkingCard() {
    var card = el("article", "answer thinking");
    var list = el("ul", "scratchpad-list");
    STEPS.forEach(function (label, index) {
      var item = el("li", "scratch-step" + (index === 0 ? " status-running" : ""));
      item.appendChild(el("span", "scratch-mark", index === 0 ? "…" : "·"));
      item.appendChild(el("span", "scratch-label", " " + label));
      list.appendChild(item);
    });
    card.appendChild(list);
    var step = 0;
    var timer = setInterval(function () {
      var items = list.children;
      if (step < items.length) {
        items[step].className = "scratch-step status-done";
        items[step].querySelector(".scratch-mark").textContent = "✓";
      }
      step += 1;
      if (step < items.length) {
        items[step].className = "scratch-step status-running";
        items[step].querySelector(".scratch-mark").textContent = "…";
      } else {
        clearInterval(timer);
      }
    }, 500);
    card._stop = function () { clearInterval(timer); };
    return card;
  }

  function beginThread() {
    if (!chat || !composer || started) return;
    started = true;
    chat.classList.remove("chat-empty-mode");
    chat.innerHTML = "";
    composer.hidden = false;
  }

  // ---------------------------------------------------------------- backend -> view model

  /** Turn one /api/ask response into what the answer card and dashboard need. */
  function toView(question, data) {
    var chart = data.chart || {};
    var table = data.table || { columns: [], rows: [] };
    var viz = { kind: "empty", note: "No chart for this answer." };
    var y = (chart.y && chart.y[0]) || null;
    var unit = chart.unit || "";
    if (chart.template === "kpi_card" && chart.value != null) {
      viz = { kind: "number", label: chart.title || "Value", value: chart.value, unit: unit };
    } else if (chart.x && y && (chart.data || []).length && !chart.series) {
      viz = {
        kind: "bars",
        unit: unit,
        items: chart.data.slice(0, 30).map(function (row) { return { label: String(row[chart.x]), value: row[y] }; })
      };
    } else if (table.rows && table.rows.length) {
      viz = { kind: "table", columns: table.columns, rows: table.rows };
    }
    var findings = (data.key_findings || []).filter(function (f) { return f && data.answer.indexOf(f) < 0; });
    var reasoning = [];
    if (data.interpreted_question) reasoning.push("Interpreted as: " + data.interpreted_question);
    if (data.sql_rationale) reasoning.push(data.sql_rationale);
    var exp = data.explainability || {};
    if (exp.applied_filters && Object.keys(exp.applied_filters).length) {
      reasoning.push("Filters: " + Object.keys(exp.applied_filters).map(function (k) {
        return k + " = " + [].concat(exp.applied_filters[k]).join(", ");
      }).join("; "));
    }
    if (data.datasets_used && data.datasets_used.length) reasoning.push("Tables used: " + data.datasets_used.join(", "));
    return {
      question: question,
      ok: data.status === "success",
      explanation: [data.answer].concat(findings).join("\n"),
      reasoning: reasoning.join("\n"),
      sql: data.sql_query,
      viz: viz,
      confidence: data.confidence,
      warnings: data.warnings || [],
      pathLabel: data.answer_path === "llm" ? "Model-assisted" : "Deterministic planner",
      chart: chart,
      status: data.status
    };
  }

  function askBackend(question, useSession) {
    var body = { question: question, domain: state.domain };
    if (useSession) body.session_id = state.sessionId;
    return postJson("/api/ask", body, 120000).then(function (data) { return toView(question, data); });
  }

  // ---------------------------------------------------------------- ask view

  function ask(text) {
    var question = String(text || "").trim();
    if (!question || busy || !chat) return;
    if (!state.domain) {
      showView("upload");
      return;
    }
    showView("ask");
    beginThread();
    busy = true;
    chat.appendChild(el("div", "bubble user", question));
    var pending = thinkingCard();
    chat.appendChild(pending);
    chat.scrollTop = chat.scrollHeight;
    history.push({ role: "user", content: question });
    recent.unshift(question);
    recent = recent.filter(function (q, i) { return recent.indexOf(q) === i; }).slice(0, 8);
    renderRecent();
    askBackend(question, true).then(function (view) {
      if (pending._stop) pending._stop();
      pending.replaceWith(answerCard(view));
      history.push({ role: "assistant", content: view.explanation });
    }).catch(function (error) {
      if (pending._stop) pending._stop();
      pending.replaceWith(el("div", "bubble error", error.message || String(error)));
    }).then(function () {
      busy = false;
      chat.scrollTop = chat.scrollHeight;
    });
  }

  // ---------------------------------------------------------------- dashboard

  /** Questions to run for the dashboard: the domain's own, else simple ones built from its columns. */
  function dashboardQuestions() {
    var detail = state.detail || {};
    var own = (detail.starter_questions || []).slice(0, DASHBOARD_QUESTIONS);
    if (own.length) return own;
    var out = [];
    (detail.tables || []).forEach(function (table) {
      var measures = table.columns.filter(function (c) {
        return !c.restricted && /int|float/.test(c.dtype) && c.role !== "key" && c.role !== "foreign_key" && !/id$/i.test(c.name);
      });
      var dims = table.columns.filter(function (c) {
        return !c.restricted && c.dtype === "object" && c.role !== "key" && c.role !== "foreign_key" && c.role !== "timestamp";
      });
      measures.slice(0, 2).forEach(function (m) {
        var label = String(m.name).replace(/_/g, " ");
        out.push("What is the total " + label + "?");
        if (dims.length) out.push("What is the total " + label + " by " + String(dims[0].name).replace(/_/g, " ") + "?");
      });
    });
    return out.slice(0, DASHBOARD_QUESTIONS);
  }

  function runDashboard() {
    var run = ++state.dashboardRun;
    state.dashboard = { kpis: [], charts: [], answers: [] };
    renderDashboard();
    var questions = dashboardQuestions();
    if (!questions.length) {
      var kpis = document.getElementById("dash-kpis");
      if (kpis) {
        kpis.innerHTML = "";
        kpis.appendChild(el("p", "dash-note", "This domain has no starter questions yet. Run onboarding from Upload data, or ask a question."));
      }
      return Promise.resolve();
    }
    // One at a time: the backend builds the domain's data once and caches it.
    return questions.reduce(function (chain, question) {
      return chain.then(function () {
        if (run !== state.dashboardRun) return null;
        return askBackend(question, false).then(function (view) {
          if (run !== state.dashboardRun) return;
          var c = view.chart || {};
          if (view.ok && view.viz.kind === "number") {
            state.dashboard.kpis.push({ label: view.viz.label, value: view.viz.value, unit: view.viz.unit, note: question });
          } else if (view.ok && view.viz.kind === "bars") {
            state.dashboard.charts.push({ title: c.title || question, note: question, items: view.viz.items, unit: view.viz.unit });
          }
          state.dashboard.answers.push(view);
          renderDashboard();
        }).catch(function () { /* one failing question must not blank the dashboard */ });
      });
    }, Promise.resolve());
  }

  // ---------------------------------------------------------------- domains

  function loadDomains(preferred) {
    return fetchJson("/api/domains", { method: "GET" }, 30000).then(function (list) {
      state.domains = list || [];
      if (preferred && state.domains.some(function (d) { return d.id === preferred; })) {
        state.domain = preferred;
      } else if (!state.domains.some(function (d) { return d.id === state.domain; })) {
        state.domain = state.domains.length ? state.domains[0].id : "";
      }
      renderDomainSelect();
    });
  }

  function loadDomain(domain) {
    state.domain = domain || "";
    state.detail = null;
    renderTables();
    applyChrome();
    renderRecent();
    if (!state.domain) {
      setStatus("No domains yet. Use Upload data.");
      renderDashboard();
      renderEmpty();
      return Promise.resolve();
    }
    setStatus("Loading " + state.domain + "…");
    return fetchJson("/api/domains/" + encodeURIComponent(state.domain), { method: "GET" }, 60000).then(function (detail) {
      state.detail = detail;
      setStatus(detail.tables.length + " table(s) · " + (detail.has_baseline_package ? "baseline package" : "inferred package"));
      renderTables();
      applyChrome();
      renderEmpty();
      return runDashboard();
    }).catch(function (error) {
      setStatus(error.message || String(error));
      var kpis = document.getElementById("dash-kpis");
      if (kpis) {
        kpis.innerHTML = "";
        kpis.appendChild(el("p", "dash-note", error.message || String(error)));
      }
    });
  }

  // ---------------------------------------------------------------- upload view

  var uploadForm = document.getElementById("upload-form");
  var uploadResults = document.getElementById("upload-results");
  var onboardButton = document.getElementById("onboard-run");
  var onboardStatus = document.getElementById("onboard-status");
  var onboardResult = document.getElementById("onboard-result");
  var uploadedDomain = "";

  function resultLine(ok, text) {
    var item = el("li", ok ? "ok" : "bad", text);
    uploadResults.appendChild(item);
  }

  function uploadOne(domain, file) {
    var form = new FormData();
    form.append("file", file);
    return fetchJson("/api/domains/" + encodeURIComponent(domain) + "/datasets", { method: "POST", body: form }, 300000);
  }

  if (uploadForm) {
    uploadForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var domain = document.getElementById("upload-domain").value.trim().toLowerCase();
      var input = document.getElementById("upload-files");
      var files = Array.prototype.slice.call(input.files || []);
      if (!domain || !files.length) return;
      var submit = document.getElementById("upload-submit");
      submit.disabled = true;
      uploadResults.innerHTML = "";
      onboardResult.hidden = true;
      onboardStatus.textContent = "";
      var uploaded = 0;
      files.reduce(function (chain, file) {
        return chain.then(function () {
          return uploadOne(domain, file).then(function (info) {
            uploaded += 1;
            resultLine(true, file.name + " → table " + info.table + " (" + info.rows + " rows, " + info.columns.length + " columns)");
          }).catch(function (error) {
            resultLine(false, file.name + ": " + (error.message || error));
          });
        });
      }, Promise.resolve()).then(function () {
        submit.disabled = false;
        if (!uploaded) return;
        uploadedDomain = domain;
        onboardButton.disabled = false;
        input.value = "";
        onboardStatus.textContent = "Uploaded to " + domain + ". Run onboarding to learn its metrics and joins, or open the dashboard now.";
        return loadDomains(domain).then(function () { return loadDomain(domain); });
      });
    });
  }

  function pollJob(jobId) {
    return fetchJson("/api/jobs/" + encodeURIComponent(jobId), { method: "GET" }, 30000).then(function (job) {
      onboardStatus.textContent = "Onboarding " + uploadedDomain + ": " + job.status + "…";
      if (job.status === "queued" || job.status === "running") {
        return new Promise(function (resolve) { setTimeout(resolve, 1500); }).then(function () { return pollJob(jobId); });
      }
      return job;
    });
  }

  if (onboardButton) {
    onboardButton.addEventListener("click", function () {
      if (!uploadedDomain) return;
      onboardButton.disabled = true;
      onboardResult.hidden = true;
      onboardStatus.textContent = "Starting onboarding for " + uploadedDomain + "…";
      postJson("/api/domains/" + encodeURIComponent(uploadedDomain) + "/onboard", { force: false }, 30000)
        .then(function (job) { return pollJob(job.job_id); })
        .then(function (job) {
          if (job.status === "succeeded") {
            onboardStatus.textContent = "Onboarding finished for " + uploadedDomain + ".";
            onboardResult.textContent = JSON.stringify(job.result, null, 2);
            onboardResult.hidden = false;
            return loadDomain(uploadedDomain);
          }
          onboardStatus.textContent = "Onboarding failed: " + (job.error || "unknown error");
        })
        .catch(function (error) { onboardStatus.textContent = error.message || String(error); })
        .then(function () { onboardButton.disabled = false; });
    });
  }

  // ---------------------------------------------------------------- wiring

  document.querySelectorAll("[data-view]").forEach(function (button) {
    button.addEventListener("click", function () { showView(button.getAttribute("data-view")); });
  });
  var openAsk = document.getElementById("open-ask");
  if (openAsk) openAsk.addEventListener("click", function () { showView("ask"); });
  var fresh = document.getElementById("new-chat");
  if (fresh) fresh.addEventListener("click", function () { state.sessionId = "web-" + Math.random().toString(36).slice(2, 10); renderEmpty(); });
  if (composer) {
    composer.addEventListener("submit", function (event) {
      event.preventDefault();
      var value = followInput ? followInput.value : "";
      if (followInput) followInput.value = "";
      ask(value);
    });
  }
  if (domainSelect) {
    domainSelect.addEventListener("change", function () {
      renderEmpty();
      loadDomain(domainSelect.value);
    });
  }

  applyChrome();
  showView("dashboard");
  renderEmpty();
  renderRecent();
  setStatus("Connecting to the backend…");

  fetchJson("/api/info", { method: "GET" }, 15000).then(function (info) {
    return loadDomains(info.default_domain).then(function () { return loadDomain(state.domain); });
  }).catch(function (error) {
    setStatus(error.message || String(error));
    var kpis = document.getElementById("dash-kpis");
    if (kpis) {
      kpis.innerHTML = "";
      kpis.appendChild(el("p", "dash-note", error.message || String(error)));
    }
  });
})();
