"""TestClient tests for the Golden Config Manager API (webapp/backend/routes/golden.py).

These exercise the real GoldenConfigBuilder/controls.yaml/device_vars.schema.json
from the repo root (only the profile *storage* directory is redirected into
tmp_path by the webapp_client fixture) - so a passing test here means the
web API genuinely round-trips through the same engine golden_config_main.py
uses, not a reimplementation of it.
"""

from __future__ import annotations


def _without_generated_timestamp(text):
    """GoldenConfigBuilder stamps a fresh '! Generated: <now>' line on every
    render - strip it before comparing two independently-rendered outputs
    for equality, or this test would be flaky across a second boundary."""
    return "\n".join(line for line in text.splitlines() if not line.startswith("! Generated:"))


def test_schema_is_derived_from_controls_yaml(webapp_client):
    schema = webapp_client.get("/api/golden/schema").json()
    assert schema, "expected at least one control form spec"
    ids = [spec["control_id"] for spec in schema]
    assert "control_00001" in ids  # Hostname
    hostname_spec = next(s for s in schema if s["control_id"] == "control_00001")
    assert hostname_spec["fields"][0]["name"] == "hostname"
    # control_00012 (Banners) is manual_review with no device_vars fields -
    # must not appear in the editable form schema.
    assert "control_00012" not in ids


def test_default_profile_is_always_present_and_read_only(webapp_client):
    profiles = webapp_client.get("/api/golden/profiles").json()
    default = next(p for p in profiles if p["profile_id"] == "__default__")
    assert default["read_only"] is True
    assert default["name"] == "Default"

    detail = webapp_client.get("/api/golden/profiles/__default__").json()
    assert detail["read_only"] is True
    assert "rendered_text" in detail and detail["rendered_text"].startswith("!")
    assert detail["missing"] == []


def test_a_seed_working_copy_profile_is_created_on_first_list(webapp_client):
    profiles = webapp_client.get("/api/golden/profiles").json()
    editable = [p for p in profiles if not p["read_only"]]
    assert len(editable) == 1
    assert editable[0]["name"] == "Working Copy"


def test_preview_does_not_persist_anything(webapp_client):
    client = webapp_client
    default_vars = client.get("/api/golden/profiles/__default__").json()["device_vars"]

    before = client.get("/api/golden/profiles").json()
    preview = client.post("/api/golden/preview", json={"device_vars": default_vars}).json()
    assert preview["valid"] is True
    assert preview["missing"] == []
    after = client.get("/api/golden/profiles").json()
    assert before == after  # no new profile, no mutation


def test_create_update_rename_duplicate_delete_profile_lifecycle(webapp_client):
    client = webapp_client
    default_vars = client.get("/api/golden/profiles/__default__").json()["device_vars"]

    created = client.post("/api/golden/profiles", json={"name": "Customer Lab", "device_vars": default_vars}).json()
    profile_id = created["profile_id"]
    default_text = client.get("/api/golden/profiles/__default__").json()["rendered_text"]
    assert _without_generated_timestamp(created["rendered_text"]) == _without_generated_timestamp(default_text)

    edited_vars = dict(default_vars)
    edited_vars["control_00001"] = {"hostname": "CUSTOMER_LAB_RT_01"}
    updated = client.put(f"/api/golden/profiles/{profile_id}", json={"device_vars": edited_vars}).json()
    assert "CUSTOMER_LAB_RT_01" in updated["rendered_text"]

    client.post(f"/api/golden/profiles/{profile_id}/rename", json={"name": "Customer Lab v2"})
    renamed = client.get(f"/api/golden/profiles/{profile_id}").json()
    assert renamed["name"] == "Customer Lab v2"

    dup = client.post(f"/api/golden/profiles/{profile_id}/duplicate", json={"new_name": "Customer Lab v2 copy"}).json()
    assert dup["profile_id"] != profile_id
    assert "CUSTOMER_LAB_RT_01" in dup["rendered_text"]

    del_resp = client.delete(f"/api/golden/profiles/{profile_id}")
    assert del_resp.json()["deleted"] is True
    assert client.get(f"/api/golden/profiles/{profile_id}").status_code == 404


def test_update_profile_rejects_invalid_shape_with_422(webapp_client):
    client = webapp_client
    default_vars = client.get("/api/golden/profiles/__default__").json()["device_vars"]
    created = client.post("/api/golden/profiles", json={"name": "Broken", "device_vars": default_vars}).json()

    bad_vars = dict(default_vars)
    bad_vars["control_00001"] = {"hostname": 12345}  # must be a string
    resp = client.put(f"/api/golden/profiles/{created['profile_id']}", json={"device_vars": bad_vars})
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_default_profile_cannot_be_saved_or_deleted(webapp_client):
    client = webapp_client
    default_vars = client.get("/api/golden/profiles/__default__").json()["device_vars"]
    resp = client.put("/api/golden/profiles/__default__", json={"device_vars": default_vars})
    assert resp.status_code == 422
    assert client.delete("/api/golden/profiles/__default__").status_code == 422


def test_restore_default_overwrites_profile_but_never_the_real_default(webapp_client):
    client = webapp_client
    default_vars = client.get("/api/golden/profiles/__default__").json()["device_vars"]
    created = client.post("/api/golden/profiles", json={"name": "Drifted", "device_vars": default_vars}).json()
    profile_id = created["profile_id"]

    drifted_vars = dict(default_vars)
    drifted_vars["control_00001"] = {"hostname": "DRIFTED_HOSTNAME"}
    client.put(f"/api/golden/profiles/{profile_id}", json={"device_vars": drifted_vars})
    assert "DRIFTED_HOSTNAME" in client.get(f"/api/golden/profiles/{profile_id}").json()["rendered_text"]

    restored = client.post(f"/api/golden/profiles/{profile_id}/restore-default").json()
    assert "DRIFTED_HOSTNAME" not in restored["rendered_text"]

    default_after = client.get("/api/golden/profiles/__default__").json()
    assert default_after["device_vars"] == default_vars  # the real default was never touched


def test_compare_with_default_is_empty_for_an_unmodified_copy_and_nonempty_after_edit(webapp_client):
    client = webapp_client
    default_vars = client.get("/api/golden/profiles/__default__").json()["device_vars"]
    created = client.post("/api/golden/profiles", json={"name": "Identical", "device_vars": default_vars}).json()
    profile_id = created["profile_id"]

    diff = client.get(f"/api/golden/profiles/{profile_id}/compare-default").json()["diff"]
    assert diff == []

    edited_vars = dict(default_vars)
    edited_vars["control_00001"] = {"hostname": "DIFFERENT_HOSTNAME"}
    client.put(f"/api/golden/profiles/{profile_id}", json={"device_vars": edited_vars})
    diff_after = client.get(f"/api/golden/profiles/{profile_id}/compare-default").json()["diff"]
    assert diff_after != []


def test_import_flags_missing_sections_without_reinterpreting_them(webapp_client):
    resp = webapp_client.post("/api/golden/import", json={"text": "not a real golden config"}).json()
    assert resp["is_valid"] is False
    assert resp["sections_found"] == []
    assert len(resp["missing_sections"]) == 15  # all 15 active controls missing
    assert resp["raw_text"] == "not a real golden config"


def test_import_recognizes_the_real_default_rendered_output_as_structurally_valid(webapp_client):
    client = webapp_client
    default_text = client.get("/api/golden/profiles/__default__").json()["rendered_text"]
    resp = client.post("/api/golden/import", json={"text": default_text}).json()
    assert resp["is_valid"] is True
    assert resp["missing_sections"] == []
    assert resp["duplicate_sections"] == []
