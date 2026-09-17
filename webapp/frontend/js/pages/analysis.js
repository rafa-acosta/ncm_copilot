import { api } from "../api.js";
import { el, clear } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { toastError, toastSuccess, toastWarning } from "../components/toast.js";
import { renderJobProgress } from "../components/jobProgress.js";
import { getState, setState } from "../state.js";
import { navigateTo } from "../router.js";

export async function render(container) {
  clear(container);

  container.appendChild(
    el("div", { class: "page-header" }, [
      el("div", { class: "page-header__heading" }, [
        el("h1", { text: "Analysis" }),
        el("p", { text: "Run the Compliance Checker against selected device configs using a chosen Golden Config." }),
      ]),
    ])
  );

  const body = el("div", { class: "stack" });
  container.appendChild(body);
  body.appendChild(el("div", { class: "skeleton skeleton--block" }));

  let configs, profiles, runs;
  try {
    [configs, profiles, runs] = await Promise.all([
      api.get("/api/configs"),
      api.get("/api/golden/profiles"),
      api.get("/api/analysis/runs"),
    ]);
  } catch (err) {
    clear(body);
    body.appendChild(errorPanel(err, { title: "Unable to load the Analysis workspace" }));
    return;
  }
  clear(body);

  if (!configs.length) {
    body.appendChild(
      el("div", { class: "empty-state card" }, [
        el("div", { class: "empty-state__icon", text: "⚙" }),
        el("div", { class: "empty-state__title", text: "No configuration files uploaded yet" }),
        el("p", { text: "Upload device configs before running an analysis." }),
        el("div", { class: "cluster", style: "justify-content:center; margin-top: 12px;" }, [
          el("button", { class: "btn btn--primary", text: "Upload Configuration Files", onclick: () => navigateTo("/configuration-files") }),
        ]),
      ])
    );
    return;
  }
  if (!profiles.length) {
    body.appendChild(errorPanel({ detail: "No Golden Config profiles are available." }, { title: "Unable to run analysis" }));
    return;
  }

  const selected = new Set(configs.map((f) => f.filename));
  const persistedProfile = getState().activeGoldenProfileId;
  let selectedProfileId = profiles.some((p) => p.profile_id === persistedProfile) ? persistedProfile : profiles[0].profile_id;

  const setupCard = el("div", { class: "card" });
  body.appendChild(setupCard);
  const resultArea = el("div", {});
  body.appendChild(resultArea);

  function renderSetup() {
    clear(setupCard);
    setupCard.appendChild(el("h3", { text: "1. Choose configuration files" }));

    const listWrap = el("div", { class: "data-table-wrap" });
    const table = el("table", { class: "data-table" }, [
      el("thead", {}, [
        el("tr", {}, [
          el("th", {}, [
            el("input", {
              type: "checkbox", checked: selected.size === configs.length ? "checked" : null, "aria-label": "Select all",
              onchange: (e) => {
                if (e.target.checked) configs.forEach((f) => selected.add(f.filename));
                else selected.clear();
                renderSetup();
              },
            }),
          ]),
          el("th", { text: "Filename" }),
          el("th", { text: "Detected Device" }),
        ]),
      ]),
      el(
        "tbody", {},
        configs.map((f) =>
          el("tr", {}, [
            el("td", {}, [
              el("input", {
                type: "checkbox", checked: selected.has(f.filename) ? "checked" : null, "aria-label": `Select ${f.filename}`,
                onchange: (e) => {
                  if (e.target.checked) selected.add(f.filename);
                  else selected.delete(f.filename);
                  updateRunSummary();
                },
              }),
            ]),
            el("td", { text: f.filename }),
            el("td", { text: f.device_name || "—" }),
          ])
        )
      ),
    ]);
    listWrap.appendChild(table);
    setupCard.appendChild(listWrap);

    setupCard.appendChild(el("h3", { text: "2. Choose the Golden Config baseline", style: "margin-top: var(--space-5);" }));
    const select = el(
      "select",
      {
        class: "input", style: "max-width: 320px;",
        onchange: (e) => { selectedProfileId = e.target.value; updateRunSummary(); },
      },
      profiles.map((p) =>
        el("option", { value: p.profile_id, text: p.name + (p.read_only ? " (Default)" : ""), selected: p.profile_id === selectedProfileId ? "selected" : null })
      )
    );
    setupCard.appendChild(select);

    setupCard.appendChild(el("h3", { text: "3. Run", style: "margin-top: var(--space-5);" }));
    const summary = el("p", { class: "muted" });
    setupCard.appendChild(summary);
    const runBtn = el("button", { class: "btn btn--primary", text: "Run Analysis", onclick: runAnalysis });
    setupCard.appendChild(runBtn);

    function updateRunSummary() {
      const activeProfile = profiles.find((p) => p.profile_id === selectedProfileId);
      summary.textContent = `${selected.size} of ${configs.length} file(s) selected — Golden Config: ${activeProfile ? activeProfile.name : "—"}. Evaluates the 15 active compliance controls per device.`;
      runBtn.disabled = selected.size === 0;
    }
    updateRunSummary();
  }
  renderSetup();

  async function runAnalysis() {
    clear(resultArea);
    setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = true));

    let jobId;
    try {
      const res = await api.post("/api/analysis/run", {
        device_filenames: Array.from(selected),
        golden_profile_id: selectedProfileId,
      });
      jobId = res.job_id;
    } catch (err) {
      resultArea.appendChild(errorPanel(err, { title: "Unable to start analysis" }));
      setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
      return;
    }

    const progressCard = el("div", { class: "card" }, [el("h3", { text: "Running Analysis" })]);
    resultArea.appendChild(progressCard);

    renderJobProgress(
      progressCard,
      jobId,
      (id) => `/api/analysis/jobs/${id}`,
      {
        onDone: (result) => {
          setState({ activeRunId: result.run_id });
          toastSuccess(`Analysis complete — ${result.analyzed_count} of ${result.device_count} device(s) analyzed.`);
          if (result.errored_devices.length) {
            toastWarning(`${result.errored_devices.length} device(s) could not be analyzed and were skipped.`, { timeout: 8000 });
          }
          clear(resultArea);
          resultArea.appendChild(renderResultCard(result));
          setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
        },
        onError: (err) => {
          resultArea.appendChild(errorPanel(err, { title: "Analysis failed" }));
          setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
        },
      }
    );
  }

  function renderResultCard(result) {
    return el("div", { class: "card" }, [
      el("h3", { text: "Analysis Complete" }),
      el("div", { class: "kpi-grid" }, [
        kpi("Run", result.run_id),
        kpi("Devices Analyzed", `${result.analyzed_count} / ${result.device_count}`),
        kpi("Failing Checks", String(result.total_fail)),
        kpi("Golden Config Used", result.golden_profile),
      ]),
      result.errored_devices.length
        ? el("div", { class: "card", style: "margin-top: var(--space-4);" }, [
            el("h4", { text: "Devices Skipped (unreadable or unexpected error)" }),
            el("ul", {}, result.errored_devices.map((e) => el("li", { text: e }))),
          ])
        : null,
      el("div", { class: "cluster", style: "margin-top: var(--space-4);" }, [
        el("button", { class: "btn btn--primary", text: "View Dashboard", onclick: () => navigateTo("/dashboard") }),
        el("button", { class: "btn", text: "Generate Briefings", onclick: () => navigateTo("/briefings") }),
        el("button", { class: "btn", text: "Generate Compliance Report", onclick: () => navigateTo("/compliance-report") }),
      ]),
    ]);
  }

  function kpi(label, value) {
    return el("div", { class: "kpi-card" }, [
      el("div", { class: "kpi-card__value", text: value }),
      el("div", { class: "kpi-card__label", text: label }),
    ]);
  }

  if (runs.length) {
    body.appendChild(
      el("div", { class: "card" }, [
        el("h3", { text: "Recent Analysis Runs" }),
        el("div", { class: "data-table-wrap" }, [
          el("table", { class: "data-table" }, [
            el("thead", {}, [el("tr", {}, [el("th", { text: "Run" }), el("th", { text: "Devices" })])]),
            el(
              "tbody", {},
              runs.slice(0, 8).map((r) => el("tr", {}, [el("td", { text: r.run_id }), el("td", { text: String(r.device_count) })]))
            ),
          ]),
        ]),
      ])
    );
  }
}
