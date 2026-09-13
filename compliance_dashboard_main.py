"""CLI entrypoint for the Executive Compliance Dashboard (Tool 6).

Aggregates every device's report.json from a Tool 1 run into a fleet-level
executive dashboard - KPIs, device posture, compliance-by-control, top
failing controls, a device x control heatmap, drill-down detail, a findings
table, and a compliance trend built from every dashboard run's history
snapshot (see compliance_history.py). No LLM anywhere in this pipeline; every
number comes from compliance_metrics.py.

Like Tools 1/3/5, each run writes into a fresh timestamped subdirectory of
--output-dir and refreshes an --output-dir/latest/ mirror - see run_archive.py.
History snapshots are separate (--history-dir, default compliance_history/)
and are never replaced - every run's snapshot is kept for the trend chart.

Usage:
    python compliance_dashboard_main.py \\
        --reports-dir reports/latest \\
        --controls controls.yaml \\
        --output-dir compliance_dashboards \\
        [--exceptions exceptions.yaml] \\
        [--history-dir compliance_history] \\
        [--formats html,pdf,csv]
"""

from __future__ import annotations

from pathlib import Path

import click

from compliance_dashboard_builder import build_dashboard, write_csv
from run_archive import new_run_dir, refresh_latest


@click.command()
@click.option(
    "--reports-dir", "reports_dir", required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="A single Tool 1 run's output root (e.g. reports/latest) - "
    "reports_dir/report.json (single device) or reports_dir/<device>/report.json (batch). "
    "Not searched recursively, so pointing this at an entire archive (not one run) is a no-op error, not silent over-collection.",
)
@click.option(
    "--controls", "controls_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to controls.yaml (used only for the controls_version marker in this run's snapshot).",
)
@click.option(
    "--output-dir", "output_dir", default="compliance_dashboards", show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Historic archive root - each run gets its own output-dir/<timestamp>/ subfolder plus a refreshed output-dir/latest/ mirror.",
)
@click.option(
    "--exceptions", "exceptions_path", default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional exceptions.yaml (same file main.py --exceptions uses) - read here for approver/ticket/expiration metadata.",
)
@click.option(
    "--history-dir", "history_dir", default="compliance_history", show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Where every run's history snapshot is kept (never replaced - see compliance_history.py) for the trend chart.",
)
@click.option(
    "--formats", default="html,pdf", show_default=True,
    help="Comma-separated output formats to generate: html, pdf, csv.",
)
def main(
    reports_dir: Path,
    controls_path: Path,
    output_dir: Path,
    exceptions_path: Path | None,
    history_dir: Path,
    formats: str,
) -> None:
    """Build the fleet-level executive compliance dashboard from a Tool 1 run."""
    requested_formats = {f.strip().lower() for f in formats.split(",") if f.strip()}
    unknown = requested_formats - {"html", "pdf", "csv"}
    if unknown:
        raise click.BadParameter(f"Unsupported format(s): {', '.join(sorted(unknown))}", param_hint="--formats")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = new_run_dir(output_dir)

    try:
        context = build_dashboard(
            reports_dir=reports_dir,
            controls_path=controls_path,
            output_dir=run_dir,
            history_dir=history_dir,
            exceptions_path=exceptions_path,
        )
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from None

    click.echo(f"HTML dashboard written to {context['html_path']}")

    if "pdf" in requested_formats:
        from report_generator import render_pdf

        pdf_path = render_pdf(context["html_path"], run_dir / "compliance_dashboard.pdf")
        click.echo(f"PDF dashboard written to {pdf_path}")
        if "html" not in requested_formats:
            context["html_path"].unlink(missing_ok=True)

    if "csv" in requested_formats:
        csv_path = write_csv(context["findings_table"], run_dir / "findings.csv")
        click.echo(f"Findings CSV written to {csv_path}")

    latest_dir = refresh_latest(run_dir, output_dir)
    click.echo(f"This run archived at {run_dir} - latest/ refreshed at {latest_dir}")
    click.echo(f"History snapshot: {context['snapshot_path']}")

    fleet = context["fleet"]
    click.echo(
        f"{fleet.device_count} device(s): {fleet.strict_compliance_pct}% strict compliance, "
        f"{fleet.assessment_coverage_pct}% coverage, {fleet.critical_finding_count} critical finding(s)."
    )


if __name__ == "__main__":
    main()
