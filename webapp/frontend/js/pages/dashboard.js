import { api } from "../api.js";
import { el, clear } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { toastError, toastSuccess } from "../components/toast.js";
import { compliancePctBadge } from "../components/statusBadge.js";
import { getState } from "../state.js";
import { navigateTo } from "../router.js";

async function dashboardExists(runId) {
  try {
    const res = await fetch(`/api/dashboard/${runId}/html`);
    return res.ok;
  } catch {
    return false;
  }
}

export async function render(container) {
  clear(container);

  container.appendChild(
    el("div", { class: "page-header" }, [
      el("div", { class: "page-header__heading" }, [
        el("h1", { text: "Executive Dashboard" }),
        el("p", { text: "Fleet-wide compliance posture for a completed analysis run." }),
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
    body.appendChild(errorPanel(err, { title: "Unable to load the Dashboard" }));
    return;
  }
  clear(body);

  if (!runs.length) {
    body.appendChild(
      el("div", { class: "empty-state card" }, [
        el("div", { class: "empty-state__icon", text: "\u{1F4CA}" }),
        el("div", { class: "empty-state__title", text: "No analysis runs yet" }),
        el("p", { text: "Run an analysis with more than one device to build a fleet dashboard." }),
        el("div", { class: "cluster", style: "justify-content:center; margin-top: 12px;" }, [
          el("button", { class: "btn btn--primary", text: "Go to Analysis", onclick: () => navigateTo("/analysis") }),
        ]),
      ])
    );
    return;
  }

  const persistedRun = getState().activeRunId;
  let runId = runs.some((r) => r.run_id === persistedRun) ? persistedRun : runs[0].run_id;

  const setupCard = el("div", { class: "card" });
  const kpiArea = el("div", { class: "stack" });
  const iframeArea = el("div", { class: "card" });
  body.appendChild(setupCard);
  body.appendChild(kpiArea);
  body.appendChild(iframeArea);

  function kpi(label, value) {
    return el("div", { class: "kpi-card" }, [
      el("div", { class: "kpi-card__value", text: value }),
      el("div", { class: "kpi-card__label", text: label }),
    ]);
  }

  function deviceTable(devices) {
    let search = "";
    const wrap = el("div", { class: "card" });
    wrap.appendChild(el("h3", { text: "Devices" }));
    const searchInput = el("input", { class: "input", style: "max-width: 280px; margin-bottom: var(--space-3);", placeholder: "Search devices...", oninput: (e) => { search = e.target.value.toLowerCase(); renderRows(); } });
    wrap.appendChild(searchInput);
    const tableWrap = el("div", { class: "data-table-wrap" });
    wrap.appendChild(tableWrap);

    function renderRows() {
      clear(tableWrap);
      const visible = devices.filter((d) => d.device_name.toLowerCase().includes(search));
      tableWrap.appendChild(
        el("table", { class: "data-table" }, [
          el("thead", {}, [
            el("tr", {}, [
              el("th", { text: "Device" }), el("th", { text: "Compliance" }), el("th", { text: "Pass" }),
              el("th", { text: "Fail" }), el("th", { text: "Critical Failure" }),
            ]),
          ]),
          el(
            "tbody", {},
            visible.map((d) =>
              el("tr", {}, [
                el("td", { text: d.device_name }),
                el("td", {}, [compliancePctBadge(d.strict_compliance_pct)]),
                el("td", { text: String(d.pass_count) }),
                el("td", { text: String(d.fail_count) }),
                el("td", {}, [
                  d.has_critical_failure
                    ? el("span", { class: "badge badge--danger", text: "⚠ Yes" })
                    : el("span", { class: "badge badge--success", text: "✓ No" }),
                ]),
              ])
            )
          ),
        ])
      );
    }
    renderRows();
    return wrap;
  }

  function controlTable(controls) {
    const sorted = [...controls].sort((a, b) => a.compliance_pct - b.compliance_pct);
    return el("div", { class: "card" }, [
      el("h3", { text: "Controls — Fleet Compliance" }),
      el("div", { class: "data-table-wrap" }, [
        el("table", { class: "data-table" }, [
          el("thead", {}, [
            el("tr", {}, [
              el("th", { text: "Control" }), el("th", { text: "Compliance" }), el("th", { text: "Failing" }), el("th", { text: "Devices Affected" }),
            ]),
          ]),
          el(
            "tbody", {},
            sorted.map((c) =>
              el("tr", {}, [
                el("td", { text: `${c.control_id} — ${c.title}` }),
                el("td", {}, [compliancePctBadge(c.compliance_pct)]),
                el("td", { text: String(c.fail_count) }),
                el("td", { text: String(c.affected_device_count) }),
              ])
            )
          ),
        ]),
      ]),
    ]);
  }

  function worstDevicesCard(worst) {
    return el("div", { class: "card" }, [
      el("h3", { text: "Lowest-Compliance Devices" }),
      el(
        "div", { class: "stack" },
        worst.map((d) => el("div", { class: "cluster", style: "justify-content: space-between;" }, [
          el("span", { text: d.device_name }),
          compliancePctBadge(d.strict_compliance_pct),
        ]))
      ),
    ]);
  }

  function renderKpis(r) {
    clear(kpiArea);
    kpiArea.appendChild(
      el("div", { class: "card" }, [
        el("h3", { text: "Fleet Summary" }),
        el("p", { class: "muted", text: r.executive_summary }),
        el("div", { class: "kpi-grid" }, [
          kpi("Devices Analyzed", String(r.device_count)),
          kpi("Strict Compliance", `${r.strict_compliance_pct}%`),
          kpi("Assessment Coverage", `${r.assessment_coverage_pct}%`),
          kpi("Critical Findings", String(r.critical_finding_count)),
        ]),
      ])
    );
    kpiArea.appendChild(deviceTable(r.device_summaries));
    kpiArea.appendChild(controlTable(r.control_summaries));
    if (r.worst_devices.length) kpiArea.appendChild(worstDevicesCard(r.worst_devices));
  }

  function showIframe() {
    clear(iframeArea);
    iframeArea.appendChild(el("h3", { text: "Full Dashboard Report" }));
    iframeArea.appendChild(
      el("iframe", {
        src: `/api/dashboard/${runId}/html`,
        title: "Compliance Dashboard",
        style: "width:100%; min-height:900px; border:1px solid var(--color-border); border-radius: var(--radius-lg); background:#fff;",
      })
    );
  }

  async function buildDashboard(rebuildBtn) {
    rebuildBtn.disabled = true;
    try {
      const result = await api.post("/api/dashboard/build", { run_id: runId });
      toastSuccess("Dashboard built.");
      renderKpis(result);
      showIframe();
    } catch (err) {
      toastError(err.detail);
    }
    rebuildBtn.disabled = false;
  }

  async function loadRun() {
    clear(setupCard);
    clear(kpiArea);
    clear(iframeArea);

    setupCard.appendChild(el("h3", { text: "Run" }));
    setupCard.appendChild(
      el(
        "select",
        { class: "input", style: "max-width: 260px;", onchange: (e) => { runId = e.target.value; loadRun(); } },
        runs.map((r) => el("option", { value: r.run_id, text: `${r.run_id} (${r.device_count} device${r.device_count === 1 ? "" : "s"})`, selected: r.run_id === runId ? "selected" : null }))
      )
    );

    const exists = await dashboardExists(runId);
    const buildBtn = el("button", {
      class: "btn btn--primary", style: "margin-top: var(--space-4);",
      text: exists ? "Rebuild Dashboard" : "Build Dashboard",
      onclick: (e) => buildDashboard(e.target),
    });
    setupCard.appendChild(buildBtn);
    if (exists) {
      setupCard.appendChild(el("p", { class: "field__hint", text: "A dashboard already exists for this run. Rebuilding refreshes it and adds a new compliance-history snapshot." }));
      showIframe();
    } else {
      iframeArea.appendChild(
        el("div", { class: "empty-state" }, [el("p", { text: "Build the dashboard to see fleet-wide KPIs, device and control compliance." })])
      );
    }
  }

  await loadRun();
}
