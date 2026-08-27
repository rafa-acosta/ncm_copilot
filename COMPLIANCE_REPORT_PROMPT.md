# PROJECT_PROMPT: Compliance Report Generator (VibeCoding)

## Context

This tool is part of **VibeCoding**, a Cisco IOS-XE security hardening framework built around 18 controls defined in `controls.yaml` (the single source of truth, shared with the Compliance Checker and Golden Config Creator).

The Compliance Checker already produces a raw findings analysis (currently via an LLM backend, e.g. `phi4_mini`). That raw output is narratively inconsistent and not audit-ready. **This tool's job is NOT to re-analyze the device config.** Its job is to take the Compliance Checker's structured findings and render them into a professional, audit-grade compliance report (Markdown + PDF via WeasyPrint), following the standards below.

Do not let any LLM step control document structure, field order, severity colors, or placeholder formatting — those must be deterministic, template-driven. The LLM (if used at all) should only ever populate narrow narrative fields (`risk_statement`, `evidence_note`), never structure or values.

---

## 1. Inputs

- `controls.yaml` — control definitions (id, title, severity, remediation guidance, CIS/Cisco reference, `<PLACEHOLDER>` variable list)
- `findings.json` (or equivalent structured output from the Compliance Checker) — one entry per control, containing at minimum:
  ```json
  {
    "control_id": "control_00011",
    "status": "non_compliant | compliant | not_applicable",
    "severity": "high | medium | low",
    "risk_statement": "...",
    "evidence": "raw config lines or show command output that triggered the finding",
    "remediation_commands": "commands using ONLY <PLACEHOLDER> tokens, never example values",
    "operator_inputs_needed": ["<snmp_server_ip>", "<auth_password>", "..."]
  }
  ```
- Device metadata: hostname, device role (edge router / access switch / core switch), audit date, `controls.yaml` version used

## 2. Hard requirements for the generated report

### 2.1 Full document structure (every report must include all sections, in this order)

1. **Cover / version control block** — document title, device hostname, audit date, `controls.yaml` version, classification banner ("Confidential — Internal Use"), generating tool + version
2. **Executive summary** — compliance score and severity breakdown (see 2.2)
3. **Scope & methodology** — frameworks referenced (CIS Cisco IOS-XE Benchmark, Cisco Hardening Guide, VibeCoding 3-plane model), what was evaluated, what was explicitly out of scope
4. **Findings detail** — one entry per non-compliant control, using the fixed schema in 2.3, grouped by severity (High → Medium → Low)
5. **Full control appendix** — table of **all 18 controls**, including passed/compliant and not-applicable ones, not just failures
6. **Remediation roadmap** — findings sorted by severity with SLA dates (2.5)
7. **Sign-off block** — space for Network and Security team approval (name, role, date, signature line)

A report missing any of these sections is incomplete — never omit the passed-controls appendix or the sign-off block even if there are zero failures.

### 2.2 Executive summary must include a literal metrics block

```
Compliance Score: <compliant_count>/18 controls compliant (<percentage>%)
🔴 High:   <n> findings
🟡 Medium: <n> findings
🟢 Low:    <n> findings
✅ Passed: <n> controls
⚪ N/A:    <n> controls
```

Compute this from `findings.json` — never let an LLM estimate or phrase this block; it must be arithmetic, not narrative.

### 2.3 Fixed per-finding schema (identical field order for every finding, no exceptions)

```
### [control_XXXXX] <Control Title> — <SEVERITY>
Status: NON-COMPLIANT
Reference: CIS Cisco IOS-XE Benchmark §<ref> | VibeCoding controls.yaml v<version>

Risk Statement: <one sentence, no filler, no "this needs to be addressed before...">
Evidence: <verbatim config line(s) or show-command output that triggered the finding>

Remediation Command:
```
<commands — placeholders only, e.g. <snmp_server_ip>, never 0123456789 or other example values>
```

Operator Inputs Required: <comma-separated list of placeholder tokens>
Owner: Network Security Team
Target Remediation Date: <computed from SLA table in 2.5>
```

Reject/regenerate any finding text that contains generic LLM filler phrases (e.g. "these issues need to be addressed to ensure...", "this is important because..."). Risk Statement is capped at one sentence — enforce this as a hard length/format check before including it in the report, not just a style preference.

### 2.4 Placeholder consistency (non-negotiable)

- Every value in "Remediation Command" blocks must be a `<PLACEHOLDER>` token — **never** a realistic-looking example value (no `0123456789`, no `9876543210`, no plausible-looking IPs/keys standing in for real ones).
- The set of tokens used in "Remediation Command" must exactly match the set listed in "Operator Inputs Required" for that finding — validate this programmatically and fail the build if they diverge.
- This is stricter than the raw Compliance Checker output, which currently mixes hardcoded example secrets with proper placeholders — the report generator must normalize this, not just pass it through.

### 2.5 Remediation SLA table (apply to every finding automatically by severity)

| Severity | SLA |
|---|---|
| High | ≤ 15 days or next maintenance window |
| Medium | ≤ 30 days |
| Low | ≤ 90 days or next refresh cycle |

Compute `Target Remediation Date` = audit date + SLA, don't leave it as a free-text field.

### 2.6 Visual elements

- Executive summary rendered as a real table (Markdown table in the .md output; an actual styled table, not an image, in the PDF via WeasyPrint CSS)
- A compliance donut/bar chart (% compliant) — generate as inline SVG or via a lightweight charting step feeding into WeasyPrint, not a hand-drawn placeholder
- Consistent severity iconography across the whole document: 🔴 High, 🟡 Medium, 🟢 Low, ✅ Compliant, ⚪ Not Applicable — never introduce a new icon set mid-document

## 3. Architecture / tech stack (consistent with existing VibeCoding tools)

- **Input parsing**: read `controls.yaml` + `findings.json`, validate schema with `pydantic` before rendering (fail fast on missing fields — do not attempt to render a partial report)
- **Templating**: Jinja2 template(s) implementing the exact structure in Section 2 — structure, field order, and icon/severity mapping live in the template, not in prompt text to an LLM
- **Rendering**: WeasyPrint for PDF output from the rendered HTML/CSS; also emit the raw Markdown as a secondary artifact for diffing/version control
- **CLI**: `click`-based, e.g. `compliance-report generate --findings findings.json --controls controls.yaml --device-role edge-router --out report.pdf`
- **Tests**: `pytest` cases asserting — (a) all 18 controls appear in the appendix regardless of pass/fail, (b) placeholder/operator-input sets match exactly per finding, (c) executive summary counts match the sum of individual finding statuses, (d) no finding text matches a deny-list of generic LLM filler phrases

## 4. Acceptance criteria

- [ ] Given a `findings.json` with N non-compliant controls, the generated report contains exactly N detailed findings plus all 18 controls in the appendix
- [ ] Executive summary percentage is arithmetically correct and matches appendix counts
- [ ] Every "Remediation Command" block contains only `<PLACEHOLDER>` tokens, verified against `Operator Inputs Required` with zero mismatches
- [ ] No finding contains repeated boilerplate phrasing (validate against a filler-phrase deny-list)
- [ ] PDF and Markdown outputs are both produced from the same rendered data (no drift between formats)
- [ ] Document includes cover block, scope/methodology, full appendix, roadmap with SLA dates, and sign-off block — build fails if any section is missing
- [ ] Tool runs standalone via CLI and can be invoked as a follow-up step after the Compliance Checker in the same pipeline

## 5. Explicitly out of scope

- Re-analyzing the device configuration (that's the Compliance Checker's job — this tool only consumes its structured output)
- Any free-form LLM narrative beyond `risk_statement`/`evidence_note` fields, and even those must pass the filler-phrase and length checks in 2.3/3

## 6. Implementation Notes (this build)

- **The spec's premise about where findings come from doesn't match this codebase.** It says the Compliance Checker's raw output already comes "via an LLM backend" — but `main.py`/`compliance_engine.py` (the actual Compliance Checker) is fully deterministic; no LLM is involved anywhere in producing its `report.json`. The LLM only appears in `vibecoding_advise.py` (the separate Compliance Remediation Advisor, see `COMPLIANCE_ANALYZER_PROMPT.md`), which runs *after* this tool's input is already produced and only touches FAIL findings. This tool consumes Tool 1's real `report.json` (`report_schema.ComplianceReport`) directly rather than inventing a separate `findings.json` format — that artifact already exists and already contains all 17 controls' status/severity/evidence/remediation.
- **No CIS Cisco IOS-XE Benchmark mapping exists anywhere in this repo.** Confirmed before implementation, and confirmed with the user rather than fabricated: the Reference line omits the CIS clause entirely (`VibeCoding controls.yaml v<version>` only). An operator with a real CIS mapping can extend `compliance_report_builder.py`'s per-finding row construction later.
- **`controls.yaml` has no version field.** Restructuring it to add one would break every other tool's `yaml.safe_load()` (all expect a bare list). `<version>` is instead the short git commit hash of `controls.yaml`'s last change (`compliance_report_builder.controls_version`), falling back to `"unknown"` outside a git repo.
- **Status model**: this system's actual states are `PASS`/`FAIL`/`EXCEPTION`/`MANUAL_REVIEW`, not the spec's literal `compliant`/`non_compliant`/`not_applicable`. Collapsing `EXCEPTION` into "compliant" would misrepresent a documented waiver as a clean pass in an audit document, so it's tracked as its own status throughout (`compliance_report_schema.FindingStatus`) and appears in Findings Detail with its exception reason shown, not silently folded into the pass count. `not_applicable` is rendered as always-0 - this system has no not-applicable concept for any control today, and reporting a fabricated count would be worse than an honest zero. `MANUAL_REVIEW` controls get their own report subsection (neither confirmed-compliant nor confirmed-non-compliant), inserted after Findings Detail.
- **"Remediation Command" is sourced from `controls.yaml`'s `command_template` field**, not `config_example` (Tool 3 deliberately uses that one instead, for the opposite reason - literal example values, never LLM-touched) and not `remediation` (prose guidance, not a command block). For 16 of 17 controls `command_template` is already exactly the placeholder-only text this section needs, used as-is. `control_00004` (TACACS) is a documented special case: its `command_template` is real pre-converted Jinja for the Golden Config Creator's benefit, not `<word>` tokens, so this tool carries its own small hardcoded placeholder-style block for that one control (`compliance_report_builder._CONTROL_00004_PLACEHOLDER_COMMAND`).
- **"Operator Inputs Required" is extracted by regex from the exact same string used as the Remediation Command**, not computed independently and cross-checked afterward - the same architectural-guarantee pattern already used for Tool 3's command-sourcing, making "the two sets match exactly" (acceptance criterion) true by construction rather than by a separate validation pass.
- **Risk Statement is deterministic by default**: the first sentence of `controls.yaml`'s `risk` field, validated against a length cap and a filler-phrase deny-list; a control that fails validation fails the whole build with a clear, control-naming error (matching "a hard... check," not a style preference). An **optional** `--llm-polish` flag lets a local LLM (via the existing `local-llm`/`llm_client.py` infrastructure) retry exactly that field once, through a purpose-built system prompt (`llm_client.RISK_STATEMENT_SYSTEM_PROMPT`/`LLMClient.polish_statement`) - the rewrite is re-validated against the identical checks before being accepted, never trusted blindly. Default mode has zero dependency on a running local LLM.
- **"Evidence Note" isn't a separate field in the fixed per-finding schema (§2.3)** - only "Evidence:" appears there; treated as the same field (an internal wording inconsistency in this spec, not a real second field), sourced deterministically from Tool 1's `evidence_found`, never LLM-touched.
- Entrypoint is `compliance_report_main.py` (run as `python compliance_report_main.py ...`), not a packaged `compliance-report` console script - this repo has no packaging infrastructure, same reasoning as `golden_config_main.py`/`vibecoding_advise.py`.
