from __future__ import annotations

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel

from webapp.backend.services import configs_service

router = APIRouter(prefix="/api/configs", tags=["configs"])


class ConfigFileOut(BaseModel):
    filename: str
    device_name: str | None
    size_bytes: int
    modified_at: float


class UploadOutcomeOut(BaseModel):
    filename: str
    status: str
    reason: str | None = None


class UploadResultOut(BaseModel):
    outcomes: list[UploadOutcomeOut]
    accepted_count: int
    rejected_count: int


class DeleteRequest(BaseModel):
    filenames: list[str] = []
    all: bool = False


@router.get("", response_model=list[ConfigFileOut])
def list_configs() -> list[ConfigFileOut]:
    return [ConfigFileOut(**vars(f)) for f in configs_service.list_configs()]


@router.post("/upload", response_model=UploadResultOut)
async def upload_configs(files: list[UploadFile]) -> UploadResultOut:
    payload = [(f.filename or "unnamed.txt", await f.read()) for f in files]
    result = configs_service.save_uploads(payload)
    outcomes = [UploadOutcomeOut(filename=o.filename, status=o.status, reason=o.reason) for o in result.outcomes]
    return UploadResultOut(outcomes=outcomes, accepted_count=result.accepted_count, rejected_count=result.rejected_count)


@router.post("/delete")
def delete_configs(payload: DeleteRequest) -> dict:
    if payload.all:
        count = configs_service.delete_all_configs()
    else:
        count = configs_service.delete_configs(payload.filenames)
    return {"deleted_count": count}


@router.get("/{filename}/text")
def get_config_text(filename: str) -> dict:
    text = configs_service.read_config_text(filename)
    return {"filename": filename, "text": text}
