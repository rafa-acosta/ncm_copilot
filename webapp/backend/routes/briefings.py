from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from webapp.backend import jobs
from webapp.backend.services import briefings_service

router = APIRouter(prefix="/api/briefings", tags=["briefings"])


class RunBriefingRequest(BaseModel):
    run_id: str
    device_filenames: list[str] | None = None  # None = brief every device in the run
    severity_min: str | None = None
    backend: str = "auto"
    golden_profile_id: str | None = None  # None = use the run's own Golden Config snapshot (safe default)


@router.post("/run")
def run_briefing(payload: RunBriefingRequest) -> dict:
    job_id = briefings_service.start_briefing(
        payload.run_id, payload.device_filenames, payload.severity_min, payload.backend, payload.golden_profile_id
    )
    return {"job_id": job_id}


@router.get("/{run_id}/golden-config-options")
def golden_config_options(run_id: str) -> dict:
    return briefings_service.get_golden_config_options(run_id)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return job.as_dict()


@router.get("/{run_id}")
def list_briefings(run_id: str) -> list[dict]:
    return briefings_service.list_briefings(run_id)


@router.get("/{run_id}/{device}")
def read_briefing(run_id: str, device: str) -> dict:
    return briefings_service.read_briefing(run_id, device)
