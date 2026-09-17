"""Dashboard screen - Tool 6 (compliance_dashboard_builder.py) over one
analysis run's reports. Produces the same self-contained static HTML the CLI
tool does (embedded directly by the frontend) plus the underlying context
dict for native KPI cards.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compliance_dashboard_builder import build_dashboard  # noqa: E402

from webapp.backend.security import resolve_within
from webapp.backend.services.analysis_service import run_dir_path

CONTROLS_PATH = REPO_ROOT / "controls.yaml"
DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
HISTORY_DIR = DATA_ROOT / "compliance_history"


class DashboardError(Exception):
    """User-facing reason a dashboard couldn't be built."""


def build_for_run(run_id: str) -> dict:
    run_dir = run_dir_path(run_id)
    device_report_dirs = [p for p in run_dir.iterdir() if p.is_dir() and (p / "report.json").exists()]
    if not device_report_dirs:
        raise DashboardError(f"Run '{run_id}' has no analyzed devices to build a dashboard from.")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    out_dir = resolve_within(run_dir, "dashboard")
    context = build_dashboard(run_dir, CONTROLS_PATH, out_dir, HISTORY_DIR)

    fleet = context["fleet"]
    return {
        "run_id": run_id,
        "html_path": str(context["html_path"]),
        "device_count": fleet.device_count,
        "strict_compliance_pct": fleet.strict_compliance_pct,
        "assessment_coverage_pct": fleet.assessment_coverage_pct,
        "critical_finding_count": fleet.critical_finding_count,
        "executive_summary": context["executive_summary"],
        "device_summaries": [
            {
                "device_name": d.device_name,
                "strict_compliance_pct": d.strict_compliance_pct,
                "pass_count": d.pass_count,
                "fail_count": d.counts.get("FAIL", 0),
                "has_critical_failure": d.has_critical_failure,
            }
            for d in context["device_summaries"]
        ],
        "control_summaries": [
            {
                "control_id": c.control_id,
                "title": c.title,
                "compliance_pct": c.compliance_pct,
                "fail_count": c.counts.get("FAIL", 0),
                "affected_device_count": c.affected_device_count,
            }
            for c in context["control_summaries"]
        ],
        "worst_devices": [
            {"device_name": d.device_name, "strict_compliance_pct": d.strict_compliance_pct}
            for d in context["worst_devices"]
        ],
    }


def read_dashboard_html(run_id: str) -> str:
    run_dir = run_dir_path(run_id)
    html_path = resolve_within(run_dir, "dashboard", "compliance_dashboard.html")
    if not html_path.exists():
        raise FileNotFoundError(run_id)
    return html_path.read_text(encoding="utf-8")
