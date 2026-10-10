import { el, formatDuration, formatTimestamp } from "../dom.js";

// Run/stage-level artifact status (Analysis/Briefing/Dashboard/Compliance
// Report generation state) - distinct from statusBadge.js's PASS/FAIL/etc.
// compliance-check badges, but reusing the same `.badge` CSS variants so the
// two vocabularies still read as one visual system. Shared across Overview,
// Analysis, and Briefings so a run's status never renders three different ways.
const STAGE_STATUS_MAP = {
  completed: { variant: "success", icon: "✓", label: "Completed" },
  in_progress: { variant: "accent", icon: "⏳", label: "In progress" },
  failed: { variant: "danger", icon: "✕", label: "Failed" },
  not_generated: { variant: "neutral", icon: "—", label: "Not generated" },
};

export function stageStatusBadge(status) {
  const meta = STAGE_STATUS_MAP[status] || STAGE_STATUS_MAP.not_generated;
  return el("span", { class: `badge badge--${meta.variant}` }, [`${meta.icon} ${meta.label}`]);
}

export function stageStatusLabel(status) {
  return (STAGE_STATUS_MAP[status] || STAGE_STATUS_MAP.not_generated).label;
}

// One <td>-ready cell combining a stage's status badge with its duration
// (or "N/A" if timing wasn't recorded - legacy run, or the stage hasn't run).
export function stageDurationCell(stage) {
  if (!stage) return el("span", { class: "muted", text: "N/A" });
  const wrap = el("div", { class: "stack", style: "gap: 2px;" }, [stageStatusBadge(stage.status)]);
  if (stage.status === "in_progress" && stage.started_at) {
    wrap.appendChild(el("span", { class: "muted", style: "font-size: var(--font-size-xs);", text: "running…" }));
  } else if (stage.duration_seconds !== null && stage.duration_seconds !== undefined) {
    wrap.appendChild(el("span", { class: "muted", style: "font-size: var(--font-size-xs);", text: formatDuration(stage.duration_seconds) }));
  } else if (stage.status === "completed" || stage.status === "failed") {
    wrap.appendChild(el("span", { class: "muted", style: "font-size: var(--font-size-xs);", text: "N/A" }));
  }
  return wrap;
}

// Golden Config traceability tag - "<name> · <source>" (e.g. "Working Copy ·
// Run snapshot", "Default · Override") - used by Overview's run table and
// the Briefings screen's traceability panel so the label always reads the
// same way. `meta` is a run_manifest golden_config dict, or null/undefined
// for a run with no recoverable Golden Config info at all.
const SOURCE_LABEL = { profile: "Profile", default: "Default", legacy: "Legacy run", override: "Override", "run snapshot": "Run snapshot" };

export function goldenConfigLabel(meta) {
  if (!meta || !meta.name) return "Unknown";
  const sourceLabel = SOURCE_LABEL[meta.source] || meta.source || "";
  return sourceLabel ? `${meta.name} (${sourceLabel})` : meta.name;
}

export function goldenConfigTag(meta) {
  if (!meta || !meta.name) return el("span", { class: "muted", text: "Unknown" });
  return el("span", { title: meta.checksum ? `Checksum: ${meta.checksum.slice(0, 12)}…` : undefined }, [goldenConfigLabel(meta)]);
}

export { formatDuration, formatTimestamp };
