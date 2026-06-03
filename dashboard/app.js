const apiBase = new URLSearchParams(window.location.search).get("api")
  || window.STRATAONE_API_BASE
  || "http://127.0.0.1:8080";

const state = {
  sites: [],
  jobs: [],
  providers: [],
  settings: null,
  inventory: null,
  selectedSite: null,
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
  providerList: document.querySelector("#providerList"),
  nodeList: document.querySelector("#nodeList"),
  lifecycleGrid: document.querySelector("#lifecycleGrid"),
  lifecycleDetail: document.querySelector("#lifecycleDetail"),
  inventoryList: document.querySelector("#inventoryList"),
  inventorySummary: document.querySelector("#inventorySummary"),
  resultOutput: document.querySelector("#resultOutput"),
  artifactOutput: document.querySelector("#artifactOutput"),
  artifactDetails: document.querySelector("#artifactDetails"),
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
  bmcUsername: document.querySelector("#bmcUsername"),
  bmcPassword: document.querySelector("#bmcPassword"),
  bmcInsecure: document.querySelector("#bmcInsecure"),
  bmcTimeout: document.querySelector("#bmcTimeout"),
  isoUrl: document.querySelector("#isoUrl"),
  isoBootOnce: document.querySelector("#isoBootOnce"),
};

const viewCopy = {
  overview: ["Overview", "Fleet health, deployment readiness, and orchestration activity."],
  deployments: ["Deployments", "Create deployments and generate desired state for hardware and hypervisor targets."],
  sites: ["Sites", "Manage registered site definitions and run operational actions."],
  jobs: ["Jobs", "Inspect queued, running, failed, and completed orchestration jobs."],
  providers: ["Providers", "Review available hardware and platform providers."],
  artifacts: ["Artifacts", "Generate and inspect deployment bundles for selected sites."],
  lifecycle: ["Lifecycle", "Plan Day-2 controls such as drift, updates, and node replacement."],
  settings: ["Settings", "Configure access posture, database, providers, artifacts, and audit policy."],
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
  document.querySelector("#refreshSettings").addEventListener("click", loadSettings);
  document.querySelector("#editSettingsSection").addEventListener("click", () => showSettingsEditor(activeSettingsSection()));
  document.querySelector("#logoutButton").addEventListener("click", toggleAuthSession);
  document.querySelector("#addNode").addEventListener("click", addDeploymentNode);
  document.querySelector("#newProvider").addEventListener("click", () => showProviderForm());
  document.querySelector("#cancelProvider").addEventListener("click", hideProviderForm);
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
    await Promise.all([loadSites(), loadJobs(), loadProviders(), loadSettings()]);
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

async function loadSettings() {
  try {
    state.settings = await apiGet("/settings");
    showSettingsSection(activeSettingsSection());
  } catch (error) {
    if (els.settingsContent) {
      els.settingsContent.innerHTML = `<div class="settings-empty">Settings unavailable: ${escapeHtml(error.message)}</div>`;
    }
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

async function runJob(action, siteName = state.selectedSite) {
  if (!siteName) return;
  try {
    const created = await apiPost(`/sites/${encodeURIComponent(siteName)}/jobs/${action}`, jobPayload(action));
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
        <button class="mini danger" data-delete-site="${escapeHtml(site.name)}">Delete</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="6">No sites registered</td></tr>`;
  document.querySelectorAll("[data-site]").forEach((row) => row.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    selectSite(row.dataset.site);
  }));
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
    item.addEventListener("click", async (event) => {
      if (event.target.closest("button")) return;
      const job = await apiGet(`/jobs/${encodeURIComponent(item.dataset.jobId)}`);
      writeResult(`${job.action} ${job.status}`, job);
      if (job.action === "artifacts" && job.result) renderArtifactResult(job.result);
    });
  });
}

function jobItem(job) {
  return `
    <div class="list-item job-item" data-job-id="${escapeHtml(job.id)}">
      <button class="job-main" data-open-job="${escapeHtml(job.id)}">
        <strong>${escapeHtml(job.action)} <span class="status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span></strong>
        <span>${escapeHtml(job.site_name)} - ${formatDate(job.created_at)}</span>
      </button>
      <button class="mini secondary" data-rerun-job="${escapeHtml(job.id)}">Rerun</button>
    </div>
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
    <div class="list-item provider-card">
      <div>
        <strong>${escapeHtml(provider.name)} <span class="badge">${provider.vendor_supported ? "vendor supported" : "community"}</span></strong>
        <span>${escapeHtml(provider.type)} - ${escapeHtml(provider.source)}</span>
        <span>${escapeHtml(provider.description)}</span>
      </div>
      <div class="row-actions">
        <button class="mini secondary" data-edit-provider="${escapeHtml(provider.name)}">Edit</button>
        ${provider.editable ? `<button class="mini danger" data-delete-provider="${escapeHtml(provider.name)}">Remove</button>` : `<button class="mini secondary" disabled>Built-in</button>`}
      </div>
    </div>
  `).join("");
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
          <button type="submit">Save Role</button>
        </form>
        <form class="settings-form" id="userForm">
          <h3>Create / Edit User</h3>
          <label>Username<input id="accessUsername" placeholder="j.smith" /></label>
          <label>Display Name<input id="accessDisplayName" placeholder="Jane Smith" /></label>
          <label>Email<input id="accessEmail" placeholder="jane.smith@example.com" /></label>
          <label>Roles<input id="accessRoles" placeholder="Operator, Viewer" /></label>
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
    const job = await apiGet(`/jobs/${encodeURIComponent(openJob.dataset.openJob)}`);
    writeResult(`${job.action} ${job.status}`, job);
    if (job.action === "artifacts" && job.result) renderArtifactResult(job.result);
    return;
  }
  const rerunJob = event.target.closest("[data-rerun-job]");
  if (rerunJob) {
    const job = state.jobs.find((item) => item.id === rerunJob.dataset.rerunJob) || await apiGet(`/jobs/${encodeURIComponent(rerunJob.dataset.rerunJob)}`);
    await runJob(job.action, job.site_name);
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
    writeResult("lifecycle workflow opened", {
      workflow: lifecycleRun.dataset.lifecycleRun,
      site: state.selectedSite || "select a site",
      status: "ready",
    });
    showView("jobs");
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
  const editSite = event.target.closest("[data-edit-site]");
  if (editSite) {
    state.selectedSite = editSite.dataset.editSite;
    loadSelectedDeploymentIntoWizard();
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
      document.querySelector("#accessRoles").value = (user.roles || []).join(", ");
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
  if (event.target.closest("[data-settings-cancel]")) {
    showSettingsSection(activeSettingsSection());
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
  if (event.target.id === "roleForm") {
    event.preventDefault();
    const role = await apiPost("/access/roles", {
      name: value("#roleName"),
      description: value("#roleDescription"),
      permissions: csv("#rolePermissions"),
    });
    writeResult("role saved", role);
    await loadSettings();
    return;
  }
  if (event.target.id === "userForm") {
    event.preventDefault();
    const user = await apiPost("/access/users", {
      username: value("#accessUsername"),
      display_name: value("#accessDisplayName"),
      email: value("#accessEmail"),
      roles: csv("#accessRoles"),
      status: value("#accessStatus"),
    });
    writeResult("user saved", user);
    await loadSettings();
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

function providerRow(provider) {
  return `
    <div class="settings-row">
      <strong>${escapeHtml(provider.name)}</strong>
      <span>${escapeHtml(provider.description)} - ${escapeHtml(provider.source)}</span>
    </div>
  `;
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
}

function renderMetrics() {
  els.successCount.textContent = state.jobs.filter((job) => job.status === "succeeded").length;
  els.attentionCount.textContent = state.jobs.filter((job) => job.status === "failed").length;
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
  els.deploymentSummary.textContent = JSON.stringify({
    site: spec.site.name,
    hardware: spec.hardware.vendor,
    platform: spec.platform.type,
    topology: spec.platform.topology,
    nodes: spec.hardware.nodes.length,
    workloads: Object.entries(spec.workloads).filter(([, enabled]) => enabled).map(([name]) => name),
  }, null, 2);
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
    username: els.bmcUsername.value || null,
    password: els.bmcPassword.value || null,
    insecure: els.bmcInsecure.checked,
    timeout: Number(els.bmcTimeout.value || 10),
  };
  if (action === "inventory") return credentials;
  if (action === "mount-iso") {
    return {
      ...credentials,
      iso_url: els.isoUrl.value || null,
      boot_once: els.isoBootOnce.checked,
    };
  }
  return {};
}

async function apiGet(path) {
  const response = await apiFetch(path);
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
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function apiDelete(path) {
  if (!state.authToken && !requestAuthToken()) throw new Error("authentication required");
  const response = await apiFetch(path, { method: "DELETE" });
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
    if (!requestAuthToken()) return;
    refreshAll();
    return;
  }
  logout();
}

function logout() {
  state.authToken = "";
  state.authUser = "signed out";
  localStorage.removeItem("strataone.authToken");
  localStorage.setItem("strataone.authUser", state.authUser);
  writeResult("logout", { status: "dashboard bearer token cleared" });
  writeSiteAction("Dashboard session cleared");
  renderAuthState();
}

function renderAuthState() {
  els.userChip.innerHTML = `${escapeHtml(state.authToken ? state.authUser : "anonymous")} <span>${state.authToken ? "token" : "no token"}</span>`;
  document.querySelector("#logoutButton").textContent = state.authToken ? "Logout" : "Login";
}

function requestAuthToken() {
  const token = window.prompt("Enter StrataOne API bearer token");
  if (!token) return false;
  state.authToken = token.trim();
  state.authUser = "api user";
  localStorage.setItem("strataone.authToken", state.authToken);
  localStorage.setItem("strataone.authUser", state.authUser);
  renderAuthState();
  return true;
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
    status: "Sign in with an API token to load protected operational data.",
    default_compose_token: "change-this-token",
  });
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
