"""Local LLM engine lifecycle management for the Settings screen - start/stop
the actual llama-server process behind a registered backend.

Launches reuse local-llm/serve_<name>.sh as-is (same model path, port, ngl,
ctx-size, env var overrides, GPU-offload log messages as the project's own
documented workflow) via llm_client._launch_hint(), which already resolves a
backend name to its real script path - nothing about *how* to launch a
backend is re-derived here. This module owns only process lifecycle (start,
stop, live status) and the "only one engine at a time" rule already
documented in local-llm/config.yaml's notes.

A process being alive is not the same as it being ready to serve (the model
may still be loading), so `reachable` (the same llm_client._is_reachable()
check Settings has always used) and `managed_status` (is a process this
module started still running) are reported as two separate facts.
"""

from __future__ import annotations

import collections
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm_client import _is_reachable, _launch_hint, load_backends_registry  # noqa: E402

_LOG_TAIL_LINES = 200
_STOP_GRACE_SECONDS = 20


class EngineError(Exception):
    """A user-facing reason an engine couldn't be started/stopped."""


@dataclass
class _ManagedEngine:
    name: str
    process: subprocess.Popen
    pgid: int
    started_at: str
    log_lines: collections.deque = field(default_factory=lambda: collections.deque(maxlen=_LOG_TAIL_LINES))
    stopped_intentionally: bool = False


_lock = threading.Lock()
_engines: dict[str, _ManagedEngine] = {}


def _resolve_script(name: str) -> Path | None:
    hint = _launch_hint(name)  # e.g. "local-llm/serve_phi4mini.sh", or a README fallback string
    if not hint.startswith("local-llm/"):
        return None
    script = REPO_ROOT / hint
    return script if script.exists() else None


def _pump_output(engine: _ManagedEngine) -> None:
    """Continuously drain the subprocess's combined stdout/stderr so its pipe
    buffer never fills and blocks it - the retained tail is only for the
    UI's diagnostics panel."""
    for line in engine.process.stdout:
        engine.log_lines.append(line.rstrip("\n"))
    engine.process.wait()


def _raise_if_conflicting_engine_running(name: str) -> None:
    """Must be called while holding `_lock`. Only one local LLM engine fits
    in VRAM on this hardware (see local-llm/config.yaml's notes)."""
    existing = _engines.get(name)
    if existing is not None and existing.process.poll() is None:
        raise EngineError(f"'{name}' is already running.")
    other_managed = next((n for n, e in _engines.items() if n != name and e.process.poll() is None), None)
    if other_managed:
        raise EngineError(
            f"'{other_managed}' is currently running. Stop it first — only one local "
            "LLM engine is supported at a time on this hardware."
        )


def start_engine(name: str) -> None:
    script = _resolve_script(name)
    if script is None:
        raise EngineError(f"No managed launch script found for '{name}'.")

    with _lock:
        _raise_if_conflicting_engine_running(name)

    # Also guard against an engine that's up but wasn't started by this app
    # (no process handle to check above) - the real constraint is VRAM, not
    # who launched the process, so a live reachability check covers that case.
    # Done outside the lock since this makes a network call per backend.
    for other_name, cfg in load_backends_registry().items():
        if other_name != name and _is_reachable(cfg.get("base_url", "")):
            raise EngineError(
                f"'{other_name}' is currently reachable at {cfg.get('base_url')} (possibly started "
                "outside this app). Stop it first — only one local LLM engine is supported at a "
                "time on this hardware."
            )

    with _lock:
        # Re-check inside the lock in case another start_engine() call raced
        # us between the checks above and here.
        _raise_if_conflicting_engine_running(name)

        process = subprocess.Popen(
            ["bash", str(script)],
            cwd=script.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,  # own process group, so stop_engine() can signal the whole tree cleanly
        )
        engine = _ManagedEngine(
            name=name,
            process=process,
            pgid=os.getpgid(process.pid),
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        _engines[name] = engine

    threading.Thread(target=_pump_output, args=(engine,), daemon=True).start()


def stop_engine(name: str) -> None:
    with _lock:
        engine = _engines.get(name)
        if engine is None or engine.process.poll() is not None:
            raise EngineError(f"'{name}' is not running (or wasn't started by this app).")
        engine.stopped_intentionally = True
        pgid = engine.pgid
        process = engine.process

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return

    def _force_kill_if_still_alive() -> None:
        try:
            process.wait(timeout=_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    threading.Thread(target=_force_kill_if_still_alive, daemon=True).start()


def get_status() -> list[dict]:
    """One entry per backend in local-llm/config.yaml - the full registry,
    not just the ones this module happens to be managing, so an externally-
    started or unmanageable backend still shows up (reachability-only)."""
    registry = load_backends_registry()
    result = []
    with _lock:
        for name, cfg in registry.items():
            base_url = cfg.get("base_url", "")
            reachable = _is_reachable(base_url)
            engine = _engines.get(name)
            alive = engine is not None and engine.process.poll() is None

            if alive:
                managed_status = "running"
            elif engine is not None:
                managed_status = "stopped" if (engine.stopped_intentionally or engine.process.returncode == 0) else "failed"
            else:
                managed_status = None

            manageable = _resolve_script(name) is not None
            result.append(
                {
                    "name": name,
                    "role": cfg.get("role", ""),
                    "base_url": base_url,
                    "model_name": cfg.get("model_name", name),
                    "reachable": reachable,
                    "manageable": manageable,
                    "managed_status": managed_status,
                    # True while a stop_engine() call is in flight (SIGTERM sent, process
                    # hasn't exited yet) - lets the UI keep polling through the shutdown
                    # window instead of only through the startup one.
                    "stopping": alive and engine.stopped_intentionally,
                    "can_start": manageable and managed_status != "running" and not reachable,
                    "can_stop": managed_status == "running" and not (alive and engine.stopped_intentionally),
                    "log_tail": list(engine.log_lines)[-40:] if engine is not None else [],
                }
            )
    return result
