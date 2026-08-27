# Glossary

Project-specific terms, abbreviations, and internal jargon. For the plain function/file catalog, see [`FUNCTION_REFERENCE.md`](FUNCTION_REFERENCE.md); for how these pieces fit together, see [`ARCHITECTURE_OVERVIEW.md`](ARCHITECTURE_OVERVIEW.md).

**Control / `control_id`** — One security requirement (e.g. "SNMP must use v3 with encryption"), identified by an ID like `control_00011`. IDs are 5-digit, zero-padded, and run `control_00001`–`control_00018` with `control_00007` intentionally missing (a gap in the original source document, preserved rather than renumbered — see `ARCHITECTURE_OVERVIEW.md`). All 17 real controls live as entries in `controls.yaml`.

**`controls.yaml`** — The single source of truth: one YAML list, one entry per control, with a fixed schema (`control_id, title, explanation, command_template, variables, not_compliance_conditions, exceptions, severity, risk, remediation, evidence, deterministic_validation, manual_review, config_example`). Every tool in this project reads it.

**Priority controls / `--priority-only`** — Controls `00001`–`00006` and `00008`–`00015` (14 total) — the ones considered foundational, as opposed to `00016`–`00018` (broader policy-checklist categories without a single deterministic command). The set is defined once as `compliance_engine.PRIORITY_CONTROL_IDS` and reused by both Tool 1 and Tool 2's `--priority-only` flags.

**`deterministic_validation` vs. `manual_review`** — Two boolean fields on each control. `deterministic_validation: true` means a script can check it automatically. `manual_review: true` (currently only `control_00012`, Banners) means the content genuinely requires human judgment (e.g. whether banner wording matches corporate legal policy) — Tool 1 always reports these as status `MANUAL_REVIEW` without attempting an automated check, and Tool 2 always renders them as a flagged placeholder rather than real commands.

**`<PLACEHOLDER>` convention** — In a golden config, a bracketed token like `<hostname>` or `<tacacs_group_name>` means "a real value must exist here and be internally consistent," not "the literal device must contain this exact string." `controls.yaml`'s `command_template` field uses this convention; Tool 2 substitutes real values from `device_vars.json` into these tokens.

**`command_template`** — A control's command(s) with `<word>` placeholders, e.g. `hostname <hostname>`. Used differently by different tools: Tool 2 (`golden_config_builder.py`) renders it literally (converting `<word>` to Jinja's `{{ word }}` and substituting); Tool 1 (`compliance_engine.py`) does **not** parse it at all — each control has its own hand-written check function instead (see `ARCHITECTURE_OVERVIEW.md` for why).

**`config_example`** — A control's fully filled-in, realistic example command block (no `<PLACEHOLDER>` tokens) — contrast with `command_template`, which has them. This is what Tool 3 inserts verbatim as a briefing's "Next step — apply" block.

**`ConfigTree`** — `config_parser.py`'s thin wrapper around the third-party `ciscoconfparse2` library. Turns raw IOS-XE config text into a queryable parent/child object tree, so checks can ask things like "does `line vty 0 15` have a `login local` child line" via regex instead of manual string splitting.

**`ControlResult`** — The dataclass Tool 1 produces per control per device: `control_id, title, status, severity, risk, evidence_found, remediation, explanation, details`. `status` is one of `PASS`/`FAIL`/`EXCEPTION`/`MANUAL_REVIEW`.

**`EXCEPTION` (status)** — A control that would have `FAIL`ed, but a `--exceptions` YAML file names it with a documented reason for this specific audit run. Never applied to a control that already `PASS`es.

**`ComplianceReport` / `ControlReportEntry`** — The pydantic models (`report_schema.py`) defining Tool 1's JSON report shape. Shared between the writer (`report_generator.render_json`) and the reader (`remediation_advisor.load_report`) so both sides can't drift out of sync.

**`device_vars.json`** — Tool 2's input: real per-device values, structured by control (e.g. `{"control_00001": {"hostname": "..."}, "control_00004": {"tacacs_servers": [...], ...}, ...}`). Validated for *shape* (not completeness — partial input is expected) against `schemas/device_vars.schema.json`.

**`render_order.yaml`** — The fixed sequence Tool 2 renders controls in (roughly matching a real IOS-XE config's natural build order: hostname/domain first, AAA before things that depend on it, banners near the end, etc.), so the file isn't hardcoded inline and can be swapped per device role later.

**`<MISSING:variable_name>`** — What Tool 2 writes into the output in place of any template variable `device_vars.json` doesn't resolve, instead of leaving it blank or crashing. In `--strict` mode, any occurrence of this aborts the whole run (and nothing is written) instead.

**"Subsumed" control** — A control whose Tool-2 rendering is a one-line pointer comment instead of real commands, because another control's rendered block already fully covers the same config surface. Currently only `control_00008` (Telnet Blocking), whose `transport input ssh` line is already part of `control_00014`'s (VTY Lines) fuller block — rendering both independently would produce two separate `line vty` stanzas in one file, which real IOS running-config never has.

**`VTY-OPEN` vs. a restrictive ACL** — `VTY-OPEN` is the name used in `samples/device_config.txt` (and the original lab source it was transcribed from) for a deliberately **permissive** ACL bound to the VTY lines (`permit tcp any any eq 22`, `permit tcp any any eq telnet` — no source restriction, and telnet allowed at all) — one of the intentional non-compliance findings the sample device demonstrates. `controls.yaml`'s `config_example` fields instead show a placeholder name like `VTY_ACL_NAME`/`ACME_VTY_MGMT_ACL` for what a properly **restrictive** ACL (scoped to a management subnet, SSH only) should be called.

**`Finding`** — Tool 3's per-control briefing entry (`remediation_advisor.py`): the LLM-written `explanation`, plus `command_block`/`remediation_recommendation` copied verbatim from `controls.yaml` (never from the LLM), plus `still_needed_variables`.

**Backend registry** — `local-llm/config.yaml`'s `backends:` map: `{name: {role, base_url, model_name}}`. `llm_client.py`'s `select_backend` reads this to resolve `--backend auto` or `--backend <name>` to an actual server to talk to. Not tied to any specific inference engine — an entry's `base_url` could point at llama.cpp, vLLM, or anything else that speaks the OpenAI-compatible `/v1` API.

**`role` (`specialist` / `fast_default`)** — A backend registry entry's tag describing what it's for, used by `--backend auto` to pick between multiple reachable backends: `specialist` (currently the larger Qwen2.5-Coder-7B model) is preferred for a single briefing where output quality matters more; `fast_default` (currently the smaller Phi-4-mini) is preferred when briefing many devices, where per-call latency compounds.

**GGUF** — The file format llama.cpp loads models from (a single quantized binary file, e.g. `phi-4-mini-instruct-q4_k_m.gguf`). Both local models in this project are fetched already in this format ("pre-quantized") rather than converted from the original safetensors weights.

**`Q4_K_M` (and `Q3_K_M`)** — A quantization level: how many bits per weight the model is compressed to, trading a small amount of output quality for a much smaller file/VRAM footprint. `Q4_K_M` (~4 bits/weight) is this project's default for both models; `Q3_K_M` is the documented smaller fallback if VRAM runs out (`local-llm/README.md`).

**`-ngl` ("number of GPU layers")** — A `llama-server` flag controlling how many of the model's transformer layers get offloaded to the GPU vs. run on CPU. `-ngl 99` (this project's default) forces effectively all layers onto GPU; a lower number is llama.cpp's graceful partial-offload fallback when a model doesn't fully fit in VRAM.

**Vulkan build (of `llama-server`)** — The specific prebuilt binary this project fetches (`llama-b<N>-bin-ubuntu-vulkan-x64.tar.gz`), chosen because llama.cpp's official releases don't ship a compile-free CUDA binary for Linux at all (only Windows does) — Vulkan is the no-compile GPU path on Linux instead, using the GPU driver's own Vulkan ICD.

**`suggested_device_vars_patch`** — A block in Tool 3's `briefing.json` output, shaped exactly like `device_vars.json` (`{control_id: {variable_name: null, ...}}`), listing every variable a briefed finding still needs filled in. Intended to eventually be mergeable directly into a real `device_vars.json` to help pre-fill Tool 2's input — the concrete mechanism behind `COMPLIANCE_ANALYZER_PROMPT.md`'s acceptance criterion that Tool 3's JSON output "eventually" feed Tool 2.

**Golden config** — The approved reference/baseline IOS-XE configuration a device is audited against (Tool 1's `--golden-config`). Either hand-authored (like `samples/golden_config.txt`) or generated by Tool 2.

**Device config** — The device under audit's actual running-config (Tool 1's `--device-config`), typically the output of `show running-config` on a real device.
