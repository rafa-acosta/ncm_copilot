"""Pydantic schema for the Compliance Report Generator's per-finding data.

Adapts report_schema.ControlReportEntry (Tool 1's output) + a controls.yaml
block into the fixed report structure COMPLIANCE_REPORT_PROMPT.md section 2.3
requires - not a new independent findings format. See
compliance_report_builder.py for how these are assembled.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Tool 1's 4-state model (PASS/FAIL/EXCEPTION/MANUAL_REVIEW) is preserved here
# rather than collapsed into the spec's literal 3-state
# (compliant/non_compliant/not_applicable) - an EXCEPTION is a documented
# waiver, not a clean pass, and collapsing it would misrepresent an audit
# document's actual compliance posture. "not_applicable" is omitted entirely:
# this system has no not-applicable concept for any control today, so there
# is nothing honest to report in that bucket.
FindingStatus = Literal["compliant", "non_compliant", "exception", "manual_review"]


class FindingRow(BaseModel):
    """One control's report-ready row, built from a ControlReportEntry + its controls.yaml block."""

    control_id: str
    title: str
    severity: Literal["Low", "Medium", "High"]
    status: FindingStatus
    evidence: str
    risk_statement: str
    remediation_command: str
    operator_inputs_required: list[str]
    exception_reason: str | None = None


class ReportContext(BaseModel):
    """Everything both the Markdown and PDF templates render from - a single
    data structure so the two outputs can't drift (COMPLIANCE_REPORT_PROMPT.md
    acceptance criterion: "no drift between formats")."""

    device_name: str
    device_role: str
    audit_date: str
    controls_version: str
    findings_detail: list[FindingRow]
    manual_review: list[FindingRow]
    appendix: list[FindingRow]
    counts: dict[str, int]
    compliance_pct: float
    donut_svg: str
    sla: dict[str, dict[str, str]]
