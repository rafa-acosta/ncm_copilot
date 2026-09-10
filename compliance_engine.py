"""Evaluates a device configuration against controls.yaml definitions.

Each control gets its own `_check_control_XXXXX` method rather than one
generic "diff the command_template" routine: several controls need block-
level reasoning (AAA group consistency, nested TACACS/VTY blocks, hash-type
consistency across N usernames) that a single regex-template engine can't
express cleanly. Every checker returns a list of human-readable failure
reasons; an empty list means the control is compliant.

Golden-config values are used two ways, decided per control:
  - shared infrastructure values (domain, TACACS group/server names, syslog
    host/interface, VTY ACL name) must match the device literally.
  - device-unique values (hostname parts, local usernames/passwords, banner
    text) are checked for structural/policy correctness only, never
    literal-compared against golden's example value.

A `_check_control_XXXXX` method, when one exists, always wins over the
control's `manual_review` flag - `manual_review` is only a fallback for
controls with no automated checker at all (evaluate_control raises if
neither exists). control_00012 (Banners) is the one control where both are
true: `manual_review: true` still gates Tool 2's golden-config rendering
(wording approval stays a human call there), but Tool 1's compliance score
now takes a deterministic presence check - see _check_control_00012.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config_parser import ConfigTree

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_EXCEPTION = "EXCEPTION"
STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"

# controls.yaml defines control_00001-00018, but only 1-15 are active for this
# version - 16-18 stay defined for future use but are filtered out unconditionally
# wherever this is used (main.py, golden_config_builder.py), never evaluated,
# scored, or rendered by default (see CLAUDE.md section 11).
ACTIVE_CONTROL_IDS = {f"control_{i:05d}" for i in range(1, 16)}

_WEAK_SECRET_TYPES = {"0", "4", "5", "7"}

_MANDATORY_COMMAND_PATTERNS = [
    (r"^no ip http server", "'no ip http server' (disable unencrypted web management)"),
    (r"^no ip http secure-server", "'no ip http secure-server' (disable HTTPS web management unless explicitly required)"),
    (r"^service password-encryption", "'service password-encryption'"),
]

_PROHIBITED_COMMAND_PATTERNS = [
    (r"^no logging\b", "'no logging' (disables system logging)"),
    (r"^ip http server\b", "'ip http server' (unencrypted web management enabled)"),
    (r"^no service password-encryption", "'no service password-encryption'"),
    (r"^no aaa new-model", "'no aaa new-model'"),
]


@dataclass
class ControlResult:
    """Outcome of evaluating a single control against a device configuration."""

    control_id: str
    title: str
    status: str
    severity: str
    risk: str
    evidence_found: str
    remediation: str
    explanation: str = ""
    details: list[str] = field(default_factory=list)


class ControlEvaluator:
    """Evaluates controls from controls.yaml against a device/golden config pair."""

    def __init__(self, exceptions: dict[str, str] | None = None):
        self.exceptions = exceptions or {}

    def evaluate_control(self, control: dict, device_config: str, golden_config: str) -> ControlResult:
        """Evaluate one control dict (as loaded from controls.yaml) and return a ControlResult."""
        control_id = control["control_id"]

        checker = getattr(self, f"_check_{control_id}", None)
        if checker is None:
            if control.get("manual_review"):
                return self._result(control, STATUS_MANUAL_REVIEW, control["evidence"],
                                     ["This control requires human review of the actual wording/content."])
            raise ValueError(f"No deterministic checker implemented for {control_id}")

        device = ConfigTree(device_config)
        golden = ConfigTree(golden_config)
        failures = checker(device, golden, control)

        if not failures:
            return self._result(control, STATUS_PASS, control["evidence"],
                                 ["All required commands present and compliant."])

        exception_reason = self.exceptions.get(control_id)
        if exception_reason:
            return self._result(control, STATUS_EXCEPTION, "; ".join(failures),
                                 [f"Exception granted: {exception_reason}", *failures])

        return self._result(control, STATUS_FAIL, "; ".join(failures), failures)

    @staticmethod
    def _result(control: dict, status: str, evidence_found: str, details: list[str]) -> ControlResult:
        return ControlResult(
            control_id=control["control_id"],
            title=control["title"],
            status=status,
            severity=control["severity"],
            risk=control["risk"],
            evidence_found=evidence_found,
            remediation=control["remediation"],
            explanation=control.get("explanation", ""),
            details=details,
        )

    # ---- per-control checkers ----------------------------------------------
    # Each returns a list[str] of failure reasons; an empty list means PASS.

    def _check_control_00001(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        hostname_line = device.first_text(r"^hostname\s")
        if not hostname_line:
            return ["No 'hostname' command found in device configuration."]
        hostname = hostname_line.split(None, 1)[1].strip()
        generic_names = {"router", "switch", "wireless_controller", "access_point", "access-point", "firewall", "pbx"}
        if hostname.lower() in generic_names:
            failures.append(f"Hostname '{hostname}' is generic.")
        parts = hostname.split("_")
        if len(parts) < 6 or any(p == "" for p in parts):
            failures.append(
                f"Hostname '{hostname}' does not follow the "
                "COMPANY_COUNTRY_TYPE_FUNCTION_SITE_DEVICENUMBER convention "
                "(expected at least 6 underscore-separated parts)."
            )
        return failures

    def _check_control_00002(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        device_line = device.first_text(r"^ip domain[- ]name\s")
        if not device_line:
            return ["No 'ip domain name' command found in device configuration."]
        golden_line = golden.first_text(r"^ip domain[- ]name\s")
        if golden_line:
            expected = golden_line.split(None, 2)[2].strip()
            actual = device_line.split(None, 2)[2].strip()
            if expected != actual:
                return [f"Domain '{actual}' does not match the corporate domain '{expected}'."]
        return []

    def _check_control_00003(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        required_patterns = [
            r"^aaa new-model",
            r"^aaa authentication password-prompt",
            r"^aaa authentication username-prompt",
            r"^aaa authentication login default group \S+ local",
            r"^aaa authentication enable default group \S+ enable",
            r"^aaa authorization config-commands",
            r"^aaa authorization exec default group \S+ local if-authenticated",
            r"^aaa authorization commands 1 default group \S+ if-authenticated",
            r"^aaa authorization commands 15 default group \S+ if-authenticated",
            r"^aaa accounting exec default start-stop group \S+",
            r"^aaa accounting commands 1 default start-stop group \S+",
            r"^aaa accounting commands 15 default start-stop group \S+",
        ]
        failures = []
        groups_found = set()
        for pattern in required_patterns:
            line = device.first_text(pattern)
            if not line:
                failures.append(f"Required AAA command missing (expected to match '{pattern}').")
                continue
            match = re.search(r"group (\S+)", line)
            if match:
                groups_found.add(match.group(1))
        if len(groups_found) > 1:
            failures.append(f"AAA commands reference inconsistent TACACS groups: {sorted(groups_found)}.")
        return failures

    def _check_control_00004(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^aaa new-model"):
            failures.append("'aaa new-model' is missing.")

        tacacs_blocks = device.blocks(r"^tacacs server\s")
        if len(tacacs_blocks) < 2:
            failures.append("Fewer than two 'tacacs server' definitions found.")

        # Golden addresses are matched positionally (1st tacacs server block to
        # 1st, 2nd to 2nd) since server names themselves aren't required to
        # match golden's - only compared literally when golden gives a real IP
        # rather than a <tacacs_server_N_ip> placeholder (placeholder = "must
        # exist and be internally consistent", not "must equal this").
        golden_addresses = []
        for gblock in golden.blocks(r"^tacacs server\s"):
            gaddr_line = next((c for c in gblock[1:] if c.startswith("address ipv4")), None)
            golden_addresses.append(gaddr_line.split()[-1] if gaddr_line else None)

        addresses_seen: dict[str, str] = {}
        for idx, block in enumerate(tacacs_blocks):
            parent, children = block[0], block[1:]
            address_line = next((c for c in children if c.startswith("address ipv4")), None)
            if not address_line:
                failures.append(f"'{parent}': no 'address ipv4' command found.")
            else:
                address = address_line.split()[-1]
                duplicate_of = addresses_seen.get(address)
                if duplicate_of:
                    failures.append(
                        f"'{parent}' and '{duplicate_of}' both use the same address ({address}); "
                        "each TACACS server must have a distinct address."
                    )
                else:
                    addresses_seen[address] = parent
                expected_address = golden_addresses[idx] if idx < len(golden_addresses) else None
                if expected_address and not re.match(r"^<.*>$", expected_address) and address != expected_address:
                    failures.append(
                        f"'{parent}': address '{address}' does not match the corporate "
                        f"TACACS server address '{expected_address}'."
                    )
            if not any(re.match(r"key \d", c) for c in children):
                failures.append(f"'{parent}': no 'key' command found.")
            if not any(c.startswith("timeout") for c in children):
                failures.append(f"'{parent}': no 'timeout' command found.")
            for child in children:
                if re.match(r"key 7 ", child):
                    failures.append(
                        f"'{parent}' uses a reversible Type 7 key; Type 6 encryption "
                        "('key config-key password-encrypt' + 'key 6 <key>') is required."
                    )

        group_blocks = device.blocks(r"^aaa group server tacacs\+\s")
        if not group_blocks:
            failures.append("No 'aaa group server tacacs+' block found.")
        else:
            parent, children = group_blocks[0][0], group_blocks[0][1:]
            group_name = parent.split()[-1]
            golden_group_blocks = golden.blocks(r"^aaa group server tacacs\+\s")
            if golden_group_blocks:
                expected_group = golden_group_blocks[0][0].split()[-1]
                if group_name != expected_group:
                    failures.append(
                        f"TACACS group name '{group_name}' does not match the corporate group '{expected_group}'."
                    )
            if not any(c.startswith("ip tacacs source-interface") for c in children):
                failures.append("No 'ip tacacs source-interface' configured under the TACACS server group.")
        return failures

    def _check_control_00005(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        username_lines = device.all_text(r"^username\s")
        if not username_lines:
            failures.append("No 'username' command found in device configuration.")
        if not device.exists(r"^enable secret\s"):
            failures.append("No 'enable secret' command found in device configuration.")

        secret_types = {m.group(1) for line in username_lines if (m := re.search(r"\bsecret\s+(\d+)\s", line))}
        weak_types = secret_types & _WEAK_SECRET_TYPES
        if weak_types:
            failures.append(
                f"Local account(s) use a weak password-hashing type: {sorted(weak_types)} (expected type 8/9 scrypt)."
            )
        if len(secret_types) > 1:
            failures.append(f"Local accounts use inconsistent password-hashing types: {sorted(secret_types)}.")
        return failures

    def _check_control_00006(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^hostname\s"):
            failures.append("Hostname is not configured.")
        if not device.exists(r"^ip domain[- ]name\s"):
            failures.append("IP domain-name is not configured.")
        zeroized = device.exists(r"^crypto key zeroize rsa")
        regenerated = device.exists(r"^crypto key generate rsa modulus \d+")
        ssh_enabled = device.exists(r"^ip ssh version\s")
        if (zeroized and not regenerated) or not ssh_enabled:
            failures.append(
                "RSA key generation (modulus 2048) is missing or RSA keys were zeroized without regeneration."
            )
        return failures

    def _check_control_00007(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^key config-key password-encrypt\s+\S+"):
            failures.append("'key config-key password-encrypt <device_master_key>' is missing.")
        if not device.exists(r"^password encryption aes"):
            failures.append("'password encryption aes' is missing.")
        return failures

    def _check_control_00008(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        # Existence-only per spec: whether the ACL is actually bound to the VTY
        # lines and restrictive rather than permissive is control_00014's job
        # (it separately validates 'access-class' binding and ACL content).
        if not device.exists(r"^ip access-list extended\s+\S+"):
            return ["No 'ip access-list extended' block found in the running configuration."]
        return []

    def _check_control_00009(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        ntp_lines = device.all_text(r"^ntp server\s")
        if not ntp_lines:
            failures.append("NTP server configuration is missing.")
        elif not any("prefer" in line for line in ntp_lines):
            failures.append("'prefer' keyword is missing on the primary NTP server.")
        authenticated = (
            device.exists(r"^ntp authenticate")
            and device.exists(r"^ntp authentication-key\s")
            and device.exists(r"^ntp trusted-key\s")
        )
        if not authenticated:
            failures.append(
                "NTP authentication is not configured "
                "('ntp authenticate' / 'ntp authentication-key' / 'ntp trusted-key' missing)."
            )
        return failures

    def _check_control_00010(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^logging on"):
            failures.append("'logging on' command is missing.")
        if not device.exists(r"^logging host\s"):
            failures.append("Logging host IP address is missing.")
        if not device.exists(r"^logging trap informational"):
            failures.append("Logging trap level is not set to 'informational'.")
        device_iface = device.first_text(r"^logging source-interface\s")
        golden_iface = golden.first_text(r"^logging source-interface\s")
        if not device_iface:
            failures.append("'logging source-interface' is not configured.")
        elif golden_iface:
            expected = golden_iface.split(None, 1)[1].strip().lower()
            actual = device_iface.split(None, 1)[1].strip().lower()
            if actual != expected:
                failures.append(
                    f"'logging source-interface' ('{actual}') does not match the corporate standard ('{expected}')."
                )
        return failures

    def _check_control_00011(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^snmp-server group\s+\S+\s+v3\s+priv"):
            failures.append("SNMPv3 group with 'priv' is not configured.")
        if not device.exists(r"^snmp-server user\s+\S+\s+\S+\s+v3\s+auth\s+sha\s+\S+\s+priv\s+aes"):
            failures.append("SNMPv3 user is not created with SHA/AES configuration.")
        if not device.exists(r"^snmp-server host\s+\S+\s+version\s+3"):
            failures.append("SNMP trap host is missing.")
        if not device.exists(r"^snmp-server enable traps"):
            failures.append("'snmp-server enable traps' command is missing.")
        if device.exists(r"^snmp-server community\s"):
            failures.append(
                "An SNMPv1/v2c community string ('snmp-server community') coexists with the SNMPv3 configuration."
            )
        return failures

    def _check_control_00012(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        # Presence-only: whether the banner's wording meets corporate legal/policy
        # language is a human judgment call this checker doesn't attempt - see
        # controls.yaml's manual_review flag, which still gates Tool 2's rendering.
        if not device.exists(r"^banner motd\b"):
            return ["'banner motd' is not configured."]
        return []

    def _check_control_00013(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        min_len_line = device.first_text(r"^security passwords min-length\s")
        if not min_len_line:
            failures.append("'security passwords min-length' is not configured.")
        elif int(min_len_line.split()[-1]) < 10:
            failures.append(
                f"'security passwords min-length' is set to {min_len_line.split()[-1]}, below the required minimum of 10."
            )
        if not device.exists(r"^service password-encryption"):
            failures.append("'service password-encryption' is missing.")
        return failures

    def _check_control_00014(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []

        con_blocks = device.blocks(r"^line con\s")
        if not con_blocks:
            failures.append("No 'line console 0' configuration found.")
        else:
            parent, children = con_blocks[0][0], con_blocks[0][1:]
            if not any(c.startswith("login local") for c in children):
                failures.append(f"'{parent}': 'login local' is missing.")
            if not any(c.startswith("exec-timeout") for c in children):
                failures.append(f"'{parent}': 'exec-timeout' is missing.")

        vty_blocks = device.blocks(r"^line vty\s")
        if not vty_blocks:
            failures.append("No 'line vty' configuration found.")

        checked_acls: set[str] = set()
        for block in vty_blocks:
            parent, children = block[0], block[1:]
            if not any(c.startswith("login local") for c in children):
                failures.append(f"'{parent}': 'login local' is missing.")
            if not any(c.startswith("exec-timeout") for c in children):
                failures.append(f"'{parent}': 'exec-timeout' is missing.")

            transport_lines = [c for c in children if c.startswith("transport input")]
            if not transport_lines or any(
                "telnet" in line or "all" in line for line in transport_lines
            ):
                failures.append(f"'{parent}': 'transport input' is not restricted to secure protocols.")

            acl_line = next((c for c in children if c.startswith("access-class")), None)
            if not acl_line:
                failures.append(f"'{parent}': no 'access-class' ACL is bound to this VTY line.")
                continue
            acl_name = acl_line.split()[1]
            if acl_name in checked_acls:
                continue
            checked_acls.add(acl_name)

            acl_blocks = device.blocks(rf"^ip access-list \S+ {re.escape(acl_name)}\b")
            if not acl_blocks:
                failures.append(f"ACL '{acl_name}' referenced by access-class was not found in the configuration.")
                continue
            acl_children = acl_blocks[0][1:]
            permissive = [
                c for c in acl_children
                if re.match(r"permit\s+(ip|tcp)\s+any\s+any\b", c) or re.search(r"eq\s+telnet\b", c)
            ]
            if permissive:
                failures.append(
                    f"ACL '{acl_name}' bound to VTY lines is permissive instead of restrictive: "
                    + "; ".join(permissive)
                )
        return failures

    def _check_control_00015(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^enable secret\s"):
            failures.append("Enable secret is missing.")
        priv15_users = [line for line in device.all_text(r"^username\s") if re.search(r"privilege\s+15\b", line)]
        if not priv15_users:
            failures.append("Local administrator with privilege 15 is not created.")
        return failures

    def _check_control_00016(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        for pattern, description in _MANDATORY_COMMAND_PATTERNS:
            if not device.exists(pattern):
                failures.append(f"Mandatory command missing: {description}.")

        cp_blocks = device.blocks(r"^control-plane")
        if not cp_blocks:
            failures.append("No 'control-plane' section found.")
        elif not any(c.startswith("service-policy input") for c in cp_blocks[0][1:]):
            failures.append(
                "No 'service-policy input <policy_name>' applied under 'control-plane' "
                "(missing Control Plane Policing)."
            )
        return failures

    def _check_control_00017(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^login block-for\s"):
            failures.append("'login block-for' is missing.")
        if not device.exists(r"^login delay\s"):
            failures.append("'login delay' is missing.")
        min_len_line = device.first_text(r"^security passwords min-length\s")
        if not min_len_line or int(min_len_line.split()[-1]) < 10:
            failures.append("'security passwords min-length' is below 10.")
        scrypt_users = [
            line for line in device.all_text(r"^username\s")
            if re.search(r"\bsecret\s+9\s", line) or "algorithm-type scrypt" in line
        ]
        if not scrypt_users:
            failures.append("Scrypt algorithm (type 9) is not configured for any local user account.")
        return failures

    def _check_control_00018(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        for pattern, description in _PROHIBITED_COMMAND_PATTERNS:
            if device.exists(pattern):
                failures.append(f"Prohibited command present: {description}.")
        return failures
