from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from webapp.backend.services import dashboard_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class BuildDashboardRequest(BaseModel):
    run_id: str


@router.post("/build")
def build_dashboard(payload: BuildDashboardRequest) -> dict:
    return dashboard_service.build_for_run(payload.run_id)


@router.get("/{run_id}/html", response_class=HTMLResponse)
def get_dashboard_html(run_id: str) -> HTMLResponse:
    try:
        html = dashboard_service.read_dashboard_html(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not built yet for this run.") from None
    return HTMLResponse(content=html)
