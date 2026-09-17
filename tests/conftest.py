"""Shared fixtures for the webapp/ test suite.

Every webapp service module keeps its writable storage paths (uploaded
configs, golden config profiles, analysis runs, compliance history) as
module-level constants derived from `webapp/data/`. `webapp_client` redirects
all of them into a pytest tmp_path so these tests never read or write the
developer's real webapp/data/ workspace. Paths that point at the *project's*
real, read-only source of truth (controls.yaml, device_vars.json, the
schema) are deliberately left untouched - that's the actual behavior being
tested.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from webapp.backend.app import create_app
from webapp.backend.services import analysis_service, configs_service, dashboard_service, golden_service


@pytest.fixture
def webapp_client(tmp_path, monkeypatch):
    monkeypatch.setattr(configs_service, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(configs_service, "DEVICE_CONFIGS_DIR", tmp_path / "device_configs")

    monkeypatch.setattr(golden_service, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(golden_service, "PROFILES_DIR", tmp_path / "golden_profiles")

    monkeypatch.setattr(analysis_service, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(analysis_service, "RUNS_DIR", tmp_path / "runs")

    monkeypatch.setattr(dashboard_service, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(dashboard_service, "HISTORY_DIR", tmp_path / "compliance_history")

    return TestClient(create_app())
