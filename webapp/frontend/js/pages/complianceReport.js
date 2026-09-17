import { api } from "../api.js";
import { el, clear, renderMarkdownLite } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { toastError, toastSuccess } from "../components/toast.js";
import { severityBadge, statusBadge } from "../components/statusBadge.js";
import { getState } from "../state.js";
import { navigateTo } from "../router.js";

export async function render(container) {
  clear(container);

  container.appendChild(
    el("div", { class: "page-header" }, [
      el("div", { class: "page-header__heading" }, [
        el("h1", { text: "Compliance Report" }),
        el("p", { text: "A device-level, audit-grade compliance report generated from the analysis engine's findings." }),
      ]),
    ])
  );

  const body = el("div", { class: "stack" });
  container.appendChild(body);
  body.appendChild(el("div", { class: "skeleton skeleton--block" }));

  let runs;
  try {
    runs = await api.get("/api/analysis/runs");
  } catch (err) {
    clear(body);
    body.appendChild(errorPanel(err, { title: "Unable to load Compliance Report" }));
    return;
  }
  clear(body);

  if (!runs.length) {
    body.appendChild(
      el("div", { class: "empty-state card" }, [
        el("div", { class: "empty-state__icon", text: "\u{1F4CB}" }),
        el("div", { class: "empty-state__title", text: "No analysis runs yet" }),
        el("p", { text: "Run an analysis first, then generate a compliance report for a device." }),
        el("div", { class: "cluster", style: "justify-content:center; margin-top: 12px;" }, [
          el("button", { class: "btn btn--primary", text: "Go to Analysis", onclick: () => navigateTo("/analysis") }),
        ]),
      ])
    );
    return;
  }

  const persistedRun = getState().activeRunId;
  let runId = runs.some((r) => r.run_id === persistedRun) ? persistedRun : runs[0].run_id;
  let deviceRole = "";
  let auditDate = "";
  let llmPolish = false;

  const setupCard = el("div", { class: "card" });
  const resultArea = el("div", {});
  body.appendChild(setupCard);
  body.appendChild(resultArea);

  async function loadRun() {
    clear(setupCard);
    let devices;
    try {
      devices = await api.get(`/api/analysis/runs/${runId}/devices`);
    } catch (err) {
      setupCard.appendChild(errorPanel(err, { title: "Unable to load this run" }));
      return;
    }
    let deviceName = devices[0] || null;

    setupCard.appendChild(el("h3", { text: "Run" }));
    setupCard.appendChild(
      el(
        "select",
        { class: "input", style: "max-width: 260px;", onchange: (e) => { runId = e.target.value; loadRun(); } },
        runs.map((r) => el("option", { value: r.run_id, text: r.run_id, selected: r.run_id === runId ? "selected" : null }))
      )
    );

    setupCard.appendChild(el("h3", { text: "Device", style: "margin-top: var(--space-5);" }));
    if (!devices.length) {
      setupCard.appendChild(el("p", { class: "muted", text: "This run has no analyzed devices." }));
      return;
    }
    setupCard.appendChild(
      el(
        "select",
        { class: "input", style: "max-width: 260px;", onchange: (e) => { deviceName = e.target.value; } },
        devices.map((d) => el("option", { value: d, text: d }))
      )
    );

    setupCard.appendChild(el("h3", { text: "Device role", style: "margin-top: var(--space-5);" }));
    setupCard.appendChild(
      el("input", {
        class: "input", style: "max-width: 320px;", placeholder: "e.g. Core Router, Branch Firewall",
        oninput: (e) => { deviceRole = e.target.value; },
      })
    );

    setupCard.appendChild(el("h3", { text: "Audit date (optional)", style: "margin-top: var(--space-5);" }));
    setupCard.appendChild(
      el("input", { class: "input", type: "date", style: "max-width: 200px;", oninput: (e) => { auditDate = e.target.value; } })
    );

    setupCard.appendChild(
      el("label", { class: "cluster", style: "margin-top: var(--space-5);" }, [
        el("input", { type: "checkbox", onchange: (e) => { llmPolish = e.target.checked; } }),
        el("span", { text: "Polish risk statements with the local LLM (optional)" }),
      ])
    );

    setupCard.appendChild(
      el("div", { style: "margin-top: var(--space-5);" }, [
        el("button", {
          class: "btn btn--primary", text: "Generate Report",
          onclick: () => generateReport(deviceName),
        }),
      ])
    );
  }

  async function generateReport(deviceName) {
    if (!deviceName) return;
    if (!deviceRole.trim()) {
      toastError("Device role is required.");
      return;
    }
    clear(resultArea);
    resultArea.appendChild(el("div", { class: "skeleton skeleton--block" }));
    setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = true));

    let result;
    try {
      result = await api.post("/api/reports/generate", {
        run_id: runId, device: deviceName, device_role: deviceRole,
        audit_date: auditDate || null, llm_polish: llmPolish, backend: "auto",
      });
    } catch (err) {
      clear(resultArea);
      resultArea.appendChild(errorPanel(err, { title: "Unable to generate the compliance report" }));
      setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
      return;
    }
    setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
    clear(resultArea);
    toastSuccess("Compliance report generated.");
    resultArea.appendChild(renderReport(result));
  }

  function renderReport(result) {
    const c = result.counts;
    const wrap = el("div", { class: "stack" });

    wrap.appendChild(
      el("div", { class: "card" }, [
        el("h3", { text: `${result.device} — ${result.device_role}` }),
        el("p", { class: "muted", text: `Audit date: ${result.audit_date}${result.backend_used ? ` · Risk statements polished by ${result.backend_used}` : ""}` }),
        el("div", { class: "kpi-grid" }, [
          kpi("Compliance", `${result.compliance_pct}%`),
          kpi("Compliant", String(c.compliant)),
          kpi("Non-Compliant (High)", String(c.High)),
          kpi("Non-Compliant (Medium)", String(c.Medium)),
          kpi("Non-Compliant (Low)", String(c.Low)),
          kpi("Exceptions", String(c.exception)),
          kpi("Manual Review", String(c.manual_review)),
        ]),
        result.pdf_available
          ? el("div", { class: "cluster", style: "margin-top: var(--space-3);" }, [
              el("a", { class: "btn btn--primary", href: `/api/reports/${runId}/${result.device}/pdf`, text: "Download PDF Report", target: "_blank" }),
            ])
          : null,
      ])
    );

    wrap.appendChild(findingsTable("Findings", result.findings_detail));
    if (result.manual_review.length) wrap.appendChild(findingsTable("Manual Review Required", result.manual_review));

    const mdToggleBtn = el("button", { class: "btn btn--sm", text: "View Report as Markdown" });
    const mdBox = el("div", { class: "card", style: "display:none; margin-top: var(--space-3);" });
    mdToggleBtn.addEventListener("click", () => {
      const showing = mdBox.style.display !== "none";
      if (showing) {
        mdBox.style.display = "none";
      } else {
        renderMarkdownLite(mdBox, result.markdown);
        mdBox.style.display = "";
      }
    });
    wrap.appendChild(mdToggleBtn);
    wrap.appendChild(mdBox);

    return wrap;
  }

  function findingsTable(title, rows) {
    if (!rows.length) {
      return el("div", { class: "card" }, [el("h3", { text: title }), el("p", { class: "muted", text: "None." })]);
    }
    return el("div", { class: "card" }, [
      el("h3", { text: title }),
      el("div", { class: "data-table-wrap" }, [
        el("table", { class: "data-table" }, [
          el("thead", {}, [
            el("tr", {}, [
              el("th", { text: "Control" }), el("th", { text: "Severity" }), el("th", { text: "Status" }),
              el("th", { text: "Risk" }), el("th", { text: "Remediation" }),
            ]),
          ]),
          el(
            "tbody", {},
            rows.map((f) =>
              el("tr", {}, [
                el("td", { text: `${f.control_id} — ${f.title}` }),
                el("td", {}, [severityBadge(f.severity)]),
                el("td", {}, [statusBadge(f.status)]),
                el("td", { text: f.risk_statement }),
                el("td", { text: f.remediation_command }),
              ])
            )
          ),
        ]),
      ]),
    ]);
  }

  function kpi(label, value) {
    return el("div", { class: "kpi-card" }, [
      el("div", { class: "kpi-card__value", text: value }),
      el("div", { class: "kpi-card__label", text: label }),
    ]);
  }

  await loadRun();
}
