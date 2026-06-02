const apiBase = window.STRATAONE_API_BASE || "http://localhost:8080";

const siteYaml = document.querySelector("#siteYaml");
const apiStatus = document.querySelector("#apiStatus");
const sitesTable = document.querySelector("#sitesTable");
const resultOutput = document.querySelector("#resultOutput");
const lastAction = document.querySelector("#lastAction");
const readyCount = document.querySelector("#readyCount");
const warnCount = document.querySelector("#warnCount");
const failCount = document.querySelector("#failCount");

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

siteYaml.value = exampleYaml;

document.querySelector("#loadExample").addEventListener("click", () => {
  siteYaml.value = exampleYaml;
  renderSiteRow(parseTinyYaml(siteYaml.value));
});

document.querySelector("#validateSite").addEventListener("click", () => runAction("validate"));
document.querySelector("#planSite").addEventListener("click", () => runAction("plan"));
document.querySelector("#preflightSite").addEventListener("click", () => runAction("preflight"));

checkApi();
renderSiteRow(parseTinyYaml(siteYaml.value));
runAction("preflight");

async function checkApi() {
  try {
    const response = await fetch(`${apiBase}/health`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    apiStatus.textContent = "API: online";
    apiStatus.className = "status-pill ok";
  } catch (error) {
    apiStatus.textContent = "API: offline";
    apiStatus.className = "status-pill fail";
  }
}

async function runAction(action) {
  lastAction.textContent = action;
  const payload = { site: parseTinyYaml(siteYaml.value) };
  try {
    const response = await fetch(`${apiBase}/sites/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    resultOutput.textContent = JSON.stringify(result, null, 2);
    if (action === "preflight") renderPreflightMetrics(result);
    if (payload.site) renderSiteRow(payload.site, result);
  } catch (error) {
    resultOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

function renderPreflightMetrics(result) {
  const checks = result.checks || [];
  readyCount.textContent = result.ready ? "1" : "0";
  warnCount.textContent = checks.filter((check) => check.status === "WARN").length;
  failCount.textContent = checks.filter((check) => check.status === "FAIL").length;
}

function renderSiteRow(site, result = {}) {
  const state = result.ready === false ? "Warn" : "Ready";
  sitesTable.innerHTML = `
    <tr>
      <td>${escapeHtml(site.site?.name || "-")}</td>
      <td>${escapeHtml(site.platform?.type || "-")}</td>
      <td>${escapeHtml(site.hardware?.vendor || "-")}</td>
      <td>${site.hardware?.nodes?.length || 0}</td>
      <td class="${state === "Ready" ? "state-ready" : "state-warn"}">${state}</td>
    </tr>
  `;
}

function parseTinyYaml(text) {
  const lines = text.split(/\r?\n/);
  const root = {};
  const stack = [{ indent: -1, value: root }];

  for (const rawLine of lines) {
    if (!rawLine.trim() || rawLine.trimStart().startsWith("#")) continue;
    const indent = rawLine.match(/^\s*/)[0].length;
    const line = rawLine.trim();

    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop();
    const parent = stack[stack.length - 1].value;

    if (line.startsWith("- ")) {
      const itemText = line.slice(2);
      const list = Array.isArray(parent) ? parent : [];
      const item = parseValueOrObject(itemText);
      list.push(item);
      if (typeof item === "object" && item !== null) stack.push({ indent, value: item });
      continue;
    }

    const [key, ...rest] = line.split(":");
    const valueText = rest.join(":").trim();
    if (valueText === "") {
      const nextValue = nextMeaningfulLineIsList(lines, rawLine) ? [] : {};
      parent[key] = nextValue;
      stack.push({ indent, value: nextValue });
    } else {
      parent[key] = parseScalar(valueText);
    }
  }
  return root;
}

function nextMeaningfulLineIsList(lines, currentLine) {
  const index = lines.indexOf(currentLine);
  for (const line of lines.slice(index + 1)) {
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
