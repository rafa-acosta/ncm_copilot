"""Core logic for the Compliance Remediation Advisor (CRA).

Turns a Compliance Checker JSON report into a severity-ordered remediation
briefing: for each FAILED control, an LLM-written plain-language explanation
of what's missing and why (see llm_client.LLMClient.explain), plus the exact
remediation commands sourced verbatim from controls.yaml.

Command-sourcing guarantee: `Finding.command_block` and
`.remediation_recommendation` are copied directly from the control's
`config_example`/`remediation` fields in `build_finding` and never pass
through the LLM - `llm_client.LLMClient.explain(...)`'s return value only
ever becomes `Finding.explanation`. This makes "every remediation command is
byte-for-byte from controls.yaml, never LLM-generated" true by construction,
not by trusting the model followed instructions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from llm_client import LLMClient
from report_schema import ComplianceReport, ControlReportEntry

TEMPLATE_DIR = Path(__file__).parent / "templates"
BRIEFING_TEMPLATE_NAME = "briefing_template.md.j2"

SEVERITY_ORDER = ["High", "Medium", "Low"]
SEVERITY_RANK = {name: i for i, name in enumerate(SEVERITY_ORDER)}
SEVERITY_EMOJI = {"High": "\U0001f534", "Medium": "\U0001f7e1", "Low": "\U0001f7e2"}

_TOKEN_RE = re.compile(r"<(\w+)>")


@dataclass
class Finding:
    """One FAILED control, assembled into a briefing entry."""

    control_id: str
    title: str
    severity: str
    risk: str
    remediation_recommendation: str
    command_block: str
    still_needed_variables: list[str]
    explanation: str
    finding_details: list[str] = field(default_factory=list)


def load_report(path: str | Path) -> ComplianceReport:
    """Load and pydantic-validate a Compliance Checker JSON report."""
    with open(path, encoding="utf-8") as f:
        return ComplianceReport.model_validate_json(f.read())


def load_controls_by_id(path: str | Path) -> dict[str, dict]:
    """Load controls.yaml into a dict keyed by control_id (same pattern as golden_config_builder.py)."""
    with open(path, encoding="utf-8") as f:
        return {c["control_id"]: c for c in yaml.safe_load(f)}


def missing_variables(control: dict, device_vars: dict | None) -> list[str]:
    """`<word>` tokens in the control's command_template that aren't already
    resolved (present and non-empty) under device_vars[control_id].

    `config_example` (the block shown to the operator as command_block) is a
    fully filled-in literal example - the <word> placeholders live in
    command_template instead (same source golden_config_builder.py renders from).
    """
    tokens = sorted(set(_TOKEN_RE.findall(control.get("command_template") or "")))
    if not device_vars:
        return tokens
    resolved = device_vars.get(control["control_id"], {})
    # A falsy-but-real value (0, False) still counts as resolved - only an
    # absent key or an explicit empty string counts as still-needed. A plain
    # truthiness check would wrongly flag e.g. start_line_number: 0 as missing.
    return [t for t in tokens if resolved.get(t) is None or resolved.get(t) == ""]


def select_findings(
    report: ComplianceReport,
    controls_by_id: dict[str, dict],
    severity_min: str | None = None,
) -> list[ControlReportEntry]:
    """FAIL-status entries only, filtered to severity >= severity_min (High first),
    sorted High -> Medium -> Low."""
    min_rank = SEVERITY_RANK[severity_min.capitalize()] if severity_min else SEVERITY_RANK["Low"]
    failed = [
        entry
        for entry in report.results
        if entry.status == "FAIL" and entry.control_id in controls_by_id and SEVERITY_RANK[entry.severity] <= min_rank
    ]
    return sorted(failed, key=lambda e: SEVERITY_RANK[e.severity])


def build_finding(
    control: dict,
    report_entry: ControlReportEntry,
    device_vars: dict | None,
    llm_client: LLMClient,
) -> Finding:
    """Assemble one Finding: deterministic command block + remediation text from
    controls.yaml, LLM-written explanation grounded in the same control plus the
    specific finding details from the report."""
    explanation = llm_client.explain(control, report_entry.details)
    return Finding(
        control_id=control["control_id"],
        title=control["title"],
        severity=control["severity"],
        risk=control["risk"].strip(),
        remediation_recommendation=control["remediation"].strip(),
        command_block=control["config_example"].strip(),
        still_needed_variables=missing_variables(control, device_vars),
        explanation=explanation,
        finding_details=report_entry.details,
    )


def _group_by_severity(findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
    grouped: dict[str, list[Finding]] = {}
    for f in findings:
        grouped.setdefault(f.severity, []).append(f)
    return [(sev, grouped[sev]) for sev in SEVERITY_ORDER if grouped.get(sev)]


def render_markdown(
    findings: list[Finding],
    device_name: str,
    backend_label: str,
    output_path: str | Path,
    generated_at: str,
    device_config_path: str = "",
    golden_config_path: str = "",
) -> Path:
    """Render the Jinja2 markdown briefing template and return `output_path`."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(disabled_extensions=(".j2",)))
    template = env.get_template(BRIEFING_TEMPLATE_NAME)
    markdown = template.render(
        device_name=device_name,
        backend_label=backend_label,
        generated_at=generated_at,
        device_config_path=device_config_path,
        golden_config_path=golden_config_path,
        grouped_findings=_group_by_severity(findings),
        severity_emoji=SEVERITY_EMOJI,
    )
    output_path = Path(output_path)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def render_briefing_json(
    findings: list[Finding],
    device_name: str,
    backend_label: str,
    output_path: str | Path,
    generated_at: str,
    device_config_path: str = "",
    golden_config_path: str = "",
) -> Path:
    """Write briefing.json: the findings list plus a suggested_device_vars_patch
    shaped exactly like device_vars.json ({control_id: {var: null, ...}}) built
    from each finding's still-needed variables, so it can eventually be merged
    directly into device_vars.json to pre-fill the Golden Config Creator."""
    patch: dict[str, dict[str, None]] = {}
    for f in findings:
        if f.still_needed_variables:
            patch[f.control_id] = dict.fromkeys(f.still_needed_variables)

    data = {
        "device_name": device_name,
        "generated_at": generated_at,
        "backend_used": backend_label,
        "device_config_path": device_config_path,
        "golden_config_path": golden_config_path,
        "findings": [
            {
                "control_id": f.control_id,
                "title": f.title,
                "severity": f.severity,
                "risk": f.risk,
                "explanation": f.explanation,
                "remediation_recommendation": f.remediation_recommendation,
                "command_block": f.command_block,
                "still_needed_variables": f.still_needed_variables,
            }
            for f in findings
        ],
        "suggested_device_vars_patch": patch,
    }
    output_path = Path(output_path)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return output_path
