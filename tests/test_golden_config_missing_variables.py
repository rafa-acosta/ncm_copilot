"""Unit tests for missing-variable handling: <MISSING:...> markers and CLI --strict."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from click.testing import CliRunner

from golden_config_builder import GoldenConfigBuilder
from golden_config_main import main as golden_config_main

REPO_ROOT = Path(__file__).parent.parent
CONTROLS_PATH = REPO_ROOT / "controls.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "device_vars.schema.json"
SAMPLE_DEVICE_VARS = json.loads((REPO_ROOT / "device_vars.json").read_text(encoding="utf-8"))
ORDER_PATH = REPO_ROOT / "render_order.yaml"


def _write_vars(tmp_path: Path, device_vars: dict) -> Path:
    path = tmp_path / "device_vars.json"
    path.write_text(json.dumps(device_vars), encoding="utf-8")
    return path


def test_missing_scalar_variable_renders_marker_and_is_recorded(tmp_path):
    device_vars = copy.deepcopy(SAMPLE_DEVICE_VARS)
    del device_vars["control_00002"]["company_name"]
    vars_path = _write_vars(tmp_path, device_vars)

    builder = GoldenConfigBuilder(CONTROLS_PATH, vars_path, order_path=ORDER_PATH, schema_path=SCHEMA_PATH)
    text = builder.build()

    assert "<MISSING:company_name>" in text
    assert "control_00002.company_name" in builder.missing


def test_missing_tacacs_servers_entirely(tmp_path):
    device_vars = copy.deepcopy(SAMPLE_DEVICE_VARS)
    del device_vars["control_00004"]["tacacs_servers"]
    vars_path = _write_vars(tmp_path, device_vars)

    builder = GoldenConfigBuilder(CONTROLS_PATH, vars_path, order_path=ORDER_PATH, schema_path=SCHEMA_PATH)
    text = builder.build()

    assert "<MISSING:tacacs_servers>" in text
    assert "control_00004.tacacs_servers" in builder.missing


def test_missing_single_field_within_a_tacacs_server(tmp_path):
    device_vars = copy.deepcopy(SAMPLE_DEVICE_VARS)
    del device_vars["control_00004"]["tacacs_servers"][1]["key"]
    vars_path = _write_vars(tmp_path, device_vars)

    builder = GoldenConfigBuilder(CONTROLS_PATH, vars_path, order_path=ORDER_PATH, schema_path=SCHEMA_PATH)
    text = builder.build()

    assert "<MISSING:tacacs_servers[1].key>" in text
    assert "control_00004.tacacs_servers[1].key" in builder.missing
    # the untouched server's key must still render normally
    assert device_vars["control_00004"]["tacacs_servers"][0]["key"] in text


def test_cli_strict_mode_aborts_and_writes_nothing(tmp_path):
    device_vars = copy.deepcopy(SAMPLE_DEVICE_VARS)
    del device_vars["control_00002"]["company_name"]
    vars_path = _write_vars(tmp_path, device_vars)
    output_path = tmp_path / "golden_config.txt"

    runner = CliRunner()
    result = runner.invoke(
        golden_config_main,
        [
            "--controls", str(CONTROLS_PATH),
            "--device-vars", str(vars_path),
            "--output", str(output_path),
            "--order", str(ORDER_PATH),
            "--strict",
        ],
    )

    assert result.exit_code != 0
    assert not output_path.exists()
    assert "company_name" in result.output


def test_cli_non_strict_writes_file_with_marker_and_summary(tmp_path):
    device_vars = copy.deepcopy(SAMPLE_DEVICE_VARS)
    del device_vars["control_00002"]["company_name"]
    vars_path = _write_vars(tmp_path, device_vars)
    output_path = tmp_path / "golden_config.txt"

    runner = CliRunner()
    result = runner.invoke(
        golden_config_main,
        [
            "--controls", str(CONTROLS_PATH),
            "--device-vars", str(vars_path),
            "--output", str(output_path),
            "--order", str(ORDER_PATH),
        ],
    )

    assert result.exit_code == 0
    assert output_path.exists()
    assert "<MISSING:company_name>" in output_path.read_text(encoding="utf-8")
    assert "unresolved" in result.output.lower()


def test_cli_full_sample_vars_produce_clean_output(tmp_path):
    output_path = tmp_path / "golden_config.txt"
    runner = CliRunner()
    result = runner.invoke(
        golden_config_main,
        [
            "--controls", str(CONTROLS_PATH),
            "--device-vars", str(REPO_ROOT / "device_vars.json"),
            "--output", str(output_path),
            "--order", str(ORDER_PATH),
            "--strict",
        ],
    )
    assert result.exit_code == 0
    assert output_path.exists()
    assert "<MISSING:" not in output_path.read_text(encoding="utf-8")
