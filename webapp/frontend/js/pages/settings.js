import { api } from "../api.js";
import { el, clear } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { toastError, toastSuccess } from "../components/toast.js";
import { confirmDialog } from "../components/modal.js";

const POLL_MS = 2000;

export async function render(container) {
  clear(container);
  container.appendChild(
    el("div", { class: "page-header" }, [
      el("div", { class: "page-header__heading" }, [
        el("h1", { text: "Settings" }),
        el("p", { text: "System status and configuration - sourced from the running backend." }),
      ]),
    ])
  );

  const body = el("div", { class: "stack" });
  container.appendChild(body);
  body.appendChild(el("div", { class: "skeleton skeleton--block" }));

  let status;
  try {
    status = await api.get("/api/settings/status");
  } catch (err) {
    clear(body);
    body.appendChild(errorPanel(err, { title: "Unable to load system status" }));
    return () => {};
  }
  clear(body);

  body.appendChild(
    el("div", { class: "card" }, [
      el("h3", { text: "Compliance Engine" }),
      settingsRow("Active controls.yaml version", status.controls_version),
      settingsRow("Data workspace", status.data_workspace),
      settingsRow("Uploaded configuration files", String(status.device_config_count)),
      settingsRow("Golden Config profiles", String(status.golden_profile_count)),
      settingsRow("Analysis runs on disk", String(status.run_count)),
    ])
  );

  const engineCard = el("div", { class: "card" });
  body.appendChild(engineCard);

  const openLogs = new Set();
  let pollTimer = null;

  function isUnsettled(backends) {
    return backends.some((b) => b.stopping || (b.managed_status === "running" && !b.reachable));
  }

  function ensurePolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      let fresh;
      try {
        fresh = await api.get("/api/settings/status");
      } catch {
        return;
      }
      status.backends = fresh.backends;
      renderEngineCard();
      if (!isUnsettled(status.backends)) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }, POLL_MS);
  }

  function statusBadgeFor(b) {
    if (b.reachable) return { variant: "success", text: "Online" };
    if (b.stopping) return { variant: "warning", text: "Stopping…" };
    if (b.managed_status === "running") return { variant: "warning", text: "Starting…" };
    if (b.managed_status === "failed") return { variant: "danger", text: "Failed to start" };
    return { variant: "danger", text: "Offline" };
  }

  async function startEngine(name) {
    try {
      status.backends = await api.post(`/api/settings/engines/${name}/start`);
      toastSuccess(`Starting ${name}…`);
    } catch (err) {
      toastError(err.detail);
      return;
    }
    renderEngineCard();
    ensurePolling();
  }

  async function stopEngine(name) {
    const ok = await confirmDialog({
      title: `Stop ${name}?`,
      body: "This interrupts any in-progress Briefings or Compliance Report LLM calls using it.",
      confirmLabel: "Stop",
      danger: true,
    });
    if (!ok) return;
    try {
      status.backends = await api.post(`/api/settings/engines/${name}/stop`);
      toastSuccess(`Stopping ${name}…`);
    } catch (err) {
      toastError(err.detail);
      return;
    }
    renderEngineCard();
    ensurePolling();
  }

  function engineRow(b) {
    const badge = statusBadgeFor(b);
    const actions = el("div", { class: "cluster" });
    if (b.can_start) {
      actions.appendChild(el("button", { class: "btn btn--sm btn--primary", text: "Start", onclick: () => startEngine(b.name) }));
    }
    if (b.can_stop) {
      actions.appendChild(el("button", { class: "btn btn--sm btn--danger", text: "Stop", onclick: () => stopEngine(b.name) }));
    }
    if (!b.manageable) {
      actions.appendChild(el("span", { class: "field__hint", text: "No launch script found" }));
    } else if (!b.can_start && !b.can_stop && b.reachable) {
      actions.appendChild(el("span", { class: "field__hint", text: "Started outside this app" }));
    }
    if (b.log_tail && b.log_tail.length) {
      actions.appendChild(
        el("button", {
          class: "btn-icon", "aria-label": `Toggle ${b.name} log`, title: "View launch log", text: "≡",
          onclick: () => {
            if (openLogs.has(b.name)) openLogs.delete(b.name);
            else openLogs.add(b.name);
            renderEngineCard();
          },
        })
      );
    }

    return el("tr", {}, [
      el("td", { text: b.name }),
      el("td", { text: b.role || "—" }),
      el("td", { text: b.base_url }),
      el("td", { text: b.model_name }),
      el("td", {}, [el("span", { class: `badge badge--${badge.variant}`, text: badge.text })]),
      el("td", {}, [actions]),
    ]);
  }

  function renderEngineCard() {
    clear(engineCard);
    engineCard.appendChild(el("h3", { text: "Local LLM Engines" }));
    engineCard.appendChild(
      el("p", {
        class: "field__hint",
        text: "Used by Briefings, and optionally by the Compliance Report's risk-statement polishing. Only one engine runs at a time on this hardware.",
      })
    );

    if (!status.backends.length) {
      engineCard.appendChild(el("p", { class: "muted", text: "No backends registered — see local-llm/config.yaml." }));
      return;
    }

    engineCard.appendChild(
      el("div", { class: "data-table-wrap" }, [
        el("table", { class: "data-table" }, [
          el("thead", {}, [
            el("tr", {}, [
              el("th", { text: "Backend" }), el("th", { text: "Role" }), el("th", { text: "Endpoint" }),
              el("th", { text: "Model" }), el("th", { text: "Status" }), el("th", { text: "" }),
            ]),
          ]),
          el("tbody", {}, status.backends.map((b) => engineRow(b))),
        ]),
      ])
    );

    for (const b of status.backends) {
      if (openLogs.has(b.name)) {
        engineCard.appendChild(el("p", { class: "field__hint", text: `${b.name} log:`, style: "margin-top: var(--space-3);" }));
        const box = el("div", { class: "code-preview" });
        if (b.log_tail.length) {
          b.log_tail.forEach((line) => box.appendChild(el("div", { text: line.length ? line : " " })));
        } else {
          box.appendChild(el("div", { text: "(no output yet)" }));
        }
        engineCard.appendChild(box);
      }
    }
  }

  renderEngineCard();
  if (isUnsettled(status.backends)) ensurePolling();

  return () => {
    if (pollTimer) clearInterval(pollTimer);
  };
}

function settingsRow(label, value) {
  return el("div", { class: "cluster", style: "justify-content: space-between; padding: 6px 0;" }, [
    el("span", { class: "muted", text: label }),
    el("code", { text: value }),
  ]);
}
