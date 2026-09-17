from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from webapp.backend import jobs
from webapp.backend.services import analysis_service

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class RunAnalysisRequest(BaseModel):
    device_filenames: list[str]
    golden_profile_id: str


@router.post("/run")
def run_analysis(payload: RunAnalysisRequest) -> dict:
    job_id = analysis_service.start_analysis(payload.device_filenames, payload.golden_profile_id)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return job.as_dict()


@router.get("/runs")
def list_runs() -> list[dict]:
    return analysis_service.list_runs()


@router.get("/runs/latest")
def latest_run() -> dict:
    run_id = analysis_service.latest_run_id()
    if run_id is None:
        raise HTTPException(status_code=404, detail="No analysis has been run yet.")
    return {"run_id": run_id}


@router.get("/runs/{run_id}/devices")
def list_run_devices(run_id: str) -> list[str]:
    return analysis_service.list_run_devices(run_id)
