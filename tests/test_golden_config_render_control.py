"""Unit tests for GoldenConfigBuilder.render_control."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from golden_config_builder import GoldenConfigBuilder

REPO_ROOT = Path(__file__).parent.parent
CONTROLS_PATH = REPO_ROOT / "controls.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "device_vars.schema.json"
SAMPLE_DEVICE_VARS_PATH = REPO_ROOT / "device_vars.json"


def _builder(device_vars: dict, tmp_path: Path) -> GoldenConfigBuilder:
    vars_path = tmp_path / "device_vars.json"
    vars_path.write_text(json.dumps(device_vars), encoding="utf-8")
    return GoldenConfigBuilder(
        controls_path=CONTROLS_PATH,
        device_vars_path=vars_path,
        schema_path=SCHEMA_PATH,
    )


def test_render_hostname_substitutes_value(tmp_path):
    builder = _builder({"control_00001": {"hostname": "ACME_USA_RT_INT_BLN_01"}}, tmp_path)
    result = builder.render_control("control_00001")
    assert "hostname ACME_USA_RT_INT_BLN_01" in result.text
    assert result.text.startswith("! control_00001 - Hostname")
    assert result.missing == []


def test_render_tacacs_two_servers(tmp_path):
    device_vars = {
        "control_00004": {
            "tacacs_servers": [
                {"name": "TAC01", "address": "1.1.1.1", "key": "abc", "timeout": 10},
                {"name": "TAC02", "address": "2.2.2.2", "key": "def", "timeout": 10},
            ],
            "tacacs_group_name": "GRP",
            "source_interface": "Loopback0",
        }
    }
    builder = _builder(device_vars, tmp_path)
    result = builder.render_control("control_00004")
    assert "tacacs server TAC01" in result.text
    assert "tacacs server TAC02" in result.text
    assert "address ipv4 1.1.1.1" in result.text
    assert "address ipv4 2.2.2.2" in result.text
    assert "aaa group server tacacs+ GRP" in result.text
    assert "server name TAC01" in result.text
    assert "server name TAC02" in result.text
    assert "ip tacacs source-interface Loopback0" in result.text
    assert result.missing == []


def test_render_tacacs_scales_beyond_two_servers(tmp_path):
    device_vars = {
        "control_00004": {
            "tacacs_servers": [
                {"name": f"TAC0{i}", "address": f"10.0.0.{i}", "key": "k", "timeout": 5}
                for i in range(1, 4)
            ],
            "tacacs_group_name": "GRP",
            "source_interface": "Loopback0",
        }
    }
    builder = _builder(device_vars, tmp_path)
    result = builder.render_control("control_00004")
    for i in range(1, 4):
        assert f"tacacs server TAC0{i}" in result.text
        assert f"server name TAC0{i}" in result.text
    assert result.text.count("tacacs server") == 3
    assert result.missing == []


def test_banner_renders_as_manual_review_block(tmp_path):
    builder = _builder({}, tmp_path)
    result = builder.render_control("control_00012")
    assert "MANUAL REVIEW REQUIRED" in result.text
    assert "banner motd" in result.text  # from config_example


def test_control_00016_always_renders_as_manual_review(tmp_path):
    # controls.yaml gives control_00016 a real command_template (for the Compliance
    # Checker's CoPP evaluation) - the Golden Config Creator must ignore it and always
    # emit a manual-review placeholder instead of substituting <copp_policy_name>.
    builder = _builder({}, tmp_path)
    result = builder.render_control("control_00016")
    assert "MANUAL REVIEW REQUIRED" in result.text
    assert "<copp_policy_name>" not in result.text
    assert "{{" not in result.text


def test_control_00018_always_renders_as_manual_review(tmp_path):
    builder = _builder({}, tmp_path)
    result = builder.render_control("control_00018")
    assert "MANUAL REVIEW REQUIRED" in result.text


def test_control_00008_is_subsumed_by_vty_lines_not_duplicated(tmp_path):
    # control_00008 and control_00014 both target 'line vty' - rendering both
    # independently would concatenate two separate 'line vty' stanzas into one
    # file, which real IOS running-config never does and which broke
    # self-consistency parsing (see test_golden_config_build_full.py).
    builder = _builder({}, tmp_path)
    result = builder.render_control("control_00008")
    assert "line vty" not in result.text
    assert "control_00014" in result.text


def test_control_00007_is_absent_and_skipped(tmp_path):
    builder = _builder({}, tmp_path)
    assert builder.render_control("control_00007") is None


def test_ssh_render_drops_destructive_zeroize_line(tmp_path):
    # 'crypto key zeroize rsa' is a documented one-time bootstrap step, but
    # golden_config.txt is a reusable baseline that may be re-applied to an
    # already-provisioned device - zeroizing there would delete working RSA
    # keys and break SSH. The renderer must drop it while still emitting the
    # regeneration + ip ssh lines.
    device_vars = {
        "control_00006": {
            "hostname": "RTR01",
            "domain_name": "acme.com",
            "ssh_version": 2,
            "ssh_timeout": 60,
            "ssh_auth_retries": 3,
        }
    }
    builder = _builder(device_vars, tmp_path)
    result = builder.render_control("control_00006")
    assert "zeroize" not in result.text
    assert "crypto key generate rsa modulus 2048" in result.text
    assert "ip ssh version 2" in result.text
