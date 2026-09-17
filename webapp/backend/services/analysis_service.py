"""Analysis Workspace screen - runs Tool 1's real evaluator against selected
uploaded configs and a chosen Golden Config profile.

Reuses main.py's own `_evaluate_device` (same per-control ASSESSMENT_ERROR
isolation, same report_generator calls) and run_archive.py's timestamp+latest
archiving convention - batch analysis here produces exactly the same
report.json/report.html shape the CLI's batch mode does, so Tools 3/5/6 (and
their web-app equivalents) work off real, familiar data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compliance_engine import ACTIVE_CONTROL_IDS  # noqa: E402
from main import _evaluate_device, load_controls  # noqa: E402
from report_generator import render_fleet_html  # noqa: E402
from run_archive import new_run_dir, refresh_latest  # noqa: E402

from webapp.backend import jobs
from webapp.backend.services import configs_service, golden_service

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
RUNS_DIR = DATA_ROOT / "runs"
CONTROLS_PATH = REPO_ROOT / "controls.yaml"

_FORMATS = {"html", "json"}


class AnalysisError(Exception):
    """A user-facing reason analysis can't start - never a raw traceback."""


def ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def start_analysis(device_filenames: list[str], golden_profile_id: str) -> str:
    ensure_dirs()
    if not device_filenames:
        raise AnalysisError("Select at least one configuration file to analyze.")

    profile = golden_service.get_profile(golden_profile_id)
    if profile["missing"]:
        raise AnalysisError(
            f"The selected Golden Config ('{profile['name']}') has {len(profile['missing'])} unresolved "
            "value(s) - resolve them in the Golden Config Manager before running analysis."
        )

    missing_files = [f for f in device_filenames if not (configs_service.DEVICE_CONFIGS_DIR / f).exists()]
    if missing_files:
        raise AnalysisError(f"File(s) not found: {', '.join(missing_files)}")

    controls = [c for c in load_controls(CONTROLS_PATH) if c["control_id"] in ACTIVE_CONTROL_IDS]
    exceptions: dict[str, str] = {}

    run_dir = new_run_dir(RUNS_DIR)
    golden_config_text = profile["rendered_text"]
    golden_config_path = run_dir / "_golden_config_used.txt"
    golden_config_path.write_text(golden_config_text, encoding="utf-8")
    # Persisted so downstream screens (Briefings) can accurately compute
    # "still-needed variables" for this run's actual Golden Config, without
    # having to guess which profile was active after the fact.
    (run_dir / "_device_vars_used.json").write_text(json.dumps(profile["device_vars"]), encoding="utf-8")

    device_entries = [(fn, configs_service.DEVICE_CONFIGS_DIR / fn) for fn in device_filenames]

    def work(report_progress):
        results_by_device: dict[str, list] = {}
        report_links: dict[str, str] = {}
        total_fail = 0
        errored_devices: list[str] = []

        for index, (filename, device_path) in enumerate(device_entries):
            device_stem = Path(filename).stem
            report_progress(index, f"Analyzing {device_stem} ({index + 1} of {len(device_entries)})")
            try:
                results = _evaluate_device(
                    device_path, golden_config_path, golden_config_text,
                    controls, exceptions, run_dir / device_stem, _FORMATS,
                )
            except Exception as exc:  # noqa: BLE001 - one unreadable file must not stop the batch
                errored_devices.append(f"{device_stem}: {exc}")
                continue
            results_by_device[device_stem] = results
            report_links[device_stem] = f"{device_stem}/report.html"
            total_fail += sum(1 for r in results if r.status == "FAIL")

        if len(device_entries) > 1 and results_by_device:
            render_fleet_html(results_by_device, report_links, run_dir / "fleet_report.html")

        refresh_latest(run_dir, RUNS_DIR)

        return {
            "run_id": run_dir.name,
            "device_count": len(device_entries),
            "analyzed_count": len(results_by_device),
            "total_fail": total_fail,
            "errored_devices": errored_devices,
            "golden_profile": profile["name"],
        }

    return jobs.start_job("analysis", total=len(device_entries), work=work)


def list_runs() -> list[dict]:
    ensure_dirs()
    runs = []
    for entry in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not entry.is_dir() or entry.name == "latest":
            continue
        device_dirs = [p for p in entry.iterdir() if p.is_dir() and (p / "report.json").exists()]
        runs.append({"run_id": entry.name, "device_count": len(device_dirs)})
    return runs


def latest_run_id() -> str | None:
    latest = RUNS_DIR / "latest"
    if not latest.exists():
        return None
    # latest/ is a refreshed copy, not a symlink (see run_archive.py) - the
    # real run_id is recoverable from the newest timestamped sibling.
    candidates = [p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name != "latest"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime).name


def run_dir_path(run_id: str) -> Path:
    from webapp.backend.security import resolve_within

    return resolve_within(RUNS_DIR, run_id)


def list_run_devices(run_id: str) -> list[str]:
    """Device (stem) names this run actually produced a report.json for -
    what Briefings/Compliance Report screens offer as pickable devices."""
    run_dir = run_dir_path(run_id)
    return sorted(p.name for p in run_dir.iterdir() if p.is_dir() and (p / "report.json").exists())
