# Architecture Overview

## Design philosophy: `controls.yaml` as the single source of truth

Every one of the four tools reads `controls.yaml`, and none of them hardcodes control content elsewhere. The intent (stated explicitly in `CLAUDE.md` and reiterated in the later specs) is to avoid schema drift: if a control's severity, risk language, or remediation text changes, it changes in exactly one place, and every tool that touches that control — the checker, the golden-config renderer, the LLM briefing — picks it up automatically. In practice this holds, with one caveat worth knowing: `compliance_engine.py` reads a control's *metadata* (`severity`, `risk`, `remediation`, `explanation`) from `controls.yaml` directly, but does **not** derive its compliance-checking *logic* from `command_template`/`not_compliance_conditions` programmatically — those checks are hand-written Python per control (see "Key design decisions" below). So `controls.yaml` is authoritative for *what a control is and why it matters*, but not literally executable as a rulebook the way, say, a JSON Schema is.

## Execution flow, per tool

### Tool 1 — Compliance Checker
1. Load `controls.yaml` (optionally filtered to `--priority-only`'s 15 controls) and an optional `--exceptions` file.
2. Read the device config and golden config as plain text (not parsed yet).
3. For each control, `ControlEvaluator.evaluate_control` parses both texts into a `ConfigTree` (a `ciscoconfparse2` wrapper) and dispatches to that control's own `_check_control_XXXXX` method, which runs its specific regex checks and returns a list of failure reasons (empty = compliant).
4. A control with `manual_review: true` in `controls.yaml` **and no `_check_control_XXXXX` method** skips step 3 entirely and is always `MANUAL_REVIEW`. A checker method, when one exists, always takes precedence over the flag — `control_00012` (Banners) has both: `manual_review: true` still governs Tool 2's rendering (step 2 below), but Tool 1 runs its checker (a presence-only check for `banner motd`) rather than reporting `MANUAL_REVIEW`.
5. A control with failures gets its status flipped from `FAIL` to `EXCEPTION` if `--exceptions` names it (a passing control is never touched by this — an exception can't "improve" a pass).
6. Aggregate all `ControlResult`s and render HTML/PDF/JSON via `report_generator.py`. In batch mode (`--device-config-dir`), steps 2–6 repeat once per device file, plus one additional fleet-summary render.

### Tool 2 — Golden Config Creator
1. Load `controls.yaml`, `device_vars.json` (validated against `schemas/device_vars.schema.json` for *shape*, not completeness), and the render order (`render_order.yaml` by default).
2. For each control ID in the render order: if it's absent from `controls.yaml` (only `control_00007`), skip silently. If it's manual-review-only or one of the two hardcoded policy-checklist IDs (`00016`, `00018`), emit `config_example` verbatim inside a `MANUAL REVIEW REQUIRED` comment. If it's "subsumed" by another control (currently `00008`, whose content control `00014` already fully covers), emit a one-line pointer comment instead of commands. Otherwise, render `command_template` — either the generic `<word>` → `{{ word }}` substitution path, or (only for `control_00004`'s repeating TACACS-server list) a hand-rolled path around real pre-converted Jinja `{% for %}` syntax.
3. Every unresolved variable becomes a visible `<MISSING:name>` marker rather than blank text or a crash, and is recorded for the run's summary.
4. Concatenate every rendered block under a generated header and write it out — unless `--strict` was given and anything was missing, in which case nothing is written and the tool exits nonzero instead.

### Tool 3 — Compliance Remediation Advisor
1. Load and pydantic-validate Tool 1's `report.json`, and `controls.yaml`.
2. Resolve a backend: `select_backend` pings every entry in `local-llm/config.yaml`'s registry and either honors an explicit `--backend <name>` or, for `auto`, prefers the backend whose `role` matches the current workload shape (see below).
3. Filter the report to `FAIL`-status entries at or above `--severity-min`, sorted High → Medium → Low.
4. For each one, call the LLM **only** for a 2–3 sentence explanation grounded in that control's risk/severity/explanation plus the specific finding text — the actual remediation command block is inserted directly from `controls.yaml`'s `config_example` field, never passed through the model.
5. Render both `briefing.md` and `briefing.json`; the JSON output additionally derives a `suggested_device_vars_patch` from every finding's still-missing template variables.

### Tool 4 — Local LLM Setup
1. `install_llama_server.sh` looks up the latest numbered `llama.cpp` GitHub release (the literal "latest" release tag carries no binary assets — it's a rolling marker) and downloads that release's prebuilt **Vulkan** Linux binary into `local-llm/bin/`.
2. `download_models.sh` fetches two pre-quantized GGUF files from Hugging Face into `local-llm/models/`, sanity-checking file size against a known-good value to catch a truncated download.
3. `serve_qwen_coder.sh`/`serve_phi4mini.sh` launch `llama-server` with that model, then confirm GPU offload actually happened by comparing `nvidia-smi` memory usage before/after startup (not by parsing the server's own log — see below).
4. `healthcheck.py` and Tool 3's `select_backend` both just ping `local-llm/config.yaml`'s registered `base_url`s over HTTP; neither has any Tool-4-specific code path.

## Key design decisions and trade-offs

- **Per-control checker functions instead of one generic "diff the `command_template`" engine** (`compliance_engine.py`). Several controls need reasoning a template-diff can't express: AAA's twelve commands must all reference the *same* TACACS group; a VTY block's `access-class` needs its *referenced ACL's own content* inspected for permissiveness, not just its presence; local-account password hashes must be checked for *consistency across N usernames*, not just individually. The cost is 17 small functions instead of one generic one; the benefit is each one can express exactly what "compliant" means for that control, matching what a human auditor would actually check.

- **Two different template-consumption strategies, deliberately** (`golden_config_builder.py` vs. `compliance_engine.py`). The renderer needs `command_template` to be literally executable; the checker doesn't touch it at all. This means `controls.yaml` changes that only affect one tool (e.g. reshaping `control_00004`'s template into a Jinja loop for the renderer) are safe to make without touching the other tool's logic — verified in practice: that TACACS restructuring shipped with zero changes to `compliance_engine.py` or its tests.

- **The LLM in Tool 3 is deliberately given a narrower job than a literal reading of its own spec** (`COMPLIANCE_ANALYZER_PROMPT.md`) asked for. The spec's original design has the model "restate the exact commands... do not invent, modify, or improve them," verified after the fact by comparing its output against the source. That's a probabilistic guarantee. The actual implementation never shows the model the command block at all — it only ever writes the explanatory prose — making "no LLM-generated command text" true by construction rather than by trusting compliance. This was a deliberate deviation, decided explicitly before implementation (see that file's Implementation Notes).

- **A named backend registry instead of a hardcoded engine choice** (`llm_client.py`). The original spec described picking between exactly two *engines*, vLLM or llama.cpp. Real hardware constraints (a 6GB-VRAM laptop GPU) made vLLM impractical entirely, and the actual need turned out to be choosing between two *models* both served by the same engine. `select_backend` was generalized to work off any number of named, role-tagged entries in `local-llm/config.yaml`, which happens to still support the original two-engine case (nothing stops a registry entry's `base_url` from pointing at a vLLM server) without any special-casing.

- **GPU offload confirmation via `nvidia-smi` memory delta, not log parsing** (`local-llm/_serve_common.sh`). The first implementation grepped `llama-server`'s startup log for text like "offloaded to GPU." Live testing against the real binary showed this llama.cpp build's default verbosity prints no such text at all — the log genuinely contains no GPU/device/offload information. The fix compares `nvidia-smi --query-gpu=memory.used` before and after startup instead, which is what actually caught GPU offload happening (or not) during testing.

- **Vulkan, not CUDA, for the local LLM backend on Linux.** `llama.cpp`'s official GitHub releases only publish a prebuilt CUDA binary for *Windows* — there's no compile-free CUDA path on Linux without a full toolchain (which this project's target machine doesn't have). Vulkan is the no-compile GPU path instead, and works through the GPU driver's own Vulkan ICD with no CUDA toolkit involved.

## Known limitations / incomplete areas

None of these are marked `TODO`/`FIXME` in the code (there are none in this codebase) — they're documented gaps, flagged explicitly during development rather than left implicit:

- **`control_00007` doesn't exist.** The source document this project's controls were transcribed from (`support_files/Prompt para VibeCoding.pdf`) jumps from `control_00006` to `control_00008` with no `control_00007` anywhere in it. Every tool treats this as intentional (skip, don't renumber) rather than an error.
- **The Golden Config Creator never renders an ACL's own body.** `control_00014`'s VTY block references an ACL by name (`access-class <vty_acl_name> in`), but no control in `controls.yaml` renders `ip access-list extended <name> ...` content — so a freshly generated `golden_config.txt` references an ACL that's never actually defined in the same file. Confirmed by self-auditing a generated golden config against itself with Tool 1: `control_00014` legitimately fails on exactly this.
- **`control_00016`'s mandatory-command items are never auto-rendered**, even though `controls.yaml` gives it a real `command_template` (added for Tool 1's own CoPP check) — Tool 2 hardcodes it as a manual-review-only control per its own spec's instruction, so a generated golden config's CoPP section is always a placeholder comment, not real commands.
- **Tool 3 only ever reads one device's `report.json` at a time.** Its backend-selection logic supports a `device_count` parameter specifically for multi-device batches (preferring the `fast_default` role when there are many), but nothing in this project currently produces a multi-device JSON report for it to read — Tool 1's batch mode produces a fleet **HTML** report but not an equivalent fleet **JSON** one. `device_count` is always `1` in practice today.
- **The SNMPv2c/v3-coexistence finding isn't demonstrated end-to-end.** It's one of six acceptance-criteria findings that required extending a control's `not_compliance_conditions` beyond the literal source document (see `CLAUDE.md` §11). The real sample device config (`samples/device_config.txt`, transcribed verbatim from a real lab document) has no SNMP configuration at all, so it can only show "SNMP missing entirely," not "v2c coexisting with v3" specifically — that scenario is covered by a dedicated unit test (`tests/test_compliance_engine.py::test_snmp_v2c_coexisting_with_v3_fails`) using a synthetic config snippet instead.
