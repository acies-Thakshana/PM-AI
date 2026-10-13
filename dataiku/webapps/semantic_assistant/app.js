(function () {
  var SUGGESTIONS = [
    { title: "Closed-won total", prompt: "What is the total value of closed-won opportunities?", icon: "Σ" },
    { title: "Won by region", prompt: "Give me the split of closed-won opportunity amount across regions.", icon: "▦" },
    { title: "Late deliveries", prompt: "Which carrier has the most late deliveries?", icon: "↑" },
    { title: "In transit", prompt: "What share of shipments are still in transit?", icon: "%" }
  ];
  var STEPS = [
    "Understanding the question",
    "Matching tables and columns",
    "Writing the query",
    "Running it on the cold-chain data",
    "Writing the answer"
  ];

  var chat = document.getElementById("chat");
  var composer = document.getElementById("composer");
  var followInput = document.getElementById("follow-input");
  var recentList = document.getElementById("recent");
  var tableList = document.getElementById("tables");
  var statusFoot = document.getElementById("status-foot");
  var history = [];
  var recent = [];
  var busy = false;
  var started = false;
  var pageTitle = document.querySelector(".topbar-title");
  var pageSubtitle = document.querySelector(".topbar-subtitle");
  var productTag = document.querySelector(".product-tag");
  var dashLogo = document.getElementById("dash-logo");
  var brandLogo = document.querySelector(".workspace-logo");
  if (dashLogo && brandLogo) dashLogo.src = brandLogo.src;

  function url(path) {
    if (typeof getWebAppBackendUrl === "function") return getWebAppBackendUrl(path);
    return path;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function scrollChat() {
    chat.scrollTop = chat.scrollHeight;
  }

  function showView(name) {
    document.getElementById("dashboard").hidden = name !== "dashboard";
    document.getElementById("ask-view").hidden = name !== "ask";
    document.querySelectorAll("[data-view]").forEach(function (button) {
      button.classList.toggle("active", button.getAttribute("data-view") === name);
    });
    document.getElementById("new-chat").hidden = name !== "ask";
    if (name === "dashboard") {
      pageTitle.textContent = "Dashboard";
      pageSubtitle.textContent = "Cold chain overview";
      productTag.textContent = "Dashboard · Cold chain";
    } else {
      pageTitle.textContent = "Ask Questions";
      pageSubtitle.textContent = "Business analyst copilot";
      productTag.textContent = "Ask · Cold chain";
      if (!composer.hidden) followInput.focus();
    }
  }

  function money(value) {
    if (value == null || value === "") return "—";
    return "$" + Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  function count(value) {
    if (value == null || value === "") return "—";
    return Number(value).toLocaleString();
  }

  function kpiCard(label, value, note) {
    var card = el("article", "kpi-card");
    card.appendChild(el("span", null, label));
    card.appendChild(el("strong", null, value));
    card.appendChild(el("em", null, note));
    return card;
  }

  function bars(target, items, valueKey, format) {
    target.innerHTML = "";
    if (!items.length) {
      target.appendChild(el("p", "dash-note", "No figures yet."));
      return;
    }
    var max = 1;
    items.forEach(function (item) {
      max = Math.max(max, Number(item[valueKey]) || 0);
    });
    items.forEach(function (item) {
      var row = el("div", "bar-row");
      row.appendChild(el("span", null, item.label));
      var track = el("div", "track");
      var fill = el("div", "fill");
      fill.style.width = (100 * (Number(item[valueKey]) || 0) / max) + "%";
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("span", "bar-value", format(item[valueKey])));
      target.appendChild(row);
    });
  }

  function renderDashboard(data) {
    var kpis = data.kpis || {};
    var host = document.getElementById("dash-kpis");
    host.innerHTML = "";
    host.appendChild(kpiCard("Closed-won", money(kpis.won_amount), "Won opportunity amount"));
    host.appendChild(kpiCard("In transit", kpis.in_transit_pct == null ? "—" : kpis.in_transit_pct + "%", count(kpis.shipments) + " shipments in total"));
    host.appendChild(kpiCard("Open critical alerts", count(kpis.unresolved_critical), count(kpis.excursions) + " temperature excursions"));
    host.appendChild(kpiCard("Accounts", count(kpis.accounts), count(kpis.opportunities) + " opportunities · " + count(kpis.service_cases) + " cases"));
    bars(document.getElementById("dash-regions"), data.won_by_region || [], "amount", money);
    bars(document.getElementById("dash-status"), data.shipment_status || [], "count", count);

    var csatHost = document.getElementById("dash-csat");
    csatHost.innerHTML = "";
    var table = document.createElement("table");
    table.className = "csat-table";
    var head = document.createElement("tr");
    ["Entitlement", "Average score", "Scored cases"].forEach(function (label) {
      head.appendChild(el("th", null, label));
    });
    table.appendChild(head);
    (data.csat || []).forEach(function (row) {
      var line = document.createElement("tr");
      line.appendChild(el("td", null, row.entitlement));
      line.appendChild(el("td", "csat-score", Number(row.avg_csat).toFixed(2)));
      line.appendChild(el("td", null, count(row.scored_cases)));
      table.appendChild(line);
    });
    if (!(data.csat || []).length) {
      csatHost.appendChild(el("p", "dash-note", "No scored cases yet."));
    } else {
      csatHost.appendChild(table);
    }

    var readout = document.getElementById("dash-readout");
    readout.innerHTML = "";
    var topRegion = (data.won_by_region || [])[0];
    var topCsat = (data.csat || [])[0];
    var lines = [];
    if (kpis.won_amount != null) lines.push("Closed-won opportunities add up to " + money(kpis.won_amount) + ".");
    if (topRegion) lines.push(topRegion.label + " leads won revenue at " + money(topRegion.amount) + ".");
    if (kpis.in_transit_pct != null) lines.push(kpis.in_transit_pct + "% of shipments are still in transit.");
    if (kpis.unresolved_critical != null) lines.push(count(kpis.unresolved_critical) + " critical temperature excursions are still open.");
    if (topCsat) lines.push(topCsat.entitlement + " has the highest support score at " + Number(topCsat.avg_csat).toFixed(2) + ".");
    if (!lines.length) lines.push("Figures will appear once the project tables are connected.");
    lines.forEach(function (line) {
      readout.appendChild(el("li", null, line));
    });
  }

  function renderEmpty() {
    chat.className = "chat chat-empty-mode";
    chat.innerHTML = "";
    composer.hidden = true;
    var wrap = el("div", "claude-empty");
    wrap.appendChild(el("div", "hero-ring"));
    wrap.appendChild(el("h2", null, "Ready to analyze the cold-chain tables"));
    wrap.appendChild(el("p", null, "Ask in plain English. The answer is grounded in SQL across accounts, opportunities, shipments, excursions, and service cases."));
    var form = el("form", "hero-composer");
    var area = document.createElement("textarea");
    area.rows = 2;
    area.placeholder = "Ask a question about the cold-chain data…";
    area.setAttribute("aria-label", "Question");
    var bar = el("div", "hero-composer-bar");
    var pills = el("div", "mode-pills");
    ["Ask", "SQL", "Reason"].forEach(function (name, index) {
      pills.appendChild(el("span", "mode-pill" + (index === 0 ? " active" : ""), name));
    });
    var send = el("button", null, "↑");
    send.type = "submit";
    bar.appendChild(pills);
    bar.appendChild(send);
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
    var sugg = el("div", "suggestion-pills");
    SUGGESTIONS.forEach(function (item) {
      var button = el("button", "sug-pill");
      button.type = "button";
      button.appendChild(el("span", "sug-ico", item.icon));
      button.appendChild(document.createTextNode(item.title));
      button.addEventListener("click", function () { ask(item.prompt); });
      sugg.appendChild(button);
    });
    wrap.appendChild(form);
    wrap.appendChild(sugg);
    chat.appendChild(wrap);
  }

  function ensureThread() {
    if (started) return;
    started = true;
    chat.className = "chat";
    chat.innerHTML = "";
    composer.hidden = false;
  }

  function renderRecent() {
    recentList.innerHTML = "";
    if (!recent.length) {
      recentList.appendChild(el("p", "sidebar-empty", "No conversations yet"));
      return;
    }
    recent.slice().reverse().forEach(function (question) {
      var item = el("li");
      var button = el("button", null, question);
      button.type = "button";
      button.addEventListener("click", function () { ask(question); });
      item.appendChild(button);
      recentList.appendChild(item);
    });
  }

  function thinkingNode() {
    var box = el("div", "thinking thinking-live");
    var steps = STEPS.map(function (label, index) {
      return { label: label, status: index === 0 ? "running" : "pending" };
    });
    var open = true;
    var toggle = el("button", "thinking-toggle");
    toggle.type = "button";
    var body = el("div", "thinking-body");
    function paint() {
      var current = "Thinking";
      steps.forEach(function (step) {
        if (step.status === "running") current = step.label;
      });
      toggle.innerHTML = "";
      toggle.appendChild(el("span", "thinking-chevron" + (open ? " open" : ""), "▸"));
      var summary = el("span", "thinking-summary");
      summary.appendChild(el("span", "thinking-dot"));
      summary.appendChild(document.createTextNode(current + "…"));
      toggle.appendChild(summary);
      body.innerHTML = "";
      var list = el("ol", "scratchpad-list");
      steps.forEach(function (step) {
        var row = el("li", "scratch-step status-" + step.status);
        var mark = step.status === "done" ? "✓" : step.status === "running" ? "…" : "○";
        row.appendChild(el("span", "scratch-mark", mark));
        row.appendChild(el("span", "scratch-label", step.label));
        list.appendChild(row);
      });
      body.appendChild(list);
      body.hidden = !open;
    }
    toggle.addEventListener("click", function () {
      open = !open;
      paint();
    });
    var timer = window.setInterval(function () {
      var running = -1;
      steps.forEach(function (step, index) {
        if (step.status === "running") running = index;
      });
      if (running >= 0 && running < steps.length - 1) {
        steps[running].status = "done";
        steps[running + 1].status = "running";
        paint();
      }
    }, 700);
    box.appendChild(toggle);
    box.appendChild(body);
    paint();
    box.stop = function () { window.clearInterval(timer); };
    return box;
  }

  function formatCell(value) {
    if (value == null || value === "") return "";
    if (typeof value === "number") {
      return Number.isInteger(value) ? String(value) : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return String(value);
  }

  function downloadCsv(payload) {
    function escape(value) {
      var text = formatCell(value);
      if (/[",\n]/.test(text)) return '"' + text.replace(/"/g, '""') + '"';
      return text;
    }
    var lines = [payload.columns.map(escape).join(",")];
    (payload.rows || []).forEach(function (row) {
      lines.push(payload.columns.map(function (column) { return escape(row[column]); }).join(","));
    });
    var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "nl2sql-result.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  function answerCard(payload) {
    var failed = payload.error || payload.row_count === 0;
    var card = el("article", "answer" + (payload.error ? " invalid" : ""));
    var head = el("div", "answer-head");
    head.appendChild(el("span", "badge " + (payload.error ? "bad" : failed ? "warn" : "ok"), payload.error ? "Could not answer" : failed ? "No matching data" : "Grounded answer"));
    var meta = [];
    if (payload.row_count != null) meta.push(payload.row_count + " row" + (payload.row_count === 1 ? "" : "s"));
    if (payload.latency_seconds != null) meta.push(payload.latency_seconds + "s");
    if (payload.confidence != null) meta.push("confidence " + Number(payload.confidence).toFixed(2));
    head.appendChild(el("span", "meta-text", meta.join(" · ")));
    card.appendChild(head);
    card.appendChild(el("p", "summary-text", payload.answer || payload.error || "No answer."));

    if (payload.columns && payload.rows && payload.rows.length) {
      var block = el("section", "block");
      var blockHead = el("div", "block-head");
      blockHead.appendChild(el("h3", null, "Data"));
      var download = el("button", "link-btn", "Download CSV");
      download.type = "button";
      download.addEventListener("click", function () { downloadCsv(payload); });
      blockHead.appendChild(download);
      block.appendChild(blockHead);
      var wrap = el("div", "table-wrap");
      var table = document.createElement("table");
      var thead = document.createElement("thead");
      var hr = document.createElement("tr");
      payload.columns.forEach(function (column) { hr.appendChild(el("th", null, column)); });
      thead.appendChild(hr);
      var tbody = document.createElement("tbody");
      payload.rows.slice(0, 25).forEach(function (row) {
        var line = document.createElement("tr");
        payload.columns.forEach(function (column) {
          line.appendChild(el("td", null, formatCell(row[column])));
        });
        tbody.appendChild(line);
      });
      table.appendChild(thead);
      table.appendChild(tbody);
      wrap.appendChild(table);
      block.appendChild(wrap);
      card.appendChild(block);
    }

    var panel = el("section", "detail-panel");
    var tabs = el("div", "tabs");
    var sqlPanel = el("div", "tab-panel");
    var reasonPanel = el("div", "tab-panel");
    var sqlPre = el("pre", "sql", payload.sql || "No SQL for this answer.");
    sqlPanel.appendChild(sqlPre);
    reasonPanel.appendChild(el("div", "reasoning-prose", payload.answer || "No reasoning available."));
    function show(which) {
      sqlPanel.hidden = which !== "sql";
      reasonPanel.hidden = which !== "reason";
      tabs.querySelectorAll(".tab").forEach(function (button) {
        button.className = "tab" + (button.getAttribute("data-tab") === which ? " active" : "");
      });
    }
    [["reason", "Reasoning"], ["sql", "SQL"]].forEach(function (item, index) {
      var button = el("button", "tab" + (index === 0 ? " active" : ""), item[1]);
      button.type = "button";
      button.setAttribute("data-tab", item[0]);
      button.addEventListener("click", function () { show(item[0]); });
      tabs.appendChild(button);
    });
    panel.appendChild(tabs);
    panel.appendChild(reasonPanel);
    panel.appendChild(sqlPanel);
    show("reason");
    card.appendChild(panel);
    return card;
  }

  function ask(question) {
    question = (question || "").trim();
    if (!question || busy) return;
    busy = true;
    ensureThread();
    chat.appendChild(el("div", "bubble user", question));
    var pending = thinkingNode();
    chat.appendChild(pending);
    scrollChat();
    if (recent.indexOf(question) === -1) recent.push(question);
    if (recent.length > 8) recent = recent.slice(-8);
    renderRecent();
    var prior = history.slice();
    history.push({ role: "user", content: question });
    fetch(url("/ask"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, history: prior })
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) throw new Error(payload.error || "The assistant could not answer.");
        return payload;
      });
    }).then(function (payload) {
      pending.stop();
      pending.replaceWith(answerCard(payload));
      history.push({ role: "assistant", content: payload.answer || "" });
      history = history.slice(-6);
    }).catch(function (error) {
      pending.stop();
      pending.replaceWith(el("div", "bubble error", error.message || String(error)));
    }).then(function () {
      busy = false;
      followInput.value = "";
      scrollChat();
      followInput.focus();
    });
  }

  document.getElementById("new-chat").addEventListener("click", function () {
    history = [];
    started = false;
    renderEmpty();
    showView("ask");
  });
  document.querySelectorAll("[data-view]").forEach(function (button) {
    button.addEventListener("click", function () {
      showView(button.getAttribute("data-view"));
    });
  });
  document.getElementById("open-ask").addEventListener("click", function () {
    showView("ask");
  });
  composer.addEventListener("submit", function (event) {
    event.preventDefault();
    ask(followInput.value);
  });

  fetch(url("/summary")).then(function (response) {
    return response.json().then(function (payload) {
      if (!response.ok) throw new Error(payload.error || "Could not load datasets.");
      return payload;
    });
  }).then(function (data) {
    var kpis = data.kpis || {};
    var rows = [
      ["sf_accounts", kpis.accounts],
      ["sf_opportunities", kpis.opportunities],
      ["sf_service_cases", kpis.service_cases],
      ["coldchain_shipments", kpis.shipments],
      ["temperature_excursions", kpis.excursions]
    ];
    tableList.innerHTML = "";
    rows.forEach(function (row) {
      var item = el("li");
      item.appendChild(document.createTextNode(row[0]));
      item.appendChild(el("span", null, row[1] == null ? "" : Number(row[1]).toLocaleString()));
      tableList.appendChild(item);
    });
    statusFoot.textContent = "Opus · cold chain · " + (kpis.shipments || 0) + " shipments";
    renderDashboard(data);
  }).catch(function (error) {
    statusFoot.textContent = error.message || "Datasets not loaded";
    var readout = document.getElementById("dash-readout");
    readout.innerHTML = "";
    readout.appendChild(el("li", null, error.message || "The project tables could not be loaded."));
  });

  renderEmpty();
  renderRecent();
  showView("dashboard");
})();
