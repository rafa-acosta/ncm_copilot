"""Centralized compliance calculations for the executive dashboard (Tool 6).

Every formula here is documented against the plain-language definition it
implements, so the dashboard UI, the PDF/CSV exports, and any future API all
derive numbers from exactly this module rather than recomputing (and
potentially drifting from) their own version.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from compliance_models import (
    ALL_STATUSES,
    APPROVED_EXCEPTION,
    ASSESSMENT_ERROR,
    FAIL,
    MANUAL_REVIEW,
    MEANINGFUL_STATUSES,
    N_A,
    NOT_ASSESSED,
    PASS,
    SEVERITY_ORDER,
    NormalizedFinding,
)


def applicable_expected_checks(findings: list[NormalizedFinding]) -> int:
    """All evaluations excluding N_A - the shared denominator for every
    percentage below, so N_A can never inflate or deflate compliance."""
    return sum(1 for f in findings if f.status != N_A)


def strict_compliance_pct(findings: list[NormalizedFinding]) -> float:
    """PASS / applicable_expected_checks * 100 - the conservative primary
    metric. Unassessed or errored checks never silently count as compliant."""
    denom = applicable_expected_checks(findings)
    if denom == 0:
        return 0.0
    passed = sum(1 for f in findings if f.status == PASS)
    return round(100 * passed / denom, 1)


def accepted_posture_pct(findings: list[NormalizedFinding]) -> float | None:
    """(PASS + valid APPROVED_EXCEPTION) / applicable_expected_checks * 100.
    An expired exception does NOT count here (it still doesn't count in
    strict_compliance_pct either, since EXCEPTION was never PASS there) -
    returns None when there are no approved exceptions at all, so the caller
    can hide this metric entirely rather than show a redundant number
    identical to strict compliance."""
    denom = applicable_expected_checks(findings)
    if denom == 0:
        return None
    has_any_exception = any(f.status == APPROVED_EXCEPTION for f in findings)
    if not has_any_exception:
        return None
    valid = sum(
        1 for f in findings
        if f.status == PASS or (f.status == APPROVED_EXCEPTION and not f.expired_exception)
    )
    return round(100 * valid / denom, 1)


def assessment_coverage_pct(findings: list[NormalizedFinding]) -> float:
    """Percentage of applicable checks with a meaningful result (PASS, FAIL,
    APPROVED_EXCEPTION, MANUAL_REVIEW - expired-or-not, it was still
    assessed), excluding NOT_ASSESSED and ASSESSMENT_ERROR. Never shown
    without strict_compliance_pct alongside it - a high compliance number
    with low coverage is not a clean bill of health."""
    denom = applicable_expected_checks(findings)
    if denom == 0:
        return 0.0
    meaningful = sum(1 for f in findings if f.status in MEANINGFUL_STATUSES)
    return round(100 * meaningful / denom, 1)


def status_counts(findings: list[NormalizedFinding]) -> dict[str, int]:
    """Raw counts per status, all 7 taxonomy values always present (0 if unused)."""
    counts = {s: 0 for s in ALL_STATUSES}
    for f in findings:
        counts[f.status] += 1
    return counts


def severity_counts(findings: list[NormalizedFinding], status: str = FAIL) -> dict[str, int]:
    """Counts of `status` findings (FAIL by default) per severity tier, all
    4 tiers always present (0 if unused - including Critical, which nothing
    uses by default in this project)."""
    counts = {sev: 0 for sev in SEVERITY_ORDER}
    for f in findings:
        if f.status == status:
            counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts


@dataclass
class DeviceSummary:
    """One device's compliance posture across every control it was evaluated for."""

    device_name: str
    counts: dict[str, int]
    applicable: int
    pass_count: int
    strict_compliance_pct: float
    has_critical_failure: bool
    fail_control_ids: list[str] = field(default_factory=list)


def aggregate_by_device(findings: list[NormalizedFinding]) -> list[DeviceSummary]:
    """One DeviceSummary per distinct device_name, in first-seen order."""
    by_device: dict[str, list[NormalizedFinding]] = {}
    for f in findings:
        by_device.setdefault(f.device_name, []).append(f)

    summaries = []
    for name, items in by_device.items():
        counts = status_counts(items)
        applicable = applicable_expected_checks(items)
        pass_count = counts[PASS]
        pct = round(100 * pass_count / applicable, 1) if applicable else 0.0
        critical = any(f.status == FAIL and f.severity == "Critical" for f in items)
        fail_ids = [f.control_id for f in items if f.status == FAIL]
        summaries.append(DeviceSummary(name, counts, applicable, pass_count, pct, critical, fail_ids))
    return summaries


@dataclass
class ControlSummary:
    """One control's compliance posture across the whole fleet."""

    control_id: str
    title: str
    severity: str
    counts: dict[str, int]
    applicable: int
    pass_count: int
    compliance_pct: float
    affected_device_count: int


def aggregate_by_control(findings: list[NormalizedFinding]) -> list[ControlSummary]:
    """One ControlSummary per distinct control_id, in first-seen order."""
    by_control: dict[str, list[NormalizedFinding]] = {}
    for f in findings:
        by_control.setdefault(f.control_id, []).append(f)

    summaries = []
    for control_id, items in by_control.items():
        counts = status_counts(items)
        applicable = applicable_expected_checks(items)
        pass_count = counts[PASS]
        pct = round(100 * pass_count / applicable, 1) if applicable else 0.0
        affected = sum(1 for f in items if f.status == FAIL)
        summaries.append(
            ControlSummary(control_id, items[0].title, items[0].severity, counts, applicable, pass_count, pct, affected)
        )
    return summaries


@dataclass
class ParetoEntry:
    control_id: str
    title: str
    severity: str
    fail_count: int
    cumulative_pct: float


def top_failing_controls(control_summaries: list[ControlSummary]) -> list[ParetoEntry]:
    """Controls ranked by fail count descending, with a running cumulative
    percentage of total failures - exposes systemic baseline/template issues
    (a handful of controls typically account for most of the fleet's failures)."""
    ranked = sorted(control_summaries, key=lambda c: -c.counts[FAIL])
    total_fails = sum(c.counts[FAIL] for c in ranked)
    entries = []
    running = 0
    for c in ranked:
        if c.counts[FAIL] == 0:
            continue
        running += c.counts[FAIL]
        cumulative = round(100 * running / total_fails, 1) if total_fails else 0.0
        entries.append(ParetoEntry(c.control_id, c.title, c.severity, c.counts[FAIL], cumulative))
    return entries


def top_non_compliant_devices(device_summaries: list[DeviceSummary], limit: int = 10) -> list[DeviceSummary]:
    """Worst strict_compliance_pct first; devices with a critical failure are
    sorted ahead of a same-percentage device without one, since a critical
    finding must never be hidden behind an otherwise-similar score."""
    return sorted(
        device_summaries,
        key=lambda d: (d.strict_compliance_pct, not d.has_critical_failure),
    )[:limit]


@dataclass
class FleetMetrics:
    """Everything the dashboard's KPI row and top-level summary need, computed once."""

    device_count: int
    applicable_expected_checks: int
    strict_compliance_pct: float
    accepted_posture_pct: float | None
    assessment_coverage_pct: float
    status_counts: dict[str, int]
    fail_severity_counts: dict[str, int]
    fully_compliant_device_count: int
    devices_with_findings_count: int
    critical_finding_count: int
    assessment_error_count: int
    approved_exception_count: int


def compute_fleet_metrics(findings: list[NormalizedFinding], device_summaries: list[DeviceSummary]) -> FleetMetrics:
    counts = status_counts(findings)
    return FleetMetrics(
        device_count=len(device_summaries),
        applicable_expected_checks=applicable_expected_checks(findings),
        strict_compliance_pct=strict_compliance_pct(findings),
        accepted_posture_pct=accepted_posture_pct(findings),
        assessment_coverage_pct=assessment_coverage_pct(findings),
        status_counts=counts,
        fail_severity_counts=severity_counts(findings, status=FAIL),
        fully_compliant_device_count=sum(1 for d in device_summaries if not d.fail_control_ids),
        devices_with_findings_count=sum(1 for d in device_summaries if d.fail_control_ids),
        critical_finding_count=sum(1 for f in findings if f.status == FAIL and f.severity == "Critical"),
        assessment_error_count=counts[ASSESSMENT_ERROR],
        approved_exception_count=counts[APPROVED_EXCEPTION],
    )
