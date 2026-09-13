"""Unit tests for compliance_history.py's snapshot persistence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from compliance_history import read_snapshots, write_snapshot
from compliance_metrics import FleetMetrics


def _metrics(strict=90.0) -> FleetMetrics:
    return FleetMetrics(
        device_count=10, applicable_expected_checks=150, strict_compliance_pct=strict,
        accepted_posture_pct=None, assessment_coverage_pct=100.0,
        status_counts={"PASS": 135, "FAIL": 15, "APPROVED_EXCEPTION": 0, "N_A": 0,
                       "MANUAL_REVIEW": 0, "ASSESSMENT_ERROR": 0, "NOT_ASSESSED": 0},
        fail_severity_counts={"Critical": 0, "High": 15, "Medium": 0, "Low": 0},
        fully_compliant_device_count=5, devices_with_findings_count=5,
        critical_finding_count=0, assessment_error_count=0, approved_exception_count=0,
    )


def test_write_snapshot_creates_a_file(tmp_path: Path):
    path = write_snapshot(tmp_path, _metrics(), "abc1234")
    assert path.exists()
    assert path.parent == tmp_path


def test_write_snapshot_never_overwrites_a_previous_one(tmp_path: Path):
    when = datetime(2026, 1, 1, 12, 0, 0)
    first = write_snapshot(tmp_path, _metrics(), "abc1234", when=when)
    second = write_snapshot(tmp_path, _metrics(), "abc1234", when=when)
    assert first != second
    assert first.exists() and second.exists()


def test_read_snapshots_empty_directory_returns_empty_list(tmp_path: Path):
    assert read_snapshots(tmp_path / "does_not_exist") == []


def test_read_snapshots_oldest_first(tmp_path: Path):
    write_snapshot(tmp_path, _metrics(strict=80.0), "abc1234", when=datetime(2026, 1, 1))
    write_snapshot(tmp_path, _metrics(strict=90.0), "abc1234", when=datetime(2026, 2, 1))
    snapshots = read_snapshots(tmp_path)
    assert len(snapshots) == 2
    assert snapshots[0]["metrics"]["strict_compliance_pct"] == 80.0
    assert snapshots[1]["metrics"]["strict_compliance_pct"] == 90.0
