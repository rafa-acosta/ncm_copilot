"""A minimal in-memory background-job tracker for long-running operations
(batch analysis, briefing generation) that need to report live progress to
a polling frontend.

Deliberately not a task queue (Celery, etc.) - this is a single-operator
local tool (see webapp/README.md), so one Python process with a thread per
job and a dict for status is the right amount of infrastructure, not a
placeholder for something bigger.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}


@dataclass
class Job:
    job_id: str
    kind: str
    status: str = "running"  # "running" | "done" | "error"
    total: int = 0
    processed: int = 0
    current_label: str = ""
    result: dict | None = None
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    finished_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "total": self.total,
            "processed": self.processed,
            "current_label": self.current_label,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def _update(job_id: str, **kwargs) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        for key, value in kwargs.items():
            setattr(job, key, value)


def start_job(kind: str, total: int, work: Callable[[Callable[[int, str], None]], dict]) -> str:
    """Runs `work` in a background thread. `work` receives a `report_progress(processed, label)`
    callback it should call after each unit completes, and must return the
    job's final `result` dict (or raise - the exception message becomes
    Job.error, never a raw traceback, though the full traceback is logged
    server-side for diagnosis)."""
    job_id = uuid.uuid4().hex[:12]
    job = Job(job_id=job_id, kind=kind, total=total)
    with _lock:
        _jobs[job_id] = job

    def report_progress(processed: int, label: str) -> None:
        _update(job_id, processed=processed, current_label=label)

    def run() -> None:
        try:
            result = work(report_progress)
        except Exception as exc:  # noqa: BLE001 - a job's own failure must never crash the server
            traceback.print_exc()
            _update(job_id, status="error", error=str(exc), finished_at=_now())
        else:
            _update(job_id, status="done", result=result, processed=job.total, finished_at=_now())

    threading.Thread(target=run, daemon=True).start()
    return job_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
