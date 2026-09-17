"""Compliance Report screen - Tool 5 (compliance_report_builder.py) over one
device's completed analysis. Single-device and fast enough to run
synchronously (no background job needed, unlike Analysis/Briefings)."""

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

from webapp.backend.security import resolve_within
from webapp.backend.services.analysis_service import run_dir_path

CONTROLS_PATH = REPO_ROOT / "controls.yaml"


class ReportError(Exception):
    """User-facing reason a compliance report couldn't be generated."""


def generate_report(
    run_id: str,
    device_name: str,
    device_role: str,
    audit_date: str | None = None,
    llm_polish: bool = False,
    backend_choice: str = "auto",
) -> dict:
    run_dir = run_dir_path(run_id)
    report_path = resolve_within(run_dir, device_name, "report.json")
    if not report_path.exists():
        raise ReportError(f"No analysis report found for '{device_name}' in this run.")

    llm_client = None
    backend_label = None
    if llm_polish:
        try:
            backend_name, base_url, model_name = select_backend(backend_choice, device_count=1)
        except BackendUnavailableError as exc:
            raise ReportError(str(exc)) from None
        llm_client = LLMClient(base_url, backend_name, model=model_name)
        backend_label = f"{backend_name} ({model_name})"

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


def read_report_pdf_path(run_id: str, device_name: str) -> Path:
    run_dir = run_dir_path(run_id)
    pdf_path = resolve_within(run_dir, device_name, "compliance_report", "report.pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(device_name)
    return pdf_path
