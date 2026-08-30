"""Unit tests for run_archive.py."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from run_archive import new_run_dir, refresh_latest


def test_new_run_dir_creates_timestamped_subdir(tmp_path):
    when = datetime(2026, 8, 27, 14, 32, 5)
    run_dir = new_run_dir(tmp_path, when=when)
    assert run_dir == tmp_path / "20260827-143205"
    assert run_dir.is_dir()


def test_new_run_dir_disambiguates_same_second_collision(tmp_path):
    when = datetime(2026, 8, 27, 14, 32, 5)
    first = new_run_dir(tmp_path, when=when)
    second = new_run_dir(tmp_path, when=when)
    third = new_run_dir(tmp_path, when=when)
    assert first != second != third
    assert second.name == "20260827-143205-2"
    assert third.name == "20260827-143205-3"
    assert first.is_dir() and second.is_dir() and third.is_dir()


def test_new_run_dir_creates_root_if_missing(tmp_path):
    root = tmp_path / "does" / "not" / "exist"
    run_dir = new_run_dir(root, when=datetime(2026, 1, 1, 0, 0, 0))
    assert run_dir.is_dir()


def test_refresh_latest_mirrors_run_dir_contents(tmp_path):
    root = tmp_path
    run_dir = new_run_dir(root, when=datetime(2026, 1, 1, 0, 0, 0))
    (run_dir / "report.html").write_text("run one", encoding="utf-8")
    (run_dir / "sub").mkdir()
    (run_dir / "sub" / "report.html").write_text("nested", encoding="utf-8")

    latest = refresh_latest(run_dir, root)

    assert latest == root / "latest"
    assert (latest / "report.html").read_text(encoding="utf-8") == "run one"
    assert (latest / "sub" / "report.html").read_text(encoding="utf-8") == "nested"


def test_refresh_latest_replaces_previous_latest_completely(tmp_path):
    root = tmp_path
    run1 = new_run_dir(root, when=datetime(2026, 1, 1, 0, 0, 0))
    (run1 / "report.html").write_text("first", encoding="utf-8")
    (run1 / "only_in_first.html").write_text("stale", encoding="utf-8")
    refresh_latest(run1, root)

    run2 = new_run_dir(root, when=datetime(2026, 1, 2, 0, 0, 0))
    (run2 / "report.html").write_text("second", encoding="utf-8")
    refresh_latest(run2, root)

    latest = root / "latest"
    assert (latest / "report.html").read_text(encoding="utf-8") == "second"
    assert not (latest / "only_in_first.html").exists()  # stale file from run1 must be gone


def test_refresh_latest_never_touches_the_timestamped_archive(tmp_path):
    root = tmp_path
    run1 = new_run_dir(root, when=datetime(2026, 1, 1, 0, 0, 0))
    (run1 / "report.html").write_text("first", encoding="utf-8")
    refresh_latest(run1, root)

    run2 = new_run_dir(root, when=datetime(2026, 1, 2, 0, 0, 0))
    (run2 / "report.html").write_text("second", encoding="utf-8")
    refresh_latest(run2, root)

    # run1's own archived copy must still exist, untouched, after run2 refreshed latest/
    assert (run1 / "report.html").read_text(encoding="utf-8") == "first"
