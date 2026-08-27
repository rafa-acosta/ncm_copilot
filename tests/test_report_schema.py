"""Unit tests for report_schema.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from report_schema import ComplianceReport

VALID_ENTRY = {
    "control_id": "control_00001",
    "title": "Hostname",
    "status": "PASS",
    "severity": "Low",
    "risk": "Some risk.",
    "evidence_found": "Some evidence.",
    "remediation": "Some remediation.",
    "explanation": "Some explanation.",
    "details": ["Detail one."],
}


def test_valid_report_round_trips():
    report = ComplianceReport(device_name="RTR01", generated_at="2026-08-26T12:00:00", results=[VALID_ENTRY])
    dumped = report.model_dump_json()
    reloaded = ComplianceReport.model_validate_json(dumped)
    assert reloaded.device_name == "RTR01"
    assert reloaded.results[0].control_id == "control_00001"
    assert reloaded.results[0].status == "PASS"


def test_malformed_status_is_rejected():
    bad_entry = {**VALID_ENTRY, "status": "NOT-APPLICABLE"}
    with pytest.raises(ValidationError):
        ComplianceReport(device_name="RTR01", generated_at="2026-08-26T12:00:00", results=[bad_entry])


def test_malformed_severity_is_rejected():
    bad_entry = {**VALID_ENTRY, "severity": "Critical"}
    with pytest.raises(ValidationError):
        ComplianceReport(device_name="RTR01", generated_at="2026-08-26T12:00:00", results=[bad_entry])


def test_details_defaults_to_empty_list():
    entry = {k: v for k, v in VALID_ENTRY.items() if k != "details"}
    report = ComplianceReport(device_name="RTR01", generated_at="2026-08-26T12:00:00", results=[entry])
    assert report.results[0].details == []
