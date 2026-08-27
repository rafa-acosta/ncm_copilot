"""CLI entrypoint for the Compliance Report Generator (Tool 5).

Run as `python compliance_report_main.py ...` - not `main.py` (already Tool
1's entrypoint) and not a packaged `compliance-report` console script (this
repo has no packaging infrastructure - same reasoning as
golden_config_main.py/vibecoding_advise.py).

Turns Tool 1's report.json into an audit-grade Markdown + PDF report. Does
NOT re-analyze the device config - see compliance_report_builder.py.

Usage:
    python compliance_report_main.py \\
        --report reports/report.json \\
        --controls controls.yaml \\
        --device-role edge-router \\
        --out report.pdf \\
        [--out-md report.md] \\
        [--audit-date 2026-08-26] \\
        [--llm-polish [--backend auto]]
"""

from __future__ import annotations

from pathlib import Path

import click
from pydantic import ValidationError

from compliance_report_builder import RiskStatementError, build_report_context, render_markdown, render_pdf
from llm_client import BackendUnavailableError, LLMClient, select_backend


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
    "--device-role", "device_role", required=True,
    help="e.g. edge-router, access-switch, core-switch.",
)
@click.option(
    "--out", "out_pdf_path", default="report.pdf", show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="PDF output path.",
)
@click.option(
    "--out-md", "out_md_path", default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Markdown output path. Defaults to --out with a .md extension.",
)
@click.option(
    "--audit-date", "audit_date", default=None,
    help="Override the audit date (YYYY-MM-DD). Defaults to the report's generated_at date.",
)
@click.option(
    "--llm-polish", "llm_polish", is_flag=True, default=False,
    help="Let a local LLM retry a risk statement that fails deterministic validation "
    "(the rewrite is still re-validated before being accepted).",
)
@click.option(
    "--backend", "backend_choice", default="auto", show_default=True,
    help="Only relevant with --llm-polish: 'auto', or a name from local-llm/config.yaml's registry.",
)
def main(
    report_path: Path,
    controls_path: Path,
    device_role: str,
    out_pdf_path: Path,
    out_md_path: Path | None,
    audit_date: str | None,
    llm_polish: bool,
    backend_choice: str,
) -> None:
    """Render Tool 1's report.json into an audit-grade Markdown + PDF compliance report."""
    if out_md_path is None:
        out_md_path = out_pdf_path.with_suffix(".md")

    llm_client = None
    if llm_polish:
        try:
            backend_name, base_url, model_name = select_backend(backend_choice, device_count=1)
        except BackendUnavailableError as exc:
            raise click.ClickException(str(exc)) from None
        llm_client = LLMClient(base_url, backend_name, model=model_name)
        click.echo(f"--llm-polish enabled, using backend: {backend_name} ({model_name})")

    try:
        context = build_report_context(
            report_path, controls_path, device_role=device_role, audit_date=audit_date, llm_client=llm_client
        )
    except ValidationError as exc:
        raise click.ClickException(f"'{report_path}' is not a valid Compliance Checker report:\n{exc}") from None
    except RiskStatementError as exc:
        raise click.ClickException(
            f"{exc}\nRe-run with --llm-polish to let a local LLM attempt a fix, "
            "or edit that control's 'risk' text in controls.yaml."
        ) from None

    render_markdown(context, out_md_path)
    render_pdf(context, out_pdf_path)

    click.echo(f"Markdown report written to {out_md_path}")
    click.echo(f"PDF report written to {out_pdf_path}")
    click.echo(
        f"{len(context.appendix)} controls: {context.counts['compliant']} compliant, "
        f"{len(context.findings_detail)} findings, {len(context.manual_review)} manual review "
        f"({context.compliance_pct}% compliant)."
    )


if __name__ == "__main__":
    main()
