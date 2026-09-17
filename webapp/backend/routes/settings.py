from __future__ import annotations

from fastapi import APIRouter

from webapp.backend.services import llm_engine_service, settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/status")
def get_status() -> dict:
    return settings_service.get_status()


@router.post("/engines/{name}/start")
def start_engine(name: str) -> list[dict]:
    llm_engine_service.start_engine(name)
    return llm_engine_service.get_status()


@router.post("/engines/{name}/stop")
def stop_engine(name: str) -> list[dict]:
    llm_engine_service.stop_engine(name)
    return llm_engine_service.get_status()
