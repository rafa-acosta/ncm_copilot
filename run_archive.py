"""Shared historic-versioning helper for every report-producing CLI (main.py,
agent_assisted_coding_advise.py, compliance_report_main.py).

Each run writes its output into a fresh timestamped subdirectory of the
tool's output root, so nothing from a previous run is ever overwritten, then
refreshes a `latest/` mirror alongside it - a stable, predictable path for
anything that wants "the current one" (a bookmark, a script, a published
artifact) without hunting through timestamps.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def new_run_dir(root: Path, when: datetime | None = None) -> Path:
    """Create and return root/YYYYMMDD-HHMMSS. Disambiguates with a numeric
    -2/-3/... suffix in the rare case two runs land in the same second."""
    when = when or datetime.now()
    stamp = when.strftime("%Y%m%d-%H%M%S")
    candidate = root / stamp
    suffix = 2
    while candidate.exists():
        candidate = root / f"{stamp}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def refresh_latest(run_dir: Path, root: Path) -> Path:
    """Replace root/latest with a fresh copy of run_dir's contents (never
    run_dir itself - the timestamped archive is left untouched). Returns
    root/latest."""
    latest = root / "latest"
    if latest.is_symlink() or latest.is_file():
        latest.unlink()
    elif latest.is_dir():
        shutil.rmtree(latest)
    shutil.copytree(run_dir, latest)
    return latest
