"""End-to-end tests for compliance_dashboard_builder.py, from synthetic report.json fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import compliance_dashboard_builder as builder
from compliance_exceptions import load_exception_metadata

REPO_ROOT = Path(__file__).parent.parent
CONTROLS_PATH = REPO_ROOT / "controls.yaml"


def _entry(control_id="control_00001", title="Hostname", status="PASS", severity="High", evidence="ev", details=None):
    return {
        "control_id": control_id, "title": title, "status": status, "severity": severity,
        "risk": "risk text", "evidence_found": evidence, "remediation": "remediate it",
        "explanation": "", "details": details or [],
    }


def _write_report(path: Path, device_name: str, entries: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "device_name": device_name,
                "generated_at": "2026-01-01T00:00:00",
                "results": entries,
                "device_config_path": "", "golden_config_path": "",
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    root = tmp_path / "reports_dir"
    _write_report(
        root / "device_a" / "report.json", "device_a",
        [_entry("control_00001", status="PASS"), _entry("control_00002", status="FAIL", severity="Critical")],
    )
    _write_report(
        root / "device_b" / "report.json", "device_b",
        [_entry("control_00001", status="PASS"), _entry("control_00002", status="PASS")],
    )
    _write_report(
        root / "device_c" / "report.json", "device_c",
        [
            _entry("control_00001", status="EXCEPTION", details=["Exception granted: lab device."]),
            _entry("control_00002", status="MANUAL_REVIEW"),
        ],
    )
    return root


def test_load_findings_single_device(tmp_path: Path):
    single_dir = tmp_path / "single"
    _write_report(single_dir / "report.json", "solo_device", [_entry(status="PASS")])
    findings = builder.load_findings(single_dir, {})
    assert len(findings) == 1
    assert findings[0].device_name == "solo_device"


def test_load_findings_batch_layout(reports_dir: Path):
    findings = builder.load_findings(reports_dir, {})
    assert {f.device_name for f in findings} == {"device_a", "device_b", "device_c"}
    assert len(findings) == 6


def test_load_findings_raises_when_nothing_found(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        builder.load_findings(empty, {})


def test_load_findings_does_not_recurse_into_historical_runs(tmp_path: Path):
    # reports/<timestamp>/<device>/report.json two levels deep - must NOT be
    # picked up if --reports-dir is pointed at the archive root by mistake.
    root = tmp_path / "reports"
    _write_report(root / "20260101-000000" / "device_a" / "report.json", "device_a", [_entry()])
    with pytest.raises(FileNotFoundError):
        builder.load_findings(root, {})


def test_classify_device_posture_critical_wins_over_ordinary_fail():
    counts = {"PASS": 0, "FAIL": 1, "APPROVED_EXCEPTION": 0, "N_A": 0, "MANUAL_REVIEW": 0, "ASSESSMENT_ERROR": 0, "NOT_ASSESSED": 0}
    assert builder.classify_device_posture(counts, has_critical_failure=True) == "Critical Non-Compliant"
    assert builder.classify_device_posture(counts, has_critical_failure=False) == "Needs Remediation"


def test_classify_device_posture_manual_review_only_is_not_fully_assessed():
    counts = {"PASS": 1, "FAIL": 0, "APPROVED_EXCEPTION": 0, "N_A": 0, "MANUAL_REVIEW": 1, "ASSESSMENT_ERROR": 0, "NOT_ASSESSED": 0}
    assert builder.classify_device_posture(counts, has_critical_failure=False) == "Not Fully Assessed"


def test_classify_device_posture_fully_compliant():
    counts = {"PASS": 2, "FAIL": 0, "APPROVED_EXCEPTION": 0, "N_A": 0, "MANUAL_REVIEW": 0, "ASSESSMENT_ERROR": 0, "NOT_ASSESSED": 0}
    assert builder.classify_device_posture(counts, has_critical_failure=False) == "Fully Compliant"


def test_build_dashboard_end_to_end(reports_dir: Path, tmp_path: Path):
    output_dir = tmp_path / "out"
    history_dir = tmp_path / "history"
    context = builder.build_dashboard(reports_dir, CONTROLS_PATH, output_dir, history_dir)

    assert context["html_path"].exists()
    html = context["html_path"].read_text(encoding="utf-8")
    assert "device_a" in html and "device_b" in html and "device_c" in html
    assert "Executive Summary" in html

    fleet = context["fleet"]
    assert fleet.device_count == 3
    assert fleet.critical_finding_count == 1

    # One history snapshot should now exist.
    snapshots_written = list(history_dir.glob("*.json"))
    assert len(snapshots_written) == 1


def test_build_dashboard_second_run_adds_a_second_snapshot(reports_dir: Path, tmp_path: Path):
    history_dir = tmp_path / "history"
    builder.build_dashboard(reports_dir, CONTROLS_PATH, tmp_path / "out1", history_dir)
    builder.build_dashboard(reports_dir, CONTROLS_PATH, tmp_path / "out2", history_dir)
    assert len(list(history_dir.glob("*.json"))) == 2


def test_executive_summary_mentions_critical_when_present(reports_dir: Path, tmp_path: Path):
    context = builder.build_dashboard(reports_dir, CONTROLS_PATH, tmp_path / "out", tmp_path / "history")
    assert "critical" in context["executive_summary"].lower()


def test_exception_metadata_expiration_reaches_the_findings_table(tmp_path: Path):
    root = tmp_path / "reports"
    _write_report(root / "d1" / "report.json", "d1", [_entry("control_00004", status="EXCEPTION")])
    exceptions_path = tmp_path / "exceptions.yaml"
    exceptions_path.write_text(
        yaml.safe_dump({"control_00004": {"reason": "lab", "expiration_date": "2020-01-01"}}), encoding="utf-8"
    )
    exception_metadata = load_exception_metadata(exceptions_path)
    findings = builder.load_findings(root, exception_metadata)
    assert findings[0].expired_exception is True

    context = builder.build_dashboard(root, CONTROLS_PATH, tmp_path / "out", tmp_path / "history", exceptions_path)
    assert context["fleet"].accepted_posture_pct == 0.0  # the only check is an expired exception, not valid
    row = context["findings_table"][0]
    assert row["expired_exception"] is True
