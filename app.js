const state = {
  summary: null,
  project: null,
  selectedProjectId: null,
  selectedDate: null,
  selectedLogPath: null,
  rawContent: "",
  lineMode: "all",
  initialDateLimit: 3,
  moreDateLimit: 30,
  logRequestId: 0,
  statusFilter: null,
  tailLines: 200,
  pollMs: 120000,
  staticMode: null,
  staticProjectCache: new Map(),
};

const STATUS_LABELS = {
  ok: "OK",
  warning: "Warning",
  error: "Error",
  stale: "Stale",
  unknown: "Unknown",
  empty: "No Logs",
};

const statusRank = {
  error: 5,
  stale: 4,
  warning: 3,
  unknown: 2,
  ok: 1,
  empty: 0,
};

const qs = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function fetchSummaryData() {
  if (state.staticMode !== false) {
    try {
      const summary = await fetchJson("data/summary.json");
      state.staticMode = true;
      return summary;
    } catch (error) {
      if (state.staticMode === true) throw error;
      state.staticMode = false;
    }
  }
  return fetchJson("/api/summary");
}

function staticProjectSlice(project, offset = 0, limit = 3) {
  const dateCount = project.dates?.length || 0;
  const safeOffset = Math.max(offset, 0);
  const safeLimit = Math.max(limit, 1);
  const dates = (project.dates || []).slice(safeOffset, safeOffset + safeLimit);
  const dateKeys = new Set(dates.map((item) => item.date));
  const logsByDate = {};
  for (const date of dateKeys) {
    logsByDate[date] = project.logsByDate?.[date] || [];
  }
  const payload = Object.fromEntries(
    Object.entries(project).filter(([key]) => !["dates", "logsByDate"].includes(key))
  );
  payload.dates = dates;
  payload.logsByDate = logsByDate;
  payload.dateOffset = safeOffset;
  payload.loadedDateCount = Math.min(safeOffset + dates.length, dateCount);
  payload.hasMoreDates = safeOffset + dates.length < dateCount;
  return payload;
}

async function fetchProjectData(projectId, offset = 0, limit = 3) {
  if (state.staticMode) {
    let project = state.staticProjectCache.get(projectId);
    if (!project) {
      project = await fetchJson(`data/projects/${encodeURIComponent(projectId)}.json`);
      state.staticProjectCache.set(projectId, project);
    }
    return staticProjectSlice(project, offset, limit);
  }
  return fetchJson(`/api/projects/${encodeURIComponent(projectId)}?offset=${offset}&limit=${limit}`);
}

function findLog(path) {
  if (!state.project || !state.selectedDate) return null;
  const logs = state.project.logsByDate[state.selectedDate] || [];
  return logs.find((log) => log.path === path) || null;
}

async function fetchLogData(projectId, path) {
  if (state.staticMode) {
    const log = findLog(path);
    if (!log?.dataPath) {
      throw new Error("Static log data is not available for this file.");
    }
    return fetchJson(log.dataPath);
  }
  return fetchJson(`/api/log?project=${encodeURIComponent(projectId)}&path=${encodeURIComponent(path)}&lines=${state.tailLines}`);
}

function setMetrics(summary) {
  qs("#metricProjects").textContent = summary.projectCount;
  qs("#metricLatest").textContent = summary.latestDate || "-";
  qs("#generatedAt").textContent = summary.windowDays ? `Last ${summary.windowDays} days` : (summary.generatedAt || "-");
  qs("#generatedAt").title = summary.generatedAt ? `Updated ${summary.generatedAt}` : "";
  renderStatusSummary(summary.projects || []);
}

function statusDot(status) {
  const label = STATUS_LABELS[status] || status;
  return `<span class="status-dot dot-${escapeHtml(status)}" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}"></span>`;
}

function statusPill(status) {
  return `<span class="status-pill status-${escapeHtml(status)}">${escapeHtml(STATUS_LABELS[status] || status)}</span>`;
}

function issueChips(item) {
  const chips = [];
  if (item.errors) chips.push(`<span class="issue-chip issue-error">${escapeHtml(item.errors)} errors</span>`);
  if (item.warnings) chips.push(`<span class="issue-chip issue-warning">${escapeHtml(item.warnings)} warnings</span>`);
  const neutral = item.count ? `${item.count} logs` : item.sizeLabel || (!chips.length ? "OK" : "");
  if (neutral) chips.push(`<span class="issue-chip issue-muted">${escapeHtml(neutral)}</span>`);
  return chips.join("");
}

function renderStatusSummary(projects) {
  const counts = projects.reduce((acc, project) => {
    acc[project.status] = (acc[project.status] || 0) + 1;
    return acc;
  }, {});
  const order = ["error", "warning", "stale", "ok", "unknown"];
  const total = projects.length;
  qs("#statusSummary").innerHTML = `
    <button class="status-chip status-all ${state.statusFilter ? "" : "active"}" type="button" data-status-filter="">
      <span>All</span>
      <strong>${escapeHtml(total)}</strong>
    </button>
  ` + order
    .filter((status) => counts[status])
    .map((status) => `
      <button class="status-chip status-${escapeHtml(status)} ${state.statusFilter === status ? "active" : ""}" type="button" data-status-filter="${escapeHtml(status)}">
        <span>${escapeHtml(STATUS_LABELS[status] || status)}</span>
        <strong>${escapeHtml(counts[status])}</strong>
      </button>
    `)
    .join("");
  qs("#statusSummary").querySelectorAll("[data-status-filter]").forEach((button) => {
    button.addEventListener("click", () => setStatusFilter(button.dataset.statusFilter || null));
  });
}

function filteredProjects() {
  const projects = state.summary?.projects || [];
  if (!state.statusFilter) return projects;
  return projects.filter((project) => project.status === state.statusFilter);
}

function setStatusFilter(status) {
  state.statusFilter = status;
  renderStatusSummary(state.summary?.projects || []);
  const projects = filteredProjects();
  const currentVisible = projects.some((project) => project.id === state.selectedProjectId);
  renderProjects();

  if (!projects.length) {
    state.project = null;
    state.selectedProjectId = null;
    state.selectedDate = null;
    state.selectedLogPath = null;
    qs("#projectName").textContent = "No matching projects";
    qs("#projectMeta").textContent = "Change the status filter";
    qs("#dateList").innerHTML = "";
    qs("#logList").innerHTML = "";
    qs("#logContent").textContent = "";
    qs("#dateCount").textContent = "-";
    qs("#logCount").textContent = "-";
    renderDateMoreButton();
    return;
  }

  if (!currentVisible) {
    loadProject(projects[0].id);
    return;
  }

  renderDates();
  const logs = currentLogs();
  if (!logs.some((log) => log.path === state.selectedLogPath)) {
    state.selectedLogPath = logs[0]?.path || null;
    state.rawContent = "";
  }
  renderLogs();
  if (state.selectedLogPath) {
    selectLog(state.selectedLogPath);
  }
}

function renderProjects() {
  const list = qs("#projectList");
  const projects = filteredProjects();
  if (!projects.length) {
    list.innerHTML = `<div class="empty-state">No projects match this filter.</div>`;
    return;
  }
  list.innerHTML = projects
    .map((project) => {
      const active = project.id === state.selectedProjectId ? "active" : "";
      return `
        <button class="project-card tone-${escapeHtml(project.status)} ${active}" type="button" data-project="${escapeHtml(project.id)}" aria-pressed="${active ? "true" : "false"}">
          <div class="project-card-top">
            <strong>${escapeHtml(project.name)}</strong>
            ${statusPill(project.status)}
          </div>
          <div class="project-card-meta">
            <span>${escapeHtml(project.server)}</span>
            <span>${escapeHtml(project.latestDate || "-")}</span>
          </div>
        </button>
      `;
    })
    .join("");
  list.querySelectorAll("[data-project]").forEach((button) => {
    button.addEventListener("click", () => loadProject(button.dataset.project));
  });
}

function renderDates() {
  const list = qs("#dateList");
  const dates = state.project?.dates || [];
  const total = state.project?.dateCount || dates.length;
  qs("#dateCount").textContent = `${dates.length}/${total} days`;
  list.innerHTML = dates
    .map((item) => {
      const active = item.date === state.selectedDate ? "active" : "";
      return `
        <button class="date-item tone-${escapeHtml(item.status)} ${active}" type="button" data-date="${escapeHtml(item.date)}" aria-pressed="${active ? "true" : "false"}">
          <div class="date-main">
            <span>${escapeHtml(item.date)}</span>
            ${statusDot(item.status)}
          </div>
          <div class="date-meta">
            ${issueChips(item)}
            <span>${escapeHtml(item.latestModified)}</span>
          </div>
        </button>
      `;
    })
    .join("");
  list.querySelectorAll("[data-date]").forEach((button) => {
    button.addEventListener("click", () => selectDate(button.dataset.date));
  });
  renderDateMoreButton();
}

function renderDateMoreButton() {
  const button = qs("#showMoreDatesButton");
  if (!button) return;
  if (!state.project) {
    button.hidden = true;
    return;
  }
  const loaded = state.project.dates?.length || 0;
  const total = state.project.dateCount || loaded;
  const remaining = Math.max(total - loaded, 0);
  button.hidden = !state.project.hasMoreDates || remaining === 0;
  button.textContent = remaining > state.moreDateLimit
    ? `Show next ${state.moreDateLimit}`
    : `Show remaining ${remaining}`;
}

function mergeProjectSlice(payload, reset = false) {
  if (reset || !state.project || state.project.id !== payload.id) {
    state.project = {
      ...payload,
      dates: [],
      logsByDate: {},
    };
  } else {
    Object.assign(state.project, {
      ...payload,
      dates: state.project.dates,
      logsByDate: state.project.logsByDate,
    });
  }

  const seen = new Set(state.project.dates.map((item) => item.date));
  for (const item of payload.dates || []) {
    if (!seen.has(item.date)) {
      state.project.dates.push(item);
      seen.add(item.date);
    }
  }
  Object.assign(state.project.logsByDate, payload.logsByDate || {});
  state.project.hasMoreDates = Boolean(payload.hasMoreDates);
  state.project.loadedDateCount = state.project.dates.length;
}

function currentLogs() {
  if (!state.project || !state.selectedDate) return [];
  const logs = state.project.logsByDate[state.selectedDate] || [];
  const filtered = state.statusFilter
    ? logs.filter((log) => log.status === state.statusFilter)
    : logs;
  return [...filtered].sort((a, b) => {
    const rankDelta = (statusRank[b.status] || 0) - (statusRank[a.status] || 0);
    if (rankDelta) return rankDelta;
    return b.mtime - a.mtime;
  });
}

function renderLogs() {
  const list = qs("#logList");
  const logs = currentLogs();
  qs("#logCount").textContent = `${logs.length} files`;
  if (!logs.length) {
    list.innerHTML = `<div class="empty-state">No logs match this filter for the selected date.</div>`;
    qs("#selectedLogName").textContent = "No log selected";
    qs("#logContent").textContent = "";
    return;
  }
  list.innerHTML = logs
    .map((log) => {
      const active = log.path === state.selectedLogPath ? "active" : "";
      return `
        <button class="log-item tone-${escapeHtml(log.status)} ${active}" type="button" data-log="${escapeHtml(log.path)}" aria-pressed="${active ? "true" : "false"}">
          <div class="log-item-top">
            <strong>${escapeHtml(log.name)}</strong>
            ${statusDot(log.status)}
          </div>
          <div class="log-meta">
            ${issueChips(log)}
            <span>${escapeHtml(log.modified)}</span>
          </div>
        </button>
      `;
    })
    .join("");
  list.querySelectorAll("[data-log]").forEach((button) => {
    button.addEventListener("click", () => selectLog(button.dataset.log));
  });
}

function renderProjectHeading() {
  const project = state.project;
  if (!project) return;
  qs("#projectName").textContent = project.name;
  qs("#projectMeta").textContent = `${project.server} | latest log day ${project.latestDate || "-"}`;
  qs("#projectMeta").title = project.source;
  qs("#projectStatus").outerHTML = `<span id="projectStatus" class="status-pill status-${escapeHtml(project.status)}">${escapeHtml(STATUS_LABELS[project.status] || project.status)}</span>`;
}

function selectDate(date) {
  state.selectedDate = date;
  const logs = currentLogs();
  state.selectedLogPath = logs[0]?.path || null;
  state.rawContent = "";
  renderDates();
  renderLogs();
  if (state.selectedLogPath) {
    selectLog(state.selectedLogPath);
  } else {
    qs("#selectedLogName").textContent = "No log selected";
    qs("#logContent").textContent = "";
  }
}

async function selectLog(path) {
  if (!state.project) return;
  const requestId = state.logRequestId + 1;
  state.logRequestId = requestId;
  state.selectedLogPath = path;
  renderLogs();
  qs("#selectedLogName").textContent = `${path} | tail ${state.tailLines}`;
  qs("#logContent").textContent = "Loading...";
  try {
    const payload = await fetchLogData(state.project.id, path);
    if (requestId !== state.logRequestId || path !== state.selectedLogPath) return;
    state.rawContent = payload.content || "";
    renderLogContent();
    focusViewerOnMobile();
  } catch (error) {
    if (requestId !== state.logRequestId) return;
    state.rawContent = "";
    qs("#logContent").textContent = `Failed to load log: ${error.message}`;
  }
}

function lineHasIssue(line) {
  const lower = line.toLowerCase();
  return (
    lower.includes("traceback") ||
    lower.includes("exception") ||
    lower.includes("server error") ||
    lower.includes("http error") ||
    lower.includes("critical") ||
    lower.includes("fatal") ||
    /\bwarn(?:ing)?\b/.test(lower) ||
    (/\berror\b/.test(lower) && !/\b(?:no|0)\s+errors?\b|errors?=0/.test(lower)) ||
    (/\bfailed|failure\b/.test(lower) && !/\b(?:no|0)\s+failed\b|failed=0/.test(lower))
  );
}

function focusViewerOnMobile() {
  if (!window.matchMedia("(max-width: 760px)").matches) return;
  qs(".viewer").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderLogContent() {
  const query = qs("#searchInput").value.trim().toLowerCase();
  let lines = state.rawContent.split("\n");
  if (state.lineMode === "issues") {
    lines = lines.filter(lineHasIssue);
  }
  if (query) {
    lines = lines.filter((line) => line.toLowerCase().includes(query));
  }
  qs("#logContent").textContent = lines.join("\n") || "No matching lines.";
}

async function loadProject(projectId, preferredDate = null) {
  state.selectedProjectId = projectId;
  renderProjects();
  qs("#selectedLogName").textContent = "Loading project";
  qs("#logContent").textContent = "Loading...";
  const project = await fetchProjectData(projectId, 0, state.initialDateLimit);
  mergeProjectSlice(project, true);
  renderProjectHeading();
  const date = state.project.logsByDate[preferredDate]
    ? preferredDate
    : state.project.latestDate || state.project.dates?.[0]?.date || null;
  if (date) {
    selectDate(date);
  } else {
    renderDates();
    renderLogs();
    qs("#logContent").textContent = "";
  }
}

async function loadMoreDates() {
  if (!state.project?.hasMoreDates) return;
  const offset = state.project.dates.length;
  const projectId = state.project.id;
  const button = qs("#showMoreDatesButton");
  button.disabled = true;
  button.textContent = "Loading...";
  try {
    const payload = await fetchProjectData(projectId, offset, state.moreDateLimit);
    mergeProjectSlice(payload);
    renderDates();
  } finally {
    button.disabled = false;
  }
}

async function loadSummary(keepSelection = false) {
  const selected = keepSelection ? state.selectedProjectId : null;
  const selectedDate = keepSelection ? state.selectedDate : null;
  const previousGeneratedAt = state.summary?.generatedAt;
  state.summary = await fetchSummaryData();
  if (previousGeneratedAt && previousGeneratedAt !== state.summary.generatedAt) {
    state.staticProjectCache.clear();
  }
  setMetrics(state.summary);
  const projects = filteredProjects();
  const selectedVisible = projects.some((project) => project.id === selected);
  const projectId = selectedVisible ? selected : projects[0]?.id;
  state.selectedProjectId = projectId;
  renderProjects();
  if (projectId) {
    await loadProject(projectId, selectedDate);
  }
}

async function pollForUpdates() {
  if (!state.summary) return;
  const previousProject = state.project;
  const previousLatestDate = previousProject?.latestDate;
  const wasOnLatestDate = Boolean(previousProject && state.selectedDate === previousLatestDate);
  const selectedId = state.selectedProjectId;
  const nextSummary = await fetchSummaryData();
  if (state.summary.generatedAt !== nextSummary.generatedAt) {
    state.staticProjectCache.clear();
  }
  const nextSelected = nextSummary.projects.find((project) => project.id === selectedId);
  const changed = previousProject && nextSelected && (
    nextSelected.latestDate !== previousProject.latestDate ||
    nextSelected.status !== previousProject.status ||
    nextSelected.latestErrors !== previousProject.latestErrors ||
    nextSelected.latestWarnings !== previousProject.latestWarnings ||
    nextSelected.fileCount !== previousProject.fileCount
  );

  state.summary = nextSummary;
  setMetrics(state.summary);
  renderProjects();

  if (changed && selectedId) {
    await loadProject(selectedId, wasOnLatestDate ? null : state.selectedDate);
  }
}

function wireControls() {
  qs("#showMoreDatesButton").addEventListener("click", loadMoreDates);
  qs("#searchInput").addEventListener("input", renderLogContent);
  qs("#allLinesButton").addEventListener("click", () => {
    state.lineMode = "all";
    qs("#allLinesButton").classList.add("active");
    qs("#issueLinesButton").classList.remove("active");
    renderLogContent();
  });
  qs("#issueLinesButton").addEventListener("click", () => {
    state.lineMode = "issues";
    qs("#issueLinesButton").classList.add("active");
    qs("#allLinesButton").classList.remove("active");
    renderLogContent();
  });
}

wireControls();
loadSummary().catch((error) => {
  qs("#logContent").textContent = error.message;
});
setInterval(() => {
  pollForUpdates().catch((error) => {
    console.warn("Auto update failed", error);
  });
}, state.pollMs);
