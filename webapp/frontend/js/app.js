import { registerRoute, initRouter } from "./router.js";
import { api } from "./api.js";
import { el } from "./dom.js";
import { openModal } from "./components/modal.js";

import * as overviewPage from "./pages/overview.js";
import * as configFilesPage from "./pages/configFiles.js";
import * as goldenConfigPage from "./pages/goldenConfig.js";
import * as analysisPage from "./pages/analysis.js";
import * as briefingsPage from "./pages/briefings.js";
import * as complianceReportPage from "./pages/complianceReport.js";
import * as dashboardPage from "./pages/dashboard.js";
import * as settingsPage from "./pages/settings.js";

registerRoute("/overview", overviewPage);
registerRoute("/configuration-files", configFilesPage);
registerRoute("/golden-config", goldenConfigPage);
registerRoute("/analysis", analysisPage);
registerRoute("/briefings", briefingsPage);
registerRoute("/compliance-report", complianceReportPage);
registerRoute("/dashboard", dashboardPage);
registerRoute("/settings", settingsPage);

const mainContent = document.getElementById("main-content");
const sidebar = document.querySelector(".app-sidebar");
initRouter(mainContent, sidebar);

// Header backend-status pill - a lightweight, low-frequency poll so the
// header always reflects reality without every page needing to fetch it.
const statusPill = document.getElementById("backend-status-pill");
async function refreshBackendStatus() {
  try {
    const status = await api.get("/api/settings/status");
    const online = status.any_backend_reachable;
    statusPill.classList.toggle("status-pill--online", online);
    statusPill.classList.toggle("status-pill--offline", !online);
    statusPill.innerHTML = "";
    statusPill.appendChild(el("span", { class: "status-pill__dot" }));
    statusPill.appendChild(document.createTextNode(online ? " LLM backend online" : " LLM backend offline"));
  } catch {
    statusPill.classList.remove("status-pill--online");
    statusPill.classList.add("status-pill--offline");
    statusPill.innerHTML = "";
    statusPill.appendChild(el("span", { class: "status-pill__dot" }));
    statusPill.appendChild(document.createTextNode(" Backend unreachable"));
  }
}
refreshBackendStatus();
setInterval(refreshBackendStatus, 15000);

document.getElementById("about-button").addEventListener("click", () => {
  openModal({
    title: "About NCM Copilot",
    bodyNode: el("div", { class: "stack" }, [
      el("p", {
        text: "NCM Copilot audits Cisco IOS-XE device configurations against a Golden Configuration baseline, using a shared controls.yaml rulebook to evaluate 15 security controls per device.",
      }),
      el("p", {
        text: "This web frontend orchestrates the existing Compliance Checker, Golden Config Creator, Remediation Advisor, Compliance Report Generator, and Executive Dashboard - it does not reimplement any of their analysis logic.",
      }),
    ]),
  });
});
