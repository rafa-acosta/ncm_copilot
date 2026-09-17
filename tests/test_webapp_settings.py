"""Tests for the Settings screen's LLM engine start/stop lifecycle
(webapp/backend/services/llm_engine_service.py) and the Settings API.

Process-lifecycle tests use a tiny fake shell script instead of the real
local-llm/serve_*.sh - spawning the actual llama-server binary against a
multi-GB GGUF model is correct integration behavior (verified manually
against the real script, see documentation/WEBAPP.md) but far too slow/
GPU-bound for a unit test. What's under test here is this module's own
process bookkeeping: start/stop, log capture, and the "only one engine at a
time" conflict rules - none of that depends on what the child process
actually is.
"""

from __future__ import annotations

import time

import pytest

from webapp.backend.services import llm_engine_service


def _write_fake_script(tmp_path, name, sleep_seconds=10):
    script = tmp_path / name
    script.write_text(f"#!/usr/bin/env bash\necho hello from {name}\nsleep {sleep_seconds}\n")
    script.chmod(0o755)
    return script


@pytest.fixture(autouse=True)
def _reset_engines():
    """The service's process table is a module-level dict (like jobs.py's
    job table) - clear it before and after every test so state never leaks
    between tests, and make sure nothing is left running on failure."""
    llm_engine_service._engines.clear()
    yield
    for name, engine in list(llm_engine_service._engines.items()):
        if engine.process.poll() is None:
            try:
                llm_engine_service.stop_engine(name)
                engine.process.wait(timeout=5)
            except Exception:
                pass
    llm_engine_service._engines.clear()


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_start_and_stop_a_managed_process_lifecycle(tmp_path, monkeypatch):
    script = _write_fake_script(tmp_path, "fake_engine.sh")
    monkeypatch.setattr(llm_engine_service, "_resolve_script", lambda name: script if name == "fake_engine" else None)
    monkeypatch.setattr(
        llm_engine_service, "load_backends_registry",
        lambda: {"fake_engine": {"role": "test", "base_url": "http://127.0.0.1:1", "model_name": "fake"}},
    )
    monkeypatch.setattr(llm_engine_service, "_is_reachable", lambda base_url, timeout=2.0: False)

    llm_engine_service.start_engine("fake_engine")
    _wait_until(lambda: any("hello from fake_engine.sh" in line for line in llm_engine_service._engines["fake_engine"].log_lines))

    status = {b["name"]: b for b in llm_engine_service.get_status()}
    engine = status["fake_engine"]
    assert engine["managed_status"] == "running"
    assert engine["can_stop"] is True
    assert engine["can_start"] is False
    assert any("hello from fake_engine.sh" in line for line in engine["log_tail"])

    llm_engine_service.stop_engine("fake_engine")
    assert _wait_until(lambda: llm_engine_service._engines["fake_engine"].process.poll() is not None)

    status_after = {b["name"]: b for b in llm_engine_service.get_status()}
    assert status_after["fake_engine"]["managed_status"] == "stopped"
    assert status_after["fake_engine"]["can_start"] is True
    assert status_after["fake_engine"]["can_stop"] is False


def test_cannot_start_two_managed_engines_at_once(tmp_path, monkeypatch):
    scripts = {"engine_a": _write_fake_script(tmp_path, "a.sh"), "engine_b": _write_fake_script(tmp_path, "b.sh")}
    monkeypatch.setattr(llm_engine_service, "_resolve_script", lambda name: scripts.get(name))
    monkeypatch.setattr(
        llm_engine_service, "load_backends_registry",
        lambda: {
            "engine_a": {"role": "x", "base_url": "http://127.0.0.1:1", "model_name": "a"},
            "engine_b": {"role": "x", "base_url": "http://127.0.0.1:2", "model_name": "b"},
        },
    )
    monkeypatch.setattr(llm_engine_service, "_is_reachable", lambda base_url, timeout=2.0: False)

    llm_engine_service.start_engine("engine_a")
    _wait_until(lambda: llm_engine_service._engines["engine_a"].process.poll() is None and len(llm_engine_service._engines["engine_a"].log_lines) > 0)

    with pytest.raises(llm_engine_service.EngineError, match="engine_a"):
        llm_engine_service.start_engine("engine_b")


def test_cannot_start_when_another_backend_is_reachable_even_if_unmanaged(tmp_path, monkeypatch):
    """The conflict guard must catch an engine that's up but wasn't started
    by this module (no process handle exists for it) - the real constraint
    is VRAM, not who launched the process."""
    script_b = _write_fake_script(tmp_path, "b.sh")
    monkeypatch.setattr(llm_engine_service, "_resolve_script", lambda name: script_b if name == "engine_b" else None)
    monkeypatch.setattr(
        llm_engine_service, "load_backends_registry",
        lambda: {
            "engine_a": {"role": "x", "base_url": "http://127.0.0.1:1", "model_name": "a"},
            "engine_b": {"role": "x", "base_url": "http://127.0.0.1:2", "model_name": "b"},
        },
    )
    monkeypatch.setattr(llm_engine_service, "_is_reachable", lambda base_url, timeout=2.0: base_url.endswith(":1"))

    assert "engine_a" not in llm_engine_service._engines  # never started by this module
    with pytest.raises(llm_engine_service.EngineError, match="engine_a"):
        llm_engine_service.start_engine("engine_b")


def test_stopping_a_non_running_engine_raises():
    with pytest.raises(llm_engine_service.EngineError):
        llm_engine_service.stop_engine("nonexistent")


def test_start_raises_for_a_backend_with_no_launch_script(monkeypatch):
    monkeypatch.setattr(llm_engine_service, "_resolve_script", lambda name: None)
    with pytest.raises(llm_engine_service.EngineError, match="No managed launch script"):
        llm_engine_service.start_engine("whatever")


def test_get_status_reports_an_unreachable_unmanaged_backend_as_startable(monkeypatch):
    monkeypatch.setattr(llm_engine_service, "_resolve_script", lambda name: None)
    monkeypatch.setattr(
        llm_engine_service, "load_backends_registry",
        lambda: {"some_backend": {"role": "x", "base_url": "http://127.0.0.1:1", "model_name": "m"}},
    )
    monkeypatch.setattr(llm_engine_service, "_is_reachable", lambda base_url, timeout=2.0: False)

    status = llm_engine_service.get_status()[0]
    assert status["manageable"] is False
    assert status["can_start"] is False  # no script to launch it with
    assert status["can_stop"] is False


def test_settings_status_route_exposes_engine_control_fields(webapp_client):
    resp = webapp_client.get("/api/settings/status")
    assert resp.status_code == 200
    backends = resp.json()["backends"]
    names = {b["name"] for b in backends}
    assert names == {"qwen_coder", "phi4_mini"}  # from local-llm/config.yaml
    for b in backends:
        assert set(b) >= {
            "name", "role", "base_url", "model_name", "reachable",
            "manageable", "managed_status", "can_start", "can_stop", "log_tail",
        }


def test_start_route_rejects_unknown_backend_name(webapp_client):
    resp = webapp_client.post("/api/settings/engines/not_a_real_backend/start")
    assert resp.status_code == 409
    assert "detail" in resp.json()


def test_stop_route_rejects_a_backend_that_isnt_running(webapp_client):
    resp = webapp_client.post("/api/settings/engines/phi4_mini/stop")
    assert resp.status_code == 409
