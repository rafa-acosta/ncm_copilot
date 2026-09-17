from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from webapp.backend.services import reports_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


class GenerateReportRequest(BaseModel):
    run_id: str
    device: str
    device_role: str
    audit_date: str | None = None
    llm_polish: bool = False
    backend: str = "auto"


@router.post("/generate")
def generate_report(payload: GenerateReportRequest) -> dict:
    return reports_service.generate_report(
        payload.run_id, payload.device, payload.device_role,
        audit_date=payload.audit_date, llm_polish=payload.llm_polish, backend_choice=payload.backend,
    )


@router.get("/{run_id}/{device}/pdf")
def download_pdf(run_id: str, device: str):
    pdf_path = reports_service.read_report_pdf_path(run_id, device)
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{device}_compliance_report.pdf")
