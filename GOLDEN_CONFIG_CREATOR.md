# Golden Config Creator — Project Prompt

> Companion tool to the Compliance Checker (see `CLAUDE.md`). Use this file as project context in VS Code / Claude Code.

## 1. Project Goal

Build a Python CLI tool that **generates `golden_config.txt`** — a fully rendered, hardened Cisco IOS-XE configuration — by combining:

1. The **controls definition file** (`controls.yaml`, derived from `prompt_vibecoding.md`) — which defines the `command_template` and `variables` for each of the 18 controls.
2. A **device variables file** (`device_vars.json`) — which supplies the actual values for every variable referenced across the controls (hostname, domain, TACACS servers, SNMP users, NTP servers, VTY ACL name, etc.).

The output, `golden_config.txt`, becomes the baseline reference consumed by the separate **Compliance Checker** tool (see `CLAUDE.md`).

## 2. Relationship to the Controls File

`controls.yaml` already defines, per control, a `command_template` with `<placeholder>` tokens and a `variables` list (see schema below, same as used by the Compliance Checker). Example for `control_00001` (Hostname):

```yaml
control_id: control_00001
title: "Hostname"
command_template: |
  hostname <hostname>
variables:
  - hostname
```

The Golden Config Creator's job is: **for every control, substitute each `<variable>` in `command_template` with the value found in `device_vars.json`, then concatenate all rendered blocks in a defined order into `golden_config.txt`.**

## 3. Device Variables Input (`device_vars.json`)

**Task 1:** Define and validate a JSON schema that covers every variable referenced across all 18 controls. Structure it by control for clarity and to support partial/optional sections:

```json
{
  "control_00001": {
    "hostname": "ACME_CR_RT_INT_BLN_01"
  },
  "control_00002": {
    "company_name": "acme.com"
  },
  "control_00003": {
    "tacacs_group": "ACME_TACACS_SERVER_GROUP"
  },
  "control_00004": {
    "tacacs_servers": [
      { "name": "ACME_TACACS_01", "address": "192.168.100.100", "key": "0123456789", "timeout": 10 },
      { "name": "ACME_TACACS_02", "address": "192.168.100.102", "key": "0123456789", "timeout": 10 }
    ],
    "tacacs_group_name": "ACME_TACACS_SERVER_GROUP",
    "source_interface": "Loopback0"
  },
  "control_00005": {
    "user": "admin",
    "privilege_level": 15,
    "password": "0123456789",
    "algorithm_type": "scrypt",
    "enable_secret": "0123456789"
  },
  "control_00006": {
    "ssh_version": 2,
    "ssh_timeout": 60,
    "ssh_auth_retries": 3
  },
  "control_00008": {
    "vty_line_numbers": "0 15",
    "vty_acl_name": "VTY_MGMT_ACL"
  },
  "control_00009": {
    "ntp_ip_address": "10.10.10.100",
    "secondary_ntp_ip_address": "20.20.20.100"
  },
  "control_00010": {
    "ip_syslog_server": "30.30.30.100",
    "syslog_interface": "Loopback0"
  },
  "control_00011": {
    "group_name": "acme_snmp_grp01",
    "user_name": "acme_snmp_user",
    "auth_password": "0123456789",
    "priv_password": "9876543210",
    "snmp_server_ip": "40.40.40.100"
  },
  "control_00012": {
    "message_of_the_day": "Authorized access only. All activity is monitored."
  },
  "control_00013": {
    "minimum_length_number": 10
  },
  "control_00014": {
    "console_password": "REDACTED",
    "console_timeout": "10 0",
    "vty_start_line": 0,
    "vty_end_line": 15,
    "vty_password": "REDACTED",
    "vty_timeout": "10 0",
    "allowed_protocols": "ssh"
  },
  "control_00015": {
    "enable_password": "0123456789",
    "user_name": "admin",
    "user_password": "0123456789"
  },
  "control_00017": {
    "local_admin": "breakglass_admin",
    "strong_password": "0123456789",
    "blocked_time": 120,
    "attempts_number": 3,
    "attempts_time": 60,
    "login_delay": 5,
    "password_length": 10,
    "admin_user": "admin",
    "user_password": "0123456789"
  }
}
```

Note: `control_00016` and `control_00018` (Mandatory Commands / Prohibited Commands) have no `command_template`/`variables` in the source doc — they are policy checklists, not renderable blocks. Skip them in the renderer; leave a `!` comment placeholder in the output noting they must be manually verified against the corporate command blacklist/whitelist.

Note: `control_00007` is a **joker/wildcard control** — reserved in the source doc for a future, not-yet-defined command. All fields are null/empty except a placeholder `config_example`. Skip it in the renderer by default (treat as inactive) unless/until a real `command_template` is defined for it.

**Task 2:** Write `schemas/device_vars.schema.json` (JSON Schema) to validate `device_vars.json` at load time. Fail fast with a clear error naming the missing control/variable if validation fails.

## 4. Rendering Engine

**Task 3:** Build `golden_config_builder.py` with a `GoldenConfigBuilder` class:

```python
class GoldenConfigBuilder:
    def __init__(self, controls_path: str, device_vars_path: str):
        ...

    def render_control(self, control_id: str) -> str:
        """Render a single control's command block using Jinja2,
        substituting <variable> tokens with values from device_vars.json.
        Prefix the block with a '!' comment header: '! control_00001 - Hostname'."""

    def build(self, priority_only: bool = False) -> str:
        """Render all controls (or only control_00001-00015 if priority_only=True)
        in a fixed, logical order (see §5) and concatenate into the final config text."""

    def save(self, output_path: str = "golden_config.txt"):
        """Write the rendered result to disk."""
```

- Use **Jinja2** for substitution: convert each `<variable>` token in `command_template` into `{{ variable }}` at load time (or store templates pre-converted in `controls.yaml`), then render with the values from `device_vars.json`.
- For controls with **repeating structures** (e.g. `control_00004` TACACS servers, which can have 2+ server entries), use a Jinja2 `{% for %}` loop over a list in `device_vars.json` rather than fixed variable names.
- For controls where `deterministic_validation: false` or no clean template exists (banners with multi-line text, mandatory/prohibited command lists), fall back to inserting the `config_example` from `controls.yaml` verbatim, wrapped in a `! MANUAL REVIEW REQUIRED` comment so it's visibly flagged for human customization.
- Preserve the native IOS `!` comment convention throughout — never inline comments that would break config parsing.

## 5. Output Ordering

Render blocks in this fixed sequence (matches typical IOS-XE config build order and control numbering):

```
1. control_00001 – Hostname
2. control_00002 – Domain
3. control_00013 – Passwords (global policy, min-length + encryption)
4. control_00003 – AAA
5. control_00004 – TACACS+
6. control_00005 – Local and emergency users
7. control_00015 – Basic Security (enable secret, admin user)
8. control_00006 – SSH
9. control_00008 – Telnet Blocking / VTY transport
10. control_00014 – VTY & Console Lines
11. control_00009 – NTP
12. control_00010 – Syslog
13. control_00011 – SNMP
14. control_00012 – Banners
15. control_00017 – Recommended Commands (brute-force protection, scrypt default)
16. control_00016 – Mandatory Commands (comment placeholder only)
17. control_00018 – Prohibited Commands (comment placeholder only)
```

**Task 4:** Make this order configurable via a `render_order.yaml` (or a constant list in code) rather than hardcoded inline, so it can be adjusted per device role later (edge router / access switch / core switch variants).

## 6. CLI Interface

**Task 5:** Build `main.py`:

```bash
python main.py \
  --controls controls.yaml \
  --device-vars device_vars.json \
  --output golden_config.txt \
  [--priority-only]        # render only control_00001-00015
  [--order render_order.yaml]
  [--strict]                # fail if any required variable is missing (default: warn + insert <MISSING:var> marker)
```

- `--strict` mode: abort with a clear error listing every missing variable/control before writing any output.
- Non-strict (default) mode: still render the file, but insert a visible `<MISSING:variable_name>` token in place of any unresolved variable, and print a summary of missing values at the end — this lets the user iterate without regenerating the whole file each time.

## 7. Sample Output Snippet (expected style)

```
! =========================================
! GOLDEN CONFIG - Generated by Golden Config Creator
! Device: ACME_CR_RT_INT_BLN_01
! Generated: <timestamp>
! =========================================

! control_00001 - Hostname
hostname ACME_CR_RT_INT_BLN_01

! control_00002 - Domain
ip domain name acme.com

! control_00003 - AAA
aaa new-model
aaa authentication password-prompt LOCAL_PASS:
aaa authentication username-prompt LOCAL_USER:
aaa authentication login default group ACME_TACACS_SERVER_GROUP local
...
```

## 8. Suggested Project Structure

```
golden-config-creator/
├── CLAUDE.md                        # this file
├── controls.yaml                    # shared with Compliance Checker project
├── device_vars.json                 # sample input
├── schemas/
│   └── device_vars.schema.json      # JSON Schema validation (Task 2)
├── render_order.yaml                # control rendering order (Task 4)
├── golden_config_builder.py         # rendering engine (Task 3)
├── main.py                          # CLI entrypoint (Task 5)
├── tests/
│   ├── test_render_control.py
│   ├── test_build_full_config.py
│   └── test_missing_variables.py
├── requirements.txt
└── output/
    └── golden_config.txt            # generated output (gitignored)
```

## 9. Tech Stack / Dependencies

- Python 3.11+
- `Jinja2` — variable substitution / templating
- `PyYAML` — controls & render-order definitions
- `jsonschema` — device_vars.json validation
- `click` — CLI interface
- `pytest` — unit tests

## 10. Acceptance Criteria

- [ ] Tool reads `controls.yaml` and `device_vars.json`, and produces a complete `golden_config.txt` with all 15 priority controls rendered correctly
- [ ] Repeating structures (multiple TACACS servers, multiple NTP servers) render correctly from list-type JSON input
- [ ] Controls without deterministic templates (banners, mandatory/prohibited command lists) are inserted as clearly flagged `! MANUAL REVIEW REQUIRED` blocks, not silently skipped
- [ ] `--strict` mode correctly aborts and lists all missing variables before writing output
- [ ] Default mode renders `<MISSING:variable_name>` markers for unresolved values and prints a summary
- [ ] Output preserves native `!` comment format throughout — no comment syntax that would break IOS parsing
- [ ] Rendering order matches §5 and is configurable via `render_order.yaml`
- [ ] Unit tests cover: full render with complete vars, missing-variable handling (strict and non-strict), multi-entry TACACS/NTP rendering
- [ ] Generated `golden_config.txt` is directly consumable, unmodified, as input to the Compliance Checker tool from the companion project

## 11. Notes for Claude Code

- This tool and the **Compliance Checker** (`CLAUDE.md`) should share the same `controls.yaml` — treat it as a shared/common module or package if both projects live in the same repo, to avoid schema drift between the generator and the validator.
- Keep variable names in `device_vars.json` **identical** to the `variables` list already defined per control in `controls.yaml` — do not introduce new naming conventions, since this file is the direct input to the substitution engine.
- `control_00016` and `control_00018` remain policy/checklist-only controls (no command_template) — do not attempt to auto-render them; treat them as manual-verification placeholders in the generated file.
- Ask before assuming default values for sensitive fields (passwords, keys) — never hardcode plaintext secrets as defaults in the codebase; require them explicitly in `device_vars.json` or via a secrets-manager integration if the user requests one later.

## 12. Implementation Notes (this build)

This tool was built into the same repo as the Compliance Checker (`ncm_copilot`), sharing `controls.yaml` per section 11 above rather than living in a separate `golden-config-creator/` tree. Deviations from the spec as written, and why:

- **Entrypoint is `golden_config_main.py`, not `main.py`.** `main.py` already exists — it's the Compliance Checker's CLI. Overwriting or renaming it would break that tool; `golden_config_main.py` keeps both entrypoints available in the shared repo.
- **`controls.yaml`'s control_00004 (TACACS) was rewritten** from two hardcoded, flat-numbered server slots (`<tacacs_server_name_1>`/`<tacacs_server_name_2>`, one shared key/timeout) to a real Jinja `{% for server in tacacs_servers %}` loop over a `tacacs_servers` list variable, matching this spec's own `device_vars.json` example and the "repeating structures... render correctly from list-type JSON input" acceptance criterion. This only changes metadata the Compliance Checker's `compliance_engine.py` never reads (it evaluates the device config directly via regex, independent of `command_template`/`variables`), so the Compliance Checker's existing tests and behavior are unaffected. No other control's `command_template`/`variables` needed a structural change — control_00009 (NTP)'s two flat server slots already match this spec's own (non-list) `device_vars.json` example for that control.
- **`device_vars.json` uses `controls.yaml`'s actual variable names**, not this spec's illustrative example, where they differ (e.g. `secret_psswd` rather than `enable_secret` for control_00005) — per section 11's own instruction that `controls.yaml` is the naming source of truth.
- **control_00016 and control_00018 are hardcoded to always render as `! MANUAL REVIEW REQUIRED` placeholders**, even though `controls.yaml` happens to carry a real `command_template` for control_00016 (added there for the Compliance Checker's own CoPP evaluation) — per section 11's explicit instruction that these two stay checklist-only and are never auto-rendered.
- **Required substitution variables are extracted by scanning each `command_template` for `<word>` tokens directly**, not read from the `variables` metadata field — several controls' `variables` lists include documentation-only names that never appear in the template itself (e.g. control_00001 lists `company_name/country/type/function/site/device_number` as naming-convention documentation, but the template only contains `<hostname>`), which would otherwise wrongly demand values the renderer never substitutes.

See `CLAUDE.md` for the Compliance Checker this tool's output feeds into.
