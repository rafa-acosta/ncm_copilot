import { el } from "../dom.js";

// Every compliance status is always icon/text + color, never color alone -
// accessibility requirement (don't rely exclusively on color).
const STATUS_MAP = {
  PASS: { variant: "success", icon: "✓", label: "PASS" },
  FAIL: { variant: "danger", icon: "✕", label: "FAIL" },
  EXCEPTION: { variant: "warning", icon: "⚠", label: "EXCEPTION" },
  MANUAL_REVIEW: { variant: "accent", icon: "✎", label: "MANUAL REVIEW" },
  ASSESSMENT_ERROR: { variant: "neutral", icon: "!", label: "ERROR" },
  compliant: { variant: "success", icon: "✓", label: "COMPLIANT" },
  non_compliant: { variant: "danger", icon: "✕", label: "NON-COMPLIANT" },
  exception: { variant: "warning", icon: "⚠", label: "EXCEPTION" },
  manual_review: { variant: "accent", icon: "✎", label: "MANUAL REVIEW" },
};

export function statusBadge(status) {
  const meta = STATUS_MAP[status] || { variant: "neutral", icon: "?", label: String(status || "UNKNOWN") };
  return el("span", { class: `badge badge--${meta.variant}` }, [`${meta.icon} ${meta.label}`]);
}

const SEVERITY_VARIANT = { Critical: "danger", High: "danger", Medium: "warning", Low: "neutral" };

export function severityBadge(severity) {
  const variant = SEVERITY_VARIANT[severity] || "neutral";
  return el("span", { class: `badge badge--${variant}`, text: severity || "—" });
}

export function compliancePctBadge(pct) {
  let variant = "success";
  if (pct < 70) variant = "danger";
  else if (pct < 90) variant = "warning";
  return el("span", { class: `badge badge--${variant}`, text: `${pct}%` });
}
