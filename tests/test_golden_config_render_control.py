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


def test_control_00008_renders_its_own_acl_block(tmp_path):
    # control_00008 (ACL for VTY) is a standalone existence-only check now - it
    # no longer targets 'line vty' at all, so it's no longer subsumed by
    # control_00014 and renders its own real ACL block, via the same
    # {% for %}-loop special case as control_00004's TACACS servers (see
    # GoldenConfigBuilder._render_acl), matching the real corporate ACL
    # (NCM Configuration Script.txt) rather than a placeholder.
    device_vars = {
        "control_00008": {
            "acl_name": "ACME_VTY_MGMT_ACL",
            "acl_rules": [
                "remark deny Cloudflare ranges",
                "deny ip any 173.245.48.0 0.0.15.255",
                "permit tcp any any eq 22",
                "deny ip any any log",
            ],
        }
    }
    builder = _builder(device_vars, tmp_path)
    result = builder.render_control("control_00008")
    assert "ip access-list extended ACME_VTY_MGMT_ACL" in result.text
    assert "deny ip any 173.245.48.0 0.0.15.255" in result.text
    assert "permit tcp any any eq 22" in result.text
    assert "deny ip any any log" in result.text
    assert "line vty" not in result.text
    assert result.missing == []


def test_control_00007_renders_normally(tmp_path):
    # control_00007 (Global password encryption) used to be an intentional gap
    # in controls.yaml (source doc jump 00006 -> 00008); it's a real, fully
    # renderable control now, substituted via the generic <word> engine like
    # any other control.
    builder = _builder({"control_00007": {"device_master_key": "test_master_key"}}, tmp_path)
    result = builder.render_control("control_00007")
    assert result is not None
    assert "key config-key password-encrypt test_master_key" in result.text
    assert "password encryption aes" in result.text
    assert result.missing == []


def test_ssh_render_drops_destructive_zeroize_line(tmp_path):
    # 'crypto key zeroize rsa' is a documented one-time bootstrap step, but
    # golden_config.txt is a reusable baseline that may be re-applied to an
    # already-provisioned device - zeroizing there would delete working RSA
    # keys and break SSH. The renderer must drop it while still emitting the
    # regeneration + ip ssh lines. hostname/domain-name are NOT rendered here
    # (control_00001/00002 own those lines - see NCM Configuration Script.txt),
    # so control_00006's device_vars carries only its own ssh_* fields.
    device_vars = {
        "control_00006": {
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
