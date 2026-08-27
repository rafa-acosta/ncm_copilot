"""Unit tests for report_generator.py."""

from __future__ import annotations

import json

from compliance_engine import STATUS_EXCEPTION, STATUS_FAIL, STATUS_MANUAL_REVIEW, STATUS_PASS, ControlResult
from report_generator import (
    build_fleet_summary,
    build_report_json,
    build_summary,
    group_by_severity,
    render_fleet_html,
    render_html,
    render_json,
    render_pdf,
)


def _result(control_id: str, status: str, severity: str = "High") -> ControlResult:
    return ControlResult(
        control_id=control_id,
        title=f"Title for {control_id}",
        status=status,
        severity=severity,
        risk="Some risk.",
        evidence_found="Some evidence.",
        remediation="Some remediation.",
        explanation="Some explanation.",
        details=["Detail one."],
    )


SAMPLE_RESULTS = [
    _result("control_00001", STATUS_PASS, "Low"),
    _result("control_00003", STATUS_FAIL, "High"),
    _result("control_00004", STATUS_FAIL, "High"),
    _result("control_00009", STATUS_EXCEPTION, "Medium"),
    _result("control_00012", STATUS_MANUAL_REVIEW, "Medium"),
]


def test_build_summary_counts():
    summary = build_summary(SAMPLE_RESULTS)
    assert summary["total"] == 5
    assert summary["counts"][STATUS_PASS] == 1
    assert summary["counts"][STATUS_FAIL] == 2
    assert summary["counts"][STATUS_EXCEPTION] == 1
    assert summary["counts"][STATUS_MANUAL_REVIEW] == 1
    assert summary["compliance_pct"] == 20.0


def test_group_by_severity_orders_high_medium_low():
    grouped = group_by_severity(SAMPLE_RESULTS)
    assert [severity for severity, _ in grouped] == ["High", "Medium", "Low"]


def test_render_html_contains_dashboard_and_status_colors(tmp_path):
    html_path = tmp_path / "report.html"
    render_html(SAMPLE_RESULTS, html_path, device_name="TEST_DEVICE")
    html = html_path.read_text(encoding="utf-8")

    assert "TEST_DEVICE" in html
    assert "status-pass" in html
    assert "status-fail" in html
    assert "status-exception" in html
    assert "status-manual_review" in html
    for result in SAMPLE_RESULTS:
        assert result.control_id in html


def test_render_pdf_produces_nonempty_file(tmp_path):
    html_path = tmp_path / "report.html"
    render_html(SAMPLE_RESULTS, html_path)
    pdf_path = tmp_path / "report.pdf"
    render_pdf(html_path, pdf_path)

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


# ---- fleet (batch) reporting -------------------------------------------------

CLEAN_RESULTS = [
    _result("control_00001", STATUS_PASS, "Low"),
    _result("control_00003", STATUS_PASS, "High"),
]

RESULTS_BY_DEVICE = {
    "rtr01": SAMPLE_RESULTS,  # 1 pass, 2 fail, 1 exception, 1 manual review -> 20%
    "rtr02": CLEAN_RESULTS,  # 2 pass -> 100%
}


def test_build_fleet_summary_totals():
    fleet = build_fleet_summary(RESULTS_BY_DEVICE)
    assert fleet["device_count"] == 2
    assert fleet["fully_compliant_count"] == 1  # only rtr02
    assert fleet["avg_compliance_pct"] == 60.0  # (20.0 + 100.0) / 2
    assert fleet["per_device"]["rtr01"]["compliance_pct"] == 20.0
    assert fleet["per_device"]["rtr02"]["compliance_pct"] == 100.0


def test_build_fleet_summary_top_failures_sorted_worst_first():
    fleet = build_fleet_summary(RESULTS_BY_DEVICE)
    control_ids = [f["control_id"] for f in fleet["top_failures"]]
    assert control_ids == ["control_00003", "control_00004"]
    assert all(f["fail_count"] == 1 for f in fleet["top_failures"])
    assert fleet["top_failures"][0]["device_names"] == ["rtr01"]


def test_build_fleet_summary_no_failures_yields_empty_top_failures():
    fleet = build_fleet_summary({"rtr02": CLEAN_RESULTS})
    assert fleet["top_failures"] == []
    assert fleet["fully_compliant_count"] == 1


def test_render_fleet_html_links_and_worst_first_ordering(tmp_path):
    links = {"rtr01": "rtr01/report.html", "rtr02": "rtr02/report.html"}
    output_path = tmp_path / "fleet_report.html"
    render_fleet_html(RESULTS_BY_DEVICE, links, output_path)
    html = output_path.read_text(encoding="utf-8")

    assert 'href="rtr01/report.html"' in html
    assert 'href="rtr02/report.html"' in html
    # worst-first: rtr01 (20%) must appear before rtr02 (100%) in the device table
    assert html.index(">rtr01<") < html.index(">rtr02<")
    assert "control_00003" in html and "control_00004" in html


# ---- JSON report (build_report_json / render_json) ----------------------------

def test_build_report_json_defaults_paths_to_empty_string():
    report = build_report_json(SAMPLE_RESULTS, device_name="RTR01")
    assert report.device_config_path == ""
    assert report.golden_config_path == ""


def test_build_report_json_includes_config_paths():
    report = build_report_json(
        SAMPLE_RESULTS,
        device_name="RTR01",
        device_config_path="/path/to/device_config.txt",
        golden_config_path="/path/to/golden_config.txt",
    )
    assert report.device_config_path == "/path/to/device_config.txt"
    assert report.golden_config_path == "/path/to/golden_config.txt"
    assert report.device_name == "RTR01"
    assert len(report.results) == len(SAMPLE_RESULTS)


def test_render_json_writes_valid_report_with_config_paths(tmp_path):
    output_path = tmp_path / "report.json"
    render_json(
        SAMPLE_RESULTS,
        output_path,
        device_name="RTR01",
        device_config_path="samples/device_config.txt",
        golden_config_path="samples/golden_config.txt",
    )
    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["device_name"] == "RTR01"
    assert data["device_config_path"] == "samples/device_config.txt"
    assert data["golden_config_path"] == "samples/golden_config.txt"
    assert len(data["results"]) == len(SAMPLE_RESULTS)
    assert data["results"][0]["control_id"] == SAMPLE_RESULTS[0].control_id


def test_render_json_old_style_report_without_config_paths_still_loads(tmp_path):
    # A report.json written before device_config_path/golden_config_path existed
    # must still validate - these fields default to "" rather than being required.
    from report_schema import ComplianceReport

    output_path = tmp_path / "old_report.json"
    old_style = {
        "device_name": "RTR01",
        "generated_at": "2026-01-01T00:00:00",
        "results": [],
    }
    output_path.write_text(json.dumps(old_style), encoding="utf-8")

    report = ComplianceReport.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert report.device_config_path == ""
    assert report.golden_config_path == ""
