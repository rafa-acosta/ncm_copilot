"""Orchestrates the executive compliance dashboard (Tool 6): load every
device's report.json under a run directory, normalize results, compute fleet
metrics, persist a history snapshot, generate the deterministic executive
summary, and render the dashboard template.

No LLM anywhere in this module - every number is calculated directly from
structured data (report.json + controls.yaml + optional exceptions.yaml),
per the dashboard's own "reporting layer must be deterministic" requirement.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

import compliance_models as models
from compliance_exceptions import ExceptionMetadata, load_exception_metadata
from compliance_history import read_snapshots, write_snapshot
from compliance_metrics import (
    DeviceSummary,
    FleetMetrics,
    aggregate_by_control,
    aggregate_by_device,
    compute_fleet_metrics,
    top_failing_controls,
    top_non_compliant_devices,
)
from compliance_report_builder import controls_version
from compliance_svg_charts import multi_segment_donut_svg, trend_sparkline_svg

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "compliance_dashboard.html"

_POSTURE_COLORS = {
    "Fully Compliant": "#1e7e34",
    "Compliant With Approved Exceptions": "#c98a00",
    "Needs Remediation": "#d9822b",
    "Critical Non-Compliant": "#b02a37",
    "Not Fully Assessed": "#6c757d",
}
_SEVERITY_COLORS = {"Critical": "#7a1f2b", "High": "#b02a37", "Medium": "#c98a00", "Low": "#3d7a91"}
_STATUS_COLORS = {
    models.PASS: "#1e7e34",
    models.FAIL: "#b02a37",
    models.APPROVED_EXCEPTION: "#c98a00",
    models.N_A: "#adb5bd",
    models.MANUAL_REVIEW: "#6f42c1",
    models.ASSESSMENT_ERROR: "#343a40",
    models.NOT_ASSESSED: "#e9ecef",
}


def load_findings(reports_dir: Path, exception_metadata: dict[str, ExceptionMetadata]) -> list[models.NormalizedFinding]:
    """Load every report.json directly under `reports_dir` - either
    `reports_dir/report.json` (single device) or `reports_dir/*/report.json`
    (batch mode's per-device subfolders). Deliberately not recursive: pointing
    this at a whole archive root (e.g. `reports/` instead of `reports/latest`)
    would otherwise silently pull in every historical run's devices too."""
    report_paths = []
    single = reports_dir / "report.json"
    if single.exists():
        report_paths.append(single)
    report_paths.extend(sorted(reports_dir.glob("*/report.json")))
    if not report_paths:
        raise FileNotFoundError(
            f"No report.json found directly under {reports_dir} "
            "(expected reports_dir/report.json or reports_dir/<device>/report.json)."
        )

    findings: list[models.NormalizedFinding] = []
    for path in report_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        device_name = data.get("device_name") or path.parent.name
        for entry in data["results"]:
            status = models.normalize_status(entry["status"])
            exc_meta = exception_metadata.get(entry["control_id"]) if status == models.APPROVED_EXCEPTION else None
            findings.append(
                models.NormalizedFinding(
                    device_name=device_name,
                    control_id=entry["control_id"],
                    title=entry["title"],
                    status=status,
                    severity=entry["severity"],
                    evidence_found=entry["evidence_found"],
                    remediation=entry["remediation"],
                    details=entry.get("details", []),
                    exception_reason=exc_meta.reason if exc_meta else None,
                    expired_exception=exc_meta.is_expired if exc_meta else False,
                )
            )
    return findings


def classify_device_posture(counts: dict[str, int], has_critical_failure: bool) -> str:
    """One of the 5 mutually-exclusive posture categories from the dashboard
    spec. MANUAL_REVIEW/ASSESSMENT_ERROR/NOT_ASSESSED entries (with no FAIL
    present) fold into "Not Fully Assessed" - none of the 5 named categories
    is a literal fit for "a human still needs to look at this," and "the
    assessment isn't finished" is the closest true statement."""
    if counts[models.FAIL] > 0 and has_critical_failure:
        return "Critical Non-Compliant"
    if counts[models.FAIL] > 0:
        return "Needs Remediation"
    if counts[models.MANUAL_REVIEW] > 0 or counts[models.ASSESSMENT_ERROR] > 0 or counts[models.NOT_ASSESSED] > 0:
        return "Not Fully Assessed"
    if counts[models.APPROVED_EXCEPTION] > 0:
        return "Compliant With Approved Exceptions"
    return "Fully Compliant"


def device_posture_breakdown(device_summaries: list[DeviceSummary]) -> list[tuple[str, int, str]]:
    order = [
        "Fully Compliant",
        "Compliant With Approved Exceptions",
        "Needs Remediation",
        "Critical Non-Compliant",
        "Not Fully Assessed",
    ]
    tally = {label: 0 for label in order}
    for d in device_summaries:
        tally[classify_device_posture(d.counts, d.has_critical_failure)] += 1
    return [(label, tally[label], _POSTURE_COLORS[label]) for label in order]


_RISK_THRESHOLDS = (
    # (predicate, label) - first match wins. Deterministic, not opinion:
    # any critical finding or sub-70% strict compliance is High Risk
    # regardless of how good the headline percentage looks otherwise.
    (lambda m: m.critical_finding_count > 0 or m.strict_compliance_pct < 70, "HIGH RISK"),
    (lambda m: m.strict_compliance_pct < 90, "MODERATE RISK"),
    (lambda m: True, "LOW RISK"),
)


def generate_executive_summary(metrics: FleetMetrics, control_count: int, pareto: list) -> str:
    """A short, deterministic risk statement built entirely from `metrics` -
    no invented causes, no LLM. Matches the style (not the numbers) of the
    dashboard spec's example."""
    risk_label = next(label for predicate, label in _RISK_THRESHOLDS if predicate(metrics))

    sentences = [
        f"Overall Configuration Posture: {risk_label}.",
        f"{metrics.device_count} network device(s) were evaluated against {control_count} configuration controls.",
        f"Strict verified compliance is {metrics.strict_compliance_pct}% "
        f"with {metrics.assessment_coverage_pct}% assessment coverage.",
    ]
    if metrics.accepted_posture_pct is not None:
        sentences.append(f"Accepted posture (including approved exceptions) is {metrics.accepted_posture_pct}%.")
    if metrics.devices_with_findings_count:
        clause = f"{metrics.devices_with_findings_count} device(s) contain unresolved deviations"
        if metrics.critical_finding_count:
            clause += f" and {metrics.critical_finding_count} critical finding(s) remain open"
        sentences.append(clause + ".")
    elif metrics.device_count:
        sentences.append("No device currently has an unresolved deviation.")
    if pareto:
        sentences.append(f"{pareto[0].title} represents the largest systemic gap.")
    return " ".join(sentences)


def build_dashboard(
    reports_dir: Path,
    controls_path: Path,
    output_dir: Path,
    history_dir: Path,
    exceptions_path: Path | None = None,
) -> dict:
    """Compute everything and render the dashboard HTML into `output_dir`
    (caller handles run-directory archiving). Returns the render context
    dict, so callers (PDF/CSV export, tests) can reuse it without re-parsing."""
    exception_metadata = load_exception_metadata(exceptions_path)
    findings = load_findings(reports_dir, exception_metadata)

    device_summaries = aggregate_by_device(findings)
    control_summaries = aggregate_by_control(findings)
    fleet_metrics = compute_fleet_metrics(findings, device_summaries)
    pareto = top_failing_controls(control_summaries)
    worst_devices = top_non_compliant_devices(device_summaries)
    posture = device_posture_breakdown(device_summaries)

    version = controls_version(controls_path)
    snapshot_path = write_snapshot(history_dir, fleet_metrics, version)
    snapshots = read_snapshots(history_dir)
    trend = {
        "strict_compliance_pct": [s["metrics"]["strict_compliance_pct"] for s in snapshots],
        "assessment_coverage_pct": [s["metrics"]["assessment_coverage_pct"] for s in snapshots],
        "critical_finding_count": [s["metrics"]["critical_finding_count"] for s in snapshots],
        "timestamps": [s["timestamp"] for s in snapshots],
    }

    findings_table = _build_findings_table(findings)

    findings_by_device: dict[str, list[models.NormalizedFinding]] = {}
    findings_by_control: dict[str, list[models.NormalizedFinding]] = {}
    heatmap: dict[str, dict[str, str]] = {}
    for f in findings:
        findings_by_device.setdefault(f.device_name, []).append(f)
        findings_by_control.setdefault(f.control_id, []).append(f)
        heatmap.setdefault(f.device_name, {})[f.control_id] = f.status

    context = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "controls_version": version,
        "fleet": fleet_metrics,
        "device_summaries": sorted(device_summaries, key=lambda d: d.strict_compliance_pct),
        "control_summaries": control_summaries,
        "pareto": pareto,
        "worst_devices": worst_devices,
        "posture_breakdown": posture,
        "posture_donut_svg": multi_segment_donut_svg(posture),
        "trend": trend,
        "trend_svg": trend_sparkline_svg(trend["strict_compliance_pct"]),
        "executive_summary": generate_executive_summary(fleet_metrics, len(control_summaries), pareto),
        "findings_table": findings_table,
        "findings_by_device": findings_by_device,
        "findings_by_control": findings_by_control,
        "heatmap": heatmap,
        "status_colors": _STATUS_COLORS,
        "severity_colors": _SEVERITY_COLORS,
        "findings_json": json.dumps(
            {
                "findings": findings_table,
                "devices": [d.device_name for d in device_summaries],
                "controls": [c.control_id for c in control_summaries],
            }
        ),
        "snapshot_path": str(snapshot_path),
    }

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(["html"]))
    template = env.get_template(TEMPLATE_NAME)
    html = template.render(**context)

    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "compliance_dashboard.html"
    html_path.write_text(html, encoding="utf-8")
    context["html_path"] = html_path
    return context


_PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
_FINDING_STATUSES = {models.FAIL, models.APPROVED_EXCEPTION, models.MANUAL_REVIEW, models.ASSESSMENT_ERROR}


def _build_findings_table(findings: list[models.NormalizedFinding]) -> list[dict]:
    """One row per non-PASS, non-N_A finding, sorted worst-first (severity,
    then FAIL ahead of a merely-reviewed/excepted item at the same severity)."""
    rows = []
    for f in findings:
        if f.status not in _FINDING_STATUSES:
            continue
        rows.append(
            {
                "device": f.device_name,
                "control_id": f.control_id,
                "title": f.title,
                "finding": f.evidence_found,
                "severity": f.severity,
                "status": f.status,
                "expired_exception": f.expired_exception,
                "owner": "",
                "ticket": "",
                "due_date": "",
            }
        )
    rows.sort(key=lambda r: (_PRIORITY_RANK.get(r["severity"], 9), r["status"] != models.FAIL, r["device"]))
    return rows


def write_csv(findings_table: list[dict], output_path: Path) -> Path:
    """Findings export for engineering remediation tracking - stdlib csv, no new dependency."""
    import csv

    fieldnames = ["device", "control_id", "title", "severity", "status", "finding", "owner", "ticket", "due_date"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(findings_table)
    return output_path
