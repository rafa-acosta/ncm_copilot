from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from webapp.backend.services import golden_service

router = APIRouter(prefix="/api/golden", tags=["golden"])


class FieldSpecOut(BaseModel):
    name: str
    json_type: str
    required_shape: dict[str, Any]


class ControlFormSpecOut(BaseModel):
    control_id: str
    title: str
    explanation: str
    fields: list[FieldSpecOut]


class ProfileSummaryOut(BaseModel):
    profile_id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    read_only: bool


class CreateProfileRequest(BaseModel):
    name: str
    description: str = ""
    device_vars: dict[str, Any] | None = None


class PreviewRequest(BaseModel):
    device_vars: dict[str, Any]


class UpdateProfileRequest(BaseModel):
    device_vars: dict[str, Any]
    description: str | None = None


class RenameProfileRequest(BaseModel):
    name: str
    description: str | None = None


class DuplicateProfileRequest(BaseModel):
    new_name: str


class ImportRequest(BaseModel):
    text: str


@router.get("/schema", response_model=list[ControlFormSpecOut])
def get_schema() -> list[ControlFormSpecOut]:
    specs = golden_service.get_form_schema()
    return [
        ControlFormSpecOut(
            control_id=s.control_id,
            title=s.title,
            explanation=s.explanation,
            fields=[FieldSpecOut(name=f.name, json_type=f.json_type, required_shape=f.required_shape) for f in s.fields],
        )
        for s in specs
    ]


@router.get("/profiles", response_model=list[ProfileSummaryOut])
def list_profiles() -> list[ProfileSummaryOut]:
    return [ProfileSummaryOut(**vars(p)) for p in golden_service.list_profiles()]


@router.post("/profiles")
def create_profile(payload: CreateProfileRequest) -> dict:
    profile_id = golden_service.create_profile(
        payload.name, description=payload.description, device_vars=payload.device_vars
    )
    return golden_service.get_profile(profile_id)


@router.post("/preview")
def preview(payload: PreviewRequest) -> dict:
    return golden_service.render_preview(payload.device_vars)


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str) -> dict:
    return golden_service.get_profile(profile_id)


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: str, payload: UpdateProfileRequest) -> dict:
    return golden_service.update_profile(profile_id, payload.device_vars, description=payload.description)


@router.post("/profiles/{profile_id}/rename")
def rename_profile(profile_id: str, payload: RenameProfileRequest) -> dict:
    golden_service.rename_profile(profile_id, payload.name, description=payload.description)
    return golden_service.get_profile(profile_id)


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: str) -> dict:
    golden_service.delete_profile(profile_id)
    return {"deleted": True}


@router.post("/profiles/{profile_id}/duplicate")
def duplicate_profile(profile_id: str, payload: DuplicateProfileRequest) -> dict:
    new_id = golden_service.duplicate_profile(profile_id, payload.new_name)
    return golden_service.get_profile(new_id)


@router.post("/profiles/{profile_id}/restore-default")
def restore_default(profile_id: str) -> dict:
    golden_service.restore_default_into(profile_id)
    return golden_service.get_profile(profile_id)


@router.get("/profiles/{profile_id}/compare-default")
def compare_with_default(profile_id: str) -> dict:
    return {"diff": golden_service.compare_with_default(profile_id)}


@router.post("/import")
def import_golden_config(payload: ImportRequest) -> dict:
    return golden_service.import_golden_config_text(payload.text)
