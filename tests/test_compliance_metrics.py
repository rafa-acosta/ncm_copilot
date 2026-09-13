"""Unit tests for compliance_metrics.py's centralized formulas."""

from __future__ import annotations

import compliance_metrics as m
from compliance_models import (
    APPROVED_EXCEPTION,
    ASSESSMENT_ERROR,
    FAIL,
    MANUAL_REVIEW,
    N_A,
    NOT_ASSESSED,
    PASS,
    NormalizedFinding,
)


def _f(device="d1", control="control_00001", status=PASS, severity="High", **kw) -> NormalizedFinding:
    return NormalizedFinding(
        device_name=device, control_id=control, title="Title", status=status, severity=severity,
        evidence_found="ev", remediation="rem", **kw,
    )


# ---- applicable_expected_checks / strict_compliance_pct ------------------------

def test_applicable_expected_checks_excludes_n_a():
    findings = [_f(status=PASS), _f(status=FAIL), _f(status=N_A)]
    assert m.applicable_expected_checks(findings) == 2


def test_strict_compliance_pct_basic():
    findings = [_f(status=PASS), _f(status=PASS), _f(status=FAIL), _f(status=FAIL)]
    assert m.strict_compliance_pct(findings) == 50.0


def test_strict_compliance_pct_n_a_does_not_inflate_denominator():
    findings = [_f(status=PASS), _f(status=N_A), _f(status=N_A)]
    # Only 1 applicable check (the N_A entries are excluded), and it's a PASS.
    assert m.strict_compliance_pct(findings) == 100.0


def test_strict_compliance_pct_empty_dataset_is_zero_not_a_crash():
    assert m.strict_compliance_pct([]) == 0.0


def test_strict_compliance_pct_unassessed_and_error_never_count_as_pass():
    findings = [_f(status=PASS), _f(status=NOT_ASSESSED), _f(status=ASSESSMENT_ERROR)]
    assert m.strict_compliance_pct(findings) == round(100 / 3, 1)


# ---- accepted_posture_pct -------------------------------------------------------

def test_accepted_posture_pct_none_when_no_exceptions_exist():
    findings = [_f(status=PASS), _f(status=FAIL)]
    assert m.accepted_posture_pct(findings) == None  # noqa: E711 - explicit None check


def test_accepted_posture_pct_counts_valid_exception_as_compliant():
    findings = [_f(status=PASS), _f(status=APPROVED_EXCEPTION), _f(status=FAIL), _f(status=FAIL)]
    assert m.accepted_posture_pct(findings) == 50.0


def test_accepted_posture_pct_excludes_expired_exception():
    findings = [
        _f(status=PASS),
        _f(status=APPROVED_EXCEPTION, expired_exception=True),
        _f(status=FAIL),
        _f(status=FAIL),
    ]
    assert m.accepted_posture_pct(findings) == 25.0


def test_expired_exception_does_not_change_strict_compliance():
    valid = [_f(status=PASS), _f(status=APPROVED_EXCEPTION, expired_exception=False), _f(status=FAIL)]
    expired = [_f(status=PASS), _f(status=APPROVED_EXCEPTION, expired_exception=True), _f(status=FAIL)]
    assert m.strict_compliance_pct(valid) == m.strict_compliance_pct(expired)


# ---- assessment_coverage_pct -----------------------------------------------------

def test_assessment_coverage_pct_excludes_not_assessed_and_errors():
    findings = [_f(status=PASS), _f(status=FAIL), _f(status=NOT_ASSESSED), _f(status=ASSESSMENT_ERROR)]
    assert m.assessment_coverage_pct(findings) == 50.0


def test_assessment_coverage_pct_counts_expired_exception_as_still_assessed():
    findings = [_f(status=APPROVED_EXCEPTION, expired_exception=True), _f(status=NOT_ASSESSED)]
    assert m.assessment_coverage_pct(findings) == 50.0


def test_assessment_coverage_pct_manual_review_counts_as_meaningful():
    findings = [_f(status=MANUAL_REVIEW), _f(status=NOT_ASSESSED)]
    assert m.assessment_coverage_pct(findings) == 50.0


# ---- severity_counts --------------------------------------------------------------

def test_severity_counts_all_tiers_present_including_unused_critical():
    findings = [_f(status=FAIL, severity="High"), _f(status=FAIL, severity="High"), _f(status=PASS, severity="Low")]
    counts = m.severity_counts(findings)
    assert counts == {"Critical": 0, "High": 2, "Medium": 0, "Low": 0}


# ---- device / control aggregation --------------------------------------------------

def test_aggregate_by_device_basic():
    findings = [
        _f(device="d1", control="control_00001", status=PASS),
        _f(device="d1", control="control_00002", status=FAIL, severity="Critical"),
        _f(device="d2", control="control_00001", status=PASS),
        _f(device="d2", control="control_00002", status=PASS),
    ]
    devices = {d.device_name: d for d in m.aggregate_by_device(findings)}
    assert devices["d1"].strict_compliance_pct == 50.0
    assert devices["d1"].has_critical_failure is True
    assert devices["d2"].strict_compliance_pct == 100.0
    assert devices["d2"].has_critical_failure is False


def test_aggregate_by_control_affected_device_count():
    findings = [
        _f(device="d1", control="control_00001", status=FAIL),
        _f(device="d2", control="control_00001", status=FAIL),
        _f(device="d3", control="control_00001", status=PASS),
    ]
    controls = {c.control_id: c for c in m.aggregate_by_control(findings)}
    assert controls["control_00001"].affected_device_count == 2
    assert controls["control_00001"].compliance_pct == round(100 / 3, 1)


# ---- Pareto / top failing controls -------------------------------------------------

def test_top_failing_controls_sorted_by_fail_count_with_cumulative_pct():
    findings = [
        _f(device="d1", control="control_00001", status=FAIL),
        _f(device="d2", control="control_00001", status=FAIL),
        _f(device="d1", control="control_00002", status=FAIL),
        _f(device="d1", control="control_00003", status=PASS),
    ]
    controls = m.aggregate_by_control(findings)
    pareto = m.top_failing_controls(controls)
    assert [p.control_id for p in pareto] == ["control_00001", "control_00002"]
    assert pareto[0].cumulative_pct == round(100 * 2 / 3, 1)
    assert pareto[1].cumulative_pct == 100.0


def test_top_failing_controls_empty_when_no_failures():
    findings = [_f(status=PASS)]
    controls = m.aggregate_by_control(findings)
    assert m.top_failing_controls(controls) == []


# ---- top_non_compliant_devices -----------------------------------------------------

def test_top_non_compliant_devices_worst_first_critical_breaks_ties():
    findings = [
        _f(device="d1", control="control_00001", status=FAIL, severity="Critical"),
        _f(device="d1", control="control_00002", status=PASS),
        _f(device="d2", control="control_00001", status=FAIL, severity="Low"),
        _f(device="d2", control="control_00002", status=PASS),
    ]
    devices = m.aggregate_by_device(findings)
    worst = m.top_non_compliant_devices(devices)
    # Both are 50% - the critical one must sort first.
    assert worst[0].device_name == "d1"
    assert worst[0].has_critical_failure is True


# ---- fleet metrics ------------------------------------------------------------------

def test_compute_fleet_metrics_empty_dataset_no_crash():
    metrics = m.compute_fleet_metrics([], [])
    assert metrics.device_count == 0
    assert metrics.strict_compliance_pct == 0.0
    assert metrics.accepted_posture_pct is None


def test_compute_fleet_metrics_critical_finding_count():
    findings = [_f(status=FAIL, severity="Critical"), _f(status=FAIL, severity="Low")]
    devices = m.aggregate_by_device(findings)
    metrics = m.compute_fleet_metrics(findings, devices)
    assert metrics.critical_finding_count == 1
