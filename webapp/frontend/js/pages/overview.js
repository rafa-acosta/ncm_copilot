import { api } from "../api.js";
import { el, clear } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { getState } from "../state.js";
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
      runs.length
        ? el(
            "div",
            { class: "data-table-wrap" },
            [
              el("table", { class: "data-table" }, [
                el("thead", {}, [el("tr", {}, [el("th", { text: "Run" }), el("th", { text: "Devices" }), el("th", { text: "" })])]),
                el(
                  "tbody",
                  {},
                  runs.slice(0, 8).map((r) =>
                    el("tr", {}, [
                      el("td", { text: r.run_id }),
                      el("td", { text: String(r.device_count) }),
                      el("td", {}, [
                        el("button", { class: "btn btn--sm", text: "View Dashboard", onclick: () => navigateTo("/dashboard") }),
                      ]),
                    ])
                  )
                ),
              ]),
            ]
          )
        : el("p", { class: "muted", text: "No analysis runs yet." }),
    ])
  );
}

function kpiCard(label, value, hint) {
  return el("div", { class: "kpi-card" }, [
    el("div", { class: "kpi-card__label", text: label }),
    el("div", { class: "kpi-card__value", text: value }),
    el("div", { class: "kpi-card__hint", text: hint }),
  ]);
}
