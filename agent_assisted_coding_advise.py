"""CLI entrypoint for the Compliance Remediation Advisor (CRA).

Run as `python agent_assisted_coding_advise.py ...` - this repo has no packaging/console-
script infrastructure yet (same naming pattern as golden_config_main.py,
which exists for the same reason: `main.py` is already the Compliance
Checker's entrypoint).

By default (no --output-md/--output-json given) each run writes into a fresh
timestamped subdirectory of --output-dir, never overwriting a past run, and
refreshes an --output-dir/latest/ mirror - see run_archive.py. Passing
--output-md and/or --output-json explicitly bypasses archiving entirely and
writes to exactly that path instead, for scripting/automation use cases that
need a fixed, predictable filename.

Usage:
    python agent_assisted_coding_advise.py \\
        --report path/to/compliance_report.json \\
        --controls controls.yaml \\
        --backend auto \\
        [--output-dir briefings] \\
        [--output-md briefing.md] \\
        [--output-json briefing.json] \\
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
from run_archive import new_run_dir, refresh_latest


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
    "--output-dir", "output_dir", default="briefings", show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Historic archive root, used unless --output-md/--output-json is given - "
    "each run gets its own output-dir/<timestamp>/ subfolder plus a refreshed output-dir/latest/ mirror. "
    "Kept separate from main.py's/compliance_report_main.py's archive roots by default: they write "
    "same-named files (report.pdf etc.) that would otherwise collide inside a shared latest/.",
)
@click.option(
    "--output-md", "output_md_path", default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the Markdown briefing to exactly this path instead (bypasses the --output-dir archive).",
)
@click.option(
    "--output-json", "output_json_path", default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the JSON briefing to exactly this path instead (bypasses the --output-dir archive).",
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
    output_dir: Path,
    output_md_path: Path | None,
    output_json_path: Path | None,
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

    explicit_path_given = output_md_path is not None or output_json_path is not None
    if explicit_path_given:
        md_path = output_md_path or Path("briefing.md")
        json_path = output_json_path or Path("briefing.json")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        run_dir = new_run_dir(output_dir)
        md_path = run_dir / "briefing.md"
        json_path = run_dir / "briefing.json"

    render_markdown(
        findings, report.device_name, backend_label, md_path, generated_at,
        device_config_path=report.device_config_path, golden_config_path=report.golden_config_path,
    )
    render_briefing_json(
        findings, report.device_name, backend_label, json_path, generated_at,
        device_config_path=report.device_config_path, golden_config_path=report.golden_config_path,
    )

    click.echo(f"Markdown briefing written to {md_path}")
    click.echo(f"JSON briefing written to {json_path}")

    if not explicit_path_given:
        latest_dir = refresh_latest(run_dir, output_dir)
        click.echo(f"This run archived at {run_dir} - latest/ refreshed at {latest_dir}")

    click.echo(f"{len(findings)} finding(s) briefed.")


if __name__ == "__main__":
    main()
