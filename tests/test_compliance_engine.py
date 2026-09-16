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
    result = evaluate("control_00001", "hostname ACME_USA_RT_INTERNET_BLN_01\n")
    assert result.status == STATUS_PASS


def test_hostname_type_field_spelled_out_fails():
    result = evaluate("control_00001", "hostname ACME_USA_Router_INT_GOLDEN_01\n")
    assert result.status == STATUS_FAIL
    assert any("Type field" in d for d in result.details)


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
        "aaa authentication login default group ACME_TACACS_SERVER_GROUP local",
        "aaa authentication enable default group ACME_TACACS_SERVER_GROUP enable",
        "aaa authorization config-commands",
        "aaa authorization exec default group ACME_TACACS_SERVER_GROUP local if-authenticated",
        "aaa authorization commands 1 default group ACME_TACACS_SERVER_GROUP if-authenticated",
        "aaa authorization commands 15 default group ACME_TACACS_SERVER_GROUP if-authenticated",
        "aaa accounting exec default start-stop group ACME_TACACS_SERVER_GROUP",
        "aaa accounting commands 1 default start-stop group ACME_TACACS_SERVER_GROUP",
        "aaa accounting commands 15 default start-stop group ACME_TACACS_SERVER_GROUP",
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
        "aaa authentication enable default group ACME_TACACS_SERVER_GROUP enable",
        "aaa authentication enable default group OTHER_GRP enable",
    )
    result = evaluate("control_00003", device)
    assert result.status == STATUS_FAIL
    assert any("inconsistent" in d.lower() for d in result.details)


def test_aaa_group_mismatch_vs_golden_fails():
    device = _COMPLETE_AAA_BLOCK.replace("ACME_TACACS_SERVER_GROUP", "ACME_GRP")
    result = evaluate("control_00003", device)
    assert result.status == STATUS_FAIL
    assert any("does not match" in d.lower() for d in result.details)


# ---- control_00014: VTY Lines -------------------------------------------------
# ACL content validation lives in control_00008 now - this control only checks
# that VTY actually binds to a real, existing ACL via 'access-class ... in'.

def test_vty_bound_to_existing_acl_passes():
    device = "\n".join(
        [
            "ip access-list extended MGMT_ACL",
            " permit tcp 10.0.0.0 0.0.0.255 any eq 22",
            " deny ip any any log",
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class MGMT_ACL in",
            " password 0123456789",
            " login authentication default",
            " exec-timeout 10 0",
            " transport input ssh",
            " transport output ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_PASS


def test_vty_login_local_instead_of_authentication_default_fails():
    device = "\n".join(
        [
            "ip access-list extended MGMT_ACL",
            " deny ip any any log",
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class MGMT_ACL in",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            " transport input ssh",
            " transport output ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_FAIL
    assert any("login authentication default" in d for d in result.details)


def test_vty_access_class_missing_in_keyword_fails():
    device = "\n".join(
        [
            "ip access-list extended MGMT_ACL",
            " deny ip any any log",
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class MGMT_ACL",
            " password 0123456789",
            " login authentication default",
            " exec-timeout 10 0",
            " transport input ssh",
            " transport output ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_FAIL
    assert any("'in' direction keyword" in d for d in result.details)


def test_vty_referenced_acl_not_found_fails():
    device = "\n".join(
        [
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class GHOST_ACL in",
            " password 0123456789",
            " login authentication default",
            " exec-timeout 10 0",
            " transport input ssh",
            " transport output ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_FAIL
    assert any("GHOST_ACL' referenced by access-class was not found" in d for d in result.details)


def test_vty_transport_output_telnet_fails():
    device = "\n".join(
        [
            "ip access-list extended MGMT_ACL",
            " deny ip any any log",
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class MGMT_ACL in",
            " password 0123456789",
            " login authentication default",
            " exec-timeout 10 0",
            " transport input ssh",
            " transport output telnet",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_FAIL
    assert any("transport output" in d for d in result.details)


def test_vty_multiple_ranges_each_evaluated_independently():
    # A device may legitimately split VTY lines across multiple ranges
    # (e.g. 'line vty 0 4' + 'line vty 5 15') - every range must independently
    # carry the required policy; one compliant range doesn't excuse another.
    device = "\n".join(
        [
            "ip access-list extended MGMT_ACL",
            " deny ip any any log",
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 4",
            " access-class MGMT_ACL in",
            " password 0123456789",
            " login authentication default",
            " exec-timeout 10 0",
            " transport input ssh",
            " transport output ssh",
            "line vty 5 15",
            " access-class MGMT_ACL in",
            " password 0123456789",
            " exec-timeout 10 0",
            " transport input ssh",
            " transport output ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_FAIL
    assert any("'line vty 5 15': 'login authentication default' is missing" in d for d in result.details)
    assert not any("line vty 0 4" in d for d in result.details)


def test_vty_exec_timeout_disabled_fails():
    # 'exec-timeout 0 0' is a special Cisco IOS value meaning "never time
    # out" - presence-only checking treats it as satisfied, which is wrong.
    device = "\n".join(
        [
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class MGMT_ACL in",
            " password 0123456789",
            " login authentication default",
            " exec-timeout 0 0",
            " transport input ssh",
            " transport output ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_FAIL
    assert any("disables session timeout entirely" in d for d in result.details)


def test_vty_exec_timeout_exceeds_golden_policy_maximum_fails():
    device = "\n".join(
        [
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 10 0",
            "line vty 0 15",
            " access-class MGMT_ACL in",
            " password 0123456789",
            " login authentication default",
            " exec-timeout 20 0",
            " transport input ssh",
            " transport output ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_FAIL
    assert any("exceeds the corporate policy maximum of 10 minute(s)" in d for d in result.details)


def test_vty_exec_timeout_shorter_than_golden_passes():
    # Stricter than the golden policy maximum is not a violation.
    device = "\n".join(
        [
            "ip access-list extended MGMT_ACL",
            " deny ip any any log",
            "line con 0",
            " password 0123456789",
            " login local",
            " exec-timeout 5 0",
            "line vty 0 15",
            " access-class MGMT_ACL in",
            " password 0123456789",
            " login authentication default",
            " exec-timeout 5 0",
            " transport input ssh",
            " transport output ssh",
        ]
    )
    result = evaluate("control_00014", device)
    assert result.status == STATUS_PASS


# ---- control_00011: SNMP dual-protocol detection ----------------------------

_COMPLIANT_SNMP = "\n".join(
    [
        "snmp-server group ACME_GRP v3 priv",
        "snmp-server user acme_user ACME_GRP v3 auth sha AAAA priv aes 128 BBBB",
        "snmp-server host 1.2.3.4 version 3 priv acme_user",
        "snmp-server enable traps",
    ]
)
# Matches _COMPLIANT_SNMP's group/user/host names exactly, so tests using both
# together aren't tripped up by the golden-literal-comparison added for these
# fields - only the specific condition under test should be able to fail.
_COMPLIANT_SNMP_GOLDEN = _COMPLIANT_SNMP


def test_snmp_v3_only_passes():
    result = evaluate("control_00011", _COMPLIANT_SNMP, golden_text=_COMPLIANT_SNMP_GOLDEN)
    assert result.status == STATUS_PASS


def test_snmp_v2c_coexisting_with_v3_fails():
    device = "snmp-server community public RO\n" + _COMPLIANT_SNMP
    result = evaluate("control_00011", device, golden_text=_COMPLIANT_SNMP_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("coexist" in d.lower() for d in result.details)


def test_snmp_group_mismatch_vs_golden_fails():
    device = _COMPLIANT_SNMP.replace("ACME_GRP", "OTHER_GRP")
    result = evaluate("control_00011", device, golden_text=_COMPLIANT_SNMP_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("SNMP group" in d for d in result.details)


def test_snmp_missing_entirely_fails():
    result = evaluate("control_00011", "hostname X\n")
    assert result.status == STATUS_FAIL
    assert len(result.details) >= 4


def test_snmp_user_references_undefined_group_fails():
    # The group and user lines are each individually well-formed, but the
    # user's own group reference is a typo ('acme_snmp_group01' vs the
    # actually-defined 'acme_snmp_grp01') - referential integrity, not shape.
    device = "\n".join(
        [
            "snmp-server group ACME_GRP v3 priv",
            "snmp-server user acme_user WRONG_GRP v3 auth sha AAAA priv aes 128 BBBB",
            "snmp-server host 1.2.3.4 version 3 priv acme_user",
            "snmp-server enable traps",
        ]
    )
    result = evaluate("control_00011", device, golden_text=_COMPLIANT_SNMP_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("references group 'WRONG_GRP'" in d for d in result.details)


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


_REAL_TACACS_GOLDEN = "\n".join(
    [
        "tacacs server ACME_TACACS_01",
        " address ipv4 192.168.100.100",
        " key 6 <ENCRYPTED_TACACS_KEY>",
        " timeout 5",
        "tacacs server ACME_TACACS_02",
        " address ipv4 192.168.100.101",
        " key 6 <ENCRYPTED_TACACS_KEY>",
        " timeout 5",
    ]
)


def test_tacacs_address_mismatch_against_real_golden_fails():
    # GOLDEN_TEXT (samples/golden_config.txt) uses <tacacs_server_N_ip>
    # placeholders, so it can never exercise the literal-match branch - this
    # golden text supplies real, non-placeholder addresses instead.
    device = "\n".join(
        [
            "aaa new-model",
            "tacacs server ACME_TACACS_01",
            " address ipv4 192.168.100.100",
            " key 6 encryptedvalue",
            " timeout 5",
            "tacacs server ACME_TACACS_02",
            " address ipv4 10.1.1.100",  # doesn't match golden's 192.168.100.101
            " key 6 encryptedvalue",
            " timeout 5",
            "aaa group server tacacs+ ACME_TACACS_SERVER_GROUP",
            " server name ACME_TACACS_01",
            " server name ACME_TACACS_02",
            " ip tacacs source-interface Loopback0",
        ]
    )
    result = evaluate("control_00004", device, golden_text=_REAL_TACACS_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("does not match the corporate" in d for d in result.details)


def test_tacacs_address_matching_real_golden_passes():
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
    result = evaluate("control_00004", device, golden_text=_REAL_TACACS_GOLDEN)
    assert result.status == STATUS_PASS


def test_tacacs_address_mismatch_against_placeholder_golden_does_not_fail_on_address():
    # GOLDEN_TEXT's addresses are <tacacs_server_N_ip> placeholders - any real
    # device address is "internally consistent" and shouldn't be flagged as a
    # literal mismatch (only presence/duplication are checked in that case).
    device = "\n".join(
        [
            "aaa new-model",
            "tacacs server ACME_TACACS_01",
            " address ipv4 176.156.1.1",
            " key 6 encryptedvalue",
            " timeout 5",
            "tacacs server ACME_TACACS_02",
            " address ipv4 10.1.1.100",
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


def test_tacacs_server_name_mismatch_against_golden_fails():
    # GOLDEN_TEXT (samples/golden_config.txt) names its two servers
    # ACME_TACACS_01 / ACME_TACACS_02 literally (not placeholders).
    device = "\n".join(
        [
            "aaa new-model",
            "tacacs server WRONG_NAME_01",
            " address ipv4 192.168.100.100",
            " key 6 encryptedvalue",
            " timeout 5",
            "tacacs server ACME_TACACS_02",
            " address ipv4 192.168.100.101",
            " key 6 encryptedvalue",
            " timeout 5",
            "aaa group server tacacs+ ACME_TACACS_SERVER_GROUP",
            " server name WRONG_NAME_01",
            " server name ACME_TACACS_02",
            " ip tacacs source-interface Loopback0",
        ]
    )
    result = evaluate("control_00004", device)
    assert result.status == STATUS_FAIL
    assert any("server name does not match" in d for d in result.details)


def test_tacacs_timeout_mismatch_against_golden_fails():
    device = "\n".join(
        [
            "aaa new-model",
            "tacacs server ACME_TACACS_01",
            " address ipv4 192.168.100.100",
            " key 6 encryptedvalue",
            " timeout 30",
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
    assert any("timeout '30' does not match the corporate standard '5'" in d for d in result.details)


def test_tacacs_group_references_undefined_server_fails():
    # A typo'd/stale 'server name' reference (e.g. missing the leading zero)
    # that doesn't correspond to any real 'tacacs server' block.
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
            " server name ACME_TACACS_2",
            " ip tacacs source-interface Loopback0",
        ]
    )
    result = evaluate("control_00004", device)
    assert result.status == STATUS_FAIL
    assert any("references server 'ACME_TACACS_2', which has no matching" in d for d in result.details)


# ---- control_00005: Local emergency users -------------------------------------

def test_emergency_user_correct_privilege_and_name_passes():
    device = "\n".join(
        [
            "username admin_bckp privilege 15 algorithm-type scrypt secret 0123456789",
            "enable secret 0123456789",
        ]
    )
    golden_text = (
        "username admin_bckp privilege 15 algorithm-type scrypt secret X\nenable secret X\n"
    )
    result = evaluate("control_00005", device, golden_text=golden_text)
    assert result.status == STATUS_PASS


def test_emergency_user_wrong_privilege_level_fails():
    device = "\n".join(
        [
            "username admin_bckp privilege 7 algorithm-type scrypt secret 0123456789",
            "enable secret 0123456789",
        ]
    )
    golden_text = (
        "username admin_bckp privilege 15 algorithm-type scrypt secret X\nenable secret X\n"
    )
    result = evaluate("control_00005", device, golden_text=golden_text)
    assert result.status == STATUS_FAIL
    assert any("privilege level is '7', expected 15" in d for d in result.details)


def test_emergency_user_name_mismatch_against_golden_fails():
    device = "\n".join(
        [
            "username admin_bkup privilege 15 algorithm-type scrypt secret 0123456789",
            "enable secret 0123456789",
        ]
    )
    golden_text = (
        "username admin_bckp privilege 15 algorithm-type scrypt secret X\nenable secret X\n"
    )
    result = evaluate("control_00005", device, golden_text=golden_text)
    assert result.status == STATUS_FAIL
    assert any("does not match the corporate standard 'admin_bckp'" in d for d in result.details)


def test_emergency_user_missing_algorithm_type_scrypt_fails():
    device = "\n".join(
        [
            "username admin_bckp privilege 15 algorithm-type md5 secret 0123456789",
            "enable secret 0123456789",
        ]
    )
    result = evaluate("control_00005", device)
    assert result.status == STATUS_FAIL
    assert any("No local emergency user with 'algorithm-type scrypt'" in d for d in result.details)


# ---- control_00015: Local admin user / enable secret ---------------------------
# The admin-standard user is identified as the username line WITHOUT
# 'algorithm-type scrypt' - the inverse of control_00005's emergency-user
# identification above. samples/golden_config.txt's only username line HAS
# scrypt (it's the control_00005 golden line), so it never supplies a golden
# admin-standard line here - tests that need one pass a dedicated golden text,
# same pattern as _RESTRICTIVE_ACL_GOLDEN / _COMPLIANT_SNMP_GOLDEN above.

_LOCAL_ADMIN_GOLDEN = "\n".join(
    [
        "username admin_bckp privilege 15 algorithm-type scrypt secret 0123456789",
        "username admin privilege 15 secret 0123456789",
        "enable secret 0123456789",
    ]
)


def test_local_admin_correct_privilege_and_secret_passes():
    device = "\n".join(
        [
            "username admin privilege 15 secret 0123456789",
            "enable secret 0123456789",
        ]
    )
    result = evaluate("control_00015", device, golden_text=_LOCAL_ADMIN_GOLDEN)
    assert result.status == STATUS_PASS


def test_local_admin_missing_fails():
    result = evaluate("control_00015", "hostname X\n", golden_text=_LOCAL_ADMIN_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("Local administrator with privilege 15 is not created" in d for d in result.details)
    assert any("Enable secret is missing" in d for d in result.details)


def test_local_admin_wrong_privilege_level_fails():
    device = "\n".join(
        [
            "username admin privilege 1 secret 0123456789",
            "enable secret 0123456789",
        ]
    )
    result = evaluate("control_00015", device, golden_text=_LOCAL_ADMIN_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("privilege level is '1', expected 15" in d for d in result.details)


def test_local_admin_username_mismatch_against_golden_fails():
    device = "\n".join(
        [
            "username administrator privilege 15 secret 0123456789",
            "enable secret 0123456789",
        ]
    )
    result = evaluate("control_00015", device, golden_text=_LOCAL_ADMIN_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("does not match the corporate standard 'admin'" in d for d in result.details)


def test_local_admin_weak_enable_secret_fails():
    device = "\n".join(
        [
            "username admin privilege 15 secret 0123456789",
            "enable secret 1234",
        ]
    )
    result = evaluate("control_00015", device, golden_text=_LOCAL_ADMIN_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("weak" in d for d in result.details)


def test_local_admin_weak_enable_secret_not_hardcoded_to_a_single_literal():
    # Proves the weak-value heuristic generalizes beyond any one known test
    # literal (e.g. '1234' or '111111') - a different short/uniform value
    # must also be caught.
    device = "\n".join(
        [
            "username admin privilege 15 secret 0123456789",
            "enable secret 0000",
        ]
    )
    result = evaluate("control_00015", device, golden_text=_LOCAL_ADMIN_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("weak" in d for d in result.details)


def test_local_admin_check_ignores_the_separate_emergency_user():
    # A device with ONLY the control_00005 emergency user (algorithm-type
    # scrypt) and no admin-standard line at all must still fail control_00015
    # - "any privilege-15 username anywhere" is not enough.
    device = "\n".join(
        [
            "username admin_bckp privilege 15 algorithm-type scrypt secret 0123456789",
            "enable secret 0123456789",
        ]
    )
    result = evaluate("control_00015", device, golden_text=_LOCAL_ADMIN_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("Local administrator with privilege 15 is not created" in d for d in result.details)


# ---- control_00006: SSH literal-value comparison -------------------------------

def test_ssh_values_matching_golden_pass():
    device = "\n".join(
        [
            "hostname X",
            "ip domain name acme.com",
            "crypto key generate rsa modulus 2048",
            "ip ssh version 2",
            "ip ssh time-out 60",
            "ip ssh authentication-retries 3",
        ]
    )
    result = evaluate("control_00006", device)
    assert result.status == STATUS_PASS


def test_ssh_version_mismatch_against_golden_fails():
    device = "\n".join(
        [
            "hostname X",
            "ip domain name acme.com",
            "crypto key generate rsa modulus 2048",
            "ip ssh version 1",
            "ip ssh time-out 60",
            "ip ssh authentication-retries 3",
        ]
    )
    result = evaluate("control_00006", device)
    assert result.status == STATUS_FAIL
    assert any("'ip ssh version' is set to '1', expected '2'" in d for d in result.details)


def test_ssh_authentication_retries_mismatch_against_golden_fails():
    device = "\n".join(
        [
            "hostname X",
            "ip domain name acme.com",
            "crypto key generate rsa modulus 2048",
            "ip ssh version 2",
            "ip ssh time-out 60",
            "ip ssh authentication-retries 10",
        ]
    )
    result = evaluate("control_00006", device)
    assert result.status == STATUS_FAIL
    assert any("authentication-retries' is set to '10', expected '3'" in d for d in result.details)


def test_ssh_rsa_keygen_missing_fails():
    device = "\n".join(
        [
            "hostname X",
            "ip domain name acme.com",
            "ip ssh version 2",
            "ip ssh time-out 60",
            "ip ssh authentication-retries 3",
        ]
    )
    result = evaluate("control_00006", device)
    assert result.status == STATUS_FAIL
    assert any("crypto key generate rsa" in d for d in result.details)


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
            "ntp server 10.10.10.100 key 1 prefer",
            "ntp server 20.20.20.100 key 1",
        ]
    )
    result = evaluate("control_00009", device)
    assert result.status == STATUS_PASS


def test_ntp_trusted_key_id_mismatch_fails():
    device = "\n".join(
        [
            "ntp authentication-key 1 md5 abc 7",
            "ntp trusted-key 2",
            "ntp authenticate",
            "ntp server 10.10.10.100 key 1 prefer",
            "ntp server 20.20.20.100 key 1",
        ]
    )
    result = evaluate("control_00009", device)
    assert result.status == STATUS_FAIL
    assert any("does not match 'ntp authentication-key" in d for d in result.details)


def test_ntp_server_missing_key_reference_fails():
    device = "\n".join(
        [
            "ntp authentication-key 1 md5 abc 7",
            "ntp trusted-key 1",
            "ntp authenticate",
            "ntp server 10.10.10.100 prefer",
            "ntp server 20.20.20.100 key 1",
        ]
    )
    result = evaluate("control_00009", device)
    assert result.status == STATUS_FAIL
    assert any("missing a 'key <id>' reference" in d for d in result.details)


# ---- control_00010: Syslog literal-value comparison ----------------------------

def test_syslog_host_matching_golden_passes():
    device = "\n".join(
        [
            "logging on",
            "logging host 30.30.30.100",
            "logging trap informational",
            "logging source-interface Loopback0",
        ]
    )
    result = evaluate("control_00010", device)
    assert result.status == STATUS_PASS


def test_syslog_host_mismatch_against_golden_fails():
    device = "\n".join(
        [
            "logging on",
            "logging host 99.99.99.99",
            "logging trap informational",
            "logging source-interface Loopback0",
        ]
    )
    result = evaluate("control_00010", device)
    assert result.status == STATUS_FAIL
    assert any("does not match the corporate syslog server '30.30.30.100'" in d for d in result.details)


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


# ---- control_00007: Global password encryption -------------------------------

def test_global_password_encryption_present_passes():
    device = "\n".join(
        [
            "key config-key password-encrypt 0123456789",
            "password encryption aes",
        ]
    )
    result = evaluate("control_00007", device)
    assert result.status == STATUS_PASS


def test_global_password_encryption_missing_key_fails():
    result = evaluate("control_00007", "password encryption aes\n")
    assert result.status == STATUS_FAIL
    assert any("password-encrypt" in d for d in result.details)


def test_global_password_encryption_missing_aes_fails():
    result = evaluate("control_00007", "key config-key password-encrypt 0123456789\n")
    assert result.status == STATUS_FAIL
    assert any("password encryption aes" in d for d in result.details)


def test_global_password_encryption_weak_master_key_fails():
    device = "\n".join(
        [
            "key config-key password-encrypt 111111",
            "password encryption aes",
        ]
    )
    result = evaluate("control_00007", device)
    assert result.status == STATUS_FAIL
    assert any("weak" in d for d in result.details)


def test_global_password_encryption_weak_master_key_not_hardcoded_to_111111():
    # Proves the weak-value heuristic is generic, not tuned to the one known
    # test literal - a different short, uniform value must also be caught.
    device = "\n".join(
        [
            "key config-key password-encrypt 0000",
            "password encryption aes",
        ]
    )
    result = evaluate("control_00007", device)
    assert result.status == STATUS_FAIL
    assert any("weak" in d for d in result.details)


# ---- control_00008: ACL for VTY -----------------------------------------------

_RESTRICTIVE_ACL_GOLDEN = "\n".join(
    [
        "ip access-list extended ACME_VTY_MGMT_ACL",
        " remark management subnet only",
        " permit tcp 10.0.0.0 0.0.0.255 any eq 22",
        " deny ip any any log",
    ]
)


def test_acl_for_vty_missing_fails():
    result = evaluate("control_00008", "hostname ACME_USA_ROUTER_INTERNET_BLN_01\n")
    assert result.status == STATUS_FAIL
    assert any("ip access-list extended" in d for d in result.details)


def test_acl_matching_golden_rule_for_rule_passes():
    device = "\n".join(
        [
            "ip access-list extended ACME_VTY_MGMT_ACL",
            " permit tcp 10.0.0.0 0.0.0.255 any eq 22",
            " deny ip any any log",
        ]
    )
    result = evaluate("control_00008", device, golden_text=_RESTRICTIVE_ACL_GOLDEN)
    assert result.status == STATUS_PASS


def test_acl_permit_any_any_diverges_from_golden_fails():
    device = "\n".join(
        [
            "ip access-list extended ACME_VTY_MGMT_ACL",
            " permit ip any any",
        ]
    )
    result = evaluate("control_00008", device, golden_text=_RESTRICTIVE_ACL_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("rule #1" in d for d in result.details)


def test_acl_missing_terminal_deny_log_fails():
    device = "\n".join(
        [
            "ip access-list extended ACME_VTY_MGMT_ACL",
            " permit tcp 10.0.0.0 0.0.0.255 any eq 22",
        ]
    )
    result = evaluate("control_00008", device, golden_text=_RESTRICTIVE_ACL_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("rule #2" in d for d in result.details)


def test_acl_name_mismatch_fails():
    device = "\n".join(
        [
            "ip access-list extended WRONG_ACL_NAME",
            " permit tcp 10.0.0.0 0.0.0.255 any eq 22",
            " deny ip any any log",
        ]
    )
    result = evaluate("control_00008", device, golden_text=_RESTRICTIVE_ACL_GOLDEN)
    assert result.status == STATUS_FAIL
    assert any("does not match the corporate ACL name" in d for d in result.details)


def test_acl_wildcard_mask_equivalent_to_any_fails_even_if_it_matched_golden():
    # A wildcard mask of 255.255.255.255 is functionally 'any' regardless of
    # golden's own wording - this must be caught semantically, not only when
    # it happens to diverge from golden's literal rule text.
    golden = "\n".join(
        [
            "ip access-list extended ACME_VTY_MGMT_ACL",
            " permit ip 0.0.0.0 255.255.255.255 any",
        ]
    )
    device = "\n".join(
        [
            "ip access-list extended ACME_VTY_MGMT_ACL",
            " permit ip 0.0.0.0 255.255.255.255 any",
        ]
    )
    result = evaluate("control_00008", device, golden_text=golden)
    assert result.status == STATUS_FAIL
    assert any("functionally equivalent to 'any'" in d for d in result.details)


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
        "hostname ACME_USA_RT_INTERNET_BLN_01\n",
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


def test_banner_mismatched_delimiter_fails():
    result = evaluate("control_00012", "banner motd $ ++This is the message of the day++ %\n")
    assert result.status == STATUS_FAIL
    assert any("delimiter" in d for d in result.details)


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


# ---- Control Validation Review (Pass 3): real 75-file fixture regression -----
# Exercises the fixes above against the actual device_configs/*.txt fixtures
# named in the review, evaluated against the real golden_config.txt at the
# repo root - not synthetic strings. This is the Golden Config Creator's own
# generated output (see golden_config_builder.py/GOLDEN_CONFIG_CREATOR.md),
# now realigned to match support_files/NCM Configuration Script.txt exactly
# and used as main.py's batch-mode source of truth for the full 75-device
# audit, superseding the old hand-maintained golden_config_11_08_2026.txt
# (kept in the repo, unreferenced, per Pass 4). Unlike the rest of this test
# module this is deliberately NOT the samples/golden_config.txt baseline,
# since several of these fixtures only make sense evaluated against the real
# fleet's golden config.

DEVICE_CONFIGS_DIR = REPO_ROOT / "device_configs"
REAL_GOLDEN_TEXT = (REPO_ROOT / "golden_config.txt").read_text(encoding="utf-8")


def _evaluate_fixture(filename: str, control_id: str):
    device_text = (DEVICE_CONFIGS_DIR / filename).read_text(encoding="utf-8")
    evaluator = ControlEvaluator()
    return evaluator.evaluate_control(ALL_CONTROLS[control_id], device_text, REAL_GOLDEN_TEXT)


def test_real_golden_config_has_no_duplicated_content():
    # Regression guard for the duplication bug found and fixed this pass -
    # a re-duplicated golden file would silently make every ConfigTree
    # lookup below ambiguous again.
    from config_parser import ConfigTree

    golden = ConfigTree(REAL_GOLDEN_TEXT)
    assert len(golden.all_text(r"^hostname\s")) == 1
    assert len(golden.blocks(r"^tacacs server\s")) == 2
    assert len(golden.blocks(r"^ip access-list extended ACME_VTY_MGMT_ACL")) == 1
    assert len(golden.blocks(r"^line vty\s")) == 2


def test_fixture_hostname_config_04_invalid_type_token_fails():
    result = _evaluate_fixture("hostname_config_04.txt", "control_00001")
    assert result.status == STATUS_FAIL
    assert any("Type field" in d for d in result.details)


def test_fixture_aaa_config_01_is_a_fixture_bug_not_a_code_gap():
    # The file's header comment claims 'aaa new-model' was removed, but line
    # 40 of the file still has it - the checker correctly evaluates the real
    # text present, so this legitimately PASSes. See documentation/
    # CONTROL_UPDATE_REPORT.md Pass 3 for the full writeup.
    result = _evaluate_fixture("aaa_config_01.txt", "control_00003")
    assert result.status == STATUS_PASS


def test_fixture_ssh_config_01_missing_rsa_keygen_fails():
    result = _evaluate_fixture("ssh_config_01.txt", "control_00006")
    assert result.status == STATUS_FAIL
    assert any("crypto key generate rsa" in d for d in result.details)


def test_fixture_password_encryption_config_02_missing_key_fails():
    result = _evaluate_fixture("password_encryption_config_02.txt", "control_00007")
    assert result.status == STATUS_FAIL


def test_fixture_password_encryption_config_03_missing_aes_fails():
    result = _evaluate_fixture("password_encryption_config_03.txt", "control_00007")
    assert result.status == STATUS_FAIL


def test_fixture_password_encryption_config_04_weak_master_key_fails():
    result = _evaluate_fixture("password_encryption_config_04.txt", "control_00007")
    assert result.status == STATUS_FAIL
    assert any("weak" in d for d in result.details)


def test_fixture_password_encryption_config_05_typo_command_fails():
    result = _evaluate_fixture("password_encryption_config_05.txt", "control_00007")
    assert result.status == STATUS_FAIL


def test_fixture_acl_vty_config_02_acl_not_bound_is_control_00014_not_00008():
    # ACL *binding* is control_00014's job by the Pass-2 architecture split
    # (control_00008 = content, control_00014 = binding) - this file's
    # defect is correctly caught there, not by control_00008.
    result = _evaluate_fixture("acl_vty_config_02.txt", "control_00014")
    assert result.status == STATUS_FAIL
    assert any("no 'access-class' ACL is bound" in d for d in result.details)


def test_fixture_acl_vty_config_04_missing_deny_log_fails():
    # Only catchable once the golden file's real Cloudflare deny-list ACL
    # (not the old 1-line placeholder) is the one being compared against.
    result = _evaluate_fixture("acl_vty_config_04.txt", "control_00008")
    assert result.status == STATUS_FAIL


def test_fixture_acl_vty_config_05_wildcard_equivalent_to_any_fails():
    result = _evaluate_fixture("acl_vty_config_05.txt", "control_00008")
    assert result.status == STATUS_FAIL
    assert any("functionally equivalent to 'any'" in d for d in result.details)


def test_fixture_snmp_config_04_user_references_wrong_group_fails():
    result = _evaluate_fixture("snmp_config_04.txt", "control_00011")
    assert result.status == STATUS_FAIL
    assert any("references group" in d for d in result.details)


def test_fixture_banner_config_02_generic_wording_is_intentionally_not_flagged():
    # manual_review governs Tool 2's rendering; Tool 1's deterministic check
    # is presence/well-formedness only - wording quality is a human call by
    # design (see _check_control_00012's docstring), not re-litigated here.
    result = _evaluate_fixture("banner_config_02.txt", "control_00012")
    assert result.status == STATUS_PASS


def test_fixture_banner_config_03_mismatched_delimiter_fails():
    result = _evaluate_fixture("banner_config_03.txt", "control_00012")
    assert result.status == STATUS_FAIL
    assert any("delimiter" in d for d in result.details)


def test_fixture_banner_config_04_wrong_company_name_is_intentionally_not_flagged():
    result = _evaluate_fixture("banner_config_04.txt", "control_00012")
    assert result.status == STATUS_PASS


def test_fixture_vty_lines_config_variants_each_fail_for_their_own_distinct_defect():
    # These 5 fixtures predate this project's Pass-2 VTY convention (split
    # 'line vty 0 4'/'5 15' ranges, 'login authentication default', explicit
    # 'transport output ssh') - each carries that older single-range/
    # 'login local' baseline PLUS its own single intended defect. Golden
    # cleanup alone doesn't fix this (control_00014 doesn't compare VTY
    # structure against golden at all - the requirements are unconditional),
    # so this is a fixture-authoring/spec-version mismatch, not a code gap -
    # each variant's own distinct signal is still present and correctly
    # detected alongside the shared baseline noise.
    expected_signal = {
        "vty_lines_config_01.txt": "transport input",
        "vty_lines_config_02.txt": "disables session timeout entirely",
        "vty_lines_config_03.txt": "login",
        "vty_lines_config_04.txt": "exceeds the corporate policy maximum",
        "vty_lines_config_05.txt": "'in' direction keyword",
    }
    for filename, needle in expected_signal.items():
        result = _evaluate_fixture(filename, "control_00014")
        assert result.status == STATUS_FAIL, filename
        assert any(needle in d for d in result.details), (filename, result.details)


def test_fixture_local_admin_config_01_enable_secret_via_control_00005_is_a_fixture_quirk():
    # This variant's own control_00015 section drops 'enable secret'
    # entirely, but control_00005's independent emergency-user section still
    # has one - real Cisco IOS has a working enable secret in effect either
    # way, so PASS is technically correct for what the device actually has.
    result = _evaluate_fixture("local_admin_config_01.txt", "control_00015")
    assert result.status == STATUS_PASS


def test_fixture_local_admin_config_02_wrong_privilege_fails():
    result = _evaluate_fixture("local_admin_config_02.txt", "control_00015")
    assert result.status == STATUS_FAIL
    assert any("privilege level is '1'" in d for d in result.details)


def test_fixture_local_admin_config_03_weak_enable_secret_fails():
    # Requires taking the LAST 'enable secret' line in file order (real
    # Cisco config-apply semantics), not the first - control_00005's section
    # has its own unrelated, non-weak 'enable secret' earlier in the file.
    result = _evaluate_fixture("local_admin_config_03.txt", "control_00015")
    assert result.status == STATUS_FAIL
    assert any("weak" in d for d in result.details)


def test_fixture_local_admin_config_04_enable_password_is_a_fixture_quirk():
    # 'enable password' replaces 'enable secret' in this variant's own
    # section, but control_00005's 'enable secret' is still present
    # elsewhere - Cisco IOS always prefers enable secret over enable
    # password when both exist, so the device genuinely has a working
    # enable secret; PASS is technically correct.
    result = _evaluate_fixture("local_admin_config_04.txt", "control_00015")
    assert result.status == STATUS_PASS


def test_fixture_local_admin_config_05_username_mismatch_fails():
    result = _evaluate_fixture("local_admin_config_05.txt", "control_00015")
    assert result.status == STATUS_FAIL
    assert any("does not match the corporate standard 'admin'" in d for d in result.details)
