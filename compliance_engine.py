"""Evaluates a device configuration against controls.yaml definitions.

Each control gets its own `_check_control_XXXXX` method rather than one
generic "diff the command_template" routine: several controls need block-
level reasoning (AAA group consistency, nested TACACS/VTY blocks, hash-type
consistency across N usernames) that a single regex-template engine can't
express cleanly. Every checker returns a list of human-readable failure
reasons; an empty list means the control is compliant.

Golden-config values are used two ways, decided per control (per the source
spec's per-control `Fixed_value` field - "yes" means the documented/golden
value is the actual required value, not just a placeholder):
  - shared infrastructure values (domain, AAA/TACACS group name, TACACS
    server names/timeout, ACL name and full rule content, NTP server IPs,
    syslog host, SNMP group/user/host) must match the device literally.
  - device-unique values that remain structural/policy-only, never
    literal-compared against golden's example value: hostname parts, local
    passwords/secrets/keys, and banner text - see control_00012's own note
    below for why `Fixed_value: yes` is deliberately NOT applied there.

VTY lines use `login authentication default` (invoking the AAA method list
control_00003 sets up); console keeps `login local` (a working fallback if
TACACS is unreachable) - these are intentionally different, not a typo.

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
# Not raised by ControlEvaluator itself - main.py's batch loop catches an
# unexpected checker exception per-control and builds a ControlResult with
# this status instead of letting it crash the rest of the device/fleet.
STATUS_ASSESSMENT_ERROR = "ASSESSMENT_ERROR"

# controls.yaml defines control_00001-00018, but only 1-15 are active for this
# version - 16-18 stay defined for future use but are filtered out unconditionally
# wherever this is used (main.py, golden_config_builder.py), never evaluated,
# scored, or rendered by default (see CLAUDE.md section 11).
ACTIVE_CONTROL_IDS = {f"control_{i:05d}" for i in range(1, 16)}

_WEAK_SECRET_TYPES = {"0", "4", "5", "7"}

# Generic, not tuned to any single known test value - a small set of
# universally-known-weak literals (case-insensitive) plus the length/
# uniformity heuristics in _is_weak_secret_value below catch the rest.
_WEAK_SECRET_LITERALS = {
    "password", "changeme", "admin", "cisco", "letmein", "qwerty",
    "welcome", "default",
}

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
    def _is_weak_secret_value(value: str) -> bool:
        """Generic weak-secret heuristic - not hardcoded to any single test value.

        Flags: all-identical-character strings ('111111', '0000'), values
        shorter than this project's own 'security passwords min-length 10'
        standard (control_00013) minus a small margin (<8 chars, e.g. '1234'),
        and a small set of universally-known-weak literals. A 10-digit
        sequential placeholder like '0123456789' (used throughout this
        project's fixtures as a device-unique example value) is intentionally
        NOT flagged - it's long and not uniform/known-weak.
        """
        if not value:
            return True
        stripped = value.strip()
        if len(set(stripped)) == 1:
            return True
        if len(stripped) < 8:
            return True
        if stripped.lower() in _WEAK_SECRET_LITERALS:
            return True
        return False

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
        elif len(parts) >= 3:
            # Part 3 (Type) must be a short device-class code (RT, SW, WLC, AP,
            # PBX, FW, ...), not the spelled-out word - a long alphabetic
            # segment here means someone typed 'Router' instead of 'RT'.
            type_segment = parts[2]
            if type_segment.isalpha() and len(type_segment) > 4:
                failures.append(
                    f"Hostname '{hostname}': Type field '{type_segment}' should be a short "
                    "device-class code (e.g. 'RT', 'SW', 'WLC', 'AP', 'PBX', 'FW'), not a spelled-out word."
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
        elif groups_found:
            group_name = next(iter(groups_found))
            golden_line = golden.first_text(r"^aaa authentication login default group \S+ local")
            golden_match = re.search(r"group (\S+)", golden_line) if golden_line else None
            if golden_match and group_name != golden_match.group(1):
                failures.append(
                    f"AAA commands reference TACACS group '{group_name}', which does not match "
                    f"the corporate group '{golden_match.group(1)}'."
                )
        return failures

    def _check_control_00004(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^aaa new-model"):
            failures.append("'aaa new-model' is missing.")

        tacacs_blocks = device.blocks(r"^tacacs server\s")
        if len(tacacs_blocks) < 2:
            failures.append("Fewer than two 'tacacs server' definitions found.")

        # Golden values are matched positionally (1st tacacs server block to
        # 1st, 2nd to 2nd) since a device's own server names aren't required
        # to match golden's independent of this - only compared literally
        # when golden gives a real value rather than a <placeholder> (a
        # placeholder means "must exist and be internally consistent", not
        # "must equal this").
        golden_names = []
        golden_addresses = []
        golden_timeouts = []
        for gblock in golden.blocks(r"^tacacs server\s"):
            golden_names.append(gblock[0].split()[-1])
            gaddr_line = next((c for c in gblock[1:] if c.startswith("address ipv4")), None)
            golden_addresses.append(gaddr_line.split()[-1] if gaddr_line else None)
            gtimeout_line = next((c for c in gblock[1:] if c.startswith("timeout")), None)
            golden_timeouts.append(gtimeout_line.split()[-1] if gtimeout_line else None)

        addresses_seen: dict[str, str] = {}
        for idx, block in enumerate(tacacs_blocks):
            parent, children = block[0], block[1:]
            server_name = parent.split()[-1]
            expected_name = golden_names[idx] if idx < len(golden_names) else None
            if expected_name and not re.match(r"^<.*>$", expected_name) and server_name != expected_name:
                failures.append(
                    f"'{parent}': server name does not match the corporate TACACS server name '{expected_name}'."
                )
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
            timeout_line = next((c for c in children if c.startswith("timeout")), None)
            if not timeout_line:
                failures.append(f"'{parent}': no 'timeout' command found.")
            else:
                expected_timeout = golden_timeouts[idx] if idx < len(golden_timeouts) else None
                actual_timeout = timeout_line.split()[-1]
                if expected_timeout and not re.match(r"^<.*>$", expected_timeout) and actual_timeout != expected_timeout:
                    failures.append(
                        f"'{parent}': timeout '{actual_timeout}' does not match the corporate standard '{expected_timeout}'."
                    )
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

            defined_server_names = {block[0].split()[-1] for block in tacacs_blocks}
            for child in children:
                if child.startswith("server name"):
                    referenced_name = child.split()[-1]
                    if referenced_name not in defined_server_names:
                        failures.append(
                            f"'{parent}': references server '{referenced_name}', which has no matching "
                            f"'tacacs server {referenced_name}' definition."
                        )
        return failures

    def _check_control_00005(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        username_lines = device.all_text(r"^username\s")
        if not username_lines:
            failures.append("No 'username' command found in device configuration.")
        if not device.exists(r"^enable secret\s"):
            failures.append("No 'enable secret' command found in device configuration.")

        # The local emergency (break-glass) user is identified by its
        # 'algorithm-type scrypt' keyword - the one thing that distinguishes
        # it from control_00015's plainer local-admin username line.
        emergency_lines = [line for line in username_lines if "algorithm-type scrypt" in line]
        if not emergency_lines:
            failures.append("No local emergency user with 'algorithm-type scrypt' found.")
        else:
            golden_emergency_line = next(
                (line for line in golden.all_text(r"^username\s") if "algorithm-type scrypt" in line), None
            )
            golden_name = golden_emergency_line.split()[1] if golden_emergency_line else None
            for line in emergency_lines:
                name = line.split()[1]
                priv_match = re.search(r"privilege\s+(\d+)", line)
                priv = priv_match.group(1) if priv_match else None
                if priv != "15":
                    failures.append(f"Emergency user '{name}': privilege level is '{priv}', expected 15.")
                if golden_name and name != golden_name:
                    failures.append(f"Emergency user name '{name}' does not match the corporate standard '{golden_name}'.")

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
        # Unconditional presence check - SSH cannot function without an RSA
        # keypair regardless of whether the device ever zeroized one. A
        # zeroize-then-regenerate later in the file is the normal
        # remediation flow and is fine; only "zeroized with no regeneration
        # anywhere" is a real problem, which this same check already catches.
        if not device.exists(r"^crypto key generate rsa modulus \d+"):
            failures.append("'crypto key generate rsa modulus <bits>' is missing - SSH cannot function without it.")
        if not device.exists(r"^ip ssh version\s"):
            failures.append("'ip ssh version' is not configured - SSH is not enabled.")

        for label, pattern in (
            ("ip ssh version", r"^ip ssh version\s"),
            ("ip ssh time-out", r"^ip ssh time-out\s"),
            ("ip ssh authentication-retries", r"^ip ssh authentication-retries\s"),
        ):
            device_line = device.first_text(pattern)
            golden_line = golden.first_text(pattern)
            if device_line and golden_line:
                expected = golden_line.split()[-1]
                actual = device_line.split()[-1]
                if actual != expected:
                    failures.append(f"'{label}' is set to '{actual}', expected '{expected}' per corporate standard.")
        return failures

    def _check_control_00007(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        key_line = device.first_text(r"^key config-key password-encrypt\s+\S+")
        if not key_line:
            failures.append("'key config-key password-encrypt <device_master_key>' is missing.")
        else:
            master_key = key_line.split()[-1]
            if self._is_weak_secret_value(master_key):
                failures.append(
                    "'key config-key password-encrypt' uses a weak/guessable master key value."
                )
        if not device.exists(r"^password encryption aes"):
            failures.append("'password encryption aes' is missing.")
        return failures

    def _check_control_00008(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        # Owns ACL content/order validation (existence, naming, and rule-by-rule
        # comparison against golden); control_00014 only checks that VTY lines
        # actually bind to a real, existing ACL via 'access-class' - keeping the
        # two controls independent rather than duplicating content checks.
        device_acl_blocks = device.blocks(r"^ip access-list extended\s")
        if not device_acl_blocks:
            return ["No 'ip access-list extended' block found in the running configuration."]

        golden_acl_blocks = golden.blocks(r"^ip access-list extended\s")
        if not golden_acl_blocks:
            return []  # nothing to compare against - existence alone is compliant

        golden_name = golden_acl_blocks[0][0].split()[-1]
        golden_rules = [c for c in golden_acl_blocks[0][1:] if not c.startswith("remark")]

        device_block = next(
            (b for b in device_acl_blocks if b[0].split()[-1] == golden_name), device_acl_blocks[0]
        )
        device_name = device_block[0].split()[-1]
        device_rules = [c for c in device_block[1:] if not c.startswith("remark")]

        failures = []
        if device_name != golden_name:
            failures.append(f"ACL name '{device_name}' does not match the corporate ACL name '{golden_name}'.")

        # Semantic check independent of golden's exact wording: a wildcard
        # mask of 255.255.255.255 wildcards every address bit, so it is
        # functionally identical to 'any' no matter what network value
        # precedes it (conventionally 0.0.0.0) - catches this even if a
        # future golden ACL happens to use the same notation somewhere.
        unrestricted_wildcard = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}\s+255\.255\.255\.255")
        for rule in device_rules:
            if rule.startswith("permit") and unrestricted_wildcard.search(rule):
                failures.append(
                    f"ACL '{device_name}' rule '{rule}' uses a wildcard mask (255.255.255.255) that is "
                    "functionally equivalent to 'any', defeating the purpose of the management ACL."
                )

        if device_rules != golden_rules:
            for i, expected in enumerate(golden_rules):
                actual = device_rules[i] if i < len(device_rules) else None
                if actual != expected:
                    failures.append(
                        f"ACL '{device_name}' rule #{i + 1}: expected '{expected}', "
                        f"found '{actual or 'nothing (ACL ends early)'}'."
                    )
                    break
            else:
                extra = device_rules[len(golden_rules):]
                failures.append(
                    f"ACL '{device_name}' has {len(extra)} extra rule(s) beyond the corporate standard: {extra}."
                )
        return failures

    def _check_control_00009(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        ntp_lines = device.all_text(r"^ntp server\s")
        if not ntp_lines:
            failures.append("NTP server configuration is missing.")
        elif not any("prefer" in line for line in ntp_lines):
            failures.append("'prefer' keyword is missing on the primary NTP server.")

        auth_key_line = device.first_text(r"^ntp authentication-key\s")
        trusted_key_line = device.first_text(r"^ntp trusted-key\s")
        authenticated = device.exists(r"^ntp authenticate") and auth_key_line and trusted_key_line
        if not authenticated:
            failures.append(
                "NTP authentication is not configured "
                "('ntp authenticate' / 'ntp authentication-key' / 'ntp trusted-key' missing)."
            )
        else:
            # The key ID must be the same one everywhere: the authentication key
            # itself, the trusted-key declaration, and each 'ntp server ... key
            # <id>' reference - a mismatch anywhere means that server's time
            # isn't actually being authenticated even though the pieces exist.
            auth_key_id = auth_key_line.split()[2]
            trusted_key_id = trusted_key_line.split()[2]
            if trusted_key_id != auth_key_id:
                failures.append(
                    f"'ntp trusted-key {trusted_key_id}' does not match 'ntp authentication-key {auth_key_id}'."
                )
            for line in ntp_lines:
                key_match = re.search(r"\bkey\s+(\S+)", line)
                if not key_match:
                    failures.append(f"'{line}': missing a 'key <id>' reference to the NTP authentication key.")
                elif key_match.group(1) != auth_key_id:
                    failures.append(f"'{line}': references key '{key_match.group(1)}', expected '{auth_key_id}'.")

        golden_ips = [line.split()[2] for line in golden.all_text(r"^ntp server\s")]
        if golden_ips:
            for line in ntp_lines:
                ip = line.split()[2]
                if ip not in golden_ips:
                    failures.append(f"NTP server '{ip}' does not match any corporate NTP server ({golden_ips}).")
        return failures

    def _check_control_00010(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []
        if not device.exists(r"^logging on"):
            failures.append("'logging on' command is missing.")
        device_host_line = device.first_text(r"^logging host\s")
        if not device_host_line:
            failures.append("Logging host IP address is missing.")
        else:
            golden_host_line = golden.first_text(r"^logging host\s")
            if golden_host_line:
                expected = golden_host_line.split()[-1]
                actual = device_host_line.split()[-1]
                if actual != expected:
                    failures.append(
                        f"Logging host '{actual}' does not match the corporate syslog server '{expected}'."
                    )
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
        group_line = device.first_text(r"^snmp-server group\s+\S+\s+v3\s+priv")
        if not group_line:
            failures.append("SNMPv3 group with 'priv' is not configured.")
        user_line = device.first_text(r"^snmp-server user\s+\S+\s+\S+\s+v3\s+auth\s+sha\s+\S+\s+priv\s+aes")
        if not user_line:
            failures.append("SNMPv3 user is not created with SHA/AES configuration.")
        host_line = device.first_text(r"^snmp-server host\s+\S+\s+version\s+3")
        if not host_line:
            failures.append("SNMP trap host is missing.")
        if not device.exists(r"^snmp-server enable traps"):
            failures.append("'snmp-server enable traps' command is missing.")
        if device.exists(r"^snmp-server community\s"):
            failures.append(
                "An SNMPv1/v2c community string ('snmp-server community') coexists with the SNMPv3 configuration."
            )

        # Referential-integrity check, mirroring the TACACS 'server name'
        # check in _check_control_00004: the group and user lines are each
        # individually well-formed on their own, but the user's own group
        # reference (token 3: 'snmp-server user <name> <group> v3 ...') must
        # also point at a group that actually exists - a typo here means the
        # user silently gets no group/view, which "does the group line
        # exist" and "does the user line exist" checked independently cannot
        # catch.
        if user_line:
            referenced_group = user_line.split()[3]
            if not device.exists(rf"^snmp-server group\s+{re.escape(referenced_group)}\s+v3\s+priv"):
                failures.append(
                    f"'snmp-server user' references group '{referenced_group}', which has no matching "
                    f"'snmp-server group {referenced_group} v3 priv' definition."
                )

        golden_group_line = golden.first_text(r"^snmp-server group\s+\S+\s+v3\s+priv")
        if group_line and golden_group_line:
            actual, expected = group_line.split()[2], golden_group_line.split()[2]
            if actual != expected:
                failures.append(f"SNMP group '{actual}' does not match the corporate group '{expected}'.")

        golden_user_line = golden.first_text(r"^snmp-server user\s+\S+\s+\S+\s+v3\s+auth\s+sha\s+\S+\s+priv\s+aes")
        if user_line and golden_user_line:
            actual, expected = user_line.split()[2], golden_user_line.split()[2]
            if actual != expected:
                failures.append(f"SNMP user '{actual}' does not match the corporate user '{expected}'.")

        golden_host_line = golden.first_text(r"^snmp-server host\s+\S+\s+version\s+3")
        if host_line and golden_host_line:
            actual, expected = host_line.split()[2], golden_host_line.split()[2]
            if actual != expected:
                failures.append(f"SNMP trap host '{actual}' does not match the corporate host '{expected}'.")
        return failures

    def _check_control_00012(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        # Presence-only for wording: whether the banner's content meets corporate
        # legal/policy language is a human judgment call this checker doesn't
        # attempt - see controls.yaml's manual_review flag, which still gates
        # Tool 2's rendering. Delimiter well-formedness IS mechanically
        # checkable, though, and is done here off the raw config text
        # (device.text) rather than ConfigTree's line-object view - Cisco
        # 'banner motd <delim> ... <delim>' isn't line-structured the way
        # every other command in this project is.
        match = re.search(r"^banner motd\s+(\S)(.*)$", device.text, re.MULTILINE)
        if not match:
            return ["'banner motd' is not configured."]
        delimiter, rest_of_line = match.group(1), match.group(2)
        if delimiter not in rest_of_line:
            return [
                f"'banner motd' opening delimiter '{delimiter}' has no matching closing '{delimiter}' - "
                "the banner is malformed/incomplete."
            ]
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

    @staticmethod
    def _exec_timeout_policy_failure(children: list[str], golden_children: list[str] | None, label: str) -> str | None:
        """Presence AND value check for 'exec-timeout <minutes> <seconds>'.

        'exec-timeout 0 0' is a special Cisco IOS value meaning "never time
        out" - always non-compliant regardless of golden. Beyond that, the
        minutes value is compared against golden's own value as a policy
        maximum (not a literal-equality check) - a shorter timeout than
        golden is stricter, not non-compliant.
        """
        line = next((c for c in children if c.startswith("exec-timeout")), None)
        if not line:
            return f"'{label}': 'exec-timeout' is missing."
        parts = line.split()
        if len(parts) < 2 or not parts[1].isdigit():
            return None
        minutes = int(parts[1])
        if minutes == 0:
            return f"'{label}': '{line}' disables session timeout entirely (sessions never expire)."
        if golden_children:
            golden_line = next((c for c in golden_children if c.startswith("exec-timeout")), None)
            golden_parts = golden_line.split() if golden_line else []
            if len(golden_parts) > 1 and golden_parts[1].isdigit():
                golden_minutes = int(golden_parts[1])
                if minutes > golden_minutes:
                    return (
                        f"'{label}': '{line}' ({minutes} minute(s)) exceeds the corporate policy "
                        f"maximum of {golden_minutes} minute(s)."
                    )
        return None

    def _check_control_00014(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        # ACL content (rule-by-rule compliance) is control_00008's job now -
        # this control only confirms VTY actually binds to a real, existing
        # ACL via 'access-class ... in', keeping the two controls independent.
        failures = []

        con_blocks = device.blocks(r"^line con\s")
        golden_con_blocks = golden.blocks(r"^line con\s")
        golden_con_children = golden_con_blocks[0][1:] if golden_con_blocks else None
        if not con_blocks:
            failures.append("No 'line console 0' configuration found.")
        else:
            parent, children = con_blocks[0][0], con_blocks[0][1:]
            if not any(c.startswith("password") for c in children):
                failures.append(f"'{parent}': password is missing.")
            if not any(c.startswith("login local") for c in children):
                failures.append(f"'{parent}': 'login local' is missing.")
            exec_timeout_failure = self._exec_timeout_policy_failure(children, golden_con_children, parent)
            if exec_timeout_failure:
                failures.append(exec_timeout_failure)

        # Evaluated independently, per block - a device may legitimately split
        # VTY lines across multiple ranges (e.g. 'line vty 0 4' + 'line vty 5
        # 15'); every range found must carry the required policy on its own.
        vty_blocks = device.blocks(r"^line vty\s")
        if not vty_blocks:
            failures.append("No 'line vty' configuration found.")
        golden_vty_blocks = golden.blocks(r"^line vty\s")
        golden_vty_children = golden_vty_blocks[0][1:] if golden_vty_blocks else None

        checked_acls: set[str] = set()
        for block in vty_blocks:
            parent, children = block[0], block[1:]
            if not any(c.startswith("password") for c in children):
                failures.append(f"'{parent}': password is missing.")
            if not any(c.startswith("login authentication default") for c in children):
                failures.append(f"'{parent}': 'login authentication default' is missing.")
            exec_timeout_failure = self._exec_timeout_policy_failure(children, golden_vty_children, parent)
            if exec_timeout_failure:
                failures.append(exec_timeout_failure)

            for direction in ("input", "output"):
                prefix = f"transport {direction}"
                transport_lines = [c for c in children if c.startswith(prefix)]
                if not transport_lines or any("telnet" in line or "all" in line for line in transport_lines):
                    failures.append(f"'{parent}': 'transport {direction}' is not restricted to secure protocols.")

            acl_line = next((c for c in children if c.startswith("access-class")), None)
            if not acl_line:
                failures.append(f"'{parent}': no 'access-class' ACL is bound to this VTY line.")
                continue
            if not acl_line.rstrip().endswith(" in"):
                failures.append(f"'{parent}': '{acl_line}' is missing the required 'in' direction keyword.")
            acl_name = acl_line.split()[1]
            if acl_name in checked_acls:
                continue
            checked_acls.add(acl_name)

            if not device.blocks(rf"^ip access-list \S+ {re.escape(acl_name)}\b"):
                failures.append(f"ACL '{acl_name}' referenced by access-class was not found in the configuration.")
        return failures

    def _check_control_00015(self, device: ConfigTree, golden: ConfigTree, control: dict) -> list[str]:
        failures = []

        # A device config is applied sequentially - if 'enable secret' is
        # configured more than once (e.g. once for control_00005's own
        # section, again for this control's section), the LAST occurrence is
        # the one actually in effect, not the first one found in the file.
        enable_secret_lines = device.all_text(r"^enable secret\s")
        if not enable_secret_lines:
            failures.append("Enable secret is missing.")
        else:
            enable_secret_line = enable_secret_lines[-1]
            secret_match = re.search(r"^enable secret\s+(?:\d+\s+)?(\S+)$", enable_secret_line)
            if secret_match and self._is_weak_secret_value(secret_match.group(1)):
                failures.append("'enable secret' uses a weak/guessable value.")

        # The admin-standard local user is identified as the username line
        # WITHOUT 'algorithm-type scrypt' - the inverse of how control_00005's
        # emergency/break-glass user is identified (that one always HAS it).
        # Checking "any username with privilege 15 anywhere" was satisfied by
        # control_00005's own emergency user regardless of what this
        # control's own section actually configured - identifying the
        # specific line closes that gap.
        username_lines = device.all_text(r"^username\s")
        admin_lines = [line for line in username_lines if "algorithm-type scrypt" not in line]
        if not admin_lines:
            failures.append("Local administrator with privilege 15 is not created.")
        else:
            golden_admin_line = next(
                (line for line in golden.all_text(r"^username\s") if "algorithm-type scrypt" not in line), None
            )
            golden_name = golden_admin_line.split()[1] if golden_admin_line else None
            for line in admin_lines:
                name = line.split()[1]
                priv_match = re.search(r"privilege\s+(\d+)", line)
                priv = priv_match.group(1) if priv_match else None
                if priv != "15":
                    failures.append(f"Local administrator '{name}': privilege level is '{priv}', expected 15.")
                if golden_name and name != golden_name:
                    failures.append(
                        f"Local administrator username '{name}' does not match the corporate standard '{golden_name}'."
                    )
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
