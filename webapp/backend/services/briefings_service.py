"""Briefings screen - Tool 3 (Compliance Remediation Advisor) over a
completed analysis run. Reuses remediation_advisor.py and llm_client.py
directly; the only new code here is picking which run/device(s) to brief
and where to save the result, matching agent_assisted_coding_advise.py's own
batch-vs-single split.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_assisted_coding_advise import _brief_device  # noqa: E402
from llm_client import BackendUnavailableError, LLMClient, select_backend  # noqa: E402
from remediation_advisor import discover_report_paths, load_controls_by_id, load_report  # noqa: E402

from webapp.backend import jobs
from webapp.backend.security import resolve_within
from webapp.backend.services import golden_service, run_manifest
from webapp.backend.services.analysis_service import run_dir_path

CONTROLS_PATH = REPO_ROOT / "controls.yaml"


class BriefingError(Exception):
    """User-facing reason a briefing run couldn't start."""


def get_golden_config_options(run_id: str) -> dict:
    """What the Briefings screen needs to build its Golden Config selector:
    the run's OWN Golden Config (from its analysis-time manifest - the safe
    default, never silently swapped for the repo's default profile) plus
    every profile the user could deliberately choose instead."""
    run_dir = run_dir_path(run_id)
    device_dirs = [p for p in run_dir.iterdir() if p.is_dir() and (p / "report.json").exists()]
    manifest = run_manifest.load_or_legacy(run_dir, len(device_dirs))
    return {
        "run_golden_config": manifest.get("golden_config"),
        "profiles": [
            {"profile_id": p.profile_id, "name": p.name, "read_only": p.read_only} for p in golden_service.list_profiles()
        ],
    }


def _resolve_device_vars(run_dir: Path, run_golden_config: dict | None, golden_profile_id: str | None) -> tuple[dict | None, dict | None]:
    """Returns (device_vars, golden_config_meta_actually_used).

    Default (golden_profile_id is None or matches the run's own profile_id):
    use the exact snapshot this run's analysis produced - never silently
    substitutes the repo's default Golden Config. Only an explicit, different
    profile_id causes a different Golden Config's device_vars to be used."""
    run_profile_id = (run_golden_config or {}).get("profile_id")
    if golden_profile_id is None or golden_profile_id == run_profile_id:
        device_vars_path = run_dir / "_device_vars_used.json"
        device_vars = json.loads(device_vars_path.read_text(encoding="utf-8")) if device_vars_path.exists() else None
        used_meta = dict(run_golden_config) if run_golden_config else None
        if used_meta is not None:
            used_meta["source"] = "run snapshot"
        return device_vars, used_meta

    profile = golden_service.get_profile(golden_profile_id)
    used_meta = {
        "name": profile["name"],
        "profile_id": golden_profile_id,
        "source": "override",
        "snapshot_path": None,
        "checksum": run_manifest.sha256_text(profile["rendered_text"]),
        "profile_updated_at": profile.get("updated_at") or None,
    }
    return profile["device_vars"], used_meta


def start_briefing(
    run_id: str,
    device_filenames: list[str] | None,
    severity_min: str | None,
    backend_choice: str = "auto",
    golden_profile_id: str | None = None,
) -> str:
    run_dir = run_dir_path(run_id)
    if device_filenames:
        report_paths = []
        for name in device_filenames:
            path = resolve_within(run_dir, Path(name).stem, "report.json")
            if not path.exists():
                raise BriefingError(f"No analysis report found for '{name}' in this run.")
            report_paths.append(path)
    else:
        try:
            report_paths = discover_report_paths(run_dir)
        except FileNotFoundError as exc:
            raise BriefingError(str(exc)) from None

    try:
        backend_name, base_url, model_name = select_backend(backend_choice, device_count=len(report_paths))
    except BackendUnavailableError as exc:
        raise BriefingError(str(exc)) from None

    llm_client = LLMClient(base_url, backend_name, model=model_name)
    backend_label = f"{backend_name} ({model_name})"
    controls_by_id = load_controls_by_id(CONTROLS_PATH)

    device_dirs = [p for p in run_dir.iterdir() if p.is_dir() and (p / "report.json").exists()]
    manifest = run_manifest.load_or_legacy(run_dir, len(device_dirs))
    device_vars, golden_config_used = _resolve_device_vars(run_dir, manifest.get("golden_config"), golden_profile_id)
    if golden_config_used is not None:
        run_manifest.update_golden_config(run_dir, golden_config_used)

    briefings_dir = run_dir / "briefings"
    briefings_dir.mkdir(exist_ok=True)

    def work(report_progress):
        mono_start = run_manifest.mark_started(run_dir, "briefing")
        briefed = []
        errors = []
        for index, path in enumerate(report_paths):
            report = load_report(path)
            report_progress(index, f"Briefing {report.device_name} ({index + 1} of {len(report_paths)})")
            try:
                device_dir = briefings_dir / report.device_name
                device_dir.mkdir(parents=True, exist_ok=True)
                count = _brief_device(
                    report, controls_by_id, device_vars, llm_client, backend_label, severity_min,
                    device_dir / "briefing.md", device_dir / "briefing.json",
                )
                # _brief_device/render_briefing_json (shared with the CLI tool)
                # stamp the analysis-time golden_config_path for reproducibility
                # but have no notion of a briefing-time override - patch that
                # traceability in here rather than changing the shared renderer.
                if golden_config_used is not None:
                    json_path = device_dir / "briefing.json"
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    data["golden_config_used"] = golden_config_used
                    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                briefed.append({"device": report.device_name, "finding_count": count})
            except Exception as exc:  # noqa: BLE001 - one device's LLM call failing must not stop the batch
                errors.append(f"{report.device_name}: {exc}")

        if errors and not briefed:
            run_manifest.mark_failed(run_dir, "briefing", mono_start, "; ".join(errors))
        else:
            run_manifest.mark_completed(run_dir, "briefing", mono_start, device_count=len(briefed), error_count=len(errors))
        return {"briefed": briefed, "errors": errors, "backend": backend_label}

    return jobs.start_job("briefing", total=len(report_paths), work=work)


def list_briefings(run_id: str) -> list[dict]:
    run_dir = run_dir_path(run_id)
    briefings_dir = run_dir / "briefings"
    if not briefings_dir.exists():
        return []
    results = []
    for device_dir in sorted(briefings_dir.iterdir()):
        md_path = device_dir / "briefing.md"
        if md_path.exists():
            results.append({"device": device_dir.name, "modified_at": md_path.stat().st_mtime})
    return results


def read_briefing(run_id: str, device_name: str) -> dict:
    run_dir = run_dir_path(run_id)
    device_dir = resolve_within(run_dir / "briefings", device_name)
    md_path = device_dir / "briefing.md"
    json_path = device_dir / "briefing.json"
    if not md_path.exists():
        raise FileNotFoundError(device_name)
    return {
        "device": device_name,
        "markdown": md_path.read_text(encoding="utf-8"),
        "data": json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else None,
    }
