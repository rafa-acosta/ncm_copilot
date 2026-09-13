# Cisco IOS-XE Config Compliance Checker — Project Prompt

> Use this file as the root project prompt in VS Code (e.g. as `CLAUDE.md` or pasted into Claude Code's project context). It defines scope, architecture, and acceptance criteria for building the tool.

## 1. Project Goal

Build a Python-based CLI tool that audits a Cisco IOS-XE device configuration against a **golden config** baseline, using a **controls definition file** (`prompt_agent_assisted_coding.md` / structured YAML/JSON equivalent) to know which commands to check and how to evaluate them. The tool outputs a **pass/fail compliance report** in **HTML and PDF**.

## 2. Inputs

| Input | Description | Format |
|---|---|---|
| `device_config.txt` | The running-config of the device under audit | Plain text (Cisco IOS-XE `show running-config` output) |
| `golden_config.txt` | The reference/approved configuration defining correct values | Plain text, uses `<PLACEHOLDER>` syntax and `!` comments |
| `controls.yaml` (or `.json`) | Structured version of the 18 controls (see §3) | YAML/JSON — to be generated from the existing `prompt_agent_assisted_coding.md` doc |

## 3. Controls Schema

Each control (`control_00001`–`control_00018`, **priority on 00001–00015**) must be modeled with these fields:

```yaml
control_id: control_00001
title: "Hostname"
explanation: "What the control does and why it exists."
command_template: |
  hostname <hostname>
variables:
  - hostname
not_compliance_conditions:
  - "Name does not meet naming convention"
  - "Hostname is generic (router, switch, etc.)"
exceptions:
  - "No specific exceptions identified for this control."
severity: Low   # Low | Medium | High
risk: "Inconsistent hostname hinders asset identification and incident response."
remediation: "Configure hostname per corporate naming convention."
evidence: "The 'hostname' line in running-config."
deterministic_validation: true   # true = script can check automatically
manual_review: false             # true = requires human judgment
config_example: |
  hostname ACME_CR_RT_INT_BLN_01
```

**Task 1:** Convert the 18 controls in `prompt_agent_assisted_coding.md` (Google Doc export) into this YAML/JSON schema — one file, `controls.yaml`, checked into the repo. This becomes the single source of truth the compliance engine reads.

## 4. Core Comparison Logic

For each control where `deterministic_validation: true`:

1. Parse the `command_template` into a matchable pattern (regex or IOS-config-tree parser — evaluate using **[ciscoconfparse2](https://pypi.org/project/ciscoconfparse2/)** or **netutils/ntc-templates** for robust IOS-XE parsing instead of naive string matching).
2. Extract the corresponding block from `golden_config.txt` to determine expected values for each `<variable>`.
3. Search `device_config.txt` for the equivalent command block.
4. Evaluate against `not_compliance_conditions`:
   - Missing command → **FAIL**
   - Present but variable mismatch vs. golden config → **FAIL**
   - Present and matching → **PASS**
5. If an `exceptions` condition is flagged (via CLI flag or exceptions file per device), mark as **EXCEPTION** instead of FAIL.
6. For controls where `manual_review: true` (e.g., banner wording, control_00012), flag as **MANUAL REVIEW REQUIRED** rather than auto-pass/fail.

**Task 2:** Implement `compliance_engine.py` with a `ControlEvaluator` class exposing:
```python
def evaluate_control(control: dict, device_config: str, golden_config: str) -> ControlResult
```
Where `ControlResult` includes: `control_id`, `title`, `status` (PASS/FAIL/EXCEPTION/MANUAL_REVIEW), `severity`, `risk`, `evidence_found`, `remediation`, `details`.

## 5. Report Generation

**Task 3:** Build `report_generator.py` that takes a `list[ControlResult]` and produces:

- **HTML report** (`report.html`) — use Jinja2 templating:
  - Summary dashboard at top: total controls, pass/fail/exception/manual-review counts, compliance %
  - Color-coded table (green/red/yellow/gray) matching the existing Excel checklist convention (mandatory/recommended/prohibited/avoid)
  - Grouped by severity (High → Medium → Low)
  - Each row expandable to show: explanation, evidence found vs. expected, remediation recommendation
- **PDF report** (`report.pdf`) — render from the same HTML template using `WeasyPrint` (preferred, pure-Python, no headless-browser dependency) or `pdfkit`/`wkhtmltopdf` as fallback.

## 6. CLI Interface

**Task 4:** Build `main.py` (entrypoint) using `argparse` or `click`:

```bash
python main.py \
  --device-config device_config.txt \
  --golden-config golden_config.txt \
  --controls controls.yaml \
  --output-dir ./reports \
  --formats html,pdf \
  [--exceptions exceptions.yaml]  # optional per-device exception overrides
```
Evaluates control_00001–00015 unconditionally (see §11's control_00007/00008/16-18 notes) - no `--priority-only` flag exists.

## 7. Suggested Project Structure

```
cisco-compliance-checker/
├── CLAUDE.md                  # this file
├── controls.yaml              # structured control definitions (Task 1)
├── main.py                    # CLI entrypoint (Task 4)
├── compliance_engine.py       # comparison/evaluation logic (Task 2)
├── config_parser.py           # IOS-XE config parsing helpers (ciscoconfparse2 wrapper)
├── report_generator.py        # HTML/PDF report builder (Task 3)
├── templates/
│   └── report_template.html   # Jinja2 template
├── samples/
│   ├── device_config.txt      # sample/test config
│   └── golden_config.txt      # sample/test golden config
├── tests/
│   ├── test_compliance_engine.py
│   └── test_report_generator.py
├── requirements.txt
└── reports/                   # generated output (gitignored)
```

## 8. Tech Stack / Dependencies

- Python 3.11+
- `ciscoconfparse2` — structured IOS-XE config parsing (preferred over raw regex)
- `PyYAML` — controls definitions
- `Jinja2` — HTML report templating
- `WeasyPrint` — HTML → PDF rendering
- `click` — CLI interface
- `pytest` — unit tests

## 9. Acceptance Criteria

- [ ] `controls.yaml` contains all 18 controls in the schema from §3, sourced accurately from `prompt_agent_assisted_coding.md`
- [ ] Tool correctly flags known audit findings from the reference lab environment as **FAIL**, including: TACACS+ key using Type 7 encoding, permissive VTY ACL active instead of restrictive ACL, SNMPv2c community coexisting with SNMPv3, inconsistent local-account password hashing types, conflicting/unauthenticated NTP blocks, missing CoPP policy on control-plane
- [ ] HTML report renders correctly in a browser with color-coded severity and expandable evidence per control
- [ ] PDF report matches HTML content and is generated without a headless browser dependency
- [ ] Tool runs end-to-end via a single CLI command against sample files in `samples/`
- [ ] Unit tests cover at least: hostname match/mismatch, AAA block completeness, VTY ACL mismatch detection, SNMP dual-protocol detection
- [ ] Code follows PEP8, includes docstrings, and control IDs/severity/risk language stay consistent with the source control definitions (English output, even though project docs may be in Spanish)

## 10. Notes for Claude Code

- Prioritize `control_00001`–`control_00015` for the first implementation pass; controls 16–18 (Mandatory/Recommended/Prohibited Commands) are broader policy categories without single deterministic command templates — implement these as a secondary pass once the core engine is stable.
- Preserve the `<PLACEHOLDER>` convention from the golden config when parsing — a placeholder in the golden config means "value must exist and be consistent," not "must equal this literal string."
- Treat `!`-prefixed lines in Cisco configs as comments — exclude them from comparison logic.
- Ask before assuming exception handling behavior for controls marked with exceptions (e.g., "no TACACS server in this environment") — these should be configurable per audit run, not hardcoded.

## 11. Implementation Notes (this build)

- The original source doc, `support_files/Prompt para VibeCoding.pdf`, defined 18 controls but was missing **control_00007** (numbering jumped 00006 → 00008). A later spec revision (`Prompt Agent Assisted Copilot Project.pdf`) defined it for real - **Global password encryption** (`key config-key password-encrypt` + `password encryption aes`) - confirmed verbatim by `support_files/NCM Configuration Script.txt` (the real production reference). `controls.yaml` now has all 18 entries, no gap.
- That same spec revision redefined **control_00008** from "Telnet Blocking" (VTY `transport input ssh` - now fully covered by control_00014's own transport-input check) to **"ACL for VTY"**: a presence-only check (`ip access-list extended <name>` exists, full stop - `_check_control_00008`). Whether that ACL is actually bound to the VTY lines and restrictive rather than permissive is control_00014's job, not control_00008's.
- **Only control_00001–00015 are active by default** in this version - `compliance_engine.ACTIVE_CONTROL_IDS` (1-15, contiguous now that 00007 exists) is applied unconditionally in `main.py` and `golden_config_builder.py.build()`. control_00016–00018 stay fully defined in `controls.yaml`/`render_order.yaml`/`schemas/device_vars.schema.json` for future re-activation, but are never evaluated, scored, or rendered by default. The old `--priority-only` CLI flag (on `main.py`/`golden_config_main.py`) was removed since this is now the only mode - there's no unfiltered "everything including 16-18" mode anymore.
- `support_files/golden_config_router_v01.pdf` (the only usable source — its `.docx` twin is empty) is a concrete lab config, not a `<PLACEHOLDER>` template, and its issues match the acceptance-criteria FAIL list. It was transcribed as `samples/device_config.txt` (the audited device). `samples/golden_config.txt` was authored fresh using the `<PLACEHOLDER>` convention to match it.
- Six acceptance-criteria findings aren't covered by any literal `not_compliance_conditions` in the source doc (TACACS Type 7, permissive VTY ACL content, SNMPv2c/v3 coexistence, inconsistent password hash types, NTP authentication, CoPP). These were added as documented extensions to the relevant controls (00004, 00014, 00011, 00005/00015, 00009, 00016 respectively) rather than invented as new control IDs. Two related findings from the later spec revision are deliberately **not** auto-resolved the same way - see `documentation/CONTROL_UPDATE_REPORT.md`'s Discrepancies section for the TACACS `key 0` (cleartext) and control_00008's `permit ip any any` example.
- See `GOLDEN_CONFIG_CREATOR.md` for the companion tool that generates `golden_config.txt` (consumed by this tool) from `controls.yaml` + `device_vars.json`. It shares this repo's `controls.yaml`; its `golden_config_main.py` entrypoint is separate from this tool's `main.py`.
- See `COMPLIANCE_ANALYZER_PROMPT.md` for the third component, the Compliance Remediation Advisor, which turns this tool's `--formats json` report output into an LLM-assisted remediation briefing. See `LOCAL_LLM_SETUP_PROMPT.md` for the local model backend it talks to.
- See `COMPLIANCE_REPORT_PROMPT.md` for the fifth component, the Compliance Report Generator, which also consumes this tool's `--formats json` report output directly (not a separate `findings.json`) to produce a deterministic, audit-grade Markdown + PDF report.
- Deviation from §4 point 6: `control_00012` (Banners) has `manual_review: true` but is no longer always reported as `MANUAL_REVIEW` by Tool 1 — a deterministic presence check (`banner motd` configured or not) now runs and drives the compliance score (PASS if present, FAIL if absent), so a missing banner is no longer invisible to the compliance percentage. `manual_review: true` still governs Tool 2's golden-config rendering (wording/legal-language approval stays a human call there). See `compliance_engine.py`'s module docstring and `_check_control_00012`.
- See `NCM_Claude_Code_Compliance_Dashboard_Prompt.md` for the sixth component, the Executive Compliance Dashboard (`compliance_dashboard_main.py`), which aggregates every device's Tool 1 `report.json` from one run into a fleet-level KPI/heatmap/drill-down dashboard, purely from `compliance_metrics.py`'s deterministic formulas (no LLM). Two changes it required in Tool 1 itself: (1) a new status, `ASSESSMENT_ERROR` (`compliance_engine.STATUS_ASSESSMENT_ERROR`) — `main.py`'s batch loop now catches a checker's unexpected exception per-control instead of letting it crash the whole device/fleet; (2) `--exceptions exceptions.yaml` entries may now be a dict with approver/ticket/approval_date/expiration_date/compensating_control, not just a plain reason string — `ControlEvaluator` still only ever sees the reason (its `EXCEPTION` logic is unchanged), the richer fields are read independently by `compliance_exceptions.py` for the dashboard, which is also the only place `expiration_date` is enforced. This project has no device metadata (site/country/model/OS/vendor) anywhere in the pipeline and no control is `Critical` severity by default — both are documented gaps in `documentation/RUNNING_THE_APP.md`'s Tool 6 section, not silently faked.
