"""TestClient tests for the Analysis workspace API (webapp/backend/routes/analysis.py).

Runs the real Tool 1 evaluator (main._evaluate_device) against real fixture
configs from the repo's device_configs/ directory - these are read-only
inputs here, uploaded into the isolated tmp_path workspace the webapp_client
fixture provides, never mutated.
"""

from __future__ import annotations

import time
from pathlib import Path

import main as main_module

from webapp.backend import jobs
from webapp.backend.services import analysis_service

REPO_DEVICE_CONFIGS = Path(__file__).resolve().parents[1] / "device_configs"


def _wait_for_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/analysis/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish in {timeout}s")


def _upload_real_fixture(client, fixture_name):
    content = (REPO_DEVICE_CONFIGS / fixture_name).read_bytes()
    resp = client.post("/api/configs/upload", files=[("files", (fixture_name, content, "text/plain"))])
    assert resp.json()["accepted_count"] == 1


def test_run_analysis_end_to_end_against_the_real_evaluator(webapp_client):
    client = webapp_client
    _upload_real_fixture(client, "aaa_config_01.txt")
    _upload_real_fixture(client, "banner_config_01.txt")

    resp = client.post(
        "/api/analysis/run",
        json={"device_filenames": ["aaa_config_01.txt", "banner_config_01.txt"], "golden_profile_id": "__default__"},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    job = _wait_for_job(client, job_id)
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["device_count"] == 2
    assert result["analyzed_count"] == 2
    assert result["errored_devices"] == []
    assert result["golden_profile"] == "Default"

    run_id = result["run_id"]
    runs = client.get("/api/analysis/runs").json()
    assert any(r["run_id"] == run_id for r in runs)
    assert client.get("/api/analysis/runs/latest").json()["run_id"] == run_id

    devices = client.get(f"/api/analysis/runs/{run_id}/devices").json()
    assert set(devices) == {"aaa_config_01", "banner_config_01"}


def test_run_analysis_rejects_unknown_files_before_starting_a_job(webapp_client):
    resp = webapp_client.post(
        "/api/analysis/run", json={"device_filenames": ["does_not_exist.txt"], "golden_profile_id": "__default__"}
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


def test_run_analysis_requires_at_least_one_file(webapp_client):
    resp = webapp_client.post("/api/analysis/run", json={"device_filenames": [], "golden_profile_id": "__default__"})
    assert resp.status_code == 400


def test_one_unreadable_device_does_not_abort_the_rest_of_the_batch(webapp_client, monkeypatch):
    """Mirrors main.py's own per-device isolation: mock one device's
    evaluation to blow up unexpectedly and confirm the other device is still
    analyzed and the batch as a whole still reports success."""
    client = webapp_client
    _upload_real_fixture(client, "aaa_config_01.txt")
    _upload_real_fixture(client, "banner_config_01.txt")

    real_evaluate = main_module._evaluate_device

    def flaky_evaluate(device_path, *args, **kwargs):
        if "banner" in device_path.name:
            raise RuntimeError("simulated unreadable device config")
        return real_evaluate(device_path, *args, **kwargs)

    monkeypatch.setattr(analysis_service, "_evaluate_device", flaky_evaluate)

    resp = client.post(
        "/api/analysis/run",
        json={"device_filenames": ["aaa_config_01.txt", "banner_config_01.txt"], "golden_profile_id": "__default__"},
    )
    job = _wait_for_job(client, resp.json()["job_id"])
    assert job["status"] == "done"
    result = job["result"]
    assert result["device_count"] == 2
    assert result["analyzed_count"] == 1
    assert len(result["errored_devices"]) == 1
    assert "banner_config_01" in result["errored_devices"][0]

    devices = client.get(f"/api/analysis/runs/{result['run_id']}/devices").json()
    assert devices == ["aaa_config_01"]


def test_unknown_job_id_returns_404(webapp_client):
    assert webapp_client.get("/api/analysis/jobs/does-not-exist").status_code == 404


def test_get_job_reflects_the_shared_job_tracker(webapp_client):
    """Sanity check that the route reads through webapp.backend.jobs, not a
    separate/duplicated tracking mechanism."""
    job_id = jobs.start_job("analysis", total=1, work=lambda report_progress: (report_progress(0, "x"), {"ok": True})[1])
    time.sleep(0.05)
    job = webapp_client.get(f"/api/analysis/jobs/{job_id}").json()
    assert job["kind"] == "analysis"
    assert job["result"] == {"ok": True}
