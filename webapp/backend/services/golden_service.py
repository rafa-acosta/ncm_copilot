"""Golden Config Manager screen.

Everything here is a thin wrapper around golden_config_builder.GoldenConfigBuilder
(the exact class golden_config_main.py/Tool 2 uses) plus profile bookkeeping.
No rendering or validation logic is reimplemented - the preview text shown to
the user is always the literal output of GoldenConfigBuilder.build(), and
device_vars.json shape validation always goes through the builder's own
jsonschema check, so there is no way for the UI's idea of "valid" to drift
from Tool 2's.

Profile storage: webapp/data/golden_profiles/<slug>/{device_vars.json,metadata.json}.
"Default" is not stored there at all - it's the repo's real, current
controls.yaml + device_vars.json + render_order.yaml, read directly and
rendered on demand, so it can never silently drift from what
`python golden_config_main.py` would actually produce today.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from compliance_engine import ACTIVE_CONTROL_IDS  # noqa: E402
from golden_config_builder import GoldenConfigBuilder  # noqa: E402

from webapp.backend.security import resolve_within, sanitize_profile_name

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
PROFILES_DIR = DATA_ROOT / "golden_profiles"

CONTROLS_PATH = REPO_ROOT / "controls.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "device_vars.schema.json"
ORDER_PATH = REPO_ROOT / "render_order.yaml"
DEFAULT_DEVICE_VARS_PATH = REPO_ROOT / "device_vars.json"

DEFAULT_PROFILE_ID = "__default__"
_SEED_PROFILE_NAME = "Working Copy"


class ProfileNotFound(Exception):
    pass


class ProfileValidationError(Exception):
    """Wraps the exact ValueError GoldenConfigBuilder raises for a
    shape-invalid device_vars.json, so callers get the same message Tool 2
    would print."""


@dataclass
class FieldSpec:
    """One editable field, derived straight from schemas/device_vars.schema.json -
    never hand-mapped per control."""

    name: str
    json_type: str  # "string" | "integer" | "boolean" | "array"
    required_shape: dict  # the raw sub-schema, for array item shape etc.


@dataclass
class ControlFormSpec:
    control_id: str
    title: str
    explanation: str
    fields: list[FieldSpec] = field(default_factory=list)


@dataclass
class ProfileSummary:
    profile_id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    read_only: bool


def ensure_dirs() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def _slug_path(profile_id: str) -> Path:
    return resolve_within(PROFILES_DIR, profile_id)


def get_form_schema() -> list[ControlFormSpec]:
    """The dynamic-form definition: every active control's editable fields,
    derived from controls.yaml (title/explanation) + device_vars.schema.json
    (the actual field shapes) - nothing hard-coded per control."""
    controls = {c["control_id"]: c for c in yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))}
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    specs = []
    for control_id in sorted(ACTIVE_CONTROL_IDS):
        control = controls.get(control_id)
        if control is None or control.get("manual_review"):
            continue  # e.g. control_00012 (Banners) has no device_vars fields - free-text example only
        props = schema.get("properties", {}).get(control_id, {}).get("properties", {})
        fields = [
            FieldSpec(name=name, json_type=sub_schema.get("type", "string"), required_shape=sub_schema)
            for name, sub_schema in props.items()
        ]
        if not fields:
            continue
        specs.append(
            ControlFormSpec(
                control_id=control_id,
                title=control["title"],
                explanation=(control.get("explanation") or "").strip(),
                fields=fields,
            )
        )
    return specs


def _load_device_vars(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _metadata_defaults(name: str) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"name": name, "description": "", "created_at": now, "updated_at": now}


def _render(device_vars: dict) -> tuple[str, list[str]]:
    """Render device_vars through the real GoldenConfigBuilder. Raises
    ProfileValidationError (wrapping the builder's own message) if the shape
    is invalid."""
    tmp_vars_path = DATA_ROOT / ".tmp_device_vars.json"
    tmp_vars_path.write_text(json.dumps(device_vars), encoding="utf-8")
    try:
        builder = GoldenConfigBuilder(
            controls_path=CONTROLS_PATH,
            device_vars_path=tmp_vars_path,
            order_path=ORDER_PATH,
            schema_path=SCHEMA_PATH,
        )
    except ValueError as exc:
        raise ProfileValidationError(str(exc)) from None
    finally:
        tmp_vars_path.unlink(missing_ok=True)
    text = builder.build()
    return text, builder.missing


def render_default() -> tuple[str, list[str]]:
    return _render(_load_device_vars(DEFAULT_DEVICE_VARS_PATH))


def render_preview(device_vars: dict) -> dict:
    """Non-persisting preview for the Golden Config form - same builder call
    update_profile() would use, but nothing is written to disk. Lets the UI
    show a live, debounced preview while editing without saving on every
    keystroke (that would make "unsaved changes" meaningless)."""
    warnings = find_duplicate_value_warnings(device_vars)
    try:
        text, missing = _render(device_vars)
    except ProfileValidationError as exc:
        return {"rendered_text": f"! Unable to render - {exc}", "missing": [], "warnings": warnings, "valid": False}
    return {"rendered_text": text, "missing": missing, "warnings": warnings, "valid": True}


def list_profiles() -> list[ProfileSummary]:
    ensure_dirs()
    _ensure_seed_profile()
    summaries = [
        ProfileSummary(
            profile_id=DEFAULT_PROFILE_ID,
            name="Default",
            description="The project's real, current Golden Configuration (controls.yaml + device_vars.json).",
            created_at="",
            updated_at="",
            read_only=True,
        )
    ]
    for entry in sorted(PROFILES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        summaries.append(
            ProfileSummary(
                profile_id=entry.name,
                name=meta.get("name", entry.name),
                description=meta.get("description", ""),
                created_at=meta.get("created_at", ""),
                updated_at=meta.get("updated_at", ""),
                read_only=False,
            )
        )
    return summaries


def _ensure_seed_profile() -> None:
    """First run: give the user one editable profile out of the box,
    seeded from the same real device_vars.json Default renders from -
    so "Working Copy" starts identical to Default until they change it."""
    if any(PROFILES_DIR.iterdir()):
        return
    create_profile(_SEED_PROFILE_NAME, description="Editable copy of the default configuration.")


def create_profile(name: str, description: str = "", device_vars: dict | None = None) -> str:
    ensure_dirs()
    slug = sanitize_profile_name(name)
    profile_dir = resolve_within(PROFILES_DIR, slug)
    suffix = 2
    while profile_dir.exists():
        profile_dir = resolve_within(PROFILES_DIR, f"{slug}-{suffix}")
        suffix += 1
    profile_dir.mkdir(parents=True)

    vars_to_write = device_vars if device_vars is not None else _load_device_vars(DEFAULT_DEVICE_VARS_PATH)
    (profile_dir / "device_vars.json").write_text(json.dumps(vars_to_write, indent=2), encoding="utf-8")
    meta = _metadata_defaults(name)
    meta["description"] = description
    (profile_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return profile_dir.name


def get_profile(profile_id: str) -> dict:
    if profile_id == DEFAULT_PROFILE_ID:
        text, missing = render_default()
        return {
            "profile_id": DEFAULT_PROFILE_ID,
            "name": "Default",
            "description": "The project's real, current Golden Configuration.",
            "read_only": True,
            "device_vars": _load_device_vars(DEFAULT_DEVICE_VARS_PATH),
            "rendered_text": text,
            "missing": missing,
        }
    profile_dir = _profile_dir_or_raise(profile_id)
    device_vars = _load_device_vars(profile_dir / "device_vars.json")
    meta = json.loads((profile_dir / "metadata.json").read_text(encoding="utf-8"))
    try:
        text, missing = _render(device_vars)
    except ProfileValidationError as exc:
        text, missing = f"! Unable to render - {exc}", []
    return {
        "profile_id": profile_id,
        "name": meta.get("name", profile_id),
        "description": meta.get("description", ""),
        "read_only": False,
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "device_vars": device_vars,
        "rendered_text": text,
        "missing": missing,
    }


def _profile_dir_or_raise(profile_id: str) -> Path:
    try:
        profile_dir = resolve_within(PROFILES_DIR, profile_id)
    except ValueError:
        raise ProfileNotFound(profile_id) from None
    if not profile_dir.is_dir() or not (profile_dir / "metadata.json").exists():
        raise ProfileNotFound(profile_id)
    return profile_dir


def update_profile(profile_id: str, device_vars: dict, description: str | None = None) -> dict:
    """Validates via the real builder before writing anything - an invalid
    save is rejected wholesale, never partially written."""
    if profile_id == DEFAULT_PROFILE_ID:
        raise ProfileValidationError("The Default configuration is read-only - save as a new profile instead.")
    profile_dir = _profile_dir_or_raise(profile_id)
    text, missing = _render(device_vars)  # raises ProfileValidationError if the shape is wrong

    warnings = find_duplicate_value_warnings(device_vars)

    (profile_dir / "device_vars.json").write_text(json.dumps(device_vars, indent=2), encoding="utf-8")
    meta = json.loads((profile_dir / "metadata.json").read_text(encoding="utf-8"))
    if description is not None:
        meta["description"] = description
    meta["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (profile_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {"rendered_text": text, "missing": missing, "warnings": warnings}


def rename_profile(profile_id: str, name: str, description: str | None = None) -> None:
    profile_dir = _profile_dir_or_raise(profile_id)
    meta = json.loads((profile_dir / "metadata.json").read_text(encoding="utf-8"))
    meta["name"] = name
    if description is not None:
        meta["description"] = description
    meta["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (profile_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def delete_profile(profile_id: str) -> None:
    if profile_id == DEFAULT_PROFILE_ID:
        raise ProfileValidationError("The Default configuration cannot be deleted.")
    profile_dir = _profile_dir_or_raise(profile_id)
    for child in profile_dir.iterdir():
        child.unlink()
    profile_dir.rmdir()


def duplicate_profile(profile_id: str, new_name: str) -> str:
    source = get_profile(profile_id)
    return create_profile(new_name, description=source["description"], device_vars=source["device_vars"])


def restore_default_into(profile_id: str) -> dict:
    """Overwrites `profile_id`'s device_vars with the real Default's -
    the Default source file itself is never touched."""
    default_vars = _load_device_vars(DEFAULT_DEVICE_VARS_PATH)
    return update_profile(profile_id, default_vars)


_GENERATED_TIMESTAMP_RE = re.compile(r"^!\s*Generated:\s")


def _strip_generated_timestamp(text: str) -> list[str]:
    """GoldenConfigBuilder stamps a fresh '! Generated: <now>' line on every
    build() call (see golden_config_builder.py) - two renders of the exact
    same device_vars a second apart would otherwise show a spurious 1-line
    diff every time, which would make "Compare with Default" useless.
    Excluded here only for comparison purposes; the real rendered text
    (with its real timestamp) is still what gets saved/previewed/exported."""
    return [line for line in text.splitlines() if not _GENERATED_TIMESTAMP_RE.match(line)]


def compare_with_default(profile_id: str) -> list[dict]:
    """Line-by-line diff between a profile's rendered output and Default's -
    both rendered through the same builder, so the comparison is
    apples-to-apples."""
    profile = get_profile(profile_id)
    default_text, _ = render_default()
    diff_lines = list(
        difflib.unified_diff(
            _strip_generated_timestamp(default_text), _strip_generated_timestamp(profile["rendered_text"]),
            fromfile="Default", tofile=profile["name"], lineterm="",
        )
    )
    return [{"line": line} for line in diff_lines]


def find_duplicate_value_warnings(device_vars: dict) -> list[str]:
    """Advisory (non-blocking) duplicate-value checks for the one control
    with a genuinely repeating, name/address-keyed structure in the schema
    (control_00004's tacacs_servers) - not a compliance rule, just an
    authoring-time sanity check the spec asked for."""
    warnings: list[str] = []
    servers = device_vars.get("control_00004", {}).get("tacacs_servers") or []
    seen_names: dict[str, int] = {}
    seen_addresses: dict[str, int] = {}
    for server in servers:
        name = server.get("name")
        address = server.get("address")
        if name:
            seen_names[name] = seen_names.get(name, 0) + 1
        if address:
            seen_addresses[address] = seen_addresses.get(address, 0) + 1
    warnings += [f"TACACS server name '{n}' is used more than once." for n, c in seen_names.items() if c > 1]
    warnings += [f"TACACS server address '{a}' is used more than once." for a, c in seen_addresses.items() if c > 1]
    return warnings


def import_golden_config_text(text: str) -> dict:
    """Structural validation only, per the project's real convention: every
    active control's own section is introduced by a '! control_XXXXX - <Title>'
    header line (see any file this project's own tools produce). Detects
    missing/duplicated sections; does NOT attempt to reverse-parse arbitrary
    command text back into individual device_vars fields - see
    documentation/WEBAPP.md for why."""
    controls = {c["control_id"]: c for c in yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))}
    header_re = re.compile(r"^!\s*(control_\d{5})\s*-\s*(.+)$", re.MULTILINE)
    found = header_re.findall(text)
    found_ids = [control_id for control_id, _title in found]

    duplicates = sorted({cid for cid in found_ids if found_ids.count(cid) > 1})
    missing = sorted(cid for cid in ACTIVE_CONTROL_IDS if cid not in found_ids)

    is_valid = not missing and not duplicates
    return {
        "is_valid": is_valid,
        "sections_found": [{"control_id": cid, "title": controls.get(cid, {}).get("title", "")} for cid in found_ids],
        "missing_sections": [{"control_id": cid, "title": controls.get(cid, {}).get("title", "")} for cid in missing],
        "duplicate_sections": duplicates,
        "raw_text": text,
    }
