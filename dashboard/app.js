const apiBase = window.STRATAONE_API_BASE || "http://localhost:8080";

const state = {
  sites: [],
  jobs: [],
  providers: [],
  selectedSite: null,
  pollTimer: null,
};

const els = {
  siteYaml: document.querySelector("#siteYaml"),
  apiStatus: document.querySelector("#apiStatus"),
  sitesTable: document.querySelector("#sitesTable"),
  jobsList: document.querySelector("#jobsList"),
  providerList: document.querySelector("#providerList"),
  resultOutput: document.querySelector("#resultOutput"),
  lastAction: document.querySelector("#lastAction"),
  siteCount: document.querySelector("#siteCount"),
  jobCount: document.querySelector("#jobCount"),
  successCount: document.querySelector("#successCount"),
  attentionCount: document.querySelector("#attentionCount"),
  selectedSiteLabel: document.querySelector("#selectedSiteLabel"),
  siteDetails: document.querySelector("#siteDetails"),
};

const exampleYaml = `site:
  name: branch-001
  location: berlin
  deployment_model: edge-hci

hardware:
  vendor: generic-redfish
  nodes:
    - serial: ABC123
      bmc_ip: 10.10.1.11
      role: host
    - serial: ABC124
      bmc_ip: 10.10.1.12
      role: host

network:
  management_vlan: 100
  storage_vlan: 110
  vm_vlan: 120
  dns_servers:
    - 10.10.0.10
    - 10.10.0.11
  ntp_servers:
    - time.windows.com

platform:
  type: azure-local
  topology: two-node-switchless
  cluster_name: al-branch-001
  azure:
    subscription_id: 00000000-0000-0000-0000-000000000000
    tenant_id: 00000000-0000-0000-0000-000000000000
    resource_group: rg-branch-001
    region: westeurope

workloads:
  aks: true
  arc_vms: true
`;

els.siteYaml.value = exampleYaml;

document.querySelector("#refreshAll").addEventListener("click", refreshAll);
document.querySelector("#loadExample").addEventListener("click", () => {
  els.siteYaml.value = exampleYaml;
  previewSite(parseTinyYaml(exampleYaml));
});
document.querySelector("#saveSite").addEventListener("click", saveSite);
document.querySelectorAll("[data-job]").forEach((button) => {
  button.addEventListener("click", () => runJob(button.dataset.job));
});

refreshAll();
state.pollTimer = setInterval(refreshJobs, 2500);

async function refreshAll() {
  await checkApi();
  await Promise.all([loadSites(), loadJobs(), loadProviders()]);
}

async function checkApi() {
  try {
    const response = await fetch(`${apiBase}/health`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    els.apiStatus.textContent = "API: online";
    els.apiStatus.className = "status-pill ok";
  } catch (error) {
    els.apiStatus.textContent = "API: offline";
    els.apiStatus.className = "status-pill fail";
  }
}

async function loadSites() {
  const data = await apiGet("/sites");
  state.sites = data.sites || [];
  if (!state.selectedSite && state.sites.length) state.selectedSite = state.sites[0].name;
  renderSites();
  renderMetrics();
}

async function loadJobs() {
  const data = await apiGet("/jobs");
  state.jobs = data.jobs || [];
  renderJobs();
  renderMetrics();
}

async function refreshJobs() {
  try {
    await loadJobs();
  } catch {
    return;
  }
}

async function loadProviders() {
  const data = await apiGet("/providers");
  state.providers = data.providers || [];
  renderProviders();
}

async function saveSite() {
  const site = parseTinyYaml(els.siteYaml.value);
  const record = await apiPost("/sites", { site });
  state.selectedSite = record.name;
  els.lastAction.textContent = "save site";
  els.resultOutput.textContent = JSON.stringify(record, null, 2);
  await loadSites();
}

async function runJob(action) {
  if (!state.selectedSite) return;
  const created = await apiPost(`/sites/${encodeURIComponent(state.selectedSite)}/jobs/${action}`, {});
  els.lastAction.textContent = `${action} queued`;
  els.resultOutput.textContent = JSON.stringify(created, null, 2);
  await loadJobs();
  pollJob(created.job_id);
}

async function pollJob(jobId) {
  for (let i = 0; i < 20; i += 1) {
    const job = await apiGet(`/jobs/${encodeURIComponent(jobId)}`);
    els.lastAction.textContent = `${job.action} ${job.status}`;
    els.resultOutput.textContent = JSON.stringify(job.result || { error: job.error, status: job.status }, null, 2);
    await loadJobs();
    if (job.status === "succeeded" || job.status === "failed") return;
    await sleep(600);
  }
}

function renderSites() {
  els.siteCount.textContent = state.sites.length;
  els.sitesTable.innerHTML = state.sites.map((site) => `
    <tr class="${site.name === state.selectedSite ? "selected" : ""}" data-site="${escapeHtml(site.name)}">
      <td>${escapeHtml(site.name)}</td>
      <td>${escapeHtml(site.platform)}</td>
      <td>${escapeHtml(site.hardware_provider)}</td>
      <td>${site.nodes}</td>
      <td>${formatDate(site.updated_at)}</td>
    </tr>
  `).join("") || `<tr><td colspan="5">No sites registered</td></tr>`;

  document.querySelectorAll("[data-site]").forEach((row) => {
    row.addEventListener("click", () => selectSite(row.dataset.site));
  });
  renderSelectedSite();
}

function selectSite(name) {
  state.selectedSite = name;
  renderSites();
}

function renderSelectedSite() {
  const site = state.sites.find((item) => item.name === state.selectedSite);
  if (!site) {
    els.selectedSiteLabel.textContent = "none";
    els.siteDetails.innerHTML = "";
    return;
  }
  els.selectedSiteLabel.textContent = site.name;
  els.siteYaml.value = toYaml(site.spec);
  els.siteDetails.innerHTML = `
    <dt>Platform</dt><dd>${escapeHtml(site.platform)}</dd>
    <dt>Hardware</dt><dd>${escapeHtml(site.hardware_provider)}</dd>
    <dt>Nodes</dt><dd>${site.nodes}</dd>
    <dt>Location</dt><dd>${escapeHtml(site.spec.site?.location || "-")}</dd>
    <dt>Model</dt><dd>${escapeHtml(site.spec.site?.deployment_model || "-")}</dd>
  `;
}

function previewSite(site) {
  els.selectedSiteLabel.textContent = site.site?.name || "draft";
  els.siteDetails.innerHTML = `
    <dt>Platform</dt><dd>${escapeHtml(site.platform?.type || "-")}</dd>
    <dt>Hardware</dt><dd>${escapeHtml(site.hardware?.vendor || "-")}</dd>
    <dt>Nodes</dt><dd>${site.hardware?.nodes?.length || 0}</dd>
    <dt>Location</dt><dd>${escapeHtml(site.site?.location || "-")}</dd>
    <dt>Model</dt><dd>${escapeHtml(site.site?.deployment_model || "-")}</dd>
  `;
}

function renderJobs() {
  els.jobCount.textContent = state.jobs.length;
  els.jobsList.innerHTML = state.jobs.slice(0, 20).map((job) => `
    <button class="list-item job-item" data-job-id="${escapeHtml(job.id)}">
      <strong>${escapeHtml(job.action)} <span class="status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span></strong>
      <span>${escapeHtml(job.site_name)} · ${formatDate(job.created_at)}</span>
    </button>
  `).join("") || `<div class="list-item"><strong>No jobs yet</strong><span>Run an action to create a tracked job.</span></div>`;

  document.querySelectorAll("[data-job-id]").forEach((item) => {
    item.addEventListener("click", async () => {
      const job = await apiGet(`/jobs/${encodeURIComponent(item.dataset.jobId)}`);
      els.lastAction.textContent = `${job.action} ${job.status}`;
      els.resultOutput.textContent = JSON.stringify(job, null, 2);
    });
  });
}

function renderProviders() {
  els.providerList.innerHTML = state.providers.map((provider) => `
    <div class="list-item">
      <strong>${escapeHtml(provider.name)}</strong>
      <span>${escapeHtml(provider.type)} · ${escapeHtml(provider.source)}</span>
      <span>${escapeHtml(provider.description)}</span>
    </div>
  `).join("");
}

function renderMetrics() {
  els.successCount.textContent = state.jobs.filter((job) => job.status === "succeeded").length;
  els.attentionCount.textContent = state.jobs.filter((job) => job.status === "failed").length;
}

async function apiGet(path) {
  const response = await fetch(`${apiBase}${path}`);
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function apiPost(path, body) {
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

function parseTinyYaml(text) {
  const lines = text.split(/\r?\n/);
  const root = {};
  const stack = [{ indent: -1, value: root }];

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    if (!rawLine.trim() || rawLine.trimStart().startsWith("#")) continue;
    const indent = rawLine.match(/^\s*/)[0].length;
    const line = rawLine.trim();

    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop();
    const parent = stack[stack.length - 1].value;

    if (line.startsWith("- ")) {
      const item = parseValueOrObject(line.slice(2));
      if (Array.isArray(parent)) parent.push(item);
      if (typeof item === "object" && item !== null) stack.push({ indent, value: item });
      continue;
    }

    const [key, ...rest] = line.split(":");
    const valueText = rest.join(":").trim();
    if (valueText === "") {
      const nextValue = nextMeaningfulLineIsList(lines, index) ? [] : {};
      parent[key] = nextValue;
      stack.push({ indent, value: nextValue });
    } else {
      parent[key] = parseScalar(valueText);
    }
  }
  return root;
}

function nextMeaningfulLineIsList(lines, currentIndex) {
  for (const line of lines.slice(currentIndex + 1)) {
    if (!line.trim()) continue;
    return line.trim().startsWith("- ");
  }
  return false;
}

function parseValueOrObject(valueText) {
  if (!valueText.includes(":")) return parseScalar(valueText);
  const [key, ...rest] = valueText.split(":");
  return { [key]: parseScalar(rest.join(":").trim()) };
}

function parseScalar(value) {
  if (value === "true") return true;
  if (value === "false") return false;
  if (/^\d+$/.test(value)) return Number(value);
  return value.replace(/^['"]|['"]$/g, "");
}

function toYaml(value, indent = 0) {
  const pad = " ".repeat(indent);
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (typeof item === "object" && item !== null) {
        const entries = Object.entries(item);
        const [firstKey, firstValue] = entries[0];
        const first = isNested(firstValue)
          ? `${pad}- ${firstKey}:\n${toYaml(firstValue, indent + 4)}`
          : `${pad}- ${firstKey}: ${formatScalar(firstValue)}`;
        const rest = entries.slice(1).map(([key, entryValue]) => {
          if (isNested(entryValue)) return `${pad}  ${key}:\n${toYaml(entryValue, indent + 4)}`;
          return `${pad}  ${key}: ${formatScalar(entryValue)}`;
        });
        return [first, ...rest].join("\n");
      }
      return `${pad}- ${formatScalar(item)}`;
    }).join("\n");
  }
  return Object.entries(value || {}).map(([key, item]) => {
    if (typeof item === "object" && item !== null) {
      return `${pad}${key}:\n${toYaml(item, indent + 2)}`;
    }
    return `${pad}${key}: ${formatScalar(item)}`;
  }).join("\n");
}

function isNested(value) {
  return typeof value === "object" && value !== null;
}

function formatScalar(value) {
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  return value ?? "";
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
