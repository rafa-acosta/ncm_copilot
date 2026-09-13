"""Pydantic schema for the Compliance Checker's JSON report output.

Shared by the writer (report_generator.render_json, called from main.py) and the
reader (remediation_advisor.load_report). Keeping this in one module is what
lets both sides stay in sync without duplicating the shape by hand.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ControlReportEntry(BaseModel):
    """One control's evaluated outcome, as written by compliance_engine.ControlResult."""

    control_id: str
    title: str
    status: Literal["PASS", "FAIL", "EXCEPTION", "MANUAL_REVIEW", "ASSESSMENT_ERROR"]
    severity: Literal["Low", "Medium", "High"]
    risk: str
    evidence_found: str
    remediation: str
    explanation: str = ""
    details: list[str] = []


class ComplianceReport(BaseModel):
    """A full Compliance Checker run for one device."""

    device_name: str
    generated_at: datetime
    results: list[ControlReportEntry]
    # Default "" (not required) so a report.json generated before these fields
    # existed still loads without a validation error.
    device_config_path: str = ""
    golden_config_path: str = ""
