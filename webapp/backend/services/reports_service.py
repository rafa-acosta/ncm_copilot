"""Compliance Report screen - Tool 5 (compliance_report_builder.py) over one
or more devices' completed analysis. A single device is fast enough to run
synchronously (generate_report, no background job); generating for many
devices at once (start_batch_reports) reuses the same jobs.py background-job
pattern Analysis/Briefings already use, so it doesn't block the request or
require polling infrastructure of its own."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from compliance_report_builder import (  # noqa: E402
    RiskStatementError,
    build_report_context,
    render_markdown,
    render_pdf,
)
from llm_client import BackendUnavailableError, LLMClient, select_backend  # noqa: E402

from webapp.backend import jobs
from webapp.backend.security import resolve_within
from webapp.backend.services import run_manifest
from webapp.backend.services.analysis_service import run_dir_path

CONTROLS_PATH = REPO_ROOT / "controls.yaml"


class ReportError(Exception):
    """User-facing reason a compliance report couldn't be generated."""


def _generate_one(
    run_dir: Path,
    device_name: str,
    device_role: str,
    audit_date: str | None,
    llm_client: LLMClient | None,
    backend_label: str | None,
) -> dict:
    """The actual per-device work, with no backend resolution or run-manifest
    timing of its own - callers (single-device generate_report, or the batch
    job below) own exactly one mark_started/mark_completed pair each, so a
    batch of 500 devices doesn't overwrite the manifest's compliance_report
    stage 500 times with only the last device's timing surviving."""
    report_path = resolve_within(run_dir, device_name, "report.json")
    if not report_path.exists():
        raise ReportError(f"No analysis report found for '{device_name}' in this run.")

    try:
        context = build_report_context(
            report_path, CONTROLS_PATH, device_role=device_role, audit_date=audit_date, llm_client=llm_client
        )
    except ValidationError as exc:
        raise ReportError(f"'{device_name}' is not a valid Compliance Checker report: {exc}") from None
    except RiskStatementError as exc:
        raise ReportError(
            f"{exc} Try again with 'Polish with LLM' enabled, or edit that control's risk text in controls.yaml."
        ) from None

    out_dir = resolve_within(run_dir, device_name, "compliance_report")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "report.md"
    pdf_path = out_dir / "report.pdf"
    render_markdown(context, md_path)
    render_pdf(context, pdf_path)

    return {
        "device": device_name,
        "device_role": device_role,
        "audit_date": context.audit_date,
        "compliance_pct": context.compliance_pct,
        "counts": context.counts,
        "findings_detail": [f.model_dump() for f in context.findings_detail],
        "manual_review": [f.model_dump() for f in context.manual_review],
        "markdown": md_path.read_text(encoding="utf-8"),
        "pdf_available": pdf_path.exists(),
        "backend_used": backend_label,
    }


def _resolve_llm_client(llm_polish: bool, backend_choice: str, device_count: int) -> tuple[LLMClient | None, str | None]:
    if not llm_polish:
        return None, None
    try:
        backend_name, base_url, model_name = select_backend(backend_choice, device_count=device_count)
    except BackendUnavailableError as exc:
        raise ReportError(str(exc)) from None
    return LLMClient(base_url, backend_name, model=model_name), f"{backend_name} ({model_name})"


def generate_report(
    run_id: str,
    device_name: str,
    device_role: str,
    audit_date: str | None = None,
    llm_polish: bool = False,
    backend_choice: str = "auto",
) -> dict:
    run_dir = run_dir_path(run_id)
    llm_client, backend_label = _resolve_llm_client(llm_polish, backend_choice, device_count=1)

    mono_start = run_manifest.mark_started(run_dir, "compliance_report")
    try:
        result = _generate_one(run_dir, device_name, device_role, audit_date, llm_client, backend_label)
    except Exception as exc:  # noqa: BLE001 - record the failure before it propagates to the route handler
        run_manifest.mark_failed(run_dir, "compliance_report", mono_start, str(exc))
        raise
    run_manifest.mark_completed(run_dir, "compliance_report", mono_start, last_device=device_name)
    return result


def start_batch_reports(
    run_id: str,
    device_filenames: list[str],
    device_role: str,
    audit_date: str | None = None,
    llm_polish: bool = False,
    backend_choice: str = "auto",
) -> str:
    """Generate a compliance report for several devices in one background
    job - the same device_role/audit_date/LLM-polish setting applies to all
    of them (this app has no per-device role metadata to draw a different
    default from). One bad device is skipped, not fatal to the rest, matching
    Analysis/Briefings' own batch behavior."""
    run_dir = run_dir_path(run_id)
    if not device_filenames:
        raise ReportError("Select at least one device to generate reports for.")

    llm_client, backend_label = _resolve_llm_client(llm_polish, backend_choice, device_count=len(device_filenames))

    def work(report_progress):
        mono_start = run_manifest.mark_started(run_dir, "compliance_report")
        generated = []
        errors = []
        for index, device_name in enumerate(device_filenames):
            report_progress(index, f"Generating report for {device_name} ({index + 1} of {len(device_filenames)})")
            try:
                generated.append(_generate_one(run_dir, device_name, device_role, audit_date, llm_client, backend_label))
            except Exception as exc:  # noqa: BLE001 - one device's failure must not abort the batch
                errors.append(f"{device_name}: {exc}")

        if errors and not generated:
            run_manifest.mark_failed(run_dir, "compliance_report", mono_start, "; ".join(errors))
        else:
            run_manifest.mark_completed(
                run_dir, "compliance_report", mono_start, device_count=len(generated), error_count=len(errors)
            )
        return {"generated": generated, "errors": errors, "backend": backend_label}

    return jobs.start_job("compliance_report", total=len(device_filenames), work=work)


def read_report_pdf_path(run_id: str, device_name: str) -> Path:
    run_dir = run_dir_path(run_id)
    pdf_path = resolve_within(run_dir, device_name, "compliance_report", "report.pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(device_name)
    return pdf_path
