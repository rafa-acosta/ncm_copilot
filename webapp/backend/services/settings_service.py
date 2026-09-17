"""Settings screen - system status, assembled from existing helpers
(llm_engine_service.get_status() for backend reachability + start/stop
control, compliance_report_builder.controls_version()) plus simple counts of
this workspace's own data.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compliance_report_builder import controls_version  # noqa: E402

from webapp.backend.services import configs_service, golden_service, llm_engine_service
from webapp.backend.services.analysis_service import RUNS_DIR

CONTROLS_PATH = REPO_ROOT / "controls.yaml"
DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def get_status() -> dict:
    backends = llm_engine_service.get_status()

    configs_service.ensure_dirs()
    golden_service.ensure_dirs()
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    run_dirs = [p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name != "latest"]

    return {
        "controls_version": controls_version(CONTROLS_PATH),
        "backends": backends,
        "any_backend_reachable": any(b["reachable"] for b in backends),
        "data_workspace": str(DATA_ROOT),
        "device_config_count": len(list(configs_service.DEVICE_CONFIGS_DIR.glob("*.txt"))),
        "golden_profile_count": len(golden_service.list_profiles()) - 1,  # exclude the synthetic Default entry
        "run_count": len(run_dirs),
    }
