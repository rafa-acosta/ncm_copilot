"""CLI-level tests for main.py: single-device (regression) and batch mode."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from main import main

REPO_ROOT = Path(__file__).parent.parent
CONTROLS_PATH = REPO_ROOT / "controls.yaml"
GOLDEN_CONFIG_PATH = REPO_ROOT / "samples" / "golden_config.txt"
DEVICE_CONFIG_PATH = REPO_ROOT / "samples" / "device_config.txt"

# A minimal, fully-compliant-ish device config used to produce a "clean" device
# in batch fixtures, distinct from the deliberately-noncompliant sample device.
_CLEAN_DEVICE_CONFIG = (REPO_ROOT / "samples" / "golden_config.txt").read_text(encoding="utf-8")


def _make_device_dir(tmp_path: Path) -> Path:
    device_dir = tmp_path / "devices"
    device_dir.mkdir()
    (device_dir / "rtr01.txt").write_text(DEVICE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (device_dir / "rtr02.txt").write_text(DEVICE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (device_dir / "rtr03_clean.txt").write_text(_CLEAN_DEVICE_CONFIG, encoding="utf-8")
    return device_dir


def test_single_device_mode_still_works_unchanged(tmp_path):
    output_dir = tmp_path / "reports"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--device-config", str(DEVICE_CONFIG_PATH),
            "--golden-config", str(GOLDEN_CONFIG_PATH),
            "--controls", str(CONTROLS_PATH),
            "--output-dir", str(output_dir),
            "--formats", "html",
        ],
    )
    assert result.exit_code == 1  # the sample device config has known FAILs
    assert (output_dir / "report.html").exists()
    assert not (output_dir / "fleet_report.html").exists()


def test_neither_flag_is_a_usage_error(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--golden-config", str(GOLDEN_CONFIG_PATH),
            "--controls", str(CONTROLS_PATH),
            "--output-dir", str(tmp_path / "reports"),
        ],
    )
    assert result.exit_code != 0
    assert "exactly one" in result.output.lower()


def test_both_flags_is_a_usage_error(tmp_path):
    device_dir = _make_device_dir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--device-config", str(DEVICE_CONFIG_PATH),
            "--device-config-dir", str(device_dir),
            "--golden-config", str(GOLDEN_CONFIG_PATH),
            "--controls", str(CONTROLS_PATH),
            "--output-dir", str(tmp_path / "reports"),
        ],
    )
    assert result.exit_code != 0
    assert "exactly one" in result.output.lower()


def test_batch_mode_produces_per_device_and_fleet_reports(tmp_path):
    device_dir = _make_device_dir(tmp_path)
    output_dir = tmp_path / "reports"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--device-config-dir", str(device_dir),
            "--golden-config", str(GOLDEN_CONFIG_PATH),
            "--controls", str(CONTROLS_PATH),
            "--output-dir", str(output_dir),
            "--formats", "html",
        ],
    )

    assert result.exit_code == 1  # rtr01/rtr02 have known FAILs
    for name in ("rtr01", "rtr02", "rtr03_clean"):
        assert (output_dir / name / "report.html").exists()
    assert (output_dir / "fleet_report.html").exists()
    assert "rtr01: " in result.output
    assert "total FAIL across the fleet" in result.output


def test_batch_mode_empty_directory_is_a_usage_error(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--device-config-dir", str(empty_dir),
            "--golden-config", str(GOLDEN_CONFIG_PATH),
            "--controls", str(CONTROLS_PATH),
            "--output-dir", str(tmp_path / "reports"),
        ],
    )
    assert result.exit_code != 0
    assert "no *.txt" in result.output.lower()


def test_batch_mode_pdf_format(tmp_path):
    device_dir = _make_device_dir(tmp_path)
    output_dir = tmp_path / "reports"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--device-config-dir", str(device_dir),
            "--golden-config", str(GOLDEN_CONFIG_PATH),
            "--controls", str(CONTROLS_PATH),
            "--output-dir", str(output_dir),
            "--formats", "pdf",
        ],
    )
    assert result.exit_code == 1
    assert (output_dir / "rtr01" / "report.pdf").exists()
    assert not (output_dir / "rtr01" / "report.html").exists()
    assert (output_dir / "fleet_report.pdf").exists()
    assert not (output_dir / "fleet_report.html").exists()
