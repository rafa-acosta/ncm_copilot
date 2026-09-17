import { api } from "../api.js";
import { el, clear, renderMarkdownLite } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { toastError, toastSuccess, toastWarning } from "../components/toast.js";
import { renderJobProgress } from "../components/jobProgress.js";
import { getState } from "../state.js";
import { navigateTo } from "../router.js";

export async function render(container) {
  clear(container);

  container.appendChild(
    el("div", { class: "page-header" }, [
      el("div", { class: "page-header__heading" }, [
        el("h1", { text: "Briefings" }),
        el("p", { text: "LLM-assisted remediation guidance for a completed analysis run." }),
      ]),
    ])
  );

  const body = el("div", { class: "stack" });
  container.appendChild(body);
  body.appendChild(el("div", { class: "skeleton skeleton--block" }));

  let runs, status;
  try {
    [runs, status] = await Promise.all([api.get("/api/analysis/runs"), api.get("/api/settings/status")]);
  } catch (err) {
    clear(body);
    body.appendChild(errorPanel(err, { title: "Unable to load Briefings" }));
    return;
  }
  clear(body);

  if (!runs.length) {
    body.appendChild(
      el("div", { class: "empty-state card" }, [
        el("div", { class: "empty-state__icon", text: "\u{1F4AC}" }),
        el("div", { class: "empty-state__title", text: "No analysis runs yet" }),
        el("p", { text: "Run an analysis first, then generate briefings from its findings." }),
        el("div", { class: "cluster", style: "justify-content:center; margin-top: 12px;" }, [
          el("button", { class: "btn btn--primary", text: "Go to Analysis", onclick: () => navigateTo("/analysis") }),
        ]),
      ])
    );
    return;
  }

  if (!status.any_backend_reachable) {
    body.appendChild(
      el("div", { class: "card" }, [
        el("span", { class: "badge badge--warning", text: "No local LLM backend reachable" }),
        el("p", { class: "field__hint", text: "Briefings require a reachable backend. Check Settings for the registered backends." }),
      ])
    );
  }

  const persistedRun = getState().activeRunId;
  let runId = runs.some((r) => r.run_id === persistedRun) ? persistedRun : runs[0].run_id;
  let briefAll = true;
  let selectedDevices = new Set();
  let severityMin = "";

  const setupCard = el("div", { class: "card" });
  const resultArea = el("div", {});
  const listCard = el("div", { class: "card" });
  body.appendChild(setupCard);
  body.appendChild(resultArea);
  body.appendChild(listCard);

  async function loadRun() {
    clear(setupCard);
    clear(resultArea);
    let devices, existing;
    try {
      [devices, existing] = await Promise.all([
        api.get(`/api/analysis/runs/${runId}/devices`),
        api.get(`/api/briefings/${runId}`),
      ]);
    } catch (err) {
      setupCard.appendChild(errorPanel(err, { title: "Unable to load this run" }));
      return;
    }
    selectedDevices = new Set(devices);

    const runSelect = el(
      "select",
      { class: "input", style: "max-width: 260px;", onchange: (e) => { runId = e.target.value; loadRun(); } },
      runs.map((r) => el("option", { value: r.run_id, text: `${r.run_id} (${r.device_count} device${r.device_count === 1 ? "" : "s"})`, selected: r.run_id === runId ? "selected" : null }))
    );
    setupCard.appendChild(el("h3", { text: "Run" }));
    setupCard.appendChild(runSelect);

    setupCard.appendChild(el("h3", { text: "Devices", style: "margin-top: var(--space-5);" }));
    const allToggle = el("label", { class: "cluster" }, [
      el("input", { type: "checkbox", checked: "checked", onchange: (e) => { briefAll = e.target.checked; deviceList.style.display = briefAll ? "none" : ""; } }),
      el("span", { text: "Brief every device in this run" }),
    ]);
    setupCard.appendChild(allToggle);
    const deviceList = el("div", { class: "stack", style: "display:none; margin-top: var(--space-2);" },
      devices.map((d) =>
        el("label", { class: "cluster" }, [
          el("input", {
            type: "checkbox", checked: "checked",
            onchange: (e) => { if (e.target.checked) selectedDevices.add(d); else selectedDevices.delete(d); },
          }),
          el("span", { text: d }),
        ])
      )
    );
    setupCard.appendChild(deviceList);

    setupCard.appendChild(el("h3", { text: "Minimum severity", style: "margin-top: var(--space-5);" }));
    setupCard.appendChild(
      el(
        "select",
        { class: "input", style: "max-width: 200px;", onchange: (e) => { severityMin = e.target.value; } },
        ["", "Low", "Medium", "High"].map((v) => el("option", { value: v, text: v || "Any severity" }))
      )
    );

    setupCard.appendChild(
      el("div", { style: "margin-top: var(--space-5);" }, [
        el("button", { class: "btn btn--primary", text: "Generate Briefings", disabled: !status.any_backend_reachable ? "disabled" : null, onclick: runBriefing }),
      ])
    );

    renderExisting(existing);
  }

  async function runBriefing() {
    clear(resultArea);
    setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = true));

    let jobId;
    try {
      const res = await api.post("/api/briefings/run", {
        run_id: runId,
        device_filenames: briefAll ? null : Array.from(selectedDevices),
        severity_min: severityMin || null,
        backend: "auto",
      });
      jobId = res.job_id;
    } catch (err) {
      resultArea.appendChild(errorPanel(err, { title: "Unable to start briefing generation" }));
      setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
      return;
    }

    const progressCard = el("div", { class: "card" }, [el("h3", { text: "Generating Briefings" })]);
    resultArea.appendChild(progressCard);

    renderJobProgress(progressCard, jobId, (id) => `/api/briefings/jobs/${id}`, {
      onDone: async (result) => {
        toastSuccess(`Briefed ${result.briefed.length} device(s) using ${result.backend}.`);
        if (result.errors.length) toastWarning(`${result.errors.length} device(s) could not be briefed.`, { timeout: 8000 });
        setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
        const existing = await api.get(`/api/briefings/${runId}`);
        renderExisting(existing);
      },
      onError: (err) => {
        resultArea.appendChild(errorPanel(err, { title: "Briefing generation failed" }));
        setupCard.querySelectorAll("button, input, select").forEach((elm) => (elm.disabled = false));
      },
    });
  }

  function renderExisting(existing) {
    clear(listCard);
    listCard.appendChild(el("h3", { text: "Available Briefings" }));
    if (!existing.length) {
      listCard.appendChild(el("p", { class: "muted", text: "No briefings generated for this run yet." }));
      return;
    }
    const viewer = el("div", {});
    listCard.appendChild(
      el("div", { class: "cluster" }, existing.map((e) =>
        el("button", { class: "btn btn--sm", text: e.device, onclick: () => viewBriefing(e.device, viewer) })
      ))
    );
    listCard.appendChild(viewer);
    viewBriefing(existing[0].device, viewer);
  }

  async function viewBriefing(device, viewer) {
    clear(viewer);
    viewer.appendChild(el("div", { class: "skeleton skeleton--block", style: "margin-top: var(--space-4);" }));
    let briefing;
    try {
      briefing = await api.get(`/api/briefings/${runId}/${device}`);
    } catch (err) {
      clear(viewer);
      viewer.appendChild(errorPanel(err, { title: `Unable to load briefing for ${device}` }));
      return;
    }
    clear(viewer);
    const prose = el("div", { class: "card", style: "margin-top: var(--space-4);" });
    viewer.appendChild(prose);
    renderMarkdownLite(prose, briefing.markdown);
    viewer.appendChild(
      el("div", { class: "cluster", style: "margin-top: var(--space-3);" }, [
        el("button", {
          class: "btn btn--sm", text: "Copy",
          onclick: async () => {
            try {
              await navigator.clipboard.writeText(briefing.markdown);
              toastSuccess("Briefing copied to clipboard.");
            } catch {
              toastError("Unable to copy to clipboard.");
            }
          },
        }),
      ])
    );
  }

  await loadRun();
}
