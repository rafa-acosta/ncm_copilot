"""Unit tests for report_generator.py."""

from __future__ import annotations

from compliance_engine import STATUS_EXCEPTION, STATUS_FAIL, STATUS_MANUAL_REVIEW, STATUS_PASS, ControlResult
from report_generator import build_summary, group_by_severity, render_html, render_pdf


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
