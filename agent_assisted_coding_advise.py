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
need a fixed, predictable filename. Single-device only - batch mode always
archives, since a fixed filename can't hold N devices' output.

Single-device usage:
    python agent_assisted_coding_advise.py \\
        --report path/to/compliance_report.json \\
        --controls controls.yaml \\
        --backend auto \\
        [--output-dir briefings] \\
        [--output-md briefing.md] \\
        [--output-json briefing.json] \\
        [--severity-min medium] \\
        [--device-vars device_vars.json]

Batch usage (brief every device a Tool 1 batch run produced, one subfolder
per device, plus one fleet-wide summary line):
    python agent_assisted_coding_advise.py \\
        --reports-dir reports/latest \\
        --controls controls.yaml \\
        --backend auto \\
        [--output-dir briefings] \\
        [--severity-min medium] \\
        [--device-vars device_vars.json]

The LLM backend is selected ONCE for the whole batch (see
llm_client.select_backend's `device_count` parameter - it prefers a
'fast_default'-role backend over a 'specialist' one once more than one device
is being briefed, since latency compounds across many calls) and reused
across every device, rather than re-selected per device. One device's report
failing to load or brief (a malformed report.json, an LLM error mid-call)
skips just that device and continues with the rest - see main()'s batch loop.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click

from llm_client import BackendUnavailableError, LLMClient, select_backend
from remediation_advisor import (
    build_finding,
    discover_report_paths,
    load_controls_by_id,
    load_report,
    render_briefing_json,
    render_markdown,
    select_findings,
)
from report_schema import ComplianceReport
from run_archive import new_run_dir, refresh_latest


def _backend_label(backend_name: str, model: str) -> str:
    return f"{backend_name} ({model})"


def _brief_device(
    report: ComplianceReport,
    controls_by_id: dict[str, dict],
    device_vars: dict | None,
    llm_client: LLMClient,
    backend_label: str,
    severity_min: str | None,
    md_path: Path,
    json_path: Path,
) -> int:
    """Build one device's findings and render its briefing. Returns the
    finding count. Raises on failure (malformed report, LLM error, etc.) -
    callers decide whether that should abort the whole run (single-device
    mode) or just skip this device (batch mode)."""
    findings_entries = select_findings(report, controls_by_id, severity_min)
    findings = [
        build_finding(controls_by_id[entry.control_id], entry, device_vars, llm_client)
        for entry in findings_entries
    ]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    render_markdown(
        findings, report.device_name, backend_label, md_path, generated_at,
        device_config_path=report.device_config_path, golden_config_path=report.golden_config_path,
    )
    render_briefing_json(
        findings, report.device_name, backend_label, json_path, generated_at,
        device_config_path=report.device_config_path, golden_config_path=report.golden_config_path,
    )
    return len(findings)


@click.command()
@click.option(
    "--report", "report_path", default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a single Compliance Checker JSON report (main.py --formats json). Mutually exclusive with --reports-dir.",
)
@click.option(
    "--reports-dir", "reports_dir_path", default=None,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory of Tool 1 report.json files to brief in batch (reports_dir/report.json or "
    "reports_dir/<device>/report.json, e.g. reports/latest). Mutually exclusive with --report.",
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
    help="Historic archive root, used unless --output-md/--output-json is given (single-device only) - "
    "each run gets its own output-dir/<timestamp>/ subfolder (or output-dir/<timestamp>/<device>/ per "
    "device in batch mode) plus a refreshed output-dir/latest/ mirror. Kept separate from main.py's/"
    "compliance_report_main.py's archive roots by default: they write same-named files (report.pdf etc.) "
    "that would otherwise collide inside a shared latest/.",
)
@click.option(
    "--output-md", "output_md_path", default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the Markdown briefing to exactly this path instead (bypasses the --output-dir archive). Single-device only.",
)
@click.option(
    "--output-json", "output_json_path", default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the JSON briefing to exactly this path instead (bypasses the --output-dir archive). Single-device only.",
)
@click.option(
    "--severity-min", "severity_min", type=click.Choice(["low", "medium", "high"], case_sensitive=False), default=None,
    help="Only include findings at or above this severity (default: include all).",
)
@click.option(
    "--device-vars", "device_vars_path", default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional device_vars.json - variables already resolved there won't be flagged as still-needed. Shared across every device in batch mode.",
)
def main(
    report_path: Path | None,
    reports_dir_path: Path | None,
    controls_path: Path,
    backend_choice: str,
    output_dir: Path,
    output_md_path: Path | None,
    output_json_path: Path | None,
    severity_min: str | None,
    device_vars_path: Path | None,
) -> None:
    """Turn one or more Compliance Checker reports into LLM-assisted remediation briefings."""
    if bool(report_path) == bool(reports_dir_path):
        raise click.UsageError("Provide exactly one of --report or --reports-dir.")

    explicit_path_given = output_md_path is not None or output_json_path is not None
    if explicit_path_given and reports_dir_path:
        raise click.UsageError("--output-md/--output-json are single-device only - not valid with --reports-dir.")

    controls_by_id = load_controls_by_id(controls_path)
    device_vars = json.loads(device_vars_path.read_text(encoding="utf-8")) if device_vars_path else None

    if reports_dir_path:
        report_paths = discover_report_paths(reports_dir_path)
    else:
        report_paths = [report_path]

    try:
        backend_name, base_url, model_name = select_backend(backend_choice, device_count=len(report_paths))
    except BackendUnavailableError as exc:
        raise click.ClickException(str(exc)) from None

    llm_client = LLMClient(base_url, backend_name, model=model_name)
    backend_label = _backend_label(backend_name, llm_client.model)
    click.echo(f"Using backend: {backend_label} at {base_url}")

    if explicit_path_given:
        md_path = output_md_path or Path("briefing.md")
        json_path = output_json_path or Path("briefing.json")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        run_dir = new_run_dir(output_dir)

    if reports_dir_path:
        briefed = 0
        skipped = 0
        for path in report_paths:
            try:
                report = load_report(path)
                device_dir = run_dir / report.device_name
                device_dir.mkdir(parents=True, exist_ok=True)
                count = _brief_device(
                    report, controls_by_id, device_vars, llm_client, backend_label, severity_min,
                    device_dir / "briefing.md", device_dir / "briefing.json",
                )
                briefed += 1
                click.echo(f"{report.device_name}: {count} finding(s) briefed.")
            except Exception as exc:  # noqa: BLE001 - one bad device must not abort the whole batch
                skipped += 1
                click.echo(f"WARNING: skipped {path} - {type(exc).__name__}: {exc}", err=True)

        latest_dir = refresh_latest(run_dir, output_dir)
        click.echo(f"This run archived at {run_dir} - latest/ refreshed at {latest_dir}")
        skipped_note = f" ({skipped} skipped due to errors)" if skipped else ""
        click.echo(f"Briefed {briefed}/{len(report_paths)} device(s){skipped_note}.")
        raise SystemExit(0 if briefed else 1)

    # Single-device mode.
    report = load_report(report_path)
    if not explicit_path_given:
        md_path = run_dir / "briefing.md"
        json_path = run_dir / "briefing.json"

    count = _brief_device(report, controls_by_id, device_vars, llm_client, backend_label, severity_min, md_path, json_path)
    if not count:
        click.echo("No FAILED controls at or above the requested severity threshold. Nothing to remediate.")

    click.echo(f"Markdown briefing written to {md_path}")
    click.echo(f"JSON briefing written to {json_path}")

    if not explicit_path_given:
        latest_dir = refresh_latest(run_dir, output_dir)
        click.echo(f"This run archived at {run_dir} - latest/ refreshed at {latest_dir}")

    click.echo(f"{count} finding(s) briefed.")


if __name__ == "__main__":
    main()
