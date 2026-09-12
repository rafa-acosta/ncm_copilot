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


# ---- control_00006: SSH literal-value comparison -------------------------------

def test_ssh_values_matching_golden_pass():
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
    assert result.status == STATUS_PASS


def test_ssh_version_mismatch_against_golden_fails():
    device = "\n".join(
        [
            "hostname X",
            "ip domain name acme.com",
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
            "ip ssh version 2",
            "ip ssh time-out 60",
            "ip ssh authentication-retries 10",
        ]
    )
    result = evaluate("control_00006", device)
    assert result.status == STATUS_FAIL
    assert any("authentication-retries' is set to '10', expected '3'" in d for d in result.details)


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
