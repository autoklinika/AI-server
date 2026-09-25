const API_BASE = "/control/api/v1";
const CONTROL_BASE = "/control";

const FALLBACK_APP_REGISTRY = [
  { id: "dashboard", group: "operations", label: "Dashboard", route: "/", icon: "◫" },
  { id: "agents", group: "operations", label: "Agents", route: "/operations/agents", icon: "A" },
  { id: "models", group: "operations", label: "Models", route: "/operations/models", icon: "M" },
  { id: "resources", group: "operations", label: "Resources", route: "/operations/resources", icon: "R" },
  { id: "jobs", group: "operations", label: "Jobs", route: "/jobs", icon: "J" },
  { id: "backup", group: "operations", label: "Backup", route: "/operations/backup", icon: "B" },
  { id: "logs", group: "operations", label: "Logs", route: "/operations/logs", icon: "L" },

  { id: "knowledge", group: "applications", label: "Knowledge", route: "/apps/knowledge", icon: "K", status: "live" },
  { id: "benchmarks", group: "applications", label: "Benchmarks", route: "/apps/benchmarks", icon: "B", status: "foundation" },
  { id: "ers", group: "applications", label: "ECU Repair Service", route: "/apps/ers", icon: "E", status: "foundation" },

  { id: "settings", group: "platform", label: "Settings", route: "/platform/settings", icon: "S" },
  { id: "providers", group: "platform", label: "Providers", route: "/platform/providers", icon: "P" },
  { id: "security", group: "platform", label: "Security", route: "/platform/security", icon: "S" },
  { id: "integrations", group: "platform", label: "Integrations", route: "/platform/integrations", icon: "I" }
];

const state = {
  health: null,
  observability: null,
  jobs: null,
  models: null,
  systems: null,
  apps: null,
  knowledge: {
    tab: "search",
    query: "",
    domain: "shared",
    loading: false,
    error: null,
    search: null,
    ask: null
  },
  errors: {},
  lastRefresh: null,
  loading: true
};

function registry() {
  return state.apps && Array.isArray(state.apps.apps)
    ? state.apps.apps.map(function (remote) {
        const fallback = FALLBACK_APP_REGISTRY.find(function (item) { return item.id === remote.id; }) || {};
        return { ...fallback, ...remote };
      })
    : FALLBACK_APP_REGISTRY;
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function controlUrl(route) {
  return CONTROL_BASE + (route === "/" ? "/" : route);
}

function routePath() {
  let path = window.location.pathname;
  if (path.startsWith(CONTROL_BASE)) path = path.slice(CONTROL_BASE.length);
  if (!path || path === "/") return "/";
  return path.replace(/\/+$/, "");
}

function humanBytes(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = value;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return (index >= 3 ? amount.toFixed(1) : Math.round(amount)) + " " + units[index];
}

function humanDurationMs(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (value < 1000) return Math.round(value) + " ms";
  return (value / 1000).toFixed(2) + " s";
}

function statusClass(status) {
  const value = String(status || "").toLowerCase();
  if (["ready", "ok", "active", "completed", "healthy", "configured"].includes(value)) return "ok";
  if (["running", "queued", "loading"].includes(value)) return "active";
  if (["degraded", "blocked", "warning", "unavailable", "failed", "expired"].includes(value)) return "bad";
  return "muted";
}

function statusDot(status) {
  return '<span class="status-dot ' + statusClass(status) + '" aria-hidden="true"></span>';
}

async function api(path, options) {
  const config = options || {};
  const headers = { "Accept": "application/json", ...(config.headers || {}) };
  if (config.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(API_BASE + path, {
    method: config.method || "GET",
    credentials: "same-origin",
    headers: headers,
    body: config.body === undefined ? undefined : JSON.stringify(config.body),
    cache: "no-store"
  });
  if (!response.ok) {
    let code = "http_" + response.status;
    try {
      const payload = await response.json();
      code = payload && payload.error && payload.error.code ? payload.error.code : code;
    } catch (_error) {
      // Keep the bounded status-only fallback.
    }
    const error = new Error(code);
    error.status = response.status;
    error.code = code;
    throw error;
  }
  return response.json();
}

async function refreshData() {
  const requests = {
    health: api("/health"),
    observability: api("/observability"),
    jobs: api("/jobs"),
    models: api("/models"),
    systems: api("/systems"),
    apps: api("/apps")
  };

  await Promise.all(Object.entries(requests).map(async function (entry) {
    const key = entry[0];
    const promise = entry[1];
    try {
      state[key] = await promise;
      delete state.errors[key];
    } catch (error) {
      state.errors[key] = { status: error.status || 0, message: error.message };
    }
  }));

  state.loading = false;
  state.lastRefresh = new Date();
  const focused = document.activeElement;
  if (!focused || !["INPUT", "TEXTAREA", "SELECT"].includes(focused.tagName)) {
    render();
  }
}

function appStatus(app) {
  if (app.id === "knowledge" && state.errors.health) return "unknown";
  return app.status || null;
}

function navGroup(group, title) {
  const current = routePath();
  const items = registry().filter(function (item) { return item.group === group; });
  return '<div class="nav-group">' +
    '<div class="nav-title">' + escapeHtml(title) + '</div>' +
    items.map(function (item) {
      const active = current === item.route || (item.route !== "/" && current.startsWith(item.route + "/"));
      return '<a class="nav-item' + (active ? " active" : "") + '" href="' + controlUrl(item.route) + '" data-nav>' +
        '<span class="nav-icon">' + escapeHtml(item.icon) + '</span>' +
        '<span>' + escapeHtml(item.label) + '</span>' +
      '</a>';
    }).join("") +
  '</div>';
}

function connectionBanner() {
  const errors = Object.values(state.errors);
  if (!errors.length) return "";
  const unauthorized = errors.some(function (item) { return item.status === 401 || item.status === 403; });
  const text = unauthorized
    ? "Platform API wymaga autoryzacji. GUI nie przechowuje tokenu w przeglądarce; potrzebny jest docelowy mechanizm sesji."
    : "Część danych Platform API jest obecnie niedostępna. Widoki oznaczone LIVE nie będą zgadywać brakujących wartości.";
  return '<div class="banner warning">' + statusDot("warning") + '<span>' + escapeHtml(text) + '</span></div>';
}

function shell(content) {
  const healthStatus = state.health ? state.health.status : (state.loading ? "loading" : "unavailable");
  const refresh = state.lastRefresh
    ? state.lastRefresh.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "—";

  return '<aside class="sidebar">' +
      '<a class="brand" href="' + controlUrl("/") + '" data-nav>' +
        '<span class="brand-mark">AI</span>' +
        '<span><strong>Control Center</strong><small>GUI-0 foundation</small></span>' +
      '</a>' +
      '<nav>' +
        navGroup("operations", "OPERATIONS") +
        navGroup("applications", "APPLICATIONS") +
        navGroup("platform", "PLATFORM") +
      '</nav>' +
    '</aside>' +
    '<main class="workspace">' +
      '<header class="topbar">' +
        '<div class="mobile-brand"><span class="brand-mark">AI</span><strong>Control Center</strong></div>' +
        '<div class="topbar-status">' + statusDot(healthStatus) +
          '<span>Platform <strong>' + escapeHtml(String(healthStatus).toUpperCase()) + '</strong></span>' +
        '</div>' +
        '<div class="topbar-meta">LIVE · ' + escapeHtml(refresh) + '</div>' +
      '</header>' +
      '<div class="content">' + connectionBanner() + content + '</div>' +
      '<nav class="mobile-nav">' +
        '<a href="' + controlUrl("/") + '" data-nav>Home</a>' +
        '<a href="' + controlUrl("/jobs") + '" data-nav>Jobs</a>' +
        '<a href="' + controlUrl("/apps/knowledge") + '" data-nav>Apps</a>' +
        '<a href="' + controlUrl("/platform/integrations") + '" data-nav>Platform</a>' +
      '</nav>' +
    '</main>';
}

function dashboard() {
  const health = state.health || {};
  const obs = state.observability || {};
  const jobs = state.jobs && Array.isArray(state.jobs.jobs) ? state.jobs.jobs : [];
  const rm = obs.resource_manager || (health.components && health.components.resource_manager) || {};
  const process = obs.process || {};
  const accelerators = obs.accelerators || (health.components && health.components.accelerators) || {};
  const devices = Array.isArray(accelerators.devices) ? accelerators.devices : [];
  const primary = devices.find(function (device) {
    return device.accelerator_id === accelerators.primary_accelerator_id;
  }) || devices[0] || null;

  const activeJobs = jobs.filter(function (job) {
    return ["running", "admitted", "queued"].includes(String(job.state).toLowerCase());
  });
  const recentJobs = jobs.filter(function (job) {
    return !["running", "admitted", "queued"].includes(String(job.state).toLowerCase());
  }).sort(function (a, b) {
    return String(b.finished_at || b.created_at || "").localeCompare(String(a.finished_at || a.created_at || ""));
  }).slice(0, 4);

  const current = activeJobs[0];
  const alertCount = health.status && health.status !== "ready" ? 1 : 0;
  const accelValue = primary
    ? (primary.total_memory_bytes ? humanBytes(primary.total_memory_bytes) : (primary.memory_class || "configured"))
    : "—";
  const accelMeta = primary ? [primary.backend, primary.kind].filter(Boolean).join(" · ") : "API pending";

  return '<section class="hero">' +
      '<div><div class="eyebrow">AI PLATFORM</div><h1>Control Center</h1>' +
      '<p>Stan platformy, praca agentów i wejście do aplikacji domenowych.</p></div>' +
      '<div class="health-pill ' + statusClass(health.status) + '">' +
        statusDot(health.status) + '<span>' + escapeHtml((health.status || "connecting").toUpperCase()) + '</span>' +
      '</div>' +
    '</section>' +

    '<section class="metric-strip">' +
      metric("GPU / UMA", accelValue, accelMeta, "/operations/resources") +
      metric("AI process", humanBytes(process.rss_bytes), "RSS", "/operations/resources") +
      metric("Storage", "—", "API pending", "/operations/resources") +
      metric("Jobs", String((rm.active || 0) + (rm.queued || 0)), (rm.active || 0) + " active · " + (rm.queued || 0) + " queued", "/jobs") +
      metric("Alerts", String(alertCount), alertCount ? "attention" : "none", "/") +
    '</section>' +

    '<section class="service-row">' +
      serviceChip("Resource Manager", rm.status || (rm.admission_blocked ? "blocked" : "ready")) +
      serviceChip("Inference", health.components && health.components.inference ? health.components.inference.status : "unknown") +
      serviceChip("GPU residency", health.components && health.components.gpu_residency ? health.components.gpu_residency.state : "unknown") +
      serviceChip("Knowledge API", state.errors.health ? "unknown" : "ready") +
    '</section>' +

    '<div class="dashboard-grid">' +
      '<section class="panel current-work">' +
        panelHeader("Current work", current ? "LIVE" : "IDLE") +
        (current ? currentJob(current) : '<div class="empty-state">Brak aktywnego joba w Resource Managerze.</div>') +
      '</section>' +
      '<section class="panel recent-events">' +
        panelHeader("Recent activity", recentJobs.length ? String(recentJobs.length) : "0") +
        (recentJobs.length ? recentJobs.map(jobRowCompact).join("") : '<div class="empty-state">Brak zakończonych jobów w pamięci scheduler-a.</div>') +
      '</section>' +
    '</div>' +

    '<section class="section-head"><div><div class="eyebrow">APPLICATIONS</div><h2>Workspace</h2></div>' +
      '<span class="section-note">Osobne aplikacje, wspólna AI Platform</span></section>' +
    '<section class="app-grid">' +
      registry().filter(function (app) { return app.group === "applications"; }).map(appCard).join("") +
    '</section>';
}

function metric(label, value, meta, route) {
  return '<a class="metric" href="' + controlUrl(route) + '" data-nav>' +
    '<span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(value) + '</strong><small>' + escapeHtml(meta) + '</small>' +
  '</a>';
}

function serviceChip(name, status) {
  return '<div class="service-chip">' + statusDot(status) +
    '<span>' + escapeHtml(name) + '</span><small>' + escapeHtml(status || "unknown") + '</small></div>';
}

function panelHeader(title, badge) {
  return '<div class="panel-head"><h3>' + escapeHtml(title) + '</h3><span class="badge">' + escapeHtml(badge) + '</span></div>';
}

function currentJob(job) {
  return '<a class="current-job" href="' + controlUrl("/jobs/" + encodeURIComponent(job.job_id)) + '" data-nav>' +
    '<div class="job-state">' + statusDot(job.state) + '<strong>' + escapeHtml(job.state || "unknown") + '</strong></div>' +
    '<h3>' + escapeHtml(job.capability || "job") + '</h3>' +
    '<div class="job-meta"><span>' + escapeHtml(job.job_id) + '</span><span>' + escapeHtml(job.priority_class || "—") + '</span>' +
    '<span>' + escapeHtml(job.assigned_provider || "waiting") + '</span></div>' +
    '<div class="open-link">Open job →</div>' +
  '</a>';
}

function jobRowCompact(job) {
  return '<a class="event-row" href="' + controlUrl("/jobs/" + encodeURIComponent(job.job_id)) + '" data-nav>' +
    '<span>' + statusDot(job.state) + escapeHtml(job.capability || "job") + '</span>' +
    '<small>' + escapeHtml(job.state || "unknown") + '</small>' +
  '</a>';
}

function appCard(app) {
  const status = appStatus(app);
  const copy = {
    knowledge: "Szukaj, pytaj AI i pracuj ze źródłami Knowledge Service.",
    benchmarks: "Laboratorium modeli, routerów i porównań jakości.",
    ers: "Domenowa aplikacja diagnostyki i przypadków ECU."
  }[app.id] || "";
  return '<a class="app-card" href="' + controlUrl(app.route) + '" data-nav>' +
    '<div class="app-card-top"><span class="app-logo">' + escapeHtml(app.icon) + '</span>' +
      '<span class="app-state">' + statusDot(status) + escapeHtml(status || "planned") + '</span></div>' +
    '<h3>' + escapeHtml(app.label) + '</h3><p>' + escapeHtml(copy) + '</p>' +
    '<span class="open-link">Open application →</span>' +
  '</a>';
}

function sectionPage(title, subtitle, body) {
  return '<section class="page-head"><div class="eyebrow">AI CONTROL CENTER</div><h1>' + escapeHtml(title) + '</h1>' +
    '<p>' + escapeHtml(subtitle) + '</p></section>' + body;
}

function modelsPage() {
  const models = state.models && Array.isArray(state.models.models) ? state.models.models : [];
  const execution = state.observability && state.observability.execution ? state.observability.execution : {};
  const body = models.length ? '<div class="cards">' + models.map(function (model) {
    return '<article class="panel detail-card">' + panelHeader(model.logical_id, "READY") +
      '<dl><dt>Capabilities</dt><dd>' + escapeHtml((model.capabilities || []).join(", ")) + '</dd>' +
      '<dt>Provider</dt><dd>' + escapeHtml(execution.provider || "—") + '</dd>' +
      '<dt>Node</dt><dd>' + escapeHtml(execution.node || "—") + '</dd>' +
      '<dt>Streaming</dt><dd>' + escapeHtml(String(model.streaming)) + '</dd></dl></article>';
  }).join("") + '</div>' : pendingPanel("Models", "Platform API nie zwróciło listy modeli.");
  return sectionPage("Models", "Logiczne modele i aktualny provider wykonawczy.", body);
}

function resourcesPage() {
  const obs = state.observability || {};
  const rm = obs.resource_manager || {};
  const leases = obs.resource_leases || {};
  const accelerators = obs.accelerators || {};
  const devices = Array.isArray(accelerators.devices) ? accelerators.devices : [];
  let deviceHtml = devices.map(function (device) {
    const residency = device.residency || {};
    return '<article class="panel detail-card">' + panelHeader(device.accelerator_id, residency.state || "unknown") +
      '<dl><dt>Kind</dt><dd>' + escapeHtml(device.kind || "—") + '</dd>' +
      '<dt>Backend</dt><dd>' + escapeHtml(device.backend || "—") + '</dd>' +
      '<dt>Memory class</dt><dd>' + escapeHtml(device.memory_class || "—") + '</dd>' +
      '<dt>Total memory</dt><dd>' + escapeHtml(humanBytes(device.total_memory_bytes)) + '</dd>' +
      '<dt>Residency</dt><dd>' + escapeHtml(residency.state || "—") + '</dd></dl></article>';
  }).join("");
  const summary = '<section class="metric-strip compact">' +
    metric("Active", String(rm.active || 0), "jobs", "/jobs") +
    metric("Queued", String(rm.queued || 0), "jobs", "/jobs") +
    metric("Leases", String(leases.active || 0), "active", "/operations/resources") +
    metric("Concurrency", String(rm.max_concurrency || "—"), "max", "/operations/resources") +
  '</section>';
  return sectionPage("Resources", "Resource Manager, leases i inventory akceleratorów.", summary +
    (deviceHtml ? '<div class="cards">' + deviceHtml + '</div>' : pendingPanel("Accelerators", "Brak danych inventory.")));
}

function jobsPage() {
  const jobs = state.jobs && Array.isArray(state.jobs.jobs) ? state.jobs.jobs : [];
  const body = jobs.length ? '<div class="table-wrap"><table><thead><tr><th>State</th><th>Capability</th><th>Priority</th><th>Provider</th><th>Job</th></tr></thead><tbody>' +
    jobs.map(function (job) {
      return '<tr><td>' + statusDot(job.state) + escapeHtml(job.state) + '</td><td>' + escapeHtml(job.capability) + '</td>' +
      '<td>' + escapeHtml(job.priority_class) + '</td><td>' + escapeHtml(job.assigned_provider || "—") + '</td>' +
      '<td><a href="' + controlUrl("/jobs/" + encodeURIComponent(job.job_id)) + '" data-nav>' + escapeHtml(job.job_id) + '</a></td></tr>';
    }).join("") + '</tbody></table></div>' : pendingPanel("Jobs", "Brak jobów w bieżącym bounded history.");
  return sectionPage("Jobs", "Centralny widok kolejki i historii Resource Managera.", body);
}

function jobDetailPage(jobId) {
  const jobs = state.jobs && Array.isArray(state.jobs.jobs) ? state.jobs.jobs : [];
  const job = jobs.find(function (item) { return item.job_id === jobId; });
  if (!job) {
    return sectionPage("Job", jobId, pendingPanel("Not found in current snapshot",
      "Job może być poza bounded history. Deep link pozostaje stabilny, ale Platform API zwróci szczegóły dopiero po rozszerzeniu retencji."));
  }
  return sectionPage("Job " + job.job_id, job.capability || "Platform job",
    '<article class="panel detail-card wide">' + panelHeader("Execution", job.state || "unknown") +
    '<dl><dt>Request</dt><dd>' + escapeHtml(job.request_id) + '</dd>' +
    '<dt>Domain</dt><dd>' + escapeHtml(job.domain) + '</dd>' +
    '<dt>Priority</dt><dd>' + escapeHtml(job.priority_class) + '</dd>' +
    '<dt>Provider</dt><dd>' + escapeHtml(job.assigned_provider || "—") + '</dd>' +
    '<dt>Node</dt><dd>' + escapeHtml(job.assigned_node || "—") + '</dd>' +
    '<dt>Created</dt><dd>' + escapeHtml(job.created_at || "—") + '</dd>' +
    '<dt>Started</dt><dd>' + escapeHtml(job.started_at || "—") + '</dd>' +
    '<dt>Finished</dt><dd>' + escapeHtml(job.finished_at || "—") + '</dd></dl></article>');
}

function integrationsPage() {
  const systems = state.systems && Array.isArray(state.systems.systems) ? state.systems.systems : [];
  const body = '<div class="cards">' + systems.map(function (system) {
    return '<article class="panel detail-card">' + panelHeader(system.system_id, "CONFIGURED") +
      '<dl><dt>Integration</dt><dd>' + escapeHtml(system.integration || "—") + '</dd>' +
      '<dt>Control policy</dt><dd>' + escapeHtml(system.control_policy || "—") + '</dd></dl></article>';
  }).join("") +
  '<article class="panel detail-card">' + panelHeader("MCP", "PLANNED") +
    '<p class="muted-copy">MCP-ready, ale nie MCP-dependent. Integracje będą przechodzić przez Capability / Permission layer.</p></article></div>';
  return sectionPage("Integrations", "Kanały platformy oraz przyszły MCP Gateway/Host.", body);
}

function knowledgePage() {
  const k = state.knowledge;
  const activeResult = k.tab === "search" ? knowledgeSearchResults(k.search) : knowledgeAskResult(k.ask);
  return sectionPage("Knowledge", "Szukaj bezpośrednio w źródłach albo pytaj AI z cytowaniami.",
    '<div class="knowledge-shell">' +
      '<div class="knowledge-tabs" role="tablist">' +
        '<button class="knowledge-tab' + (k.tab === "search" ? " active" : "") + '" data-knowledge-tab="search">Szukaj</button>' +
        '<button class="knowledge-tab' + (k.tab === "ask" ? " active" : "") + '" data-knowledge-tab="ask">Zapytaj AI</button>' +
      '</div>' +
      '<form id="knowledge-form" class="knowledge-form panel">' +
        '<div class="knowledge-input-row">' +
          '<input id="knowledge-query" name="query" required maxlength="8192" autocomplete="off" ' +
            'placeholder="' + (k.tab === "search" ? "np. MPC555 reset architecture" : "np. Dlaczego BDM może być niedostępne w tym ECU?") + '" ' +
            'value="' + escapeHtml(k.query) + '">' +
          '<button type="submit" class="primary-button"' + (k.loading ? " disabled" : "") + '>' +
            (k.loading ? "Pracuję…" : (k.tab === "search" ? "Szukaj" : "Zapytaj")) +
          '</button>' +
        '</div>' +
        '<div class="knowledge-options">' +
          '<label>Domena <select id="knowledge-domain" name="domain">' +
            '<option value="shared"' + (k.domain === "shared" ? " selected" : "") + '>shared</option>' +
            '<option value="ecu-repair"' + (k.domain === "ecu-repair" ? " selected" : "") + '>ecu-repair</option>' +
          '</select></label>' +
          '<span>Tryb: hybrid</span><span>Źródła przez Platform API</span>' +
        '</div>' +
        (k.error ? '<div class="knowledge-error">' + escapeHtml(k.error) + '</div>' : '') +
      '</form>' +
      '<div class="knowledge-results">' + activeResult + '</div>' +
    '</div>');
}

function knowledgeSearchResults(payload) {
  if (!payload) {
    return '<div class="panel knowledge-empty"><h3>Raw retrieval</h3><p>Wyniki pokażą fragment, relevance score, źródło i lokalizator.</p></div>';
  }
  const results = Array.isArray(payload.results) ? payload.results : [];
  if (!results.length) {
    return '<div class="panel knowledge-empty"><h3>Brak wyników</h3><p>Knowledge Service nie znalazł pasujących fragmentów.</p></div>';
  }
  return '<div class="knowledge-result-meta">Backend: ' + escapeHtml(payload.backend || "—") +
    ' · ' + humanDurationMs(payload.duration_ms) + ' · ' + results.length + ' wyników</div>' +
    results.map(function (result, index) {
      const meta = result.metadata || {};
      const source = result.source || {};
      const locator = meta.page ? "str. " + meta.page : (meta.section || "");
      const docId = meta.document_id;
      const open = docId
        ? '<a class="source-link" href="' + API_BASE + '/knowledge/documents/' + encodeURIComponent(docId) + '/content" target="_blank" rel="noopener">Otwórz źródło ↗</a>'
        : '';
      return '<article class="panel knowledge-result">' +
        '<div class="knowledge-result-head"><span>#' + (index + 1) + '</span><strong>' +
          Math.round(Number(result.score || 0) * 100) + '%</strong></div>' +
        '<p>' + escapeHtml(result.text || "") + '</p>' +
        '<div class="knowledge-source"><div><strong>' + escapeHtml(source.title || source.uri || "Źródło") + '</strong>' +
          '<small>' + escapeHtml([source.type, locator].filter(Boolean).join(" · ")) + '</small></div>' + open + '</div>' +
      '</article>';
    }).join("");
}

function knowledgeAskResult(payload) {
  if (!payload) {
    return '<div class="panel knowledge-empty"><h3>RAG z cytowaniami</h3><p>Odpowiedź będzie oparta wyłącznie na wynikach Knowledge Service i pokaże użyte źródła.</p></div>';
  }
  const citations = Array.isArray(payload.citations) ? payload.citations : [];
  const retrieval = payload.retrieval || {};
  const execution = payload.execution || {};
  let citationsHtml = citations.map(function (citation) {
    const source = citation.source || {};
    const open = citation.document_id
      ? '<a class="source-link" href="' + API_BASE + '/knowledge/documents/' + encodeURIComponent(citation.document_id) + '/content" target="_blank" rel="noopener">Otwórz ↗</a>'
      : '';
    return '<article class="citation-card">' +
      '<div class="citation-ref">' + escapeHtml(citation.ref || "source") + '</div>' +
      '<div><strong>' + escapeHtml(source.title || source.uri || "Źródło") + '</strong>' +
      '<small>' + escapeHtml([citation.page ? "str. " + citation.page : "", citation.section || ""].filter(Boolean).join(" · ")) + '</small>' +
      '<p>' + escapeHtml(citation.snippet || "") + '</p></div>' + open +
    '</article>';
  }).join("");

  return '<article class="panel knowledge-answer">' +
    '<div class="panel-head"><h3>Odpowiedź</h3><span class="badge">' +
      escapeHtml(payload.insufficient_context ? "LIMITED" : "CITED RAG") + '</span></div>' +
    '<div class="knowledge-answer-body"><p class="answer-text">' + escapeHtml(payload.answer || "") + '</p>' +
      (payload.insufficiency_reason ? '<p class="insufficient">' + escapeHtml(payload.insufficiency_reason) + '</p>' : '') +
      '<div class="answer-meta"><span>Retrieval ' + escapeHtml(retrieval.backend || "—") + '</span>' +
      '<span>' + humanDurationMs(retrieval.duration_ms) + '</span>' +
      '<span>LLM ' + humanDurationMs(execution.duration_ms) + '</span></div>' +
    '</div></article>' +
    '<div class="citations-head"><h3>Źródła</h3><span>' + citations.length + '</span></div>' +
    (citationsHtml || '<div class="panel knowledge-empty"><p>Brak cytowań.</p></div>');
}

async function runKnowledge(form) {
  const query = String(new FormData(form).get("query") || "").trim();
  const domain = String(new FormData(form).get("domain") || "shared");
  if (!query) return;

  state.knowledge.query = query;
  state.knowledge.domain = domain;
  state.knowledge.loading = true;
  state.knowledge.error = null;
  render();

  const target = state.knowledge.tab === "search" ? "/knowledge/search" : "/knowledge/ask";
  try {
    const payload = await api(target, {
      method: "POST",
      body: {
        schema_version: 1,
        query: query,
        mode: "hybrid",
        context: { domain: domain }
      }
    });
    if (state.knowledge.tab === "search") state.knowledge.search = payload;
    else state.knowledge.ask = payload;
  } catch (error) {
    state.knowledge.error = "Knowledge API: " + (error.code || error.message || "unknown_error");
  } finally {
    state.knowledge.loading = false;
    render();
  }
}

function wirePageActions() {
  document.querySelectorAll("[data-knowledge-tab]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.knowledge.tab = button.dataset.knowledgeTab;
      state.knowledge.error = null;
      render();
    });
  });
  const form = document.getElementById("knowledge-form");
  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      runKnowledge(form);
    });
  }
}

function placeholderApplication(title, text) {
  return sectionPage(title, text,
    '<div class="app-hero panel"><div><h2>Foundation ready</h2>' +
    '<p>Route, deep link i miejsce w App Registry są gotowe. Logika aplikacji zostanie dodana jako osobny moduł bez rozbudowy Control Center w monolit.</p></div></div>');
}

function pendingPanel(title, text) {
  return '<div class="panel pending"><div class="pending-icon">…</div><div><h3>' + escapeHtml(title) + '</h3><p>' + escapeHtml(text) + '</p></div></div>';
}

function genericOperations(title, subtitle, note) {
  return sectionPage(title, subtitle, pendingPanel(title, note));
}

function notFoundPage(path) {
  return sectionPage("404", "Nieznany deep link.",
    '<div class="panel pending"><div><h3>' + escapeHtml(path) + '</h3><p>Ten adres nie jest jeszcze zarejestrowany w AI Control Center.</p>' +
    '<a class="button-link" href="' + controlUrl("/") + '" data-nav>Back to dashboard</a></div></div>');
}

function pageForRoute() {
  const path = routePath();
  if (path === "/") return dashboard();
  if (path === "/operations/models") return modelsPage();
  if (path === "/operations/resources") return resourcesPage();
  if (path === "/jobs") return jobsPage();
  if (path.startsWith("/jobs/")) return jobDetailPage(decodeURIComponent(path.slice("/jobs/".length)));
  if (path === "/platform/integrations") return integrationsPage();
  if (path === "/apps/knowledge") return knowledgePage();
  if (path === "/apps/benchmarks") return placeholderApplication("Benchmarks", "Laboratorium benchmarków jako osobna aplikacja.");
  if (path === "/apps/ers") return placeholderApplication("ECU Repair Service", "Domenowa aplikacja ERS jako osobny workspace.");
  if (path === "/operations/agents") return genericOperations("Agents", "Stan i kontrolowane akcje agentów.", "Agent control API nie jest jeszcze wystawione przez Platform API.");
  if (path === "/operations/backup") return genericOperations("Backup", "Backup / DR z Stage K.", "Status backupu nie ma jeszcze stabilnego kontraktu Platform API.");
  if (path === "/operations/logs") return genericOperations("Logs", "Filtrowane logi operacyjne.", "Log API nie jest jeszcze częścią Platform API v1.");
  if (path === "/platform/settings") return genericOperations("Settings", "Konfiguracja GUI i platformy.", "GUI-0 nie wprowadza jeszcze mutacji konfiguracji.");
  if (path === "/platform/providers") return modelsPage();
  if (path === "/platform/security") return genericOperations("Security", "Polityki dostępu Control Center.", "Autoryzacja sesyjna GUI jest osobnym kontraktem; token Platform API nie będzie osadzany w frontendzie.");
  if (path.startsWith("/traces/")) return genericOperations("Trace", path.slice("/traces/".length), "Flight Recorder zostanie dodany w fazie observability.");
  if (path.startsWith("/incidents/")) return genericOperations("Incident", path.slice("/incidents/".length), "Incident Timeline zostanie dodany w fazie observability.");
  if (path.startsWith("/models/")) return modelsPage();
  return notFoundPage(path);
}

function render() {
  document.getElementById("app").innerHTML = shell(pageForRoute());
  wirePageActions();
}

function navigate(url) {
  window.history.pushState({}, "", url);
  render();
  window.scrollTo({ top: 0, behavior: "instant" });
}

document.addEventListener("click", function (event) {
  const link = event.target.closest("a[data-nav]");
  if (!link) return;
  if (link.origin !== window.location.origin) return;
  event.preventDefault();
  navigate(link.href);
});

window.addEventListener("popstate", render);

document.addEventListener("visibilitychange", function () {
  if (!document.hidden) refreshData();
});

render();
refreshData();

window.setInterval(function () {
  if (!document.hidden) refreshData();
}, 10000);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/control/sw.js", { scope: "/control/" }).catch(function () {
      // PWA is an enhancement. Control Center stays usable without a worker.
    });
  });
}
