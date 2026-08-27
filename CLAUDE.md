# Cisco IOS-XE Config Compliance Checker — Project Prompt

> Use this file as the root project prompt in VS Code (e.g. as `CLAUDE.md` or pasted into Claude Code's project context). It defines scope, architecture, and acceptance criteria for building the tool.

## 1. Project Goal

Build a Python-based CLI tool that audits a Cisco IOS-XE device configuration against a **golden config** baseline, using a **controls definition file** (`prompt_vibecoding.md` / structured YAML/JSON equivalent) to know which commands to check and how to evaluate them. The tool outputs a **pass/fail compliance report** in **HTML and PDF**.

## 2. Inputs

| Input | Description | Format |
|---|---|---|
| `device_config.txt` | The running-config of the device under audit | Plain text (Cisco IOS-XE `show running-config` output) |
| `golden_config.txt` | The reference/approved configuration defining correct values | Plain text, uses `<PLACEHOLDER>` syntax and `!` comments |
| `controls.yaml` (or `.json`) | Structured version of the 18 controls (see §3) | YAML/JSON — to be generated from the existing `prompt_vibecoding.md` doc |

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

**Task 1:** Convert the 18 controls in `prompt_vibecoding.md` (Google Doc export) into this YAML/JSON schema — one file, `controls.yaml`, checked into the repo. This becomes the single source of truth the compliance engine reads.

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
  [--priority-only]        # limit to control_00001–00015
  [--exceptions exceptions.yaml]  # optional per-device exception overrides
```

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

- [ ] `controls.yaml` contains all 18 controls in the schema from §3, sourced accurately from `prompt_vibecoding.md`
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

- Source doc `support_files/Prompt para VibeCoding.pdf` defines 18 controls, but **control_00007 does not exist in the source** (numbering jumps 00006 → 00008). `controls.yaml` preserves this gap (17 entries: 00001–00006, 00008–00018) rather than renumbering.
- `support_files/golden_config_router_v01.pdf` (the only usable source — its `.docx` twin is empty) is a concrete lab config, not a `<PLACEHOLDER>` template, and its issues match the acceptance-criteria FAIL list. It was transcribed as `samples/device_config.txt` (the audited device). `samples/golden_config.txt` was authored fresh using the `<PLACEHOLDER>` convention to match it.
- Six acceptance-criteria findings aren't covered by any literal `not_compliance_conditions` in the source doc (TACACS Type 7, permissive VTY ACL content, SNMPv2c/v3 coexistence, inconsistent password hash types, NTP authentication, CoPP). These were added as documented extensions to the relevant controls (00004, 00008/00014, 00011, 00005/00015, 00009, 00016 respectively) rather than invented as new control IDs.
- See `GOLDEN_CONFIG_CREATOR.md` for the companion tool that generates `golden_config.txt` (consumed by this tool) from `controls.yaml` + `device_vars.json`. It shares this repo's `controls.yaml`; its `golden_config_main.py` entrypoint is separate from this tool's `main.py`.
- See `COMPLIANCE_ANALYZER_PROMPT.md` for the third component, the Compliance Remediation Advisor, which turns this tool's `--formats json` report output into an LLM-assisted remediation briefing. See `LOCAL_LLM_SETUP_PROMPT.md` for the local model backend it talks to.
- See `COMPLIANCE_REPORT_PROMPT.md` for the fifth component, the Compliance Report Generator, which also consumes this tool's `--formats json` report output directly (not a separate `findings.json`) to produce a deterministic, audit-grade Markdown + PDF report.
