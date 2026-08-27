"""Core logic for the Compliance Report Generator (Tool 5).

Turns Tool 1's report.json + controls.yaml into a ReportContext, the single
data structure both the Markdown and PDF templates render from. Deliberately
does NOT re-analyze the device config (that's Tool 1's job) and does NOT let
an LLM touch document structure, field order, severity colors, or
placeholder formatting - see this module's function docstrings for exactly
where the one optional, narrowly-validated LLM touchpoint is.
"""

from __future__ import annotations

import math
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from compliance_report_schema import FindingRow, FindingStatus, ReportContext
from report_schema import ComplianceReport, ControlReportEntry

_REPO_ROOT = Path(__file__).parent
_TEMPLATE_DIR = _REPO_ROOT / "templates"
_TOKEN_RE = re.compile(r"<(\w+)>")

# Starter deny-list of generic LLM-sounding filler phrases (COMPLIANCE_REPORT_PROMPT.md
# section 2.3's two named examples, plus common hedging patterns). Not exhaustive -
# extend as needed; matched case-insensitively as substrings.
FILLER_PHRASES = [
    "these issues need to be addressed to ensure",
    "this is important because",
    "it is important to note that",
    "it should be noted that",
    "in order to ensure",
    "as previously mentioned",
    "moving forward",
    "this could potentially",
    "may want to consider",
    "might want to consider",
    "needs to be addressed",
]

# A "hard length/format check" per the spec, not just a style preference. 220
# comfortably fits every real control's risk-statement first sentence in this
# project's controls.yaml (longest is 202 chars) while still catching a
# genuinely rambling one.
MAX_RISK_STATEMENT_LENGTH = 220

_SLA_DAYS = {"High": 15, "Medium": 30, "Low": 90}
_SLA_QUALIFIER = {
    "High": "or next maintenance window",
    "Medium": "",
    "Low": "or next refresh cycle",
}

# control_00004's command_template is real pre-converted Jinja (a {% for %}
# loop over an N-length tacacs_servers list) for golden_config_builder.py's
# benefit, not <word> placeholder tokens - so it can't be used directly here
# the way every other control's command_template can. This is a hand-written
# placeholder-style stand-in, documented as a special case (the same control
# is special-cased for the same underlying reason in golden_config_builder.py).
_CONTROL_00004_PLACEHOLDER_COMMAND = """aaa new-model
! Repeat the following 'tacacs server' block for each TACACS+ server.
tacacs server <tacacs_server_name>
 address ipv4 <tacacs_server_address>
 key 6 <tacacs_key>
 timeout <tacacs_timeout>
aaa group server tacacs+ <tacacs_group_name>
 server name <tacacs_server_name>
 ip tacacs source-interface <source_interface>"""


class RiskStatementError(ValueError):
    """Raised when a control's risk statement fails validation and no (or a
    failed) --llm-polish retry was available to fix it."""


def controls_version(controls_path: str | Path) -> str:
    """Short git commit hash of controls.yaml's last change, or "unknown".

    controls.yaml has no in-file version field - adding one would mean
    restructuring it from a bare list to a dict, breaking every other tool's
    yaml.safe_load() (all four expect a list). Deriving the version from git
    avoids that; never raises (wrapped defensively so a report can still be
    generated outside a git repo or before controls.yaml is committed).
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", str(controls_path)],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        version = result.stdout.strip()
        return version if result.returncode == 0 and version else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _validate_statement(text: str) -> list[str]:
    """Return every violation found (empty list = valid): length cap and filler-phrase deny-list."""
    violations = []
    if len(text) > MAX_RISK_STATEMENT_LENGTH:
        violations.append(f"exceeds {MAX_RISK_STATEMENT_LENGTH} characters ({len(text)})")
    lowered = text.lower()
    for phrase in FILLER_PHRASES:
        if phrase in lowered:
            violations.append(f"contains a denied filler phrase: '{phrase}'")
    return violations


def _first_sentence(text: str) -> str:
    normalized = " ".join(text.split())
    first = re.split(r"(?<=[.!?])\s", normalized, maxsplit=1)[0]
    return first if first.endswith((".", "!", "?")) else first + "."


def extract_risk_statement(control: dict, llm_client=None) -> str:
    """One-sentence, filler-free risk statement for `control`.

    Deterministic by default: the first sentence of controls.yaml's `risk`
    field. If that fails validation (too long, or contains a denied filler
    phrase) and no llm_client is given, raises RiskStatementError naming the
    control - this is a hard check, not a style preference, per the spec.

    If an llm_client IS given (--llm-polish), it gets exactly one retry: the
    LLM is asked to rewrite the statement within the same constraints, and
    the rewrite is re-validated against the identical deny-list/length check
    before being accepted - the LLM never bypasses validation, it only gets
    a chance to produce text that passes it.
    """
    candidate = _first_sentence(control["risk"])
    violations = _validate_statement(candidate)
    if not violations:
        return candidate

    if llm_client is not None:
        polished = llm_client.polish_statement(candidate, violations)
        polished = _first_sentence(polished)
        polish_violations = _validate_statement(polished)
        if not polish_violations:
            return polished
        violations = violations + [f"(--llm-polish retry also failed) {v}" for v in polish_violations]

    raise RiskStatementError(
        f"{control['control_id']}: risk statement failed validation: {'; '.join(violations)}"
    )


def remediation_command_and_inputs(control: dict) -> tuple[str, list[str]]:
    """(command_text, operator_inputs) for `control`.

    For every control except control_00004, command_text is controls.yaml's
    command_template AS-IS - it's already placeholder-only text (the spec's
    exact requirement), no rendering needed. operator_inputs is extracted by
    regex from that SAME string, so the two can never diverge - the
    "commands and operator inputs match exactly" guarantee is architectural,
    not a separate validation step run after the fact.
    """
    if control["control_id"] == "control_00004":
        command_text = _CONTROL_00004_PLACEHOLDER_COMMAND
    else:
        command_text = control["command_template"].strip()
    inputs = sorted(set(_TOKEN_RE.findall(command_text)))
    return command_text, inputs


_STATUS_MAP: dict[str, FindingStatus] = {
    "PASS": "compliant",
    "FAIL": "non_compliant",
    "EXCEPTION": "exception",
    "MANUAL_REVIEW": "manual_review",
}


def _build_row(entry: ControlReportEntry, control: dict, llm_client=None) -> FindingRow:
    command_text, inputs = remediation_command_and_inputs(control)
    exception_reason = None
    if entry.status == "EXCEPTION":
        exception_reason = next((d for d in entry.details if d.startswith("Exception granted:")), entry.evidence_found)
    return FindingRow(
        control_id=control["control_id"],
        title=control["title"],
        severity=control["severity"],
        status=_STATUS_MAP[entry.status],
        evidence=entry.evidence_found,
        risk_statement=extract_risk_statement(control, llm_client=llm_client),
        remediation_command=command_text,
        operator_inputs_required=inputs,
        exception_reason=exception_reason,
    )


def bucket_findings(
    report: ComplianceReport, controls_by_id: dict[str, dict], llm_client=None
) -> tuple[list[FindingRow], list[FindingRow], list[FindingRow], dict[str, int]]:
    """Split every control into (findings_detail, manual_review, appendix, counts).

    findings_detail: FAIL + EXCEPTION (both are documented non-compliance -
    an exception is a waiver, not a clean pass; omitting it would hide a real
    weakness from an auditor). manual_review: MANUAL_REVIEW controls, kept
    separate since they're neither confirmed-compliant nor
    confirmed-non-compliant. appendix: every control, every status (the spec's
    "full control appendix" requirement).
    """
    findings_detail: list[FindingRow] = []
    manual_review: list[FindingRow] = []
    appendix: list[FindingRow] = []
    counts = {"High": 0, "Medium": 0, "Low": 0, "compliant": 0, "exception": 0, "manual_review": 0, "not_applicable": 0}

    for entry in report.results:
        control = controls_by_id.get(entry.control_id)
        if control is None:
            continue
        row = _build_row(entry, control, llm_client=llm_client)
        appendix.append(row)

        if row.status == "non_compliant":
            counts[row.severity] += 1
            findings_detail.append(row)
        elif row.status == "exception":
            counts["exception"] += 1
            findings_detail.append(row)
        elif row.status == "manual_review":
            counts["manual_review"] += 1
            manual_review.append(row)
        else:
            counts["compliant"] += 1

    severity_order = {"High": 0, "Medium": 1, "Low": 2}
    findings_detail.sort(key=lambda r: severity_order.get(r.severity, 3))
    return findings_detail, manual_review, appendix, counts


def sla_table(audit_date: date) -> dict[str, dict[str, str]]:
    """{severity: {date: 'YYYY-MM-DD', text: 'YYYY-MM-DD (<= N days) or ...'}} for every severity."""
    table = {}
    for severity, days in _SLA_DAYS.items():
        target = audit_date + timedelta(days=days)
        qualifier = _SLA_QUALIFIER[severity]
        text = f"{target.isoformat()} (<= {days} days" + (f", {qualifier})" if qualifier else ")")
        table[severity] = {"date": target.isoformat(), "text": text}
    return table


def donut_svg(compliance_pct: float, size: int = 160, stroke: int = 20) -> str:
    """A small self-contained inline SVG donut chart - no charting dependency."""
    radius = (size - stroke) / 2
    center = size / 2
    circumference = 2 * math.pi * radius
    filled = circumference * (compliance_pct / 100)
    color = "#1e7e34" if compliance_pct >= 80 else ("#8a6d00" if compliance_pct >= 50 else "#b02a37")
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" '
        f'aria-label="{compliance_pct:.0f}% compliant">'
        f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" stroke="#e6e6e6" stroke-width="{stroke}"/>'
        f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-dasharray="{filled:.1f} {circumference:.1f}" stroke-linecap="butt" '
        f'transform="rotate(-90 {center} {center})"/>'
        f'<text x="{center}" y="{center}" text-anchor="middle" dominant-baseline="middle" '
        f'font-size="{size * 0.2:.0f}" font-family="sans-serif" font-weight="700">{compliance_pct:.0f}%</text>'
        f"</svg>"
    )


def build_report_context(
    report_path: str | Path,
    controls_path: str | Path,
    device_role: str,
    audit_date: str | None = None,
    llm_client=None,
) -> ReportContext:
    """Load report.json + controls.yaml and assemble the single ReportContext
    both templates render from - no drift between the Markdown and PDF
    outputs, because both come from exactly this one structure."""
    with open(report_path, encoding="utf-8") as f:
        report = ComplianceReport.model_validate_json(f.read())
    with open(controls_path, encoding="utf-8") as f:
        controls_by_id = {c["control_id"]: c for c in yaml.safe_load(f)}

    resolved_audit_date = date.fromisoformat(audit_date) if audit_date else report.generated_at.date()

    findings_detail, manual_review, appendix, counts = bucket_findings(report, controls_by_id, llm_client=llm_client)

    total = len(appendix)
    compliance_pct = round(100 * counts["compliant"] / total, 1) if total else 0.0

    return ReportContext(
        device_name=report.device_name,
        device_role=device_role,
        audit_date=resolved_audit_date.isoformat(),
        controls_version=controls_version(controls_path),
        findings_detail=findings_detail,
        manual_review=manual_review,
        appendix=appendix,
        counts=counts,
        compliance_pct=compliance_pct,
        donut_svg=donut_svg(compliance_pct),
        sla=sla_table(resolved_audit_date),
    )


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=select_autoescape(["html"]))


def render_markdown(context: ReportContext, output_path: str | Path) -> Path:
    """Render templates/compliance_report.md.j2 and return output_path."""
    template = _env().get_template("compliance_report.md.j2")
    output_path = Path(output_path)
    output_path.write_text(template.render(ctx=context), encoding="utf-8")
    return output_path


def render_pdf(context: ReportContext, output_path: str | Path) -> Path:
    """Render templates/compliance_report.html.j2 and convert straight to PDF
    via WeasyPrint - no intermediate .html file is kept on disk."""
    from weasyprint import HTML  # imported lazily: heavy optional dependency

    template = _env().get_template("compliance_report.html")
    html_text = template.render(ctx=context)
    output_path = Path(output_path)
    HTML(string=html_text).write_pdf(str(output_path))
    return output_path
