"""CLI entrypoint for the Cisco IOS-XE Config Compliance Checker.

Usage:
    python main.py \\
        --device-config device_config.txt \\
        --golden-config golden_config.txt \\
        --controls controls.yaml \\
        --output-dir ./reports \\
        --formats html,pdf \\
        [--priority-only] \\
        [--exceptions exceptions.yaml]
"""

from __future__ import annotations

from pathlib import Path

import click
import yaml

from compliance_engine import PRIORITY_CONTROL_IDS, ControlEvaluator
from report_generator import render_html, render_pdf


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


@click.command()
@click.option(
    "--device-config", "device_config_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the device's running-config (plain text).",
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
    help="Directory to write the generated report(s) into.",
)
@click.option(
    "--formats", default="html,pdf", show_default=True,
    help="Comma-separated output formats to generate: html, pdf.",
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
    device_config_path: Path,
    golden_config_path: Path,
    controls_path: Path,
    output_dir: Path,
    formats: str,
    priority_only: bool,
    exceptions_path: Path | None,
) -> None:
    """Audit an IOS-XE device configuration against a golden config baseline."""
    device_config = device_config_path.read_text(encoding="utf-8")
    golden_config = golden_config_path.read_text(encoding="utf-8")
    controls = load_controls(controls_path)
    exceptions = load_exceptions(exceptions_path)

    if priority_only:
        controls = [c for c in controls if c["control_id"] in PRIORITY_CONTROL_IDS]

    evaluator = ControlEvaluator(exceptions=exceptions)
    results = [evaluator.evaluate_control(c, device_config, golden_config) for c in controls]

    output_dir.mkdir(parents=True, exist_ok=True)
    requested_formats = {f.strip().lower() for f in formats.split(",") if f.strip()}
    unknown = requested_formats - {"html", "pdf"}
    if unknown:
        raise click.BadParameter(f"Unsupported format(s): {', '.join(sorted(unknown))}", param_hint="--formats")

    html_path = output_dir / "report.html"
    if requested_formats & {"html", "pdf"}:
        render_html(results, html_path, device_name=device_config_path.stem)
    if "html" in requested_formats:
        click.echo(f"HTML report written to {html_path}")

    if "pdf" in requested_formats:
        pdf_path = output_dir / "report.pdf"
        render_pdf(html_path, pdf_path)
        click.echo(f"PDF report written to {pdf_path}")
        if "html" not in requested_formats:
            html_path.unlink(missing_ok=True)

    fail_count = sum(1 for r in results if r.status == "FAIL")
    click.echo(f"Evaluated {len(results)} controls: {fail_count} FAIL.")
    raise SystemExit(1 if fail_count else 0)


if __name__ == "__main__":
    main()
