import { api } from "../api.js";
import { el, clear, renderMarkdownLite } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { toastError, toastSuccess, toastWarning } from "../components/toast.js";
import { severityBadge, statusBadge, compliancePctBadge } from "../components/statusBadge.js";
import { renderJobProgress } from "../components/jobProgress.js";
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
  let activeJobDisposer = null;

  const setupCard = el("div", { class: "card" });
  const resultArea = el("div", {});
  body.appendChild(setupCard);
  body.appendChild(resultArea);

  async function loadRun() {
    clear(setupCard);
    clear(resultArea);
    let devices;
    try {
      devices = await api.get(`/api/analysis/runs/${runId}/devices`);
    } catch (err) {
      setupCard.appendChild(errorPanel(err, { title: "Unable to load this run" }));
      return;
    }

    setupCard.appendChild(el("h3", { text: "Run" }));
    setupCard.appendChild(
      el(
        "select",
        { class: "input", style: "max-width: 260px;", onchange: (e) => { runId = e.target.value; loadRun(); } },
        runs.map((r) => el("option", { value: r.run_id, text: r.run_id, selected: r.run_id === runId ? "selected" : null }))
      )
    );

    setupCard.appendChild(el("h3", { text: "Device(s)", style: "margin-top: var(--space-5);" }));
    if (!devices.length) {
      setupCard.appendChild(el("p", { class: "muted", text: "This run has no analyzed devices." }));
      return;
    }

    // One device selected -> the original single-report flow. More than one
    // -> a batch job (see reports_service.start_batch_reports), so 500
    // devices no longer means 500 manual "select, fill role, Generate" cycles.
    const selectedDevices = new Set([devices[0]]);

    // Plain <select> scrolling gets unusable past a few hundred devices - a
    // live filter keeps this responsive at 500+ (see item 9/TEST 7). Filters
    // by device name only, the one identifier list_run_devices() exposes;
    // no other device metadata (IP, site, type) exists anywhere in this app.
    let deviceSearch = "";
    const resultsHint = el("div", { class: "field__hint" });
    const listWrap = el("div", { class: "data-table-wrap", style: "max-height: 260px; overflow-y: auto;" });
    const selectAllCheckbox = el("input", { type: "checkbox", "aria-label": "Select all filtered" });
    const generateBtn = el("button", { class: "btn btn--primary", text: "Generate Report", onclick: () => generateReports(Array.from(selectedDevices)) });

    function updateGenerateLabel() {
      const n = selectedDevices.size;
      generateBtn.textContent = n > 1 ? `Generate ${n} Reports` : "Generate Report";
      generateBtn.disabled = n === 0;
    }

    function renderDeviceRows() {
      const query = deviceSearch.toLowerCase();
      const matches = query ? devices.filter((d) => d.toLowerCase().includes(query)) : devices;
      resultsHint.textContent = query ? `${matches.length} of ${devices.length} device(s)` : `${devices.length} device(s)`;
      const visibleSelectedCount = matches.filter((d) => selectedDevices.has(d)).length;
      selectAllCheckbox.checked = matches.length > 0 && visibleSelectedCount === matches.length;
      selectAllCheckbox.indeterminate = !selectAllCheckbox.checked && visibleSelectedCount > 0;

      clear(listWrap);
      listWrap.appendChild(
        el("table", { class: "data-table" }, [
          el("thead", {}, [el("tr", {}, [el("th", {}, [selectAllCheckbox]), el("th", { text: "Device" })])]),
          el(
            "tbody", {},
            matches.map((d) =>
              el("tr", {}, [
                el("td", {}, [
                  el("input", {
                    type: "checkbox", checked: selectedDevices.has(d) ? "checked" : null, "aria-label": `Select ${d}`,
                    onchange: (e) => {
                      if (e.target.checked) selectedDevices.add(d);
                      else selectedDevices.delete(d);
                      updateGenerateLabel();
                      const nowSelected = matches.filter((v) => selectedDevices.has(v)).length;
                      selectAllCheckbox.checked = matches.length > 0 && nowSelected === matches.length;
                      selectAllCheckbox.indeterminate = selectAllCheckbox.checked ? false : nowSelected > 0;
                    },
                  }),
                ]),
                el("td", { text: d }),
              ])
            )
          ),
        ])
      );
      updateGenerateLabel();
    }
    selectAllCheckbox.onchange = (e) => {
      const query = deviceSearch.toLowerCase();
      const matches = query ? devices.filter((d) => d.toLowerCase().includes(query)) : devices;
      if (e.target.checked) matches.forEach((d) => selectedDevices.add(d));
      else matches.forEach((d) => selectedDevices.delete(d));
      renderDeviceRows();
    };

    setupCard.appendChild(
      el("input", {
        class: "input", style: "max-width: 320px;", placeholder: "Search devices (e.g. hostname)...",
        oninput: (e) => { deviceSearch = e.target.value; renderDeviceRows(); },
      })
    );
    setupCard.appendChild(resultsHint);
    setupCard.appendChild(listWrap);
    renderDeviceRows();

    setupCard.appendChild(el("h3", { text: "Device role", style: "margin-top: var(--space-5);" }));
    setupCard.appendChild(
      el("input", {
        class: "input", style: "max-width: 320px;", placeholder: "e.g. Core Router, Branch Firewall",
        oninput: (e) => { deviceRole = e.target.value; },
      })
    );
    setupCard.appendChild(
      el("p", { class: "field__hint", text: "Applied to every selected device - this app has no per-device role of its own to default to." })
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

    setupCard.appendChild(el("div", { style: "margin-top: var(--space-5);" }, [generateBtn]));
  }

  async function generateReports(deviceNames) {
    if (!deviceNames.length) {
      toastWarning("Select at least one device.");
      return;
    }
    if (!deviceRole.trim()) {
      toastError("Device role is required.");
      return;
    }
    clear(resultArea);
    setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = true));

    const payload = {
      run_id: runId, device_filenames: deviceNames, device_role: deviceRole,
      audit_date: auditDate || null, llm_polish: llmPolish, backend: "auto",
    };

    let jobId;
    try {
      const res = await api.post("/api/reports/generate-batch", payload);
      jobId = res.job_id;
    } catch (err) {
      resultArea.appendChild(errorPanel(err, { title: "Unable to generate the compliance report" }));
      setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
      return;
    }

    const progressCard = el("div", { class: "card" }, [el("h3", { text: deviceNames.length > 1 ? "Generating Compliance Reports" : "Generating Compliance Report" })]);
    resultArea.appendChild(progressCard);

    activeJobDisposer = renderJobProgress(progressCard, jobId, (id) => `/api/reports/jobs/${id}`, {
      onDone: (result) => {
        setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
        clear(resultArea);
        toastSuccess(`Generated ${result.generated.length} of ${deviceNames.length} report(s).`);
        if (result.errors.length) toastWarning(`${result.errors.length} device(s) could not be reported.`, { timeout: 8000 });
        resultArea.appendChild(result.generated.length === 1 ? renderReport(result.generated[0]) : renderBatchResults(result));
      },
      onError: (err) => {
        setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
        resultArea.appendChild(errorPanel(err, { title: "Compliance report generation failed" }));
      },
    });
  }

  function renderBatchResults(result) {
    const wrap = el("div", { class: "stack" });
    const detailArea = el("div", {});
    wrap.appendChild(
      el("div", { class: "card" }, [
        el("h3", { text: `Compliance Reports (${result.generated.length})` }),
        el("div", { class: "data-table-wrap" }, [
          el("table", { class: "data-table" }, [
            el("thead", {}, [el("tr", {}, [el("th", { text: "Device" }), el("th", { text: "Compliance" }), el("th", { text: "" })])]),
            el(
              "tbody", {},
              result.generated.map((r) =>
                el("tr", {}, [
                  el("td", { text: r.device }),
                  el("td", {}, [compliancePctBadge(r.compliance_pct)]),
                  el("td", {}, [
                    el("div", { class: "cluster" }, [
                      el("button", { class: "btn btn--sm", text: "View Details", onclick: () => { clear(detailArea); detailArea.appendChild(renderReport(r)); } }),
                      r.pdf_available
                        ? el("a", { class: "btn btn--sm", href: `/api/reports/${runId}/${r.device}/pdf`, text: "PDF", target: "_blank" })
                        : null,
                    ]),
                  ]),
                ])
              )
            ),
          ]),
        ]),
        result.errors.length
          ? el("div", { style: "margin-top: var(--space-4);" }, [
              el("h4", { text: "Devices Skipped (error during generation)" }),
              el("ul", {}, result.errors.map((e) => el("li", { text: e }))),
            ])
          : null,
      ])
    );
    wrap.appendChild(detailArea);
    return wrap;
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

  return () => {
    if (activeJobDisposer) activeJobDisposer();
  };
}
