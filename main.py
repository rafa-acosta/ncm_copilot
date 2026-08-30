"""CLI entrypoint for the Cisco IOS-XE Config Compliance Checker.

Every run writes into a fresh timestamped subdirectory of --output-dir, so
past runs are never overwritten, then refreshes an --output-dir/latest/
mirror of that run - see run_archive.py.

Single-device usage:
    python main.py \\
        --device-config device_config.txt \\
        --golden-config golden_config.txt \\
        --controls controls.yaml \\
        --output-dir ./reports \\
        --formats html,pdf \\
        [--priority-only] \\
        [--exceptions exceptions.yaml]

Batch usage (audit every *.txt config in a folder against the same golden
config, plus one fleet-level summary report):
    python main.py \\
        --device-config-dir ./device_configs \\
        --golden-config golden_config.txt \\
        --controls controls.yaml \\
        --output-dir ./reports \\
        --formats html,pdf
"""

from __future__ import annotations

from pathlib import Path

import click
import yaml

from compliance_engine import PRIORITY_CONTROL_IDS, ControlEvaluator, ControlResult
from report_generator import render_fleet_html, render_html, render_json, render_pdf
from run_archive import new_run_dir, refresh_latest


def load_controls(path: Path) -> list[dict]:
    """Load the list of control definitions from controls.yaml."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_exceptions(path: Path | None) -> dict[str, str]:
    """Load a control_id -> reason mapping from an optional exceptions file."""
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return dict(data)


def _evaluate_device(
    device_config_path: Path,
    golden_config_path: Path,
    golden_config: str,
    controls: list[dict],
    exceptions: dict[str, str],
    report_dir: Path,
    requested_formats: set[str],
) -> list[ControlResult]:
    """Evaluate one device config and write its report(s) into `report_dir`."""
    device_config = device_config_path.read_text(encoding="utf-8")
    evaluator = ControlEvaluator(exceptions=exceptions)
    results = [evaluator.evaluate_control(c, device_config, golden_config) for c in controls]

    report_dir.mkdir(parents=True, exist_ok=True)
    html_path = report_dir / "report.html"
    if requested_formats & {"html", "pdf"}:
        render_html(results, html_path, device_name=device_config_path.stem)
    if "pdf" in requested_formats:
        render_pdf(html_path, report_dir / "report.pdf")
        if "html" not in requested_formats:
            html_path.unlink(missing_ok=True)
    if "json" in requested_formats:
        render_json(
            results,
            report_dir / "report.json",
            device_name=device_config_path.stem,
            device_config_path=str(device_config_path),
            golden_config_path=str(golden_config_path),
        )
    return results


@click.command()
@click.option(
    "--device-config", "device_config_path", default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a single device's running-config (plain text). Mutually exclusive with --device-config-dir.",
)
@click.option(
    "--device-config-dir", "device_config_dir", default=None,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory of *.txt device configs to audit in batch. Mutually exclusive with --device-config.",
)
@click.option(
    "--golden-config", "golden_config_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the golden config baseline (plain text, <PLACEHOLDER> syntax).",
)
@click.option(
    "--controls", "controls_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to controls.yaml.",
)
@click.option(
    "--output-dir", "output_dir", required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Root directory for the historic archive - each run gets its own output-dir/<timestamp>/ "
    "subfolder (never overwritten) plus a refreshed output-dir/latest/ mirror.",
)
@click.option(
    "--formats", default="html,pdf", show_default=True,
    help="Comma-separated output formats to generate: html, pdf, json.",
)
@click.option(
    "--priority-only", is_flag=True, default=False,
    help="Limit evaluation to control_00001-control_00015.",
)
@click.option(
    "--exceptions", "exceptions_path", default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional YAML file mapping control_id -> exception reason for this audit run.",
)
def main(
    device_config_path: Path | None,
    device_config_dir: Path | None,
    golden_config_path: Path,
    controls_path: Path,
    output_dir: Path,
    formats: str,
    priority_only: bool,
    exceptions_path: Path | None,
) -> None:
    """Audit one or more IOS-XE device configurations against a golden config baseline."""
    if bool(device_config_path) == bool(device_config_dir):
        raise click.UsageError("Provide exactly one of --device-config or --device-config-dir.")

    golden_config = golden_config_path.read_text(encoding="utf-8")
    controls = load_controls(controls_path)
    exceptions = load_exceptions(exceptions_path)

    if priority_only:
        controls = [c for c in controls if c["control_id"] in PRIORITY_CONTROL_IDS]

    requested_formats = {f.strip().lower() for f in formats.split(",") if f.strip()}
    unknown = requested_formats - {"html", "pdf", "json"}
    if unknown:
        raise click.BadParameter(f"Unsupported format(s): {', '.join(sorted(unknown))}", param_hint="--formats")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = new_run_dir(output_dir)

    if device_config_path:
        results = _evaluate_device(
            device_config_path, golden_config_path, golden_config, controls, exceptions, run_dir, requested_formats
        )
        if "html" in requested_formats:
            click.echo(f"HTML report written to {run_dir / 'report.html'}")
        if "pdf" in requested_formats:
            click.echo(f"PDF report written to {run_dir / 'report.pdf'}")
        if "json" in requested_formats:
            click.echo(f"JSON report written to {run_dir / 'report.json'}")

        latest_dir = refresh_latest(run_dir, output_dir)
        click.echo(f"This run archived at {run_dir} - latest/ refreshed at {latest_dir}")

        fail_count = sum(1 for r in results if r.status == "FAIL")
        click.echo(f"Evaluated {len(results)} controls: {fail_count} FAIL.")
        raise SystemExit(1 if fail_count else 0)

    # Batch mode: one subfolder per device, plus a fleet-level summary report.
    device_files = sorted(device_config_dir.glob("*.txt"))
    if not device_files:
        raise click.UsageError(f"No *.txt device config files found in {device_config_dir}.")

    results_by_device: dict[str, list[ControlResult]] = {}
    report_links: dict[str, str] = {}
    total_fail = 0
    for device_file in device_files:
        name = device_file.stem
        results = _evaluate_device(
            device_file, golden_config_path, golden_config, controls, exceptions, run_dir / name, requested_formats
        )
        results_by_device[name] = results
        report_links[name] = f"{name}/report.html"
        fail_count = sum(1 for r in results if r.status == "FAIL")
        total_fail += fail_count
        click.echo(f"{name}: {len(results)} controls, {fail_count} FAIL")

    fleet_html_path = run_dir / "fleet_report.html"
    if requested_formats & {"html", "pdf"}:
        render_fleet_html(results_by_device, report_links, fleet_html_path)
    if "html" in requested_formats:
        click.echo(f"Fleet report written to {fleet_html_path}")
    if "pdf" in requested_formats:
        fleet_pdf_path = run_dir / "fleet_report.pdf"
        render_pdf(fleet_html_path, fleet_pdf_path)
        click.echo(f"Fleet PDF report written to {fleet_pdf_path}")
        if "html" not in requested_formats:
            fleet_html_path.unlink(missing_ok=True)

    latest_dir = refresh_latest(run_dir, output_dir)
    click.echo(f"This run archived at {run_dir} - latest/ refreshed at {latest_dir}")

    click.echo(f"Audited {len(device_files)} device(s): {total_fail} total FAIL across the fleet.")
    raise SystemExit(1 if total_fail else 0)


if __name__ == "__main__":
    main()
