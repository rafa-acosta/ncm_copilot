"""Historical snapshot persistence for the compliance dashboard's trend charts.

Each dashboard run writes one JSON snapshot to `history_dir/<timestamp>.json`
(same timestamped-archive convention as run_archive.py, reused here for a
different purpose: run_archive.py's `latest/` mirror is a full-replace, which
is exactly wrong for history - we want every snapshot kept, not the newest
one replacing the rest). A snapshot holds the run's aggregated metrics, not a
full per-device/per-control replay - enough to redraw every trend line, not
to reconstruct a past run's heatmap or drill-downs. Only the current run
supports full drill-down.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from compliance_metrics import FleetMetrics


def write_snapshot(history_dir: Path, metrics: FleetMetrics, controls_version: str, when: datetime | None = None) -> Path:
    """Write one snapshot file and return its path. Never overwrites a
    previous snapshot - each call gets its own timestamped filename (with a
    numeric suffix on the rare same-second collision)."""
    when = when or datetime.now()
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = when.strftime("%Y%m%d-%H%M%S")
    path = history_dir / f"{stamp}.json"
    suffix = 2
    while path.exists():
        path = history_dir / f"{stamp}-{suffix}.json"
        suffix += 1

    snapshot = {
        "timestamp": when.isoformat(timespec="seconds"),
        "controls_version": controls_version,
        "metrics": asdict(metrics),
    }
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return path


def read_snapshots(history_dir: Path) -> list[dict]:
    """All snapshots in `history_dir`, oldest first. Empty list if the
    directory doesn't exist yet (a first run has no history to show)."""
    if not history_dir.exists():
        return []
    snapshots = []
    for path in sorted(history_dir.glob("*.json")):
        snapshots.append(json.loads(path.read_text(encoding="utf-8")))
    snapshots.sort(key=lambda s: s["timestamp"])
    return snapshots
