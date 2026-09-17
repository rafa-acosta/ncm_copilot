"""TestClient tests for the Configuration Files API (webapp/backend/routes/configs.py)."""

from __future__ import annotations


def test_upload_list_and_delete_round_trip(webapp_client):
    client = webapp_client

    files = [
        ("files", ("router1.txt", b"hostname ROUTER1\n!\nend\n", "text/plain")),
        ("files", ("router2.txt", b"hostname ROUTER2\n!\nend\n", "text/plain")),
    ]
    resp = client.post("/api/configs/upload", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 0

    listing = client.get("/api/configs").json()
    names = {f["filename"] for f in listing}
    assert names == {"router1.txt", "router2.txt"}
    router1 = next(f for f in listing if f["filename"] == "router1.txt")
    assert router1["device_name"] == "ROUTER1"

    delete_resp = client.post("/api/configs/delete", json={"filenames": ["router1.txt"]})
    assert delete_resp.json()["deleted_count"] == 1
    assert [f["filename"] for f in client.get("/api/configs").json()] == ["router2.txt"]

    delete_all_resp = client.post("/api/configs/delete", json={"all": True})
    assert delete_all_resp.json()["deleted_count"] == 1
    assert client.get("/api/configs").json() == []


def test_upload_reports_per_file_rejection_without_dropping_good_files(webapp_client):
    client = webapp_client

    files = [
        ("files", ("good.txt", b"hostname GOOD\n!\nend\n", "text/plain")),
        ("files", ("bad.exe", b"MZ\x90\x00", "application/octet-stream")),
        ("files", ("empty.txt", b"", "text/plain")),
    ]
    resp = client.post("/api/configs/upload", files=files)
    body = resp.json()
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 2

    outcomes = {o["filename"]: o for o in body["outcomes"]}
    assert outcomes["good.txt"]["status"] == "added"
    assert outcomes["bad.exe"]["status"] == "rejected"
    assert "Only .txt" in outcomes["bad.exe"]["reason"]
    assert outcomes["empty.txt"]["status"] == "rejected"

    # The rejected .exe must never have been written to disk under any name.
    remaining = {f["filename"] for f in client.get("/api/configs").json()}
    assert remaining == {"good.txt"}


def test_upload_sanitizes_path_traversal_filename(webapp_client):
    client = webapp_client
    files = [("files", ("../../etc/passwd.txt", b"hostname X\n", "text/plain"))]
    resp = client.post("/api/configs/upload", files=files)
    body = resp.json()
    assert body["accepted_count"] == 1
    assert body["outcomes"][0]["filename"] == "passwd.txt"

    listing = client.get("/api/configs").json()
    assert [f["filename"] for f in listing] == ["passwd.txt"]


def test_read_config_text_returns_original_content_unmodified(webapp_client):
    client = webapp_client
    original = "hostname EXACT\n! comment line\nend\n"
    client.post("/api/configs/upload", files=[("files", ("exact.txt", original.encode(), "text/plain"))])
    resp = client.get("/api/configs/exact.txt/text")
    assert resp.json()["text"] == original
