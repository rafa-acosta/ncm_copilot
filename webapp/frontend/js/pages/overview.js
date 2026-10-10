import { api } from "../api.js";
import { el, clear, formatDuration, formatTimestamp } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { stageStatusBadge, goldenConfigLabel } from "../components/runStatus.js";
import { getState, setState } from "../state.js";
import { navigateTo } from "../router.js";

export async function render(container) {
  clear(container);
  container.appendChild(
    el("div", { class: "page-header" }, [
      el("div", { class: "page-header__heading" }, [
        el("h1", { text: "Overview" }),
        el("p", { text: "Network Configuration Compliance - current environment status." }),
      ]),
    ])
  );

  const body = el("div", { class: "stack" });
  container.appendChild(body);
  body.appendChild(el("div", { class: "skeleton skeleton--block" }));

  let status, configs, profiles, runs;
  try {
    [status, configs, profiles, runs] = await Promise.all([
      api.get("/api/settings/status"),
      api.get("/api/configs"),
      api.get("/api/golden/profiles"),
      api.get("/api/analysis/runs"),
    ]);
  } catch (err) {
    clear(body);
    body.appendChild(errorPanel(err, { title: "Unable to load overview" }));
    return;
  }
  clear(body);

  const activeProfileId = getState().activeGoldenProfileId;
  const activeProfile = profiles.find((p) => p.profile_id === activeProfileId) || null;
  const latestRun = runs[0] || null;

  body.appendChild(
    el("div", { class: "kpi-grid" }, [
      kpiCard("Configuration Files", String(configs.length), "Uploaded device configs ready to audit"),
      kpiCard(
        "Active Golden Config",
        activeProfile ? activeProfile.name : "None selected",
        activeProfile ? "Used as the audit baseline" : "Choose one in Golden Config"
      ),
      kpiCard(
        "Last Analysis Run",
        latestRun ? latestRun.run_id : "None yet",
        latestRun ? `${latestRun.device_count} device(s) analyzed` : "Run an analysis to get started"
      ),
      kpiCard(
        "System Status",
        status.any_backend_reachable ? "LLM backend online" : "LLM backend offline",
        `controls.yaml ${status.controls_version}`
      ),
    ])
  );

  if (!configs.length) {
    body.appendChild(
      el("div", { class: "empty-state card" }, [
        el("div", { class: "empty-state__icon", text: "\u{1F680}" }),
        el("div", { class: "empty-state__title", text: "Get started" }),
        el("p", { text: "Upload one or more device configuration files, then run an analysis against a Golden Config." }),
        el("div", { class: "cluster", style: "justify-content:center; margin-top: 12px;" }, [
          el("button", { class: "btn btn--primary", text: "Upload Configuration Files", onclick: () => navigateTo("/configuration-files") }),
        ]),
      ])
    );
    return;
  }

  body.appendChild(
    el("div", { class: "card" }, [
      el("h3", { text: "Primary Actions" }),
      el("div", { class: "cluster" }, [
        el("button", { class: "btn btn--primary", text: "Upload Configuration Files", onclick: () => navigateTo("/configuration-files") }),
        el("button", { class: "btn", text: "Run Analysis", onclick: () => navigateTo("/analysis") }),
        el("button", { class: "btn", text: "View Dashboard", onclick: () => navigateTo("/dashboard") }),
      ]),
    ])
  );

  body.appendChild(
    el("div", { class: "card" }, [
      el("h3", { text: "Recent Analysis Runs" }),
      runs.length ? recentRunsTable(runs) : el("p", { class: "muted", text: "No analysis runs yet." }),
    ])
  );
}

// A run's overall status is a rollup of its stages: any failure dominates,
// then "still running", then "every requested stage finished" - a run that
// only ever completed Analysis (never briefed/dashboarded) is still
// "Completed" for the stage it actually ran, not stuck at "in progress".
function overallRunStatus(run) {
  const stages = [run.analysis, run.briefing, run.dashboard].filter(Boolean);
  if (stages.some((s) => s.status === "failed")) return "failed";
  if (stages.some((s) => s.status === "in_progress")) return "in_progress";
  if (run.analysis && run.analysis.status === "completed") return "completed";
  return run.analysis ? run.analysis.status : "not_generated";
}

function totalElapsed(run) {
  const durations = [run.analysis, run.briefing, run.dashboard]
    .map((s) => s && s.duration_seconds)
    .filter((d) => d !== null && d !== undefined);
  if (durations.length < 2) return null; // a single stage's own duration already shows this - avoid redundant text
  return durations.reduce((sum, d) => sum + d, 0);
}

function recentRunsTable(runs) {
  return el("div", { class: "data-table-wrap" }, [
    el("table", { class: "data-table" }, [
      el("thead", {}, [
        el("tr", {}, [
          el("th", { text: "Run ID" }), el("th", { text: "Started" }), el("th", { text: "Devices" }),
          el("th", { text: "Golden Config" }), el("th", { text: "Analysis" }), el("th", { text: "Time" }),
          el("th", { text: "Briefing" }), el("th", { text: "Time" }), el("th", { text: "Dashboard" }),
          el("th", { text: "Time" }), el("th", { text: "Status" }), el("th", { text: "Total" }),
        ]),
      ]),
      el(
        "tbody", {},
        runs.slice(0, 8).map((r) => {
          const total = totalElapsed(r);
          return el("tr", {
            class: "is-clickable",
            title: "Open this run's Analysis workspace",
            onclick: () => { setState({ activeRunId: r.run_id }); navigateTo("/analysis"); },
          }, [
            el("td", { text: r.run_id }),
            el("td", { text: r.created_at ? formatTimestamp(r.created_at) : (r.is_legacy ? "Legacy run" : "N/A") }),
            el("td", { text: String(r.device_count) }),
            el("td", { text: goldenConfigLabel(r.golden_config) }),
            el("td", {}, [stageStatusBadge(r.analysis ? r.analysis.status : "not_generated")]),
            el("td", { text: formatDuration(r.analysis ? r.analysis.duration_seconds : null) }),
            el("td", {}, [stageStatusBadge(r.briefing ? r.briefing.status : "not_generated")]),
            el("td", { text: formatDuration(r.briefing ? r.briefing.duration_seconds : null) }),
            el("td", {}, [stageStatusBadge(r.dashboard ? r.dashboard.status : "not_generated")]),
            el("td", { text: formatDuration(r.dashboard ? r.dashboard.duration_seconds : null) }),
            el("td", {}, [stageStatusBadge(overallRunStatus(r))]),
            el("td", { text: total !== null ? formatDuration(total) : "—" }),
          ]);
        })
      ),
    ]),
  ]);
}

function kpiCard(label, value, hint) {
  return el("div", { class: "kpi-card" }, [
    el("div", { class: "kpi-card__label", text: label }),
    el("div", { class: "kpi-card__value", text: value }),
    el("div", { class: "kpi-card__hint", text: hint }),
  ]);
}
