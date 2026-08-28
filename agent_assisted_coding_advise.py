"""CLI entrypoint for the Compliance Remediation Advisor (CRA).

Run as `python vibecoding_advise.py ...` - this repo has no packaging/console-
script infrastructure yet (same naming pattern as golden_config_main.py,
which exists for the same reason: `main.py` is already the Compliance
Checker's entrypoint).

Usage:
    python vibecoding_advise.py \\
        --report path/to/compliance_report.json \\
        --controls controls.yaml \\
        --backend auto \\
        --output-md briefing.md \\
        --output-json briefing.json \\
        [--severity-min medium] \\
        [--device-vars device_vars.json]
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click

from llm_client import BackendUnavailableError, LLMClient, select_backend
from remediation_advisor import build_finding, load_controls_by_id, load_report, render_briefing_json, render_markdown, select_findings


def _backend_label(backend_name: str, model: str) -> str:
    return f"{backend_name} ({model})"


@click.command()
@click.option(
    "--report", "report_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a Compliance Checker JSON report (main.py --formats json).",
)
@click.option(
    "--controls", "controls_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to controls.yaml.",
)
@click.option(
    "--backend", "backend_choice", default="auto", show_default=True,
    help="Local LLM backend to use: 'auto', or a name from local-llm/config.yaml's backends: registry (e.g. qwen_coder, phi4_mini).",
)
@click.option(
    "--output-md", "output_md_path", default="briefing.md", show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to write the Markdown briefing to.",
)
@click.option(
    "--output-json", "output_json_path", default="briefing.json", show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to write the JSON briefing to.",
)
@click.option(
    "--severity-min", "severity_min", type=click.Choice(["low", "medium", "high"], case_sensitive=False), default=None,
    help="Only include findings at or above this severity (default: include all).",
)
@click.option(
    "--device-vars", "device_vars_path", default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional device_vars.json - variables already resolved there won't be flagged as still-needed.",
)
def main(
    report_path: Path,
    controls_path: Path,
    backend_choice: str,
    output_md_path: Path,
    output_json_path: Path,
    severity_min: str | None,
    device_vars_path: Path | None,
) -> None:
    """Turn a Compliance Checker report into an LLM-assisted remediation briefing."""
    report = load_report(report_path)
    controls_by_id = load_controls_by_id(controls_path)
    device_vars = json.loads(device_vars_path.read_text(encoding="utf-8")) if device_vars_path else None

    try:
        backend_name, base_url, model_name = select_backend(backend_choice, device_count=1)
    except BackendUnavailableError as exc:
        raise click.ClickException(str(exc)) from None

    llm_client = LLMClient(base_url, backend_name, model=model_name)
    backend_label = _backend_label(backend_name, llm_client.model)
    click.echo(f"Using backend: {backend_label} at {base_url}")

    findings_entries = select_findings(report, controls_by_id, severity_min)
    if not findings_entries:
        click.echo("No FAILED controls at or above the requested severity threshold. Nothing to remediate.")

    findings = [
        build_finding(controls_by_id[entry.control_id], entry, device_vars, llm_client)
        for entry in findings_entries
    ]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    render_markdown(
        findings, report.device_name, backend_label, output_md_path, generated_at,
        device_config_path=report.device_config_path, golden_config_path=report.golden_config_path,
    )
    render_briefing_json(
        findings, report.device_name, backend_label, output_json_path, generated_at,
        device_config_path=report.device_config_path, golden_config_path=report.golden_config_path,
    )

    click.echo(f"Markdown briefing written to {output_md_path}")
    click.echo(f"JSON briefing written to {output_json_path}")
    click.echo(f"{len(findings)} finding(s) briefed.")


if __name__ == "__main__":
    main()
