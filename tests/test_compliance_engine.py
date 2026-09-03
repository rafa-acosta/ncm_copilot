"""Unit tests for compliance_engine.ControlEvaluator."""

from __future__ import annotations

from pathlib import Path

import yaml

from compliance_engine import STATUS_EXCEPTION, STATUS_FAIL, STATUS_MANUAL_REVIEW, STATUS_PASS, ControlEvaluator

REPO_ROOT = Path(__file__).parent.parent
ALL_CONTROLS = {c["control_id"]: c for c in yaml.safe_load((REPO_ROOT / "controls.yaml").read_text(encoding="utf-8"))}
GOLDEN_TEXT = (REPO_ROOT / "samples" / "golden_config.txt").read_text(encoding="utf-8")


def evaluate(control_id: str, device_text: str, golden_text: str = GOLDEN_TEXT, exceptions=None):
    evaluator = ControlEvaluator(exceptions=exceptions)
    return evaluator.evaluate_control(ALL_CONTROLS[control_id], device_text, golden_text)


# ---- control_00001: Hostname ------------------------------------------------

def test_hostname_matching_convention_passes():
    result = evaluate("control_00001", "hostname ACME_USA_ROUTER_INTERNET_BLN_01\n")
    assert result.status == STATUS_PASS


def test_hostname_generic_fails():
    result = evaluate("control_00001", "hostname router\n")
    assert result.status == STATUS_FAIL
    assert any("generic" in d for d in result.details)


def test_hostname_missing_naming_parts_fails():
    result = evaluate("control_00001", "hostname ACME-ROUTER\n")
    assert result.status == STATUS_FAIL
    assert any("convention" in d for d in result.details)


def test_hostname_absent_fails():
    result = evaluate("control_00001", "ip domain name acme.com\n")
    assert result.status == STATUS_FAIL


# ---- control_00003: AAA block completeness ----------------------------------

_COMPLETE_AAA_BLOCK = "\n".join(
    [
        "aaa new-model",
        "aaa authentication password-prompt LOCAL_PASS:",
        "aaa authentication username-prompt LOCAL_USER:",
        "aaa authentication login default group ACME_GRP local",
        "aaa authentication enable default group ACME_GRP enable",
        "aaa authorization config-commands",
        "aaa authorization exec default group ACME_GRP local if-authenticated",
        "aaa authorization commands 1 default group ACME_GRP if-authenticated",
        "aaa authorization commands 15 default group ACME_GRP if-authenticated",
        "aaa accounting exec default start-stop group ACME_GRP",
        "aaa accounting commands 1 default start-stop group ACME_GRP",
        "aaa accounting commands 15 default start-stop group ACME_GRP",
    ]
)


def test_aaa_complete_block_passes():
    result = evaluate("control_00003", _COMPLETE_AAA_BLOCK)
    assert result.status == STATUS_PASS


def test_aaa_missing_commands_fails():
    device = "aaa new-model\naaa authentication login default group ACME_GRP local\n"
    result = evaluate("control_00003", device)
    assert result.status == STATUS_FAIL
    assert len(result.details) > 1


def test_aaa_inconsistent_tacacs_group_fails():
    device = _COMPLETE_AAA_BLOCK.replace(
        "aaa authentication enable default group ACME_GRP enable",
        "aaa authentication enable default group OTHER_GRP enable",
    )
    result = evaluate("control_00003", device)
    assert result.status == STATUS_FAIL
    assert any("inconsistent" in d.lower() for d in result.details)


# ---- control_00014: VTY ACL mismatch detection ------------------------------

def test_vty_restrictive_acl_passes():
    device = "\n".join(
        [
            "ip access-list extended MGMT_ACL",
            " permit tcp 10.0.0.0 0.0.0.255 any eq 22",
            " deny ip any any log",
            "line con 0",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class MGMT_ACL in",
            " login local",
            " exec-timeout 10 0",
            " transport input ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_PASS


def test_vty_permissive_acl_fails():
    device = "\n".join(
        [
            "ip access-list extended OPEN_ACL",
            " permit tcp any any eq 22",
            " permit tcp any any eq telnet",
            "line con 0",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class OPEN_ACL in",
            " login local",
            " exec-timeout 10 0",
            " transport input ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_FAIL
    assert any("permissive" in d.lower() for d in result.details)


# ---- control_00011: SNMP dual-protocol detection ----------------------------

_COMPLIANT_SNMP = "\n".join(
    [
        "snmp-server group ACME_GRP v3 priv",
        "snmp-server user acme_user ACME_GRP v3 auth sha AAAA priv aes 128 BBBB",
        "snmp-server host 1.2.3.4 version 3 priv acme_user",
        "snmp-server enable traps",
    ]
)


def test_snmp_v3_only_passes():
    result = evaluate("control_00011", _COMPLIANT_SNMP)
    assert result.status == STATUS_PASS


def test_snmp_v2c_coexisting_with_v3_fails():
    device = "snmp-server community public RO\n" + _COMPLIANT_SNMP
    result = evaluate("control_00011", device)
    assert result.status == STATUS_FAIL
    assert any("coexist" in d.lower() for d in result.details)


def test_snmp_missing_entirely_fails():
    result = evaluate("control_00011", "hostname X\n")
    assert result.status == STATUS_FAIL
    assert len(result.details) >= 4


# ---- additional acceptance-criteria findings --------------------------------

def test_tacacs_type7_key_fails():
    device = "\n".join(
        [
            "aaa new-model",
            "tacacs server ACME_TACACS_01",
            " key 7 0123456789",
            " timeout 5",
            "tacacs server ACME_TACACS_02",
            " key 7 0123456789",
            " timeout 5",
            "aaa group server tacacs+ ACME_TACACS_SERVER_GROUP",
            " server name ACME_TACACS_01",
            " server name ACME_TACACS_02",
            " ip tacacs source-interface Loopback0",
        ]
    )
    result = evaluate("control_00004", device)
    assert result.status == STATUS_FAIL
    assert any("type 7" in d.lower() for d in result.details)


def test_tacacs_type6_key_passes_that_condition():
    device = "\n".join(
        [
            "aaa new-model",
            "tacacs server ACME_TACACS_01",
            " address ipv4 192.168.100.100",
            " key 6 encryptedvalue",
            " timeout 5",
            "tacacs server ACME_TACACS_02",
            " address ipv4 192.168.100.101",
            " key 6 encryptedvalue",
            " timeout 5",
            "aaa group server tacacs+ ACME_TACACS_SERVER_GROUP",
            " server name ACME_TACACS_01",
            " server name ACME_TACACS_02",
            " ip tacacs source-interface Loopback0",
        ]
    )
    result = evaluate("control_00004", device)
    assert result.status == STATUS_PASS


def test_tacacs_missing_address_fails():
    device = "\n".join(
        [
            "aaa new-model",
            "tacacs server ACME_TACACS_01",
            " key 6 encryptedvalue",
            " timeout 5",
            "tacacs server ACME_TACACS_02",
            " address ipv4 192.168.100.101",
            " key 6 encryptedvalue",
            " timeout 5",
            "aaa group server tacacs+ ACME_TACACS_SERVER_GROUP",
            " server name ACME_TACACS_01",
            " server name ACME_TACACS_02",
            " ip tacacs source-interface Loopback0",
        ]
    )
    result = evaluate("control_00004", device)
    assert result.status == STATUS_FAIL
    assert any("address ipv4" in d for d in result.details)


def test_tacacs_duplicate_address_fails():
    device = "\n".join(
        [
            "aaa new-model",
            "tacacs server ACME_TACACS_01",
            " address ipv4 192.168.100.100",
            " key 6 encryptedvalue",
            " timeout 5",
            "tacacs server ACME_TACACS_02",
            " address ipv4 192.168.100.100",
            " key 6 encryptedvalue",
            " timeout 5",
            "aaa group server tacacs+ ACME_TACACS_SERVER_GROUP",
            " server name ACME_TACACS_01",
            " server name ACME_TACACS_02",
            " ip tacacs source-interface Loopback0",
        ]
    )
    result = evaluate("control_00004", device)
    assert result.status == STATUS_FAIL
    assert any("same address" in d for d in result.details)


def test_inconsistent_password_hash_types_fails():
    device = "\n".join(
        [
            "username admin privilege 15 secret 9 $9$abc",
            "username nimda privilege 15 secret 5 $1$def",
            "enable secret 9 $9$xyz",
        ]
    )
    result = evaluate("control_00005", device)
    assert result.status == STATUS_FAIL
    assert any("inconsistent" in d.lower() for d in result.details)


def test_ntp_unauthenticated_fails():
    result = evaluate("control_00009", "ntp server 1.2.3.4\n")
    assert result.status == STATUS_FAIL
    assert any("authentication" in d.lower() for d in result.details)


def test_ntp_authenticated_with_prefer_passes():
    device = "\n".join(
        [
            "ntp authentication-key 1 md5 abc 7",
            "ntp trusted-key 1",
            "ntp authenticate",
            "ntp server 10.10.10.100 prefer",
            "ntp server 20.20.20.100",
        ]
    )
    result = evaluate("control_00009", device)
    assert result.status == STATUS_PASS


def test_missing_copp_fails():
    result = evaluate("control_00016", "control-plane\nno ip http server\nno ip http secure-server\nservice password-encryption\n")
    assert result.status == STATUS_FAIL
    assert any("policing" in d.lower() or "service-policy" in d.lower() for d in result.details)


def test_copp_present_passes_that_condition():
    device = "\n".join(
        [
            "no ip http server",
            "no ip http secure-server",
            "service password-encryption",
            "control-plane",
            " service-policy input COPP_POLICY_ACME",
        ]
    )
    result = evaluate("control_00016", device)
    assert result.status == STATUS_PASS


# ---- exceptions and manual review -------------------------------------------

def test_exception_overrides_fail_status():
    result = evaluate(
        "control_00001",
        "hostname router\n",
        exceptions={"control_00001": "Legacy device, rename scheduled for next maintenance window."},
    )
    assert result.status == STATUS_EXCEPTION
    assert any("Exception granted" in d for d in result.details)


def test_exception_does_not_apply_when_passing():
    result = evaluate(
        "control_00001",
        "hostname ACME_USA_ROUTER_INTERNET_BLN_01\n",
        exceptions={"control_00001": "Not needed here."},
    )
    assert result.status == STATUS_PASS


def test_banner_present_passes():
    result = evaluate("control_00012", "banner motd $ hi $\n")
    assert result.status == STATUS_PASS


def test_banner_absent_fails():
    result = evaluate("control_00012", "hostname ACME_USA_ROUTER_INTERNET_BLN_01\n")
    assert result.status == STATUS_FAIL
    assert any("banner motd" in d for d in result.details)


def test_manual_review_fallback_used_only_when_no_checker_exists():
    # control_00012 has both a checker AND manual_review: true in the real
    # controls.yaml - the checker wins (see the two tests above). This
    # exercises the other branch directly: a control with manual_review: true
    # and no _check_control_XXXXX method still falls back to MANUAL_REVIEW.
    control = {
        "control_id": "control_09999", "title": "Fixture", "severity": "Low",
        "risk": "x", "remediation": "x", "evidence": "x", "manual_review": True,
    }
    evaluator = ControlEvaluator()
    result = evaluator.evaluate_control(control, "hostname x\n", GOLDEN_TEXT)
    assert result.status == STATUS_MANUAL_REVIEW
