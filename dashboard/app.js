const apiBase = window.STRATAONE_API_BASE || "http://localhost:8080";

const state = {
  sites: [],
  jobs: [],
  providers: [],
  inventory: null,
  selectedSite: null,
  selectedHardware: "generic-redfish",
  selectedPlatform: "azure-local",
  activeView: "overview",
  activeStep: "intent",
};

const els = {
  apiStatus: document.querySelector("#apiStatus"),
  viewTitle: document.querySelector("#viewTitle"),
  viewSubtitle: document.querySelector("#viewSubtitle"),
  siteYaml: document.querySelector("#siteYaml"),
  selectedYaml: document.querySelector("#selectedYaml"),
  sitesTable: document.querySelector("#sitesTable"),
  jobsList: document.querySelector("#jobsList"),
  overviewJobs: document.querySelector("#overviewJobs"),
  providerList: document.querySelector("#providerList"),
  inventoryList: document.querySelector("#inventoryList"),
  inventorySummary: document.querySelector("#inventorySummary"),
  resultOutput: document.querySelector("#resultOutput"),
  artifactOutput: document.querySelector("#artifactOutput"),
  artifactDetails: document.querySelector("#artifactDetails"),
  lastAction: document.querySelector("#lastAction"),
  siteCount: document.querySelector("#siteCount"),
  jobCount: document.querySelector("#jobCount"),
  successCount: document.querySelector("#successCount"),
  attentionCount: document.querySelector("#attentionCount"),
  selectedSiteLabel: document.querySelector("#selectedSiteLabel"),
  siteDetails: document.querySelector("#siteDetails"),
  fleetStrip: document.querySelector("#fleetStrip"),
  deploymentSummary: document.querySelector("#deploymentSummary"),
  bmcUsername: document.querySelector("#bmcUsername"),
  bmcPassword: document.querySelector("#bmcPassword"),
  bmcInsecure: document.querySelector("#bmcInsecure"),
  bmcTimeout: document.querySelector("#bmcTimeout"),
};

const viewCopy = {
  overview: ["Overview", "Fleet health, deployment readiness, and orchestration activity."],
  deployments: ["Deployments", "Create deployments and generate desired state for hardware and hypervisor targets."],
  sites: ["Sites", "Manage registered site definitions and run operational actions."],
  jobs: ["Jobs", "Inspect queued, running, failed, and completed orchestration jobs."],
  providers: ["Providers", "Review available hardware and platform providers."],
  artifacts: ["Artifacts", "Generate and inspect deployment bundles for selected sites."],
  lifecycle: ["Lifecycle", "Plan Day-2 controls such as drift, updates, and node replacement."],
};

const exampleYaml = toYaml(exampleSpec());
els.siteYaml.value = exampleYaml;

wireEvents();
renderDeploymentSummary(exampleSpec());
refreshAll();
setInterval(refreshJobs, 2500);

function wireEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  document.querySelectorAll(".step").forEach((button) => {
    button.addEventListener("click", () => showWizardStep(button.dataset.step));
  });
  document.querySelectorAll("[data-hardware]").forEach((button) => {
    button.addEventListener("click", () => selectChoice("hardware", button.dataset.hardware));
  });
  document.querySelectorAll("[data-platform]").forEach((button) => {
    button.addEventListener("click", () => selectChoice("platform", button.dataset.platform));
  });
  document.querySelector("#refreshAll").addEventListener("click", refreshAll);
  document.querySelector("#newDeploymentTop").addEventListener("click", () => showView("deployments"));
  document.querySelector("#newDeploymentSites").addEventListener("click", () => showView("deployments"));
  document.querySelector("#loadExample").addEventListener("click", () => {
    els.siteYaml.value = exampleYaml;
    renderDeploymentSummary(exampleSpec());
  });
  document.querySelector("#saveSite").addEventListener("click", () => saveSite(parseTinyYaml(els.siteYaml.value)));
  document.querySelector("#generateDesiredState").addEventListener("click", () => {
    const spec = deploymentSpecFromForm();
    els.siteYaml.value = toYaml(spec);
    renderDeploymentSummary(spec);
  });
  document.querySelector("#saveGeneratedDeployment").addEventListener("click", async () => {
    const spec = deploymentSpecFromForm();
    els.siteYaml.value = toYaml(spec);
    await saveSite(spec);
  });
  document.querySelector("#saveAndPlanDeployment").addEventListener("click", async () => {
    const spec = deploymentSpecFromForm();
    els.siteYaml.value = toYaml(spec);
    const record = await saveSite(spec);
    await runJob("plan", record.name);
  });
  document.querySelectorAll("[data-job]").forEach((button) => {
    button.addEventListener("click", () => runJob(button.dataset.job));
  });
}

function showView(view) {
  state.activeView = view;
  document.querySelectorAll(".view").forEach((section) => section.classList.remove("active"));
  document.querySelector(`#view-${view}`).classList.add("active");
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  const [title, subtitle] = viewCopy[view];
  els.viewTitle.textContent = title;
  els.viewSubtitle.textContent = subtitle;
}

function showWizardStep(step) {
  state.activeStep = step;
  document.querySelectorAll(".step").forEach((button) => button.classList.toggle("active", button.dataset.step === step));
  document.querySelectorAll(".wizard-page").forEach((page) => page.classList.toggle("active", page.dataset.page === step));
}

function selectChoice(type, value) {
  if (type === "hardware") state.selectedHardware = value;
  if (type === "platform") state.selectedPlatform = value;
  document.querySelectorAll(`[data-${type}]`).forEach((button) => {
    button.classList.toggle("selected", button.dataset[type] === value);
  });
  const spec = deploymentSpecFromForm();
  els.siteYaml.value = toYaml(spec);
  renderDeploymentSummary(spec);
}

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
  } catch {
    els.apiStatus.textContent = "API: offline";
    els.apiStatus.className = "status-pill fail";
  }
}

async function loadSites() {
  const data = await apiGet("/sites");
  state.sites = data.sites || [];
  if (!state.selectedSite && state.sites.length) state.selectedSite = state.sites[0].name;
  renderSites();
  renderFleet();
  await loadInventory();
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

async function saveSite(spec) {
  const record = await apiPost("/sites", { site: spec });
  state.selectedSite = record.name;
  writeResult("save site", record);
  await loadSites();
  showView("sites");
  return record;
}

async function runJob(action, siteName = state.selectedSite) {
  if (!siteName) return;
  const created = await apiPost(`/sites/${encodeURIComponent(siteName)}/jobs/${action}`, jobPayload(action));
  writeResult(`${action} queued`, created);
  await loadJobs();
  pollJob(created.job_id);
}

async function pollJob(jobId) {
  for (let i = 0; i < 24; i += 1) {
    const job = await apiGet(`/jobs/${encodeURIComponent(jobId)}`);
    writeResult(`${job.action} ${job.status}`, job.result || { error: job.error, status: job.status });
    await loadJobs();
    if (job.status === "succeeded" || job.status === "failed") {
      if (job.action === "inventory" && job.status === "succeeded") await loadInventory();
      if (job.action === "artifacts" && job.status === "succeeded") renderArtifactResult(job.result);
      return;
    }
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
  document.querySelectorAll("[data-site]").forEach((row) => row.addEventListener("click", () => selectSite(row.dataset.site)));
  renderSelectedSite();
}

function selectSite(name) {
  state.selectedSite = name;
  renderSites();
  loadInventory();
}

function renderSelectedSite() {
  const site = state.sites.find((item) => item.name === state.selectedSite);
  if (!site) {
    els.selectedSiteLabel.textContent = "none";
    els.siteDetails.innerHTML = "";
    els.artifactDetails.innerHTML = "";
    return;
  }
  els.selectedSiteLabel.textContent = site.name;
  els.selectedYaml.value = toYaml(site.spec);
  els.siteDetails.innerHTML = detailRows({
    Platform: site.platform,
    Hardware: site.hardware_provider,
    Nodes: site.nodes,
    Location: site.spec.site?.location || "-",
    Model: site.spec.site?.deployment_model || "-",
    Inventory: state.inventory ? `${state.inventory.reachable_nodes}/${state.inventory.total_nodes} reachable` : "not collected",
  });
  els.artifactDetails.innerHTML = detailRows({
    Site: site.name,
    Platform: site.platform,
    Cluster: site.spec.platform?.cluster_name || site.name,
    "Last action": latestJob("artifacts")?.status || "not generated",
  });
}

function renderFleet() {
  els.fleetStrip.innerHTML = state.sites.map((site) => {
    const latest = latestJobForSite(site.name);
    return `
      <button class="fleet-card" data-site="${escapeHtml(site.name)}">
        <strong>${escapeHtml(site.name)}</strong>
        <span>${escapeHtml(site.platform)} - ${escapeHtml(site.hardware_provider)} - ${site.nodes} nodes</span>
        <span>Latest job: ${latest ? `${latest.action} ${latest.status}` : "none"}</span>
      </button>
    `;
  }).join("") || `<div class="fleet-card"><strong>No sites</strong><span>Create a deployment to begin.</span></div>`;
  document.querySelectorAll(".fleet-card[data-site]").forEach((card) => card.addEventListener("click", () => {
    state.selectedSite = card.dataset.site;
    showView("sites");
    renderSites();
  }));
}

function renderJobs() {
  els.jobCount.textContent = state.jobs.length;
  const items = state.jobs.slice(0, 40).map(jobItem).join("") || `<div class="list-item"><strong>No jobs yet</strong><span>Run an action to create a tracked job.</span></div>`;
  els.jobsList.innerHTML = items;
  els.overviewJobs.innerHTML = state.jobs.slice(0, 6).map(jobItem).join("") || items;
  document.querySelectorAll("[data-job-id]").forEach((item) => {
    item.addEventListener("click", async () => {
      const job = await apiGet(`/jobs/${encodeURIComponent(item.dataset.jobId)}`);
      writeResult(`${job.action} ${job.status}`, job);
      if (job.action === "artifacts" && job.result) renderArtifactResult(job.result);
    });
  });
}

function jobItem(job) {
  return `
    <button class="list-item job-item" data-job-id="${escapeHtml(job.id)}">
      <strong>${escapeHtml(job.action)} <span class="status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span></strong>
      <span>${escapeHtml(job.site_name)} - ${formatDate(job.created_at)}</span>
    </button>
  `;
}

async function loadInventory() {
  if (!state.selectedSite) return;
  try {
    state.inventory = await apiGet(`/sites/${encodeURIComponent(state.selectedSite)}/inventory`);
  } catch {
    state.inventory = null;
  }
  renderInventory();
  renderSelectedSite();
}

function renderInventory() {
  if (!state.inventory) {
    els.inventorySummary.textContent = "No inventory collected";
    els.inventoryList.innerHTML = `<div class="list-item"><strong>No inventory yet</strong><span>Run Inventory with BMC credentials to collect hardware details.</span></div>`;
    return;
  }
  const report = state.inventory.report;
  els.inventorySummary.textContent = `${state.inventory.reachable_nodes}/${state.inventory.total_nodes} nodes reachable - ${formatDate(state.inventory.collected_at)}`;
  els.inventoryList.innerHTML = (report.nodes || []).map((node) => `
    <div class="list-item">
      <strong>${escapeHtml(node.serial)} <span class="${node.reachable ? "status-succeeded" : "status-failed"}">${node.reachable ? "reachable" : "unreachable"}</span></strong>
      <span>${escapeHtml(node.bmc_ip)} - ${escapeHtml([node.manufacturer, node.model].filter(Boolean).join(" ") || "model unknown")}</span>
      <span>BIOS ${escapeHtml(node.bios_version || "-")} - CPU ${node.processor_count ?? "-"} - Memory ${node.memory_gib ? `${node.memory_gib} GiB` : "-"}</span>
      <span>NICs ${(node.nics || []).length} - Storage ${(node.storage || []).length} - Capabilities ${(node.capabilities || []).join(", ") || "-"}</span>
      ${node.error ? `<span class="status-failed">${escapeHtml(node.error)}</span>` : ""}
    </div>
  `).join("");
}

function renderProviders() {
  els.providerList.innerHTML = state.providers.map((provider) => `
    <div class="list-item">
      <strong>${escapeHtml(provider.name)}</strong>
      <span>${escapeHtml(provider.type)} - ${escapeHtml(provider.source)}</span>
      <span>${escapeHtml(provider.description)}</span>
    </div>
  `).join("");
}

function renderArtifactResult(result) {
  els.artifactOutput.textContent = JSON.stringify(result, null, 2);
}

function renderMetrics() {
  els.successCount.textContent = state.jobs.filter((job) => job.status === "succeeded").length;
  els.attentionCount.textContent = state.jobs.filter((job) => job.status === "failed").length;
}

function deploymentSpecFromForm() {
  return {
    site: {
      name: value("#deployName"),
      location: value("#deployLocation"),
      deployment_model: value("#deployModel"),
    },
    hardware: {
      vendor: state.selectedHardware,
      nodes: [
        { serial: value("#node1Serial"), bmc_ip: value("#node1Bmc"), role: "host" },
        { serial: value("#node2Serial"), bmc_ip: value("#node2Bmc"), role: "host" },
      ].filter((node) => node.serial && node.bmc_ip),
    },
    network: {
      management_vlan: numberValue("#managementVlan"),
      storage_vlan: numberValue("#storageVlan"),
      vm_vlan: numberValue("#vmVlan"),
      dns_servers: csv("#dnsServers"),
      ntp_servers: csv("#ntpServers"),
    },
    platform: {
      type: state.selectedPlatform,
      topology: value("#topology"),
      cluster_name: value("#clusterName"),
      azure: {
        subscription_id: value("#subscriptionId"),
        tenant_id: value("#tenantId"),
        resource_group: value("#resourceGroup"),
        region: value("#azureRegion"),
      },
    },
    workloads: {
      aks: checked("#workloadAks"),
      avd: checked("#workloadAvd"),
      arc_vms: checked("#workloadArcVms"),
      kubernetes: state.selectedPlatform === "openshift-virtualization",
    },
  };
}

function renderDeploymentSummary(spec) {
  els.deploymentSummary.textContent = JSON.stringify({
    site: spec.site.name,
    hardware: spec.hardware.vendor,
    platform: spec.platform.type,
    topology: spec.platform.topology,
    nodes: spec.hardware.nodes.length,
    workloads: Object.entries(spec.workloads).filter(([, enabled]) => enabled).map(([name]) => name),
  }, null, 2);
}

function exampleSpec() {
  return {
    site: { name: "branch-001", location: "berlin", deployment_model: "edge-hci" },
    hardware: {
      vendor: "generic-redfish",
      nodes: [
        { serial: "ABC123", bmc_ip: "10.10.1.11", role: "host" },
        { serial: "ABC124", bmc_ip: "10.10.1.12", role: "host" },
      ],
    },
    network: {
      management_vlan: 100,
      storage_vlan: 110,
      vm_vlan: 120,
      dns_servers: ["10.10.0.10", "10.10.0.11"],
      ntp_servers: ["time.windows.com"],
    },
    platform: {
      type: "azure-local",
      topology: "two-node-switchless",
      cluster_name: "al-branch-001",
      azure: {
        subscription_id: "00000000-0000-0000-0000-000000000000",
        tenant_id: "00000000-0000-0000-0000-000000000000",
        resource_group: "rg-branch-001",
        region: "westeurope",
      },
    },
    workloads: { aks: true, avd: false, arc_vms: true, kubernetes: false },
  };
}

function jobPayload(action) {
  if (action !== "inventory") return {};
  return {
    username: els.bmcUsername.value || null,
    password: els.bmcPassword.value || null,
    insecure: els.bmcInsecure.checked,
    timeout: Number(els.bmcTimeout.value || 10),
  };
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
    if (isNested(item)) return `${pad}${key}:\n${toYaml(item, indent + 2)}`;
    return `${pad}${key}: ${formatScalar(item)}`;
  }).join("\n");
}

function isNested(value) {
  return typeof value === "object" && value !== null;
}

function detailRows(items) {
  return Object.entries(items).map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("");
}

function latestJob(action) {
  return state.jobs.find((job) => job.site_name === state.selectedSite && job.action === action);
}

function latestJobForSite(siteName) {
  return state.jobs.find((job) => job.site_name === siteName);
}

function writeResult(label, payload) {
  els.lastAction.textContent = label;
  els.resultOutput.textContent = JSON.stringify(payload, null, 2);
  if (els.artifactOutput && label.includes("artifacts")) els.artifactOutput.textContent = JSON.stringify(payload, null, 2);
}

function value(selector) {
  return document.querySelector(selector).value.trim();
}

function numberValue(selector) {
  return Number(value(selector));
}

function checked(selector) {
  return document.querySelector(selector).checked;
}

function csv(selector) {
  return value(selector).split(",").map((item) => item.trim()).filter(Boolean);
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
