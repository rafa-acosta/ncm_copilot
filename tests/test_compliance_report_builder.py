"""Unit tests for compliance_report_builder.py."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import compliance_report_builder as crb
from compliance_report_schema import FindingRow, ReportContext
from report_schema import ComplianceReport

REPO_ROOT = Path(__file__).parent.parent
CONTROLS_PATH = REPO_ROOT / "controls.yaml"
GOLDEN_CONFIG_PATH = REPO_ROOT / "samples" / "golden_config.txt"
DEVICE_CONFIG_PATH = REPO_ROOT / "samples" / "device_config.txt"


def _controls_by_id() -> dict[str, dict]:
    return {c["control_id"]: c for c in yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))}


def _real_report() -> ComplianceReport:
    from compliance_engine import ControlEvaluator
    from report_generator import build_report_json

    controls = yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))
    device_config = DEVICE_CONFIG_PATH.read_text(encoding="utf-8")
    golden_config = GOLDEN_CONFIG_PATH.read_text(encoding="utf-8")
    evaluator = ControlEvaluator()
    results = [evaluator.evaluate_control(c, device_config, golden_config) for c in controls]
    return build_report_json(
        results, device_name="device_config",
        device_config_path=str(DEVICE_CONFIG_PATH), golden_config_path=str(GOLDEN_CONFIG_PATH),
    )


# ---- controls_version ----------------------------------------------------------

def test_controls_version_returns_short_git_hash():
    version = crb.controls_version(CONTROLS_PATH)
    assert version != "unknown"
    assert len(version) >= 6  # short hashes are typically 7 chars, allow some slack


def test_controls_version_unknown_outside_git(tmp_path):
    fake_controls = tmp_path / "controls.yaml"
    fake_controls.write_text("- control_id: control_00001\n", encoding="utf-8")
    # a path outside the repo's git tree - git will report it as unknown/error
    version = crb.controls_version(tmp_path / "does_not_exist.yaml")
    assert version == "unknown"


# ---- remediation_command_and_inputs: the "sets match exactly" guarantee --------

def test_remediation_command_and_inputs_match_for_every_control():
    controls_by_id = _controls_by_id()
    for control in controls_by_id.values():
        command_text, inputs = crb.remediation_command_and_inputs(control)
        extracted = sorted(set(crb._TOKEN_RE.findall(command_text)))
        assert inputs == extracted, f"{control['control_id']}: inputs list diverged from the command text"


def test_control_00004_uses_placeholder_style_block_not_jinja():
    controls_by_id = _controls_by_id()
    command_text, inputs = crb.remediation_command_and_inputs(controls_by_id["control_00004"])
    assert "{%" not in command_text
    assert "{{" not in command_text
    assert "<tacacs_server_name>" in command_text
    assert "tacacs_server_name" in inputs


def test_ordinary_control_uses_command_template_verbatim():
    controls_by_id = _controls_by_id()
    control = controls_by_id["control_00001"]
    command_text, inputs = crb.remediation_command_and_inputs(control)
    assert command_text == control["command_template"].strip()
    assert inputs == ["hostname"]


# ---- risk statement validation --------------------------------------------------

def test_extract_risk_statement_real_controls_all_pass_deterministically():
    controls_by_id = _controls_by_id()
    for control in controls_by_id.values():
        statement = crb.extract_risk_statement(control)
        assert statement.endswith(".")
        assert len(statement) <= crb.MAX_RISK_STATEMENT_LENGTH


def test_extract_risk_statement_rejects_filler_phrase_without_llm():
    control = {"control_id": "control_99999", "risk": "This is important because it is important to note that things could break."}
    with pytest.raises(crb.RiskStatementError, match="control_99999"):
        crb.extract_risk_statement(control)


def test_extract_risk_statement_rejects_too_long_without_llm():
    control = {"control_id": "control_99999", "risk": "A" * (crb.MAX_RISK_STATEMENT_LENGTH + 50) + "."}
    with pytest.raises(crb.RiskStatementError):
        crb.extract_risk_statement(control)


class _FakeLLMClient:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.calls = []

    def polish_statement(self, original, violations):
        self.calls.append((original, violations))
        return self._response_text


def test_extract_risk_statement_llm_polish_accepts_clean_rewrite():
    control = {"control_id": "control_99999", "risk": "This is important because things could break."}
    fake_client = _FakeLLMClient("Misconfiguration exposes the device to compromise.")
    statement = crb.extract_risk_statement(control, llm_client=fake_client)
    assert statement == "Misconfiguration exposes the device to compromise."
    assert len(fake_client.calls) == 1


def test_extract_risk_statement_llm_polish_still_rejects_bad_rewrite():
    control = {"control_id": "control_99999", "risk": "This is important because things could break."}
    fake_client = _FakeLLMClient("This is important because it is still bad.")
    with pytest.raises(crb.RiskStatementError, match="llm-polish retry also failed"):
        crb.extract_risk_statement(control, llm_client=fake_client)


# ---- bucket_findings: status handling -------------------------------------------

def test_bucket_findings_all_17_controls_appear_in_appendix():
    report = _real_report()
    controls_by_id = _controls_by_id()
    findings_detail, manual_review, appendix, counts = crb.bucket_findings(report, controls_by_id)
    assert len(appendix) == 17
    assert {row.control_id for row in appendix} == set(controls_by_id)


def test_bucket_findings_counts_sum_to_appendix():
    report = _real_report()
    controls_by_id = _controls_by_id()
    findings_detail, manual_review, appendix, counts = crb.bucket_findings(report, controls_by_id)
    total_from_counts = counts["High"] + counts["Medium"] + counts["Low"] + counts["compliant"] + counts["exception"] + counts["manual_review"]
    assert total_from_counts == len(appendix)


def test_bucket_findings_findings_detail_sorted_high_to_low():
    report = _real_report()
    controls_by_id = _controls_by_id()
    findings_detail, _, _, _ = crb.bucket_findings(report, controls_by_id)
    order = {"High": 0, "Medium": 1, "Low": 2}
    ranks = [order[row.severity] for row in findings_detail if row.status == "non_compliant"]
    assert ranks == sorted(ranks)


def test_bucket_findings_manual_review_kept_separate():
    # control_00012 (Banners) now gets a deterministic presence check in the
    # real evaluator (see compliance_engine.py), so it no longer produces a
    # MANUAL_REVIEW status against the real sample configs - build a synthetic
    # report to exercise bucket_findings' manual-review bucketing directly.
    entries = [
        {
            "control_id": "control_00012", "title": "Banners", "status": "MANUAL_REVIEW", "severity": "Medium",
            "risk": "x", "evidence_found": "'banner motd' section in the running configuration.",
            "remediation": "x", "explanation": "",
            "details": ["This control requires human review of the actual wording/content."],
        }
    ]
    report = ComplianceReport(device_name="RTR01", generated_at="2026-08-26T12:00:00", results=entries)
    controls_by_id = _controls_by_id()
    findings_detail, manual_review, appendix, counts = crb.bucket_findings(report, controls_by_id)
    assert any(row.control_id == "control_00012" for row in manual_review)  # Banners
    assert not any(row.control_id == "control_00012" for row in findings_detail)


def test_bucket_findings_exception_status_appears_in_findings_detail_with_reason():
    entries = [
        {
            "control_id": "control_00001", "title": "Hostname", "status": "EXCEPTION", "severity": "Low",
            "risk": "x", "evidence_found": "Hostname is generic.", "remediation": "x", "explanation": "",
            "details": ["Exception granted: lab device, rename scheduled.", "Hostname is generic."],
        }
    ]
    report = ComplianceReport(device_name="RTR01", generated_at="2026-08-26T12:00:00", results=entries)
    controls_by_id = _controls_by_id()
    findings_detail, manual_review, appendix, counts = crb.bucket_findings(report, controls_by_id)
    assert len(findings_detail) == 1
    assert findings_detail[0].status == "exception"
    assert "lab device" in findings_detail[0].exception_reason
    assert counts["exception"] == 1


# ---- SLA table -------------------------------------------------------------------

def test_sla_table_dates_match_severity_days():
    audit_date = date(2026, 1, 1)
    table = crb.sla_table(audit_date)
    assert table["High"]["date"] == "2026-01-16"     # +15 days
    assert table["Medium"]["date"] == "2026-01-31"    # +30 days
    assert table["Low"]["date"] == "2026-04-01"        # +90 days
    assert "maintenance window" in table["High"]["text"]
    assert "refresh cycle" in table["Low"]["text"]


# ---- donut_svg ---------------------------------------------------------------------

def test_donut_svg_is_well_formed_and_labeled():
    svg = crb.donut_svg(47.1)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "47% compliant" in svg


# ---- build_report_context: full integration -------------------------------------

def test_build_report_context_end_to_end(tmp_path):
    report = _real_report()
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    ctx = crb.build_report_context(report_path, CONTROLS_PATH, device_role="edge-router")
    assert isinstance(ctx, ReportContext)
    assert ctx.device_name == "device_config"
    assert ctx.device_role == "edge-router"
    assert len(ctx.appendix) == 17
    assert ctx.compliance_pct == round(100 * ctx.counts["compliant"] / 17, 1)


def test_build_report_context_audit_date_override(tmp_path):
    report = _real_report()
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    ctx = crb.build_report_context(report_path, CONTROLS_PATH, device_role="edge-router", audit_date="2030-01-01")
    assert ctx.audit_date == "2030-01-01"
    assert ctx.sla["High"]["date"] == "2030-01-16"


# ---- rendering: no drift between formats -----------------------------------------

def test_render_markdown_and_pdf_reflect_same_data(tmp_path):
    row = FindingRow(
        control_id="control_00099", title="Synthetic", severity="High", status="non_compliant",
        evidence="ev", risk_statement="Risk.", remediation_command="cmd <x>",
        operator_inputs_required=["x"],
    )
    ctx = ReportContext(
        device_name="RTR01", device_role="edge-router", audit_date="2026-01-01", controls_version="abc1234",
        findings_detail=[row], manual_review=[], appendix=[row],
        counts={"High": 1, "Medium": 0, "Low": 0, "compliant": 0, "exception": 0, "manual_review": 0, "not_applicable": 0},
        compliance_pct=0.0, donut_svg=crb.donut_svg(0.0), sla=crb.sla_table(date(2026, 1, 1)),
    )
    md_path = tmp_path / "report.md"
    pdf_path = tmp_path / "report.pdf"
    crb.render_markdown(ctx, md_path)
    crb.render_pdf(ctx, pdf_path)

    md_text = md_path.read_text(encoding="utf-8")
    assert "control_00099" in md_text
    assert "<x>" in md_text
    assert pdf_path.exists() and pdf_path.stat().st_size > 0


def test_render_markdown_zero_findings_still_has_all_sections(tmp_path):
    ctx = ReportContext(
        device_name="RTR01", device_role="edge-router", audit_date="2026-01-01", controls_version="abc1234",
        findings_detail=[], manual_review=[], appendix=[],
        counts={"High": 0, "Medium": 0, "Low": 0, "compliant": 0, "exception": 0, "manual_review": 0, "not_applicable": 0},
        compliance_pct=0.0, donut_svg=crb.donut_svg(0.0), sla=crb.sla_table(date(2026, 1, 1)),
    )
    md_path = tmp_path / "report.md"
    crb.render_markdown(ctx, md_path)
    text = md_path.read_text(encoding="utf-8")
    for heading in [
        "## Executive Summary", "## Scope & Methodology", "## Findings Detail",
        "## Manual Review Required", "## Full Control Appendix", "## Remediation Roadmap", "## Sign-off",
    ]:
        assert heading in text, f"missing section: {heading}"
    assert "No non-compliant or exception findings" in text
    assert "No open remediation items" in text
