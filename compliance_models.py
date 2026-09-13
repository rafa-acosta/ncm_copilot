"""Normalized status/severity taxonomy for the executive compliance dashboard (Tool 6).

Tool 1 (compliance_engine.py) only ever produces 5 real statuses: PASS, FAIL,
EXCEPTION, MANUAL_REVIEW, and (since main.py's per-control try/except)
ASSESSMENT_ERROR. This module maps those onto the richer 7-value taxonomy the
dashboard needs. APPROVED_EXCEPTION comes from EXCEPTION (an individual
finding is further reclassified to FAIL by compliance_metrics.py if its
exceptions.yaml entry has expired - that needs the exceptions file, not just
the status string, so it isn't done here). N_A and NOT_ASSESSED are defined
for completeness and correct formula behavior, but nothing in this engine
produces either today - every control is evaluated for every device
unconditionally, and a device that fails to load at all simply isn't in the
report set rather than appearing as NOT_ASSESSED rows. That's a documented
gap, not a fabricated one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PASS = "PASS"
FAIL = "FAIL"
APPROVED_EXCEPTION = "APPROVED_EXCEPTION"
N_A = "N_A"
MANUAL_REVIEW = "MANUAL_REVIEW"
ASSESSMENT_ERROR = "ASSESSMENT_ERROR"
NOT_ASSESSED = "NOT_ASSESSED"

ALL_STATUSES = [PASS, FAIL, APPROVED_EXCEPTION, N_A, MANUAL_REVIEW, ASSESSMENT_ERROR, NOT_ASSESSED]

# "Meaningful" per the dashboard spec: assessed one way or another, as opposed
# to never having been evaluated at all (NOT_ASSESSED) or a collection/parsing
# failure (ASSESSMENT_ERROR) - both excluded from assessment_coverage_pct's
# numerator (see compliance_metrics.py) but still counted in its denominator
# via applicable_expected_checks (everything except N_A).
MEANINGFUL_STATUSES = {PASS, FAIL, APPROVED_EXCEPTION, MANUAL_REVIEW}

_TOOL1_STATUS_MAP = {
    "PASS": PASS,
    "FAIL": FAIL,
    "EXCEPTION": APPROVED_EXCEPTION,
    "MANUAL_REVIEW": MANUAL_REVIEW,
    "ASSESSMENT_ERROR": ASSESSMENT_ERROR,
}


def normalize_status(tool1_status: str) -> str:
    """Map one of Tool 1's ControlReportEntry.status values onto the dashboard's 7-value taxonomy."""
    try:
        return _TOOL1_STATUS_MAP[tool1_status]
    except KeyError:
        raise ValueError(f"Unknown Tool 1 status: {tool1_status!r}") from None


# Low to high. controls.yaml only uses Low/Medium/High today - Critical is
# wired through every part of the dashboard but nothing is elevated to it by
# default (see documentation/CONTROL_UPDATE_REPORT.md for why: inventing which
# controls count as business-critical isn't this tool's call to make).
SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]


@dataclass
class NormalizedFinding:
    """One device-control evaluation, normalized for the analytics layer -
    built from a report_schema.ControlReportEntry plus the device it came
    from and (for APPROVED_EXCEPTION entries) any exceptions.yaml metadata."""

    device_name: str
    control_id: str
    title: str
    status: str  # one of the 7-value taxonomy above
    severity: str
    evidence_found: str
    remediation: str
    details: list[str] = field(default_factory=list)
    exception_reason: str | None = None
    expired_exception: bool = False
