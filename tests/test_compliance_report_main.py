"""CLI-level tests for compliance_report_main.py."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import compliance_report_main
from compliance_report_main import main

REPO_ROOT = Path(__file__).parent.parent
CONTROLS_PATH = REPO_ROOT / "controls.yaml"
GOLDEN_CONFIG_PATH = REPO_ROOT / "samples" / "golden_config.txt"
DEVICE_CONFIG_PATH = REPO_ROOT / "samples" / "device_config.txt"


def _real_report_path(tmp_path: Path) -> Path:
    """Generate a real report.json via Tool 1 for use as this tool's input.

    Written under a distinctly-named folder (not "reports") - this tool's own
    default --output-dir is also "reports", and several tests below chdir
    into `tmp_path`, so sharing the name would make Tool 1's own archive run
    collide with the run this test is actually trying to isolate and assert on.
    """
    from click.testing import CliRunner as _Runner

    from main import main as compliance_checker_main

    output_dir = tmp_path / "tool1_input_reports"
    _Runner().invoke(
        compliance_checker_main,
        [
            "--device-config", str(DEVICE_CONFIG_PATH),
            "--golden-config", str(GOLDEN_CONFIG_PATH),
            "--controls", str(CONTROLS_PATH),
            "--output-dir", str(output_dir),
            "--formats", "json",
        ],
    )
    return output_dir / "latest" / "report.json"


def test_cli_produces_md_and_pdf(tmp_path):
    report_path = _real_report_path(tmp_path)
    out_pdf = tmp_path / "out.pdf"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--report", str(report_path),
            "--controls", str(CONTROLS_PATH),
            "--device-role", "edge-router",
            "--out", str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()
    assert (tmp_path / "out.md").exists()  # --out-md defaults to --out's stem + .md
    assert "17 controls" in result.output


def test_cli_default_output_archives_and_refreshes_latest(tmp_path, monkeypatch):
    report_path = _real_report_path(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--report", str(report_path),
            "--controls", str(CONTROLS_PATH),
            "--device-role", "edge-router",
        ],
    )
    assert result.exit_code == 0, result.output
    output_dir = tmp_path / "compliance_reports"
    assert (output_dir / "latest" / "report.pdf").exists()
    assert (output_dir / "latest" / "report.md").exists()
    run_dirs = [p for p in output_dir.iterdir() if p.is_dir() and p.name != "latest"]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "report.pdf").exists()


def test_cli_explicit_out_bypasses_archive_entirely(tmp_path):
    report_path = _real_report_path(tmp_path)
    out_pdf = tmp_path / "standalone.pdf"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--report", str(report_path),
            "--controls", str(CONTROLS_PATH),
            "--device-role", "edge-router",
            "--out", str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()
    assert not (tmp_path / "compliance_reports").exists()  # no archive folder created at all


def test_cli_out_md_explicit_override(tmp_path):
    report_path = _real_report_path(tmp_path)
    out_pdf = tmp_path / "out.pdf"
    out_md = tmp_path / "custom_name.md"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--report", str(report_path),
            "--controls", str(CONTROLS_PATH),
            "--device-role", "core-switch",
            "--out", str(out_pdf),
            "--out-md", str(out_md),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_md.exists()


def test_cli_invalid_report_json_fails_loudly(tmp_path):
    bad_report = tmp_path / "bad_report.json"
    bad_report.write_text('{"device_name": "x", "generated_at": "2026-01-01T00:00:00", "results": [{"control_id": "c1", "title": "t", "status": "WEIRD_STATUS", "severity": "High", "risk": "r", "evidence_found": "e", "remediation": "m"}]}', encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--report", str(bad_report),
            "--controls", str(CONTROLS_PATH),
            "--device-role", "edge-router",
            "--out", str(tmp_path / "out.pdf"),
        ],
    )
    assert result.exit_code != 0
    assert not (tmp_path / "out.pdf").exists()
    assert "not a valid Compliance Checker report" in result.output


def test_cli_risk_statement_failure_without_llm_polish_fails_loudly(tmp_path, monkeypatch):
    report_path = _real_report_path(tmp_path)

    # Rig a control's risk text to fail validation, without touching the real controls.yaml.
    import yaml as _yaml

    controls = _yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))
    for c in controls:
        if c["control_id"] == "control_00004":
            c["risk"] = "This is important because it is important to note that things could break."
    rigged_controls_path = tmp_path / "rigged_controls.yaml"
    rigged_controls_path.write_text(_yaml.safe_dump(controls), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--report", str(report_path),
            "--controls", str(rigged_controls_path),
            "--device-role", "edge-router",
            "--out", str(tmp_path / "out.pdf"),
        ],
    )
    assert result.exit_code != 0
    assert not (tmp_path / "out.pdf").exists()
    assert "control_00004" in result.output


def test_cli_llm_polish_fixes_a_failing_risk_statement(tmp_path, monkeypatch):
    from types import SimpleNamespace

    report_path = _real_report_path(tmp_path)

    import yaml as _yaml

    controls = _yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))
    for c in controls:
        if c["control_id"] == "control_00004":
            c["risk"] = "This is important because it is important to note that things could break."
    rigged_controls_path = tmp_path / "rigged_controls.yaml"
    rigged_controls_path.write_text(_yaml.safe_dump(controls), encoding="utf-8")

    class _FakeLLMClient:
        def __init__(self, *a, **k):
            pass

        def polish_statement(self, original, violations):
            return "TACACS failure forces reliance on local accounts."

    monkeypatch.setattr(compliance_report_main, "select_backend", lambda *a, **k: ("phi4_mini", "http://fake/v1", "phi-4-mini"))
    monkeypatch.setattr(compliance_report_main, "LLMClient", _FakeLLMClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--report", str(report_path),
            "--controls", str(rigged_controls_path),
            "--device-role", "edge-router",
            "--out", str(tmp_path / "out.pdf"),
            "--llm-polish",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out.pdf").exists()
