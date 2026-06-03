const apiBase = new URLSearchParams(window.location.search).get("api")
  || window.STRATAONE_API_BASE
  || "http://127.0.0.1:8080";

const state = {
  sites: [],
  jobs: [],
  providers: [],
  approvals: [],
  artifacts: [],
  isos: [],
  audit: [],
  sessions: [],
  discovery: [],
  settings: null,
  inventory: null,
  selectedJobId: null,
  selectedDetailTab: "overview",
  eventStreamAbort: null,
  selectedSite: null,
  jobFilter: "all",
  selectedHardware: "generic-redfish",
  selectedPlatform: "azure-local",
  authToken: localStorage.getItem("strataone.authToken") || "",
  authUser: localStorage.getItem("strataone.authUser") || "operator",
  activeView: "overview",
  activeStep: "intent",
  deploymentNodes: [
    { serial: "ABC123", bmc_ip: "10.10.1.11", role: "host" },
    { serial: "ABC124", bmc_ip: "10.10.1.12", role: "host" },
  ],
};

const productInfo = {
  name: "StrataOne",
  edition: "Enterprise preview",
  version: "0.1.0",
  developer: "John Goulden",
  organization: "VirtuArchitect",
  repository: "https://github.com/VirtuArchitect/StrataOne",
  license: "MIT",
  apiVersion: "0.1.0",
};

const wizardSteps = ["intent", "hardware", "platform", "network", "review"];

const els = {
  apiStatus: document.querySelector("#apiStatus"),
  userChip: document.querySelector(".user-chip"),
  viewTitle: document.querySelector("#viewTitle"),
  viewSubtitle: document.querySelector("#viewSubtitle"),
  siteYaml: document.querySelector("#siteYaml"),
  selectedYaml: document.querySelector("#selectedYaml"),
  sitesTable: document.querySelector("#sitesTable"),
  jobsList: document.querySelector("#jobsList"),
  overviewJobs: document.querySelector("#overviewJobs"),
  jobsFilterLabel: document.querySelector("#jobsFilterLabel"),
  approvalsList: document.querySelector("#approvalsList"),
  approvalRequestSite: document.querySelector("#approvalRequestSite"),
  approvalRequestAction: document.querySelector("#approvalRequestAction"),
  jobDetail: document.querySelector("#jobDetail"),
  jobDetailSubtitle: document.querySelector("#jobDetailSubtitle"),
  providerList: document.querySelector("#providerList"),
  nodeList: document.querySelector("#nodeList"),
  lifecycleGrid: document.querySelector("#lifecycleGrid"),
  lifecycleDetail: document.querySelector("#lifecycleDetail"),
  inventoryList: document.querySelector("#inventoryList"),
  inventorySummary: document.querySelector("#inventorySummary"),
  resultOutput: document.querySelector("#resultOutput"),
  artifactOutput: document.querySelector("#artifactOutput"),
  artifactDetails: document.querySelector("#artifactDetails"),
  artifactList: document.querySelector("#artifactList"),
  isoList: document.querySelector("#isoList"),
  deploymentDetailTitle: document.querySelector("#deploymentDetailTitle"),
  deploymentDetailSubtitle: document.querySelector("#deploymentDetailSubtitle"),
  deploymentDetailContent: document.querySelector("#deploymentDetailContent"),
  providerMatrix: document.querySelector("#providerMatrix"),
  discoveryList: document.querySelector("#discoveryList"),
  aboutGrid: document.querySelector("#aboutGrid"),
  settingsTitle: document.querySelector("#settingsTitle"),
  settingsSubtitle: document.querySelector("#settingsSubtitle"),
  settingsContent: document.querySelector("#settingsContent"),
  lastAction: document.querySelector("#lastAction"),
  siteCount: document.querySelector("#siteCount"),
  jobCount: document.querySelector("#jobCount"),
  successCount: document.querySelector("#successCount"),
  attentionCount: document.querySelector("#attentionCount"),
  selectedSiteLabel: document.querySelector("#selectedSiteLabel"),
  siteDetails: document.querySelector("#siteDetails"),
  siteActionStatus: document.querySelector("#siteActionStatus"),
  fleetStrip: document.querySelector("#fleetStrip"),
  deploymentSummary: document.querySelector("#deploymentSummary"),
  deploymentReadiness: document.querySelector("#deploymentReadiness"),
  bmcUsername: document.querySelector("#bmcUsername"),
  bmcPassword: document.querySelector("#bmcPassword"),
  bmcInsecure: document.querySelector("#bmcInsecure"),
  bmcTimeout: document.querySelector("#bmcTimeout"),
  bmcCredentialRef: document.querySelector("#bmcCredentialRef"),
  isoUrl: document.querySelector("#isoUrl"),
  isoRef: document.querySelector("#isoRef"),
  isoBootOnce: document.querySelector("#isoBootOnce"),
  discoveryProvider: document.querySelector("#discoveryProvider"),
  discoveryCredential: document.querySelector("#discoveryCredential"),
  authModal: document.querySelector("#authModal"),
  loginUsername: document.querySelector("#loginUsername"),
  loginPassword: document.querySelector("#loginPassword"),
};

const viewCopy = {
  overview: ["Overview", "Fleet health, deployment readiness, and orchestration activity."],
  deployments: ["Deployments", "Create deployments and generate desired state for hardware and hypervisor targets."],
  sites: ["Sites", "Manage registered site definitions and run operational actions."],
  "deployment-detail": ["Deployment Detail", "Inspect one deployment across nodes, runs, inventory, artifacts, and lifecycle."],
  jobs: ["Jobs", "Inspect queued, running, failed, and completed orchestration jobs."],
  approvals: ["Approvals", "Review and approve live infrastructure actions before execution."],
  providers: ["Providers", "Review available hardware and platform providers."],
  artifacts: ["Artifacts", "Generate and inspect deployment bundles for selected sites."],
  lifecycle: ["Lifecycle", "Plan Day-2 controls such as drift, updates, and node replacement."],
  settings: ["Settings", "Configure access posture, database, providers, artifacts, and audit policy."],
  about: ["About", "Version, ownership, licensing, and product information."],
};

const settingsCopy = {
  general: ["General", "Instance identity and runtime defaults"],
  access: ["Access & RBAC", "Role model and access-control posture"],
  secrets: ["Secrets", "Credential handling and secret-store posture"],
  database: ["Database", "Storage backend, counts, and persistence location"],
  providers: ["Providers", "Enabled hardware and platform providers"],
  api: ["API", "API exposure, docs, CORS, and session policy"],
  artifacts: ["Artifacts", "Artifact output and retention policy"],
  audit: ["Audit", "Audit and history-retention posture"],
};

const lifecycleItems = [
  {
    id: "firmware",
    title: "Firmware Compliance",
    summary: "Uses Redfish/OEM inventory baselines.",
    actions: ["Collect latest firmware inventory", "Compare against provider baseline", "Create remediation plan"],
  },
  {
    id: "updates",
    title: "Update Rings",
    summary: "Prepares staged rollout workflows.",
    actions: ["Assign site to update ring", "Schedule maintenance window", "Run staged update precheck"],
  },
  {
    id: "drift",
    title: "Drift Detection",
    summary: "Compares latest state to desired state.",
    actions: ["Run drift scan", "Review configuration differences", "Open remediation run"],
  },
  {
    id: "replacement",
    title: "Node Replacement",
    summary: "Guided rebuild flow for failed hosts.",
    actions: ["Validate replacement node", "Drain workloads", "Rejoin cluster and restore baseline"],
  },
];

const exampleYaml = toYaml(exampleSpec());
els.siteYaml.value = exampleYaml;

wireEvents();
renderAuthState();
renderNodeEditor();
renderLifecycle("firmware");
renderDeploymentSummary(exampleSpec());
renderAbout();
refreshAll();
setInterval(refreshJobs, 2500);

function wireEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", async () => {
      showView(button.dataset.view);
      if (button.dataset.view === "settings") await loadSettings();
    });
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
  document.querySelector("#refreshApprovals").addEventListener("click", loadApprovals);
  document.querySelector("#refreshJobDetail").addEventListener("click", refreshSelectedJobDetail);
  document.querySelector("#refreshDiscovery").addEventListener("click", loadDiscovery);
  document.querySelector("#refreshSettings").addEventListener("click", loadSettings);
  document.querySelector("#editSettingsSection").addEventListener("click", () => showSettingsEditor(activeSettingsSection()));
  document.querySelector("#logoutButton").addEventListener("click", toggleAuthSession);
  document.querySelector("#cancelLogin").addEventListener("click", hideAuthModal);
  document.querySelector("#addNode").addEventListener("click", addDeploymentNode);
  document.querySelector("#newProvider").addEventListener("click", () => showProviderForm());
  document.querySelector("#cancelProvider").addEventListener("click", hideProviderForm);
  document.querySelector("#cancelProviderConfig").addEventListener("click", hideProviderConfig);
  document.querySelector("#previousStep").addEventListener("click", previousWizardStep);
  document.querySelector("#nextStep").addEventListener("click", nextWizardStep);
  document.querySelector("#newDeploymentTop").addEventListener("click", () => showView("deployments"));
  document.querySelector("#newDeploymentSites").addEventListener("click", () => showView("deployments"));
  document.querySelector("#loadSelectedDeployment").addEventListener("click", loadSelectedDeploymentIntoWizard);
  document.querySelector("#editSelectedSite").addEventListener("click", loadSelectedDeploymentIntoWizard);
  document.querySelector("#deleteSelectedSite").addEventListener("click", deleteSelectedSite);
  document.querySelector("#saveSelectedYaml").addEventListener("click", () => saveSite(parseTinyYaml(els.selectedYaml.value)));
  document.querySelectorAll("[data-view-shortcut]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.viewShortcut));
  });
  document.querySelectorAll("[data-metric-link]").forEach((button) => {
    button.addEventListener("click", () => openMetricLink(button.dataset.metricLink));
  });
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
  document.querySelectorAll("[data-detail-tab]").forEach((button) => {
    button.addEventListener("click", () => showDeploymentDetailTab(button.dataset.detailTab));
  });
  document.querySelectorAll(".settings-tab").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!state.settings) await loadSettings();
      showSettingsSection(button.dataset.settingsSection);
    });
  });
  document.addEventListener("click", handleDocumentActions);
  document.addEventListener("submit", handleDocumentSubmit);
}

function showView(view) {
  state.activeView = view;
  document.querySelectorAll(".view").forEach((section) => {
    const active = section.id === `view-${view}`;
    section.classList.toggle("active", active);
    section.hidden = !active;
  });
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
  document.querySelectorAll(".wizard-page").forEach((page) => {
    const active = page.dataset.page === step;
    page.classList.toggle("active", active);
    page.hidden = !active;
  });
  const index = wizardSteps.indexOf(step);
  document.querySelector("#previousStep").disabled = index === 0;
  document.querySelector("#nextStep").textContent = index === wizardSteps.length - 1 ? "Review Ready" : "Next";
  if (step === "review") {
    const spec = deploymentSpecFromForm();
    els.siteYaml.value = toYaml(spec);
    renderDeploymentSummary(spec);
  }
}

function previousWizardStep() {
  const index = wizardSteps.indexOf(state.activeStep);
  showWizardStep(wizardSteps[Math.max(0, index - 1)]);
}

function nextWizardStep() {
  const index = wizardSteps.indexOf(state.activeStep);
  showWizardStep(wizardSteps[Math.min(wizardSteps.length - 1, index + 1)]);
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
  try {
    await Promise.all([loadSites(), loadJobs(), loadProviders(), loadApprovals(), loadSettings(), loadDiscovery(), loadIsos()]);
  } catch (error) {
    if (isAuthError(error)) {
      renderAuthRequired();
      return;
    }
    writeResult("refresh failed", { error: error.message });
  }
}

async function checkApi() {
  try {
    const response = await fetchWithTimeout(`${apiBase}/health`);
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
  renderApprovalRequestOptions();
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
  renderDiscoveryOptions();
}

async function loadApprovals() {
  const data = await apiGet("/approvals");
  state.approvals = data.approvals || [];
  renderApprovals();
}

async function loadAudit() {
  const data = await apiGet("/audit?limit=50");
  state.audit = data.audit || [];
}

async function loadSessions() {
  const data = await apiGet("/auth/sessions");
  state.sessions = data.sessions || [];
}

async function loadSettings() {
  try {
    const [settings] = await Promise.all([apiGet("/settings"), loadAudit(), loadSessions()]);
    state.settings = settings;
    renderDiscoveryOptions();
    showSettingsSection(activeSettingsSection());
  } catch (error) {
    if (isAuthError(error)) {
      state.settings = null;
      showSettingsSection(activeSettingsSection());
      handleAuthRequired("/settings requires sign in.");
      return;
    }
    if (els.settingsContent) {
      els.settingsContent.innerHTML = `<div class="settings-empty">Settings unavailable: ${escapeHtml(error.message)}</div>`;
    }
  }
}

async function loadDiscovery() {
  try {
    const data = await apiGet("/discovery");
    state.discovery = data.runs || [];
    renderDiscovery();
  } catch {
    state.discovery = [];
    renderDiscovery();
  }
}

async function loadIsos() {
  try {
    const data = await apiGet("/isos");
    state.isos = data.isos || [];
    renderIsos();
  } catch {
    state.isos = [];
    renderIsos();
  }
}

function activeSettingsSection() {
  return document.querySelector(".settings-tab.active")?.dataset.settingsSection || "general";
}

function showSettingsSection(section) {
  document.querySelectorAll(".settings-tab").forEach((button) => button.classList.toggle("active", button.dataset.settingsSection === section));
  if (!els.settingsContent) return;
  const [title, subtitle] = settingsCopy[section] || settingsCopy.general;
  els.settingsTitle.textContent = title;
  els.settingsSubtitle.textContent = subtitle;
  if (!state.settings) {
    els.settingsContent.innerHTML = `<div class="settings-empty">Loading settings...</div>`;
    return;
  }
  els.settingsContent.innerHTML = renderSettingsSection(section, state.settings[section]);
}

async function saveSite(spec) {
  const record = await apiPost("/sites", { site: spec });
  state.selectedSite = record.name;
  writeResult("save site", record);
  await loadSites();
  showView("sites");
  return record;
}

async function deleteSelectedSite() {
  if (!state.selectedSite) return;
  const deleted = await apiDelete(`/sites/${encodeURIComponent(state.selectedSite)}`);
  writeResult("delete site", deleted);
  state.selectedSite = null;
  state.inventory = null;
  await loadSites();
}

function loadSelectedDeploymentIntoWizard() {
  const site = state.sites.find((item) => item.name === state.selectedSite);
  if (!site) return;
  hydrateDeploymentForm(site.spec);
  els.siteYaml.value = toYaml(site.spec);
  renderDeploymentSummary(site.spec);
  showView("deployments");
}

async function runJob(action, siteName = state.selectedSite, extraParams = {}) {
  if (!siteName) return;
  try {
    const created = await apiPost(`/sites/${encodeURIComponent(siteName)}/jobs/${action}`, { ...jobPayload(action), ...extraParams });
    if (created.status === "approval-required") {
      writeResult(`${action} approval required`, created);
      writeSiteAction(`${action} requires approval ${created.approval_id}`, "info");
      await loadApprovals();
      showView("approvals");
      return;
    }
    writeResult(`${action} queued`, created);
    writeSiteAction(`${action} queued for ${siteName}`);
    await loadJobs();
    pollJob(created.job_id);
  } catch (error) {
    writeResult(`${action} failed`, { error: error.message, site: siteName });
    writeSiteAction(`${action} failed: ${error.message}`, "fail");
  }
}

async function pollJob(jobId) {
  for (let i = 0; i < 24; i += 1) {
    const job = await apiGet(`/jobs/${encodeURIComponent(jobId)}`);
    writeResult(`${job.action} ${job.status}`, job.result || { error: job.error, status: job.status });
    await loadJobs();
    if (job.status === "succeeded" || job.status === "failed") {
      writeSiteAction(`${job.action} ${job.status}`, job.status === "failed" ? "fail" : "ok");
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
      <td class="table-actions">
        <button class="mini secondary" data-edit-site="${escapeHtml(site.name)}">Edit</button>
        <button class="mini secondary" data-open-deployment="${escapeHtml(site.name)}">Open</button>
        <button class="mini danger" data-delete-site="${escapeHtml(site.name)}">Delete</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="6">No sites registered</td></tr>`;
  document.querySelectorAll("[data-site]").forEach((row) => row.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    selectSite(row.dataset.site);
  }));
  renderSelectedSite();
  updateMetricInteractivity();
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
  renderDeploymentDetail();
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
  const visibleJobs = filteredJobs();
  const emptyCopy = state.jobFilter === "all"
    ? ["No jobs yet", "Run an action to create a tracked job."]
    : [`No ${jobFilterLabel(state.jobFilter).toLowerCase()} jobs`, "Change the dashboard filter or run a matching action."];
  const items = visibleJobs.slice(0, 40).map(jobItem).join("") || `<div class="list-item"><strong>${emptyCopy[0]}</strong><span>${emptyCopy[1]}</span></div>`;
  els.jobsList.innerHTML = items;
  els.overviewJobs.innerHTML = state.jobs.slice(0, 6).map(jobItem).join("") || items;
  if (els.jobsFilterLabel) els.jobsFilterLabel.textContent = state.jobFilter === "all" ? "Tracked orchestration activity" : `${jobFilterLabel(state.jobFilter)} orchestration activity`;
  document.querySelectorAll("[data-job-id]").forEach((item) => {
    item.addEventListener("click", async (event) => {
      if (event.target.closest("button")) return;
      const job = await apiGet(`/jobs/${encodeURIComponent(item.dataset.jobId)}`);
      writeResult(`${job.action} ${job.status}`, job);
      if (job.action === "artifacts" && job.result) renderArtifactResult(job.result);
    });
  });
  if (state.selectedJobId) refreshSelectedJobDetail();
  updateMetricInteractivity();
}

function filteredJobs() {
  if (state.jobFilter === "all") return state.jobs;
  return state.jobs.filter((job) => job.status === state.jobFilter);
}

function jobFilterLabel(filter) {
  if (filter === "succeeded") return "Successful";
  if (filter === "failed") return "Attention";
  return "All";
}

function jobItem(job) {
  return `
    <div class="list-item job-item" data-job-id="${escapeHtml(job.id)}">
      <button class="job-main" data-open-job="${escapeHtml(job.id)}">
        <strong>${escapeHtml(job.action)} <span class="status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span></strong>
        <span>${escapeHtml(job.site_name)} - ${formatDate(job.created_at)}</span>
      </button>
      <button class="mini secondary" data-rerun-job="${escapeHtml(job.id)}">Rerun</button>
      ${["queued", "running"].includes(job.status) ? `<button class="mini danger" data-cancel-job="${escapeHtml(job.id)}">Cancel</button>` : ""}
    </div>
  `;
}

async function openJobDetail(jobId) {
  state.selectedJobId = jobId;
  const [job, events] = await Promise.all([
    apiGet(`/jobs/${encodeURIComponent(jobId)}`),
    apiGet(`/jobs/${encodeURIComponent(jobId)}/events`),
  ]);
  renderJobDetail(job, events.events || []);
  streamJobEvents(jobId);
  writeResult(`${job.action} ${job.status}`, job);
}

async function refreshSelectedJobDetail() {
  if (!state.selectedJobId || !els.jobDetail) return;
  try {
    await openJobDetail(state.selectedJobId);
  } catch (error) {
    els.jobDetail.innerHTML = `<div class="settings-empty">Run detail unavailable: ${escapeHtml(error.message)}</div>`;
  }
}

function renderJobDetail(job, events) {
  if (!els.jobDetail) return;
  els.jobDetailSubtitle.textContent = `${job.site_name} - ${job.action} - ${job.status}`;
  const timeline = jobTimeline(job, events);
  els.jobDetail.innerHTML = `
    <div class="settings-grid detail-metrics">
      ${settingCard("Status", job.status)}
      ${settingCard("Site", job.site_name)}
      ${settingCard("Action", job.action)}
      ${settingCard("Started", formatDate(job.started_at || job.created_at))}
      ${settingCard("Finished", formatDate(job.finished_at))}
      ${settingCard("Events", events.length)}
    </div>
    <div class="button-row detail-actions">
      <button data-rerun-job="${escapeHtml(job.id)}">Rerun</button>
      ${["queued", "running"].includes(job.status) ? `<button class="danger" data-cancel-job="${escapeHtml(job.id)}">Cancel</button>` : ""}
      <button class="secondary" data-copy-job-result="${escapeHtml(job.id)}">Inspect Result</button>
    </div>
    <div class="timeline">
      ${timeline.map((item) => `
        <div class="timeline-row ${escapeHtml(item.status)}">
          <span></span>
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <small>${escapeHtml(item.detail)}</small>
          </div>
        </div>
      `).join("")}
    </div>
    <h3>Event Stream</h3>
    <div class="event-list" id="activeEventList">
      ${events.map((event) => `
        <div class="event-row ${escapeHtml(event.level)}">
          <strong>${escapeHtml(event.message)}</strong>
          <span>${formatDate(event.created_at)} - ${escapeHtml(JSON.stringify(event.detail || {}))}</span>
        </div>
      `).join("") || `<div class="settings-empty">No events recorded yet.</div>`}
    </div>
  `;
}

async function streamJobEvents(jobId) {
  if (state.eventStreamAbort) state.eventStreamAbort.abort();
  if (!state.authToken) return;
  const controller = new AbortController();
  state.eventStreamAbort = controller;
  try {
    const response = await fetch(`${apiBase}/jobs/${encodeURIComponent(jobId)}/events/stream`, {
      headers: { Authorization: `Bearer ${state.authToken}` },
      signal: controller.signal,
    });
    if (!response.ok || !response.body) return;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      chunks.forEach(appendSseEvent);
    }
  } catch (error) {
    if (error.name !== "AbortError") writeResult("event stream failed", { error: error.message });
  }
}

function appendSseEvent(chunk) {
  const line = chunk.split("\n").find((item) => item.startsWith("data: "));
  if (!line) return;
  try {
    const event = JSON.parse(line.slice(6));
    const list = document.querySelector("#activeEventList");
    if (!list || list.querySelector(`[data-event-id="${event.id}"]`)) return;
    list.insertAdjacentHTML("beforeend", `
      <div class="event-row ${escapeHtml(event.level)}" data-event-id="${escapeHtml(event.id)}">
        <strong>${escapeHtml(event.message)}</strong>
        <span>${formatDate(event.created_at)} - ${escapeHtml(JSON.stringify(event.detail || {}))}</span>
      </div>
    `);
    list.scrollTop = list.scrollHeight;
  } catch {
    return;
  }
}

function jobTimeline(job, events) {
  const has = (text) => events.some((event) => event.message.toLowerCase().includes(text));
  return [
    { title: "Queued", detail: formatDate(job.created_at), status: "done" },
    { title: "Started", detail: job.started_at ? formatDate(job.started_at) : "Waiting for worker", status: job.started_at ? "done" : "pending" },
    { title: "Provider execution", detail: has("completed") || has("failed") ? "Provider contract executed" : "Awaiting provider result", status: job.status === "failed" ? "failed" : job.result ? "done" : "pending" },
    { title: "Completed", detail: job.finished_at ? formatDate(job.finished_at) : "Still running", status: job.status === "failed" ? "failed" : job.status === "succeeded" ? "done" : "pending" },
  ];
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
  renderDeploymentDetail();
}

async function loadArtifacts(siteName = state.selectedSite) {
  if (!siteName) return;
  try {
    const data = await apiGet(`/sites/${encodeURIComponent(siteName)}/artifacts/files`);
    state.artifacts = data.files || [];
  } catch {
    state.artifacts = [];
  }
  renderArtifactsList();
  renderDeploymentDetail();
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

function renderArtifactsList() {
  if (!els.artifactList) return;
  els.artifactList.innerHTML = state.artifacts.map((file) => `
    <button class="list-item artifact-item" data-artifact-file="${escapeHtml(file.name)}">
      <strong>${escapeHtml(file.name)}</strong>
      <span>${Math.ceil(file.size_bytes / 1024)} KB - ${formatDate(file.updated_at)}</span>
    </button>
  `).join("") || `<div class="list-item"><strong>No artifact files</strong><span>Generate artifacts for the selected site to populate this list.</span></div>`;
}

function openDeploymentDetail(siteName = state.selectedSite) {
  if (!siteName) return;
  state.selectedSite = siteName;
  state.selectedDetailTab = "overview";
  showView("deployment-detail");
  renderDeploymentDetail();
  loadInventory();
  loadArtifacts(siteName);
}

function showDeploymentDetailTab(tab) {
  state.selectedDetailTab = tab;
  document.querySelectorAll("[data-detail-tab]").forEach((button) => button.classList.toggle("active", button.dataset.detailTab === tab));
  renderDeploymentDetail();
  if (tab === "artifacts") loadArtifacts();
}

function renderDeploymentDetail() {
  if (!els.deploymentDetailContent) return;
  const site = state.sites.find((item) => item.name === state.selectedSite);
  if (!site) {
    els.deploymentDetailTitle.textContent = "Deployment Detail";
    els.deploymentDetailSubtitle.textContent = "No deployment selected";
    els.deploymentDetailContent.innerHTML = `<div class="settings-empty">Select or create a deployment to inspect operational detail.</div>`;
    return;
  }
  els.deploymentDetailTitle.textContent = site.name;
  els.deploymentDetailSubtitle.textContent = `${site.platform} - ${site.hardware_provider} - ${site.nodes} nodes`;
  document.querySelectorAll("[data-detail-tab]").forEach((button) => button.classList.toggle("active", button.dataset.detailTab === state.selectedDetailTab));
  const renderers = {
    overview: () => renderDeploymentOverview(site),
    nodes: () => renderDeploymentNodes(site),
    runs: () => renderDeploymentRuns(site),
    inventory: () => renderInventoryComparison(site),
    artifacts: () => renderDeploymentArtifacts(site),
    lifecycle: () => renderDeploymentLifecycle(site),
  };
  els.deploymentDetailContent.innerHTML = (renderers[state.selectedDetailTab] || renderers.overview)();
}

function renderDeploymentOverview(site) {
  return `
    <div class="settings-grid">
      ${settingCard("Platform", site.platform)}
      ${settingCard("Hardware", site.hardware_provider)}
      ${settingCard("Nodes", site.nodes)}
      ${settingCard("Location", site.spec.site?.location || "-")}
      ${settingCard("Model", site.spec.site?.deployment_model || "-")}
      ${settingCard("Latest Run", latestJobForSite(site.name)?.status || "none")}
    </div>
    <h3>Operational Readiness</h3>
    ${renderReadinessList(validateDeploymentSpec(site.spec))}
  `;
}

function renderDeploymentNodes(site) {
  return `
    <div class="settings-list">
      ${(site.spec.hardware?.nodes || []).map((node, index) => `
        <div class="settings-row">
          <div>
            <strong>${escapeHtml(node.serial || `Node ${index + 1}`)}</strong>
            <span>${escapeHtml(node.bmc_ip || "-")} - ${escapeHtml(node.role || "host")}</span>
          </div>
          <button class="mini secondary" data-edit-site="${escapeHtml(site.name)}">Edit</button>
        </div>
      `).join("")}
    </div>
  `;
}

function renderDeploymentRuns(site) {
  const jobs = state.jobs.filter((job) => job.site_name === site.name);
  return `<div class="settings-list">${jobs.map(jobItem).join("") || `<div class="settings-empty">No runs for this deployment.</div>`}</div>`;
}

function renderInventoryComparison(site) {
  const desired = site.spec.hardware?.nodes || [];
  const actual = state.inventory?.report?.nodes || [];
  return `
    <div class="settings-grid">
      ${settingCard("Desired Nodes", desired.length)}
      ${settingCard("Inventory Nodes", actual.length)}
      ${settingCard("Reachable", state.inventory ? `${state.inventory.reachable_nodes}/${state.inventory.total_nodes}` : "not collected")}
    </div>
    <div class="settings-list">
      ${desired.map((node) => {
        const observed = actual.find((item) => item.serial === node.serial || item.bmc_ip === node.bmc_ip);
        const status = observed ? (observed.reachable ? "matched" : "unreachable") : "missing";
        return `
          <div class="settings-row">
            <div>
              <strong>${escapeHtml(node.serial)} <span class="badge">${escapeHtml(status)}</span></strong>
              <span>Desired BMC ${escapeHtml(node.bmc_ip)}${observed ? ` - observed ${escapeHtml(observed.manufacturer || "")} ${escapeHtml(observed.model || "")}` : ""}</span>
              <span>Firmware ${(observed?.firmware || []).length} - NICs ${(observed?.nics || []).length} - Storage ${(observed?.storage || []).length}</span>
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderDeploymentArtifacts(site) {
  return `
    <div class="button-row detail-actions"><button data-job="artifacts">Generate Artifacts</button><button class="secondary" data-refresh-artifacts="${escapeHtml(site.name)}">Refresh Files</button></div>
    <div class="settings-list">
      ${state.artifacts.map((file) => `
        <div class="settings-row">
          <div>
            <strong>${escapeHtml(file.name)}</strong>
            <span>${Math.ceil(file.size_bytes / 1024)} KB - ${formatDate(file.updated_at)}</span>
          </div>
          <button class="mini secondary" data-artifact-file="${escapeHtml(file.name)}">View</button>
        </div>
      `).join("") || `<div class="settings-empty">No artifact files generated yet.</div>`}
    </div>
  `;
}

function renderDeploymentLifecycle(site) {
  return `
    <div class="settings-list">
      ${lifecycleItems.map((item) => `
        <div class="settings-row">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(item.summary)}</span>
          </div>
          <button class="mini secondary" data-lifecycle-run="${escapeHtml(item.id)}">Run</button>
        </div>
      `).join("")}
    </div>
  `;
}

function renderReadinessList(issues) {
  return issues.length
    ? `<div class="readiness-panel blocked"><strong>${issues.length} issue${issues.length === 1 ? "" : "s"}</strong><ul>${issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul></div>`
    : `<div class="readiness-panel ready"><strong>Ready</strong><span>Desired state passes dashboard readiness validation.</span></div>`;
}

function renderProviders() {
  renderProviderMatrix();
  els.providerList.innerHTML = state.providers.map((provider) => `
    <div class="list-item provider-card">
      <div>
        <strong class="provider-title">${providerNameMarkup(provider)} <span class="badge">${provider.vendor_supported ? "vendor supported" : "community"}</span></strong>
        <span>${escapeHtml(provider.type)} - ${escapeHtml(provider.source)}</span>
        <span>${escapeHtml(provider.description)}</span>
      </div>
      <div class="row-actions">
        <button class="mini secondary" data-provider-detail="${escapeHtml(provider.name)}">Details</button>
        <button class="mini secondary" data-edit-provider="${escapeHtml(provider.name)}">Edit</button>
        ${provider.editable ? `<button class="mini danger" data-delete-provider="${escapeHtml(provider.name)}">Remove</button>` : `<button class="mini secondary" disabled>Built-in</button>`}
      </div>
    </div>
  `).join("");
}

function renderDiscoveryOptions() {
  if (els.discoveryProvider) {
    const hardware = state.providers.filter((provider) => provider.type === "hardware");
    els.discoveryProvider.innerHTML = hardware.map((provider) => `<option value="${escapeHtml(provider.name)}">${escapeHtml(provider.name)}</option>`).join("");
  }
  if (els.discoveryCredential) {
    const refs = state.settings?.secrets?.refs || [];
    els.discoveryCredential.innerHTML = [
      `<option value="">No credential reference</option>`,
      ...refs.map((secret) => `<option value="${escapeHtml(secret.name)}">${escapeHtml(secret.name)} (${escapeHtml(secret.provider)})</option>`),
    ].join("");
  }
  if (els.bmcCredentialRef) {
    const refs = state.settings?.secrets?.refs || [];
    els.bmcCredentialRef.innerHTML = [
      `<option value="">Use transient fields or default vault</option>`,
      ...refs.filter((secret) => secret.type === "bmc").map((secret) => `<option value="${escapeHtml(secret.name)}">${escapeHtml(secret.name)}</option>`),
    ].join("");
  }
}

function renderDiscovery() {
  renderDiscoveryOptions();
  if (!els.discoveryList) return;
  els.discoveryList.innerHTML = state.discovery.map((run) => `
    <div class="settings-row">
      <div>
        <strong>${escapeHtml(run.name)} <span class="badge">${escapeHtml(run.status)}</span></strong>
        <span>${escapeHtml(run.cidr)} - ${escapeHtml(run.provider)} - ${formatDate(run.created_at)}</span>
        <span>${escapeHtml(run.result?.candidate_count || 0)} candidate BMC addresses planned</span>
      </div>
      <div class="row-actions">
        <button class="mini secondary" data-show-discovery="${escapeHtml(run.id)}">Inspect</button>
        <button class="mini" data-execute-discovery="${escapeHtml(run.id)}">Execute</button>
        <button class="mini danger" data-delete-discovery="${escapeHtml(run.id)}">Delete</button>
      </div>
    </div>
  `).join("") || `<div class="settings-empty">No discovery plans yet.</div>`;
}

function renderIsos() {
  if (els.isoRef) {
    els.isoRef.innerHTML = [
      `<option value="">Use ISO URL below</option>`,
      ...state.isos.map((iso) => `<option value="${escapeHtml(iso.name)}">${escapeHtml(iso.name)}</option>`),
    ].join("");
  }
  if (!els.isoList) return;
  els.isoList.innerHTML = state.isos.map((iso) => `
    <div class="settings-row">
      <div>
        <strong>${escapeHtml(iso.name)} <span class="badge">${escapeHtml(iso.status)}</span></strong>
        <span>${escapeHtml(iso.uri)}</span>
        <span>${iso.checksum ? `${escapeHtml(iso.checksum_algorithm)} ${escapeHtml(iso.checksum)}` : "No checksum registered"}</span>
      </div>
      <button class="mini danger" data-delete-iso="${escapeHtml(iso.name)}">Delete</button>
    </div>
  `).join("") || `<div class="settings-empty">No ISOs registered.</div>`;
}

function renderAbout() {
  if (!els.aboutGrid) return;
  els.aboutGrid.innerHTML = `
    ${settingCard("Product", productInfo.name)}
    ${settingCard("Edition", productInfo.edition)}
    ${settingCard("Version", productInfo.version)}
    ${settingCard("API Version", productInfo.apiVersion)}
    ${settingCard("Developer", productInfo.developer)}
    ${settingCard("Organization", productInfo.organization)}
    ${settingCard("License", productInfo.license)}
    <div class="setting-card">
      <span>GitHub</span>
      <strong><a href="${productInfo.repository}" target="_blank" rel="noreferrer">VirtuArchitect/StrataOne</a></strong>
    </div>
  `;
}

function renderProviderMatrix() {
  if (!els.providerMatrix) return;
  const capabilities = ["inventory", "power", "iso mount", "firmware", "deploy", "drift", "node replace"];
  els.providerMatrix.innerHTML = `
    <div class="matrix-header">
      <strong>Provider Capability Matrix</strong>
      <span>Configuration and supported operation posture</span>
    </div>
    <div class="capability-matrix">
      <div class="matrix-row matrix-head"><span>Provider</span>${capabilities.map((capability) => `<span>${escapeHtml(capability)}</span>`).join("")}</div>
      ${state.providers.map((provider) => `
        <div class="matrix-row">
          <span>${providerNameMarkup(provider)}</span>
          ${capabilities.map((capability) => `<span class="${providerCapability(provider, capability) ? "status-succeeded" : "status-running"}">${providerCapability(provider, capability) ? "Yes" : "Planned"}</span>`).join("")}
        </div>
      `).join("")}
    </div>
  `;
}

function providerCapability(provider, capability) {
  if (provider.type === "hardware") return ["inventory", "power", "iso mount", "firmware"].includes(capability);
  if (provider.name === "azure-local") return ["deploy", "drift", "node replace"].includes(capability);
  return ["drift"].includes(capability);
}

function renderApprovals() {
  if (!els.approvalsList) return;
  renderApprovalRequestOptions();
  els.approvalsList.innerHTML = state.approvals.map((approval) => `
    <div class="list-item approval-card">
      <div>
        <strong>${escapeHtml(approval.action)} <span class="badge">${escapeHtml(approval.status)}</span></strong>
        <span>${escapeHtml(approval.site_name)} - requested by ${escapeHtml(approval.requested_by)} - ${formatDate(approval.created_at)}</span>
        <span>${escapeHtml(JSON.stringify(approval.detail || {}))}</span>
      </div>
      <div class="row-actions">
        ${approval.status === "pending" ? `
          <button class="mini" data-approve="${escapeHtml(approval.id)}">Approve</button>
          <button class="mini" data-approve-run="${escapeHtml(approval.id)}">Approve & Run</button>
          <button class="mini danger" data-reject="${escapeHtml(approval.id)}">Reject</button>
        ` : `<button class="mini secondary" disabled>${escapeHtml(approval.status)}</button>`}
      </div>
    </div>
  `).join("") || `<div class="list-item"><strong>No pending approvals</strong><span>Live actions that require approval will appear here.</span></div>`;
}

function renderApprovalRequestOptions() {
  if (!els.approvalRequestSite) return;
  els.approvalRequestSite.innerHTML = state.sites.map((site) => `
    <option value="${escapeHtml(site.name)}" ${site.name === state.selectedSite ? "selected" : ""}>${escapeHtml(site.name)}</option>
  `).join("") || `<option value="">No sites available</option>`;
}

function renderNodeEditor() {
  els.nodeList.innerHTML = state.deploymentNodes.map((node, index) => `
    <div class="node-row" data-node-index="${index}">
      <label>Serial<input data-node-field="serial" value="${escapeHtml(node.serial)}" /></label>
      <label>BMC IP<input data-node-field="bmc_ip" value="${escapeHtml(node.bmc_ip)}" /></label>
      <label>Role<input data-node-field="role" value="${escapeHtml(node.role || "host")}" /></label>
      <button class="mini danger" data-remove-node="${index}" ${state.deploymentNodes.length === 1 ? "disabled" : ""}>Remove</button>
    </div>
  `).join("");
}

function syncDeploymentNodesFromEditor() {
  state.deploymentNodes = [...document.querySelectorAll("[data-node-index]")].map((row) => ({
    serial: row.querySelector('[data-node-field="serial"]').value.trim(),
    bmc_ip: row.querySelector('[data-node-field="bmc_ip"]').value.trim(),
    role: row.querySelector('[data-node-field="role"]').value.trim() || "host",
  })).filter((node) => node.serial || node.bmc_ip);
}

function addDeploymentNode() {
  syncDeploymentNodesFromEditor();
  state.deploymentNodes.push({ serial: "", bmc_ip: "", role: "host" });
  renderNodeEditor();
}

function removeDeploymentNode(index) {
  syncDeploymentNodesFromEditor();
  state.deploymentNodes.splice(index, 1);
  if (!state.deploymentNodes.length) state.deploymentNodes.push({ serial: "", bmc_ip: "", role: "host" });
  renderNodeEditor();
}

function showProviderForm(provider) {
  document.querySelector("#providerForm").hidden = false;
  setValue("#providerName", provider?.name || "");
  setValue("#providerType", provider?.type || "hardware");
  setValue("#providerDescription", provider?.description || "");
  document.querySelector("#providerSupported").checked = Boolean(provider?.vendor_supported);
  document.querySelector("#providerName").disabled = Boolean(provider && !provider.editable);
  document.querySelector("#providerName").focus();
}

function hideProviderForm() {
  document.querySelector("#providerForm").hidden = true;
  document.querySelector("#providerName").disabled = false;
}

function hideProviderConfig() {
  document.querySelector("#providerConfigForm").hidden = true;
}

function renderLifecycle(activeId) {
  const active = lifecycleItems.find((item) => item.id === activeId) || lifecycleItems[0];
  els.lifecycleGrid.innerHTML = lifecycleItems.map((item) => `
    <button class="capability ${item.id === active.id ? "active" : ""}" data-lifecycle="${escapeHtml(item.id)}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.summary)}</span>
    </button>
  `).join("");
  els.lifecycleDetail.innerHTML = `
    <div class="panel-header">
      <div>
        <h2>${escapeHtml(active.title)}</h2>
        <span>${escapeHtml(active.summary)}</span>
      </div>
      <button data-lifecycle-run="${escapeHtml(active.id)}">Open Workflow</button>
    </div>
    <ol class="flow-list">
      ${active.actions.map((action) => `<li><strong>${escapeHtml(action)}</strong><span>Ready for guided workflow implementation.</span></li>`).join("")}
    </ol>
  `;
}

function renderSettingsSection(section, data) {
  if (!data) return `<div class="settings-empty">No settings found for ${escapeHtml(section)}.</div>`;
  if (section === "access") {
    return `
      <div class="settings-grid">
        ${settingCard("Mode", data.mode)}
        ${settingCard("RBAC Enforced", data.rbac_enforced ? "enabled" : "planned")}
        ${settingCard("OIDC", data.oidc_enabled ? "configured" : "not configured")}
      </div>
      <div class="rbac-grid">
        <form class="settings-form" id="roleForm">
          <h3>Create / Edit Role</h3>
          <label>Role Name<input id="roleName" placeholder="Change Manager" /></label>
          <label>Description<input id="roleDescription" placeholder="Approves deployment changes" /></label>
          <label>Permissions<input id="rolePermissions" placeholder="approve-runs, read-audit" /></label>
          <div class="permission-picker">
            ${(data.permissions || []).map((permission) => `<label><input type="checkbox" data-permission="${escapeHtml(permission)}" /> ${escapeHtml(permission)}</label>`).join("")}
          </div>
          <button type="submit">Save Role</button>
        </form>
        <form class="settings-form" id="userForm">
          <h3>Create / Edit User</h3>
          <label>Username<input id="accessUsername" placeholder="j.smith" /></label>
          <label>Display Name<input id="accessDisplayName" placeholder="Jane Smith" /></label>
          <label>Email<input id="accessEmail" placeholder="jane.smith@example.com" /></label>
          <label>Password<input id="accessPassword" type="password" autocomplete="new-password" placeholder="Set or rotate password" /></label>
          <label>Role
            <select id="accessRole">
              ${roleOptions(data.roles || [])}
            </select>
          </label>
          <label>Status
            <select id="accessStatus">
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
          <button type="submit">Save User</button>
        </form>
      </div>
      <h3>Roles</h3>
      <div class="settings-list">
        ${(data.roles || []).map((role) => `
          <div class="settings-row">
            <div>
              <strong>${escapeHtml(role.name)} ${role.built_in ? '<span class="badge">built-in</span>' : ""}</strong>
              <span>${escapeHtml(role.description || "No description")}</span>
              <span>${escapeHtml((role.permissions || []).join(", "))}</span>
            </div>
            <div class="row-actions">
              <button class="mini secondary" data-edit-role="${escapeHtml(role.name)}">Edit</button>
              ${role.built_in ? "" : `<button class="mini danger" data-delete-role="${escapeHtml(role.name)}">Delete</button>`}
            </div>
          </div>
        `).join("")}
      </div>
      <h3>Users</h3>
      <div class="settings-list">
        ${(data.users || []).map((user) => `
          <div class="settings-row">
            <div>
              <strong>${escapeHtml(user.display_name)} <span class="badge">${escapeHtml(user.status)}</span></strong>
              <span>${escapeHtml(user.username)} - ${escapeHtml(user.email)}</span>
              <span>${escapeHtml((user.roles || []).join(", ") || "No roles assigned")}</span>
            </div>
            <div class="row-actions">
              <button class="mini secondary" data-edit-user="${escapeHtml(user.username)}">Edit</button>
              <button class="mini danger" data-delete-user="${escapeHtml(user.username)}">Delete</button>
            </div>
          </div>
        `).join("")}
      </div>
      <h3>Active Sessions</h3>
      <div class="settings-list">
        ${state.sessions.map((session) => `
          <div class="settings-row">
            <div>
              <strong>${escapeHtml(session.username)} <span class="badge">${escapeHtml(session.token_fingerprint)}</span></strong>
              <span>Created ${formatDate(session.created_at)} - expires ${formatDate(session.expires_at)}</span>
            </div>
            <button class="mini danger" data-revoke-session="${escapeHtml(session.id)}">Revoke</button>
          </div>
        `).join("") || `<div class="settings-empty">No active sessions.</div>`}
      </div>
    `;
  }
  if (section === "providers") {
    return `
      <div class="settings-grid">
        ${settingCard("Plugin Directory", data.plugin_dir)}
        ${settingCard("Hardware Providers", (data.hardware || []).length)}
        ${settingCard("Platform Providers", (data.platform || []).length)}
      </div>
      <h3>Hardware</h3>
      <div class="settings-list">${(data.hardware || []).map(providerRow).join("")}</div>
      <h3>Platform</h3>
      <div class="settings-list">${(data.platform || []).map(providerRow).join("")}</div>
    `;
  }
  if (section === "secrets") {
    return `
      <div class="settings-grid">
        ${settingCard("Vault Provider", data.vault_provider)}
        ${settingCard("Vault File", data.vault_file_configured ? "configured" : "not configured")}
        ${settingCard("HashiCorp Vault", data.hashicorp_vault_configured ? "configured" : "not configured")}
      </div>
      <form class="settings-form" id="secretRefForm">
        <h3>Create / Edit Secret Reference</h3>
        <div class="form-grid">
          <label>Name<input id="secretName" placeholder="branch-bmc" /></label>
          <label>Type
            <select id="secretType">
              <option value="bmc">BMC credentials</option>
              <option value="azure">Azure credentials</option>
              <option value="provider">Provider token</option>
              <option value="generic">Generic secret</option>
            </select>
          </label>
          <label>Provider
            <select id="secretProvider">
              <option value="env">Environment</option>
              <option value="file">File vault</option>
              <option value="vault">HashiCorp Vault</option>
            </select>
          </label>
          <label>Reference<input id="secretReference" placeholder="STRATAONE_BMC_PASSWORD or secret/data/branch/bmc" /></label>
        </div>
        <span class="form-help">Secret values are not displayed in the dashboard. Store only the external reference used by workers.</span>
        <button type="submit">Save Secret Reference</button>
      </form>
      <h3>Secret References</h3>
      <div class="settings-list">
        ${(data.refs || []).map((secret) => `
          <div class="settings-row">
            <div>
              <strong>${escapeHtml(secret.name)} <span class="badge">${escapeHtml(secret.type)}</span></strong>
              <span>${escapeHtml(secret.provider)} - ${escapeHtml(secret.reference)}</span>
              <span>Updated ${formatDate(secret.updated_at)}</span>
            </div>
            <button class="mini danger" data-delete-secret="${escapeHtml(secret.name)}">Delete</button>
          </div>
        `).join("") || `<div class="settings-empty">No secret references configured.</div>`}
      </div>
    `;
  }
  if (section === "api") {
    return `
      <div class="settings-grid">
        ${settingCard("CORS", data.cors)}
        ${settingCard("Docs", data.docs)}
        ${settingCard("Health", data.health)}
        ${settingCard("Session Timeout", `${data.session_timeout_minutes} minutes`)}
        ${settingCard("Approval Actions", (data.approval_required_actions || []).join(", ") || "none")}
      </div>
    `;
  }
  if (section === "audit") {
    return `
      <div class="settings-grid">
        ${settingCard("Audit Events", state.audit.length)}
        ${settingCard("Tracking", data.configuration_change_tracking)}
        ${settingCard("Retention", `${data.job_history_retention_days} days`)}
      </div>
      <div class="settings-list">
        ${state.audit.map((item) => `
          <div class="settings-row">
            <div>
              <strong>${escapeHtml(item.action)} <span class="badge">${escapeHtml(item.actor)}</span></strong>
              <span>${escapeHtml(item.resource)} - ${formatDate(item.created_at)}</span>
              <span>${escapeHtml(JSON.stringify(item.detail || {}))}</span>
            </div>
          </div>
        `).join("") || `<div class="settings-empty">No audit events recorded.</div>`}
      </div>
    `;
  }
  return `<div class="settings-grid">${Object.entries(data).map(([key, value]) => settingCard(labelize(key), formatSettingValue(value))).join("")}</div>`;
}

function showSettingsEditor(section) {
  if (section === "access") {
    document.querySelector("#roleName")?.focus();
    return;
  }
  const data = state.settings?.[section];
  if (!data) return;
  els.settingsContent.innerHTML = `
    <form class="settings-form wide" id="settingsJsonForm">
      <h3>Edit ${escapeHtml(settingsCopy[section]?.[0] || section)}</h3>
      <textarea id="settingsJsonEditor" spellcheck="false">${escapeHtml(JSON.stringify(data, null, 2))}</textarea>
      <div class="button-row"><button type="submit">Preview Settings</button><button class="secondary" type="button" data-settings-cancel>Cancel</button></div>
    </form>
  `;
}

async function handleDocumentActions(event) {
  const openJob = event.target.closest("[data-open-job]");
  if (openJob) {
    await openJobDetail(openJob.dataset.openJob);
    return;
  }
  const copyJobResult = event.target.closest("[data-copy-job-result]");
  if (copyJobResult) {
    const job = await apiGet(`/jobs/${encodeURIComponent(copyJobResult.dataset.copyJobResult)}`);
    writeResult(`${job.action} result`, job.result || { status: job.status, error: job.error });
    return;
  }
  const rerunJob = event.target.closest("[data-rerun-job]");
  if (rerunJob) {
    const result = await apiPost(`/jobs/${encodeURIComponent(rerunJob.dataset.rerunJob)}/retry`, {});
    writeResult("job retry queued", result);
    await loadJobs();
    return;
  }
  const cancelJob = event.target.closest("[data-cancel-job]");
  if (cancelJob) {
    const result = await apiPost(`/jobs/${encodeURIComponent(cancelJob.dataset.cancelJob)}/cancel`, {});
    writeResult("job canceled", result);
    await loadJobs();
    if (state.selectedJobId === cancelJob.dataset.cancelJob) await refreshSelectedJobDetail();
    return;
  }
  const approve = event.target.closest("[data-approve]");
  if (approve) {
    const result = await apiPost(`/approvals/${encodeURIComponent(approve.dataset.approve)}/approve`, {});
    writeResult("approval approved", result);
    await loadApprovals();
    return;
  }
  const approveRun = event.target.closest("[data-approve-run]");
  if (approveRun) {
    const result = await apiPost(`/approvals/${encodeURIComponent(approveRun.dataset.approveRun)}/run`, {});
    writeResult("approval approved and queued", result);
    await Promise.all([loadApprovals(), loadJobs()]);
    showView("jobs");
    await openJobDetail(result.job_id);
    return;
  }
  const reject = event.target.closest("[data-reject]");
  if (reject) {
    const result = await apiPost(`/approvals/${encodeURIComponent(reject.dataset.reject)}/reject`, { reason: "Rejected from dashboard" });
    writeResult("approval rejected", result);
    await loadApprovals();
    return;
  }
  const removeNode = event.target.closest("[data-remove-node]");
  if (removeNode) {
    removeDeploymentNode(Number(removeNode.dataset.removeNode));
    return;
  }
  const lifecycle = event.target.closest("[data-lifecycle]");
  if (lifecycle) {
    renderLifecycle(lifecycle.dataset.lifecycle);
    return;
  }
  const lifecycleRun = event.target.closest("[data-lifecycle-run]");
  if (lifecycleRun) {
    const action = lifecycleRun.dataset.lifecycleRun === "drift" ? "drift-detect"
      : lifecycleRun.dataset.lifecycleRun === "replacement" ? "node-replacement"
      : "preflight";
    await runJob(action);
    showView("jobs");
    return;
  }
  const providerDetail = event.target.closest("[data-provider-detail]");
  if (providerDetail) {
    await showProviderDetail(providerDetail.dataset.providerDetail);
    return;
  }
  const testProvider = event.target.closest("[data-test-provider]");
  if (testProvider) {
    const result = await apiPost(`/providers/${encodeURIComponent(testProvider.dataset.testProvider)}/test`, {});
    writeResult("provider test", result);
    return;
  }
  const editProvider = event.target.closest("[data-edit-provider]");
  if (editProvider) {
    const provider = state.providers.find((item) => item.name === editProvider.dataset.editProvider);
    if (provider) showProviderForm(provider);
    return;
  }
  const deleteProvider = event.target.closest("[data-delete-provider]");
  if (deleteProvider) {
    await apiDelete(`/providers/${encodeURIComponent(deleteProvider.dataset.deleteProvider)}`);
    await loadProviders();
    await loadSettings();
    return;
  }
  const deleteSecret = event.target.closest("[data-delete-secret]");
  if (deleteSecret) {
    const result = await apiDelete(`/secrets/${encodeURIComponent(deleteSecret.dataset.deleteSecret)}`);
    writeResult("secret reference deleted", result);
    await loadSettings();
    return;
  }
  const showDiscovery = event.target.closest("[data-show-discovery]");
  if (showDiscovery) {
    const run = state.discovery.find((item) => item.id === showDiscovery.dataset.showDiscovery);
    writeResult("discovery plan", run || {});
    return;
  }
  const executeDiscovery = event.target.closest("[data-execute-discovery]");
  if (executeDiscovery) {
    const result = await apiPost(`/discovery/${encodeURIComponent(executeDiscovery.dataset.executeDiscovery)}/execute`, {});
    writeResult("discovery executed", result);
    await loadDiscovery();
    return;
  }
  const deleteDiscovery = event.target.closest("[data-delete-discovery]");
  if (deleteDiscovery) {
    const result = await apiDelete(`/discovery/${encodeURIComponent(deleteDiscovery.dataset.deleteDiscovery)}`);
    writeResult("discovery deleted", result);
    await loadDiscovery();
    return;
  }
  const deleteIso = event.target.closest("[data-delete-iso]");
  if (deleteIso) {
    const result = await apiDelete(`/isos/${encodeURIComponent(deleteIso.dataset.deleteIso)}`);
    writeResult("iso deleted", result);
    await loadIsos();
    return;
  }
  const editSite = event.target.closest("[data-edit-site]");
  if (editSite) {
    state.selectedSite = editSite.dataset.editSite;
    loadSelectedDeploymentIntoWizard();
    return;
  }
  const openDeployment = event.target.closest("[data-open-deployment]");
  if (openDeployment) {
    openDeploymentDetail(openDeployment.dataset.openDeployment);
    return;
  }
  const deleteSite = event.target.closest("[data-delete-site]");
  if (deleteSite) {
    state.selectedSite = deleteSite.dataset.deleteSite;
    await deleteSelectedSite();
    return;
  }
  const editRole = event.target.closest("[data-edit-role]");
  if (editRole) {
    const role = state.settings?.access?.roles?.find((item) => item.name === editRole.dataset.editRole);
    if (role) {
      document.querySelector("#roleName").value = role.name;
      document.querySelector("#roleDescription").value = role.description || "";
      document.querySelector("#rolePermissions").value = (role.permissions || []).join(", ");
      document.querySelectorAll("[data-permission]").forEach((input) => {
        input.checked = (role.permissions || []).includes(input.dataset.permission);
      });
    }
    return;
  }
  const deleteRole = event.target.closest("[data-delete-role]");
  if (deleteRole) {
    await apiDelete(`/access/roles/${encodeURIComponent(deleteRole.dataset.deleteRole)}`);
    await loadSettings();
    return;
  }
  const editUser = event.target.closest("[data-edit-user]");
  if (editUser) {
    const user = state.settings?.access?.users?.find((item) => item.username === editUser.dataset.editUser);
    if (user) {
      document.querySelector("#accessUsername").value = user.username;
      document.querySelector("#accessDisplayName").value = user.display_name;
      document.querySelector("#accessEmail").value = user.email;
      document.querySelector("#accessPassword").value = "";
      document.querySelector("#accessRole").value = (user.roles || [])[0] || "";
      document.querySelector("#accessStatus").value = user.status;
    }
    return;
  }
  const deleteUser = event.target.closest("[data-delete-user]");
  if (deleteUser) {
    await apiDelete(`/access/users/${encodeURIComponent(deleteUser.dataset.deleteUser)}`);
    await loadSettings();
    return;
  }
  const revokeSession = event.target.closest("[data-revoke-session]");
  if (revokeSession) {
    const result = await apiDelete(`/auth/sessions/${encodeURIComponent(revokeSession.dataset.revokeSession)}`);
    writeResult("session revoked", result);
    await loadSettings();
    return;
  }
  if (event.target.closest("[data-settings-cancel]")) {
    showSettingsSection(activeSettingsSection());
    return;
  }
  const artifactFile = event.target.closest("[data-artifact-file]");
  if (artifactFile) {
    await openArtifactFile(artifactFile.dataset.artifactFile);
    return;
  }
  const refreshArtifacts = event.target.closest("[data-refresh-artifacts]");
  if (refreshArtifacts) {
    await loadArtifacts(refreshArtifacts.dataset.refreshArtifacts);
    return;
  }
}

async function handleDocumentSubmit(event) {
  if (event.target.id === "providerForm") {
    event.preventDefault();
    const provider = await apiPost("/providers", {
      name: value("#providerName"),
      type: value("#providerType"),
      description: value("#providerDescription"),
      vendor_supported: document.querySelector("#providerSupported").checked,
    });
    writeResult("provider saved", provider);
    hideProviderForm();
    await loadProviders();
    await loadSettings();
    return;
  }
  if (event.target.id === "providerConfigForm") {
    event.preventDefault();
    const providerName = document.querySelector("#providerConfigForm").dataset.providerName;
    const config = JSON.parse(document.querySelector("#providerConfigJson").value || "{}");
    const saved = await apiPost(`/providers/${encodeURIComponent(providerName)}/config`, { config });
    writeResult("provider config saved", saved);
    return;
  }
  if (event.target.id === "secretRefForm") {
    event.preventDefault();
    const saved = await apiPost("/secrets", {
      name: value("#secretName"),
      type: value("#secretType"),
      provider: value("#secretProvider"),
      reference: value("#secretReference"),
      metadata: {},
    });
    writeResult("secret reference saved", saved);
    await loadSettings();
    return;
  }
  if (event.target.id === "discoveryForm") {
    event.preventDefault();
    const planned = await apiPost("/discovery", {
      name: value("#discoveryName"),
      cidr: value("#discoveryCidr"),
      provider: value("#discoveryProvider"),
      credential_ref: value("#discoveryCredential") || null,
    });
    writeResult("discovery planned", planned);
    await loadDiscovery();
    return;
  }
  if (event.target.id === "isoForm") {
    event.preventDefault();
    const saved = await apiPost("/isos", {
      name: value("#isoName"),
      uri: value("#isoUri"),
      checksum: value("#isoChecksum") || null,
      checksum_algorithm: value("#isoChecksumAlgorithm") || "sha256",
    });
    writeResult("iso registered", saved);
    await loadIsos();
    return;
  }
  if (event.target.id === "roleForm") {
    event.preventDefault();
    const role = await apiPost("/access/roles", {
      name: value("#roleName"),
      description: value("#roleDescription"),
      permissions: selectedPermissions(),
    });
    writeResult("role saved", role);
    await loadSettings();
    return;
  }
  if (event.target.id === "userForm") {
    event.preventDefault();
    const payload = {
      username: value("#accessUsername"),
      display_name: value("#accessDisplayName"),
      email: value("#accessEmail"),
      roles: value("#accessRole") ? [value("#accessRole")] : [],
      status: value("#accessStatus"),
    };
    if (value("#accessPassword")) payload.password = value("#accessPassword");
    const user = await apiPost("/access/users", payload);
    writeResult("user saved", user);
    await loadSettings();
    return;
  }
  if (event.target.id === "approvalRequestForm") {
    event.preventDefault();
    const siteName = value("#approvalRequestSite");
    const action = value("#approvalRequestAction");
    if (!siteName || !action) {
      writeResult("approval request failed", { error: "site and action are required" });
      return;
    }
    await runJob(action, siteName);
    await loadApprovals();
    return;
  }
  if (event.target.id === "authLoginForm") {
    event.preventDefault();
    await loginWithPassword();
    return;
  }
  if (event.target.id === "settingsJsonForm") {
    event.preventDefault();
    try {
      const parsed = JSON.parse(document.querySelector("#settingsJsonEditor").value);
      writeResult("settings preview", parsed);
      showSettingsSection(activeSettingsSection());
    } catch (error) {
      writeResult("settings edit error", { error: error.message });
    }
  }
}

function settingCard(label, value) {
  return `<div class="setting-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function roleOptions(roles) {
  return [
    `<option value="">Select a role</option>`,
    ...roles.map((role) => `<option value="${escapeHtml(role.name)}">${escapeHtml(role.name)}</option>`),
  ].join("");
}

function providerRow(provider) {
  return `
    <div class="settings-row">
      <div>
        <strong class="provider-title">${providerNameMarkup(provider)}</strong>
        <span>${escapeHtml(provider.description)} - ${escapeHtml(provider.source)}</span>
      </div>
    </div>
  `;
}

async function showProviderDetail(providerName) {
  const detail = await apiGet(`/providers/${encodeURIComponent(providerName)}`);
  const form = document.querySelector("#providerConfigForm");
  form.hidden = false;
  form.dataset.providerName = providerName;
  document.querySelector("#providerConfigTitle").innerHTML = `${providerNameMarkup(detail.provider)} Details`;
  document.querySelector("#providerDetailGrid").innerHTML = `
    ${settingCard("Type", detail.provider.type)}
    ${settingCard("Source", detail.provider.source)}
    ${settingCard("Support", detail.provider.vendor_supported ? "vendor supported" : "community")}
    ${settingCard("Config", detail.config ? "configured" : "not configured")}
  `;
  document.querySelector("#providerConfigJson").value = JSON.stringify(detail.config?.config || detail.template || {}, null, 2);
  if (!form.querySelector("[data-test-provider]")) {
    form.querySelector(".button-row").insertAdjacentHTML("afterbegin", `<button class="secondary" type="button" data-test-provider="${escapeHtml(providerName)}">Test Provider</button>`);
  } else {
    form.querySelector("[data-test-provider]").dataset.testProvider = providerName;
  }
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

function providerNameMarkup(provider) {
  const identity = providerIdentity(typeof provider === "string" ? provider : provider.name);
  return `<span class="provider-name"><span class="vendor-mark ${escapeHtml(identity.className)}">${escapeHtml(identity.mark)}</span><span>${escapeHtml(identity.label)}</span></span>`;
}

function providerIdentity(name) {
  const normalized = String(name || "").toLowerCase();
  const known = {
    "generic-redfish": ["RF", "Generic Redfish", "vendor-redfish"],
    "dell-idrac": ["D", "Dell iDRAC", "vendor-dell"],
    "hpe-ilo": ["HPE", "HPE iLO", "vendor-hpe"],
    "lenovo-xclarity": ["L", "Lenovo XClarity", "vendor-lenovo"],
    "supermicro-redfish": ["SM", "Supermicro Redfish", "vendor-supermicro"],
    "cisco-intersight": ["C", "Cisco Intersight", "vendor-cisco"],
    "azure-local": ["AZ", "Azure Local", "vendor-azure"],
    "hyper-v": ["HV", "Hyper-V", "vendor-hyperv"],
    "kvm": ["KVM", "KVM", "vendor-kvm"],
    "nutanix-ahv": ["N", "Nutanix AHV", "vendor-nutanix"],
    "openshift-virtualization": ["OS", "OpenShift Virtualization", "vendor-openshift"],
    "proxmox": ["PX", "Proxmox", "vendor-proxmox"],
    "vmware-vsphere": ["VM", "VMware vSphere", "vendor-vmware"],
  };
  const [mark, label, className] = known[normalized] || [normalized.slice(0, 2).toUpperCase() || "PR", name, "vendor-generic"];
  return { mark, label, className };
}

function formatSettingValue(value) {
  if (typeof value === "boolean") return value ? "enabled" : "disabled";
  if (Array.isArray(value)) return `${value.length} configured`;
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return value ?? "-";
}

function labelize(value) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function renderArtifactResult(result) {
  els.artifactOutput.textContent = JSON.stringify(result, null, 2);
  loadArtifacts();
}

async function openArtifactFile(fileName) {
  if (!state.selectedSite) return;
  const file = await apiGet(`/sites/${encodeURIComponent(state.selectedSite)}/artifacts/files/${encodeURIComponent(fileName)}`);
  els.artifactOutput.textContent = file.content;
  writeResult("artifact file", { site: state.selectedSite, file: file.name });
}

function renderMetrics() {
  els.successCount.textContent = state.jobs.filter((job) => job.status === "succeeded").length;
  els.attentionCount.textContent = state.jobs.filter((job) => job.status === "failed").length;
  updateMetricInteractivity();
}

function updateMetricInteractivity() {
  const counts = {
    sites: state.sites.length,
    jobs: state.jobs.length,
    succeeded: state.jobs.filter((job) => job.status === "succeeded").length,
    failed: state.jobs.filter((job) => job.status === "failed").length,
  };
  document.querySelectorAll("[data-metric-link]").forEach((button) => {
    const count = counts[button.dataset.metricLink] || 0;
    button.disabled = count === 0;
    button.classList.toggle("is-clickable", count > 0);
    button.setAttribute("aria-label", count > 0 ? `Open ${button.dataset.metricLink}` : `${button.dataset.metricLink} unavailable`);
  });
}

function openMetricLink(metric) {
  if (metric === "sites") {
    if (!state.sites.length) return;
    showView("sites");
    return;
  }
  const filter = metric === "jobs" ? "all" : metric;
  const hasMatches = filter === "all" ? state.jobs.length : state.jobs.some((job) => job.status === filter);
  if (!hasMatches) return;
  state.jobFilter = filter;
  renderJobs();
  showView("jobs");
}

function deploymentSpecFromForm() {
  syncDeploymentNodesFromEditor();
  return {
    site: {
      name: value("#deployName"),
      location: value("#deployLocation"),
      deployment_model: value("#deployModel"),
    },
    hardware: {
      vendor: state.selectedHardware,
      nodes: state.deploymentNodes.filter((node) => node.serial && node.bmc_ip),
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
  const issues = validateDeploymentSpec(spec);
  renderDeploymentReadiness(issues);
  els.deploymentSummary.textContent = JSON.stringify({
    site: spec.site.name,
    hardware: spec.hardware.vendor,
    platform: spec.platform.type,
    topology: spec.platform.topology,
    nodes: spec.hardware.nodes.length,
    workloads: Object.entries(spec.workloads).filter(([, enabled]) => enabled).map(([name]) => name),
  }, null, 2);
}

function validateDeploymentSpec(spec) {
  const issues = [];
  const requiredText = [
    ["Site name", spec.site.name],
    ["Location", spec.site.location],
    ["Cluster name", spec.platform.cluster_name],
    ["Topology", spec.platform.topology],
  ];
  requiredText.forEach(([label, value]) => {
    if (!String(value || "").trim()) issues.push(`${label} is required.`);
  });
  if (!spec.hardware.nodes.length) issues.push("At least one deployment node is required.");
  const serials = new Set();
  spec.hardware.nodes.forEach((node, index) => {
    if (!node.serial) issues.push(`Node ${index + 1} serial is required.`);
    if (node.serial && serials.has(node.serial)) issues.push(`Node serial ${node.serial} is duplicated.`);
    serials.add(node.serial);
    if (!isIpv4(node.bmc_ip)) issues.push(`Node ${index + 1} BMC IP must be a valid IPv4 address.`);
  });
  ["management_vlan", "storage_vlan", "vm_vlan"].forEach((key) => {
    const value = spec.network[key];
    if (!Number.isInteger(value) || value < 1 || value > 4094) issues.push(`${labelize(key)} must be between 1 and 4094.`);
  });
  [...spec.network.dns_servers, ...spec.network.ntp_servers].forEach((entry) => {
    if (!entry) issues.push("DNS and NTP entries cannot be empty.");
  });
  if (spec.platform.type === "azure-local") {
    if (!isGuid(spec.platform.azure.subscription_id)) issues.push("Azure Subscription must be a GUID.");
    if (!isGuid(spec.platform.azure.tenant_id)) issues.push("Azure Tenant must be a GUID.");
    if (!spec.platform.azure.resource_group) issues.push("Azure Resource Group is required.");
    if (!spec.platform.azure.region) issues.push("Azure Region is required.");
  }
  return issues;
}

function renderDeploymentReadiness(issues) {
  if (!els.deploymentReadiness) return;
  const ready = issues.length === 0;
  els.deploymentReadiness.className = `readiness-panel ${ready ? "ready" : "blocked"}`;
  els.deploymentReadiness.innerHTML = ready
    ? `<strong>Ready for save and plan</strong><span>Required site, node, network, and platform fields are complete.</span>`
    : `<strong>${issues.length} readiness issue${issues.length === 1 ? "" : "s"}</strong><ul>${issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>`;
  document.querySelector("#saveGeneratedDeployment").disabled = !ready;
  document.querySelector("#saveAndPlanDeployment").disabled = !ready;
}

function isIpv4(value) {
  const parts = String(value || "").split(".");
  return parts.length === 4 && parts.every((part) => /^\d+$/.test(part) && Number(part) >= 0 && Number(part) <= 255);
}

function isGuid(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(String(value || ""));
}

function hydrateDeploymentForm(spec) {
  setValue("#deployName", spec.site?.name || "");
  setValue("#deployLocation", spec.site?.location || "");
  setValue("#deployModel", spec.site?.deployment_model || "edge-hci");
  setValue("#clusterName", spec.platform?.cluster_name || spec.site?.name || "");
  setValue("#topology", spec.platform?.topology || "");
  setValue("#subscriptionId", spec.platform?.azure?.subscription_id || "");
  setValue("#tenantId", spec.platform?.azure?.tenant_id || "");
  setValue("#resourceGroup", spec.platform?.azure?.resource_group || "");
  setValue("#azureRegion", spec.platform?.azure?.region || "");
  setValue("#managementVlan", spec.network?.management_vlan ?? "");
  setValue("#storageVlan", spec.network?.storage_vlan ?? "");
  setValue("#vmVlan", spec.network?.vm_vlan ?? "");
  setValue("#dnsServers", (spec.network?.dns_servers || []).join(","));
  setValue("#ntpServers", (spec.network?.ntp_servers || []).join(","));
  state.deploymentNodes = (spec.hardware?.nodes || []).map((node) => ({
    serial: node.serial || "",
    bmc_ip: node.bmc_ip || "",
    role: node.role || "host",
  }));
  if (!state.deploymentNodes.length) state.deploymentNodes = [{ serial: "", bmc_ip: "", role: "host" }];
  renderNodeEditor();
  document.querySelector("#workloadAks").checked = Boolean(spec.workloads?.aks);
  document.querySelector("#workloadArcVms").checked = Boolean(spec.workloads?.arc_vms);
  document.querySelector("#workloadAvd").checked = Boolean(spec.workloads?.avd);
  selectChoice("hardware", spec.hardware?.vendor || "generic-redfish");
  selectChoice("platform", spec.platform?.type || "azure-local");
  showWizardStep("intent");
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
  const credentials = {
    credential_ref: els.bmcCredentialRef?.value || null,
    username: els.bmcUsername.value || null,
    password: els.bmcPassword.value || null,
    insecure: els.bmcInsecure.checked,
    timeout: Number(els.bmcTimeout.value || 10),
  };
  if (action === "inventory") return credentials;
  if (action === "mount-iso") {
    return {
      ...credentials,
      iso_ref: els.isoRef?.value || null,
      iso_url: els.isoUrl.value || null,
      boot_once: els.isoBootOnce.checked,
    };
  }
  if (action === "eject-iso") return credentials;
  return {};
}

async function apiGet(path) {
  const response = await apiFetch(path);
  if (response.status === 401) {
    handleAuthRequired(`${path} requires sign in.`);
    throw new Error(`${path} failed with HTTP ${response.status}`);
  }
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function apiPost(path, body) {
  if (!state.authToken && !requestAuthToken()) throw new Error("authentication required");
  const response = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    handleAuthRequired(`${path} requires sign in.`);
    throw new Error(`${path} failed with HTTP ${response.status}`);
  }
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function apiDelete(path) {
  if (!state.authToken && !requestAuthToken()) throw new Error("authentication required");
  const response = await apiFetch(path, { method: "DELETE" });
  if (response.status === 401) {
    handleAuthRequired(`${path} requires sign in.`);
    throw new Error(`${path} failed with HTTP ${response.status}`);
  }
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function apiFetch(path, options = {}) {
  const response = await fetchWithTimeout(`${apiBase}${path}`, withAuth(options));
  return response;
}

async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8000);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === "AbortError") throw new Error(`${url} timed out`);
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function withAuth(options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.authToken) headers.set("Authorization", `Bearer ${state.authToken}`);
  return { ...options, headers };
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

function writeSiteAction(message, status = "info") {
  if (!els.siteActionStatus) return;
  els.siteActionStatus.textContent = message;
  els.siteActionStatus.className = `action-status ${status}`;
}

function toggleAuthSession() {
  if (!state.authToken) {
    showAuthModal();
    return;
  }
  logout();
}

function logout() {
  if (state.authToken) {
    fetchWithTimeout(`${apiBase}/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${state.authToken}` },
    }).catch(() => {});
  }
  clearAuthState("signed out");
  writeResult("logout", { status: "dashboard bearer token cleared" });
  writeSiteAction("Dashboard session cleared");
  renderAuthState();
}

function clearAuthState(userLabel = "anonymous") {
  state.authToken = "";
  state.authUser = userLabel;
  localStorage.removeItem("strataone.authToken");
  localStorage.setItem("strataone.authUser", state.authUser);
}

function renderAuthState() {
  els.userChip.innerHTML = `${escapeHtml(state.authToken ? state.authUser : "anonymous")} <span>${state.authToken ? "token" : "no token"}</span>`;
  document.querySelector("#logoutButton").textContent = state.authToken ? "Logout" : "Login";
}

function requestAuthToken() {
  showAuthModal();
  return false;
}

function showAuthModal() {
  if (!els.authModal.hidden) return;
  els.authModal.hidden = false;
  els.loginPassword.value = "";
  els.loginUsername.focus();
}

function hideAuthModal() {
  els.authModal.hidden = true;
}

async function loginWithPassword() {
  const response = await fetchWithTimeout(`${apiBase}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: els.loginUsername.value.trim(),
      password: els.loginPassword.value,
    }),
  });
  if (!response.ok) {
    writeResult("login failed", { status: "invalid username or password" });
    return;
  }
  const session = await response.json();
  state.authToken = session.token;
  state.authUser = session.display_name || session.username;
  localStorage.setItem("strataone.authToken", state.authToken);
  localStorage.setItem("strataone.authUser", state.authUser);
  hideAuthModal();
  renderAuthState();
  await refreshAll();
}

function renderAuthRequired() {
  state.sites = [];
  state.jobs = [];
  state.providers = [];
  state.inventory = null;
  renderSites();
  renderFleet();
  renderJobs();
  renderProviders();
  renderMetrics();
  writeResult("authentication required", {
    status: "Sign in with a StrataOne local user account to load protected operational data.",
    default_user: "admin",
  });
  showAuthModal();
}

function handleAuthRequired(message = "Sign in required.") {
  clearAuthState("anonymous");
  renderAuthState();
  if (els.settingsContent && state.activeView === "settings") {
    els.settingsContent.innerHTML = `<div class="settings-empty">Sign in to view and manage settings.</div>`;
  }
  writeResult("authentication required", { status: message, default_user: "admin" });
  showAuthModal();
}

function isAuthError(error) {
  return String(error.message || "").includes("HTTP 401");
}

function value(selector) {
  return document.querySelector(selector).value.trim();
}

function setValue(selector, value) {
  document.querySelector(selector).value = value;
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

function selectedPermissions() {
  const checkedPermissions = [...document.querySelectorAll("[data-permission]:checked")].map((item) => item.dataset.permission);
  return checkedPermissions.length ? checkedPermissions : csv("#rolePermissions");
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
