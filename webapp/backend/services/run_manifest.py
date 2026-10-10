"""Central, persisted per-run metadata manifest.

Every analysis run directory (webapp/data/runs/<run_id>/) gets exactly one
`_run_manifest.json` alongside the artifacts main.py's own evaluator already
writes there (report.json, _golden_config_used.txt, etc.). This is the single
source of truth for run-level status/timing/traceability that no existing
file captured before: which Golden Config profile produced the snapshot, and
when each stage (analysis/briefing/dashboard/compliance_report) started,
finished, and how long it took.

Deliberately a plain JSON file, not a database - matches this project's
existing convention (golden_profiles/<slug>/metadata.json, jobs.py's comment
about "single-operator local tool") and needs no migration story. A
process-wide lock serializes writes since analysis/briefing jobs update their
stage from a background thread (see jobs.py) while the request thread may
read concurrently.

Backward compatibility: runs created before this module existed have no
manifest file. `load_or_legacy()` never writes anything on a mere read - it
returns a best-effort, explicitly-marked-legacy manifest computed from
whatever the run directory itself proves (report.json files, a briefings/
folder, a dashboard/ folder), leaving every field that can't be recovered
that way as None rather than guessing. Callers/UI render None as "N/A" /
"Unknown" / "Legacy run", never as an exception.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

STATUS_NOT_GENERATED = "not_generated"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

STAGES = ("analysis", "briefing", "dashboard", "compliance_report")

MANIFEST_FILENAME = "_run_manifest.json"

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _manifest_path(run_dir: Path) -> Path:
    return run_dir / MANIFEST_FILENAME


def _empty_stage() -> dict:
    return {
        "status": STATUS_NOT_GENERATED,
        "started_at": None,
        "completed_at": None,
        "duration_seconds": None,
        "error": None,
    }


def _empty_manifest(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "created_at": _now_iso(),
        "configuration_count": None,
        "selected_configuration_count": None,
        "golden_config": None,
        "analysis": _empty_stage(),
        "briefing": _empty_stage(),
        "dashboard": _empty_stage(),
        "compliance_report": _empty_stage(),
        "is_legacy": False,
    }


def load(run_dir: Path) -> dict | None:
    """Raw read - None if this run has no manifest yet (legacy run, or one
    still mid-creation). Never raises on a corrupt file; treats it as absent
    rather than crashing the page that asked for it."""
    path = _manifest_path(run_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save(run_dir: Path, manifest: dict) -> None:
    _manifest_path(run_dir).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def create_for_analysis(
    run_dir: Path,
    run_id: str,
    configuration_count: int,
    selected_configuration_count: int,
    golden_config: dict,
) -> dict:
    """Called once, at the start of a new analysis run - establishes the
    manifest before the background job's own status/timing updates land."""
    with _lock:
        manifest = _empty_manifest(run_id)
        manifest["configuration_count"] = configuration_count
        manifest["selected_configuration_count"] = selected_configuration_count
        manifest["golden_config"] = golden_config
        _save(run_dir, manifest)
        return manifest


def mark_started(run_dir: Path, stage: str) -> float:
    """Records stage start (wall-clock, for the UI/audit trail) and returns a
    monotonic reference the caller must pass back to mark_completed/mark_failed
    for a duration immune to system clock adjustments - see time.monotonic()."""
    assert stage in STAGES, stage
    with _lock:
        manifest = load(run_dir) or _empty_manifest(run_dir.name)
        manifest[stage] = {
            "status": STATUS_IN_PROGRESS,
            "started_at": _now_iso(),
            "completed_at": None,
            "duration_seconds": None,
            "error": None,
        }
        _save(run_dir, manifest)
    return time.monotonic()


def mark_completed(run_dir: Path, stage: str, monotonic_start: float | None, **extra) -> dict:
    assert stage in STAGES, stage
    duration = round(time.monotonic() - monotonic_start, 3) if monotonic_start is not None else None
    with _lock:
        manifest = load(run_dir) or _empty_manifest(run_dir.name)
        stage_data = manifest.get(stage) or _empty_stage()
        stage_data.update(
            {"status": STATUS_COMPLETED, "completed_at": _now_iso(), "duration_seconds": duration, "error": None, **extra}
        )
        manifest[stage] = stage_data
        _save(run_dir, manifest)
        return manifest


def mark_failed(run_dir: Path, stage: str, monotonic_start: float | None, error: str) -> dict:
    assert stage in STAGES, stage
    duration = round(time.monotonic() - monotonic_start, 3) if monotonic_start is not None else None
    with _lock:
        manifest = load(run_dir) or _empty_manifest(run_dir.name)
        stage_data = manifest.get(stage) or _empty_stage()
        stage_data.update({"status": STATUS_FAILED, "completed_at": _now_iso(), "duration_seconds": duration, "error": error})
        manifest[stage] = stage_data
        _save(run_dir, manifest)
        return manifest


def update_golden_config(run_dir: Path, golden_config: dict) -> dict:
    """Lets a later stage (Briefings, if the user overrides the Golden Config
    for that briefing only) record what it actually used without touching the
    analysis-time snapshot this run was originally built from."""
    with _lock:
        manifest = load(run_dir) or _empty_manifest(run_dir.name)
        manifest["briefing_golden_config"] = golden_config
        _save(run_dir, manifest)
        return manifest


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def legacy_summary(run_dir: Path, device_count: int) -> dict:
    """Best-effort manifest-shaped view for a run that predates this module -
    derived only from what the run directory itself proves, computed on every
    read (never written to disk, so listing runs stays a read-only operation).
    Anything not recoverable this way stays None; the frontend renders that as
    N/A/Unknown/"Legacy run" rather than crashing or guessing."""
    manifest = _empty_manifest(run_dir.name)
    manifest["configuration_count"] = device_count
    manifest["selected_configuration_count"] = device_count
    manifest["is_legacy"] = True

    snapshot_path = run_dir / "_golden_config_used.txt"
    manifest["golden_config"] = {
        "name": "Unknown",
        "profile_id": None,
        "source": "legacy",
        "snapshot_path": snapshot_path.name if snapshot_path.exists() else None,
        "checksum": sha256_text(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.exists() else None,
        "profile_updated_at": None,
    }

    # No timing survives for a pre-manifest run, but its outcome does: the
    # artifacts either exist on disk or they don't.
    manifest["analysis"]["status"] = STATUS_COMPLETED if device_count else STATUS_NOT_GENERATED
    briefings_dir = run_dir / "briefings"
    if briefings_dir.is_dir() and any(briefings_dir.iterdir()):
        manifest["briefing"]["status"] = STATUS_COMPLETED
    if (run_dir / "dashboard" / "compliance_dashboard.html").exists():
        manifest["dashboard"]["status"] = STATUS_COMPLETED
    if any(run_dir.glob("*/compliance_report/report.pdf")):
        manifest["compliance_report"]["status"] = STATUS_COMPLETED

    return manifest


def load_or_legacy(run_dir: Path, device_count: int) -> dict:
    """What every read path should call: the real manifest if this run has
    one, otherwise a computed legacy view - never None, so callers never need
    their own None-handling branch."""
    manifest = load(run_dir)
    if manifest is not None:
        return manifest
    return legacy_summary(run_dir, device_count)
