"""Builds HTML and PDF compliance reports from a list of ControlResult objects."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from compliance_engine import (
    STATUS_EXCEPTION,
    STATUS_FAIL,
    STATUS_MANUAL_REVIEW,
    STATUS_PASS,
    ControlResult,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "report_template.html"
FLEET_TEMPLATE_NAME = "fleet_report_template.html"

SEVERITY_ORDER = ["High", "Medium", "Low"]

STATUS_LABELS = {
    STATUS_PASS: "Pass",
    STATUS_FAIL: "Fail",
    STATUS_EXCEPTION: "Exception",
    STATUS_MANUAL_REVIEW: "Manual Review",
}


def build_summary(results: list[ControlResult]) -> dict:
    """Aggregate counts and overall compliance percentage for the dashboard."""
    total = len(results)
    counts = {status: 0 for status in STATUS_LABELS}
    for result in results:
        counts[result.status] += 1
    compliance_pct = round(100 * counts[STATUS_PASS] / total, 1) if total else 0.0
    return {"total": total, "counts": counts, "compliance_pct": compliance_pct}


def group_by_severity(results: list[ControlResult]) -> list[tuple[str, list[ControlResult]]]:
    """Group results by severity, ordered High -> Medium -> Low."""
    grouped: dict[str, list[ControlResult]] = {}
    for result in results:
        grouped.setdefault(result.severity, []).append(result)
    ordered = [(sev, grouped[sev]) for sev in SEVERITY_ORDER if grouped.get(sev)]
    for sev, items in grouped.items():
        if sev not in SEVERITY_ORDER:
            ordered.append((sev, items))
    return ordered


def render_html(results: list[ControlResult], output_path: Path, device_name: str = "") -> Path:
    """Render the Jinja2 report template to `output_path` and return that path."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(TEMPLATE_NAME)
    html = template.render(
        summary=build_summary(results),
        grouped_results=group_by_severity(results),
        status_labels=STATUS_LABELS,
        device_name=device_name,
    )
    output_path = Path(output_path)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def build_fleet_summary(results_by_device: dict[str, list[ControlResult]]) -> dict:
    """Aggregate per-device summaries plus fleet totals and the most common failures."""
    per_device = {name: build_summary(results) for name, results in results_by_device.items()}
    device_count = len(per_device)
    avg_compliance = (
        round(sum(s["compliance_pct"] for s in per_device.values()) / device_count, 1) if device_count else 0.0
    )
    fully_compliant = sum(1 for s in per_device.values() if s["counts"][STATUS_FAIL] == 0)

    failures: dict[str, dict] = {}
    for device_name, results in results_by_device.items():
        for result in results:
            if result.status != STATUS_FAIL:
                continue
            entry = failures.setdefault(
                result.control_id,
                {"control_id": result.control_id, "title": result.title, "severity": result.severity,
                 "fail_count": 0, "device_names": []},
            )
            entry["fail_count"] += 1
            entry["device_names"].append(device_name)

    top_failures = sorted(failures.values(), key=lambda f: f["fail_count"], reverse=True)

    return {
        "per_device": per_device,
        "device_count": device_count,
        "avg_compliance_pct": avg_compliance,
        "fully_compliant_count": fully_compliant,
        "top_failures": top_failures,
    }


def render_fleet_html(
    results_by_device: dict[str, list[ControlResult]],
    report_links: dict[str, str],
    output_path: Path,
) -> Path:
    """Render the fleet-level summary report and return `output_path`."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(FLEET_TEMPLATE_NAME)
    fleet = build_fleet_summary(results_by_device)
    devices = [
        {"name": name, "link": report_links[name], **fleet["per_device"][name]}
        for name in results_by_device
    ]
    devices.sort(key=lambda d: d["compliance_pct"])  # worst first

    html = template.render(fleet=fleet, devices=devices, status_labels=STATUS_LABELS)
    output_path = Path(output_path)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def render_pdf(html_path: Path, output_path: Path) -> Path:
    """Render a PDF from a previously-generated HTML report using WeasyPrint."""
    from weasyprint import HTML  # imported lazily: heavy optional dependency

    output_path = Path(output_path)
    HTML(filename=str(html_path)).write_pdf(str(output_path))
    return output_path
