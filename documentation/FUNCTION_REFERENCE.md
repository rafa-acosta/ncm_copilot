# Function Reference

Every function and class method in the codebase, excluding trivial `__init__`/dunder methods (dataclass-generated ones aren't listed separately — the dataclass's field list is its "signature"). Grouped by module. `self`/`cls` are omitted from the "Inputs" column where obvious.

## Table of Contents

- [compliance_engine.py](#compliance_enginepy) — Tool 1 evaluation logic
- [config_parser.py](#config_parserpy) — Tool 1 config-tree wrapper
- [report_generator.py](#report_generatorpy) — Tool 1 report rendering
- [report_schema.py](#report_schemapy) — shared JSON report schema
- [main.py](#mainpy) — Tool 1 CLI
- [golden_config_builder.py](#golden_config_builderpy) — Tool 2 rendering engine
- [golden_config_main.py](#golden_config_mainpy) — Tool 2 CLI
- [llm_client.py](#llm_clientpy) — Tool 3 backend client
- [remediation_advisor.py](#remediation_advisorpy) — Tool 3 core logic
- [agent_assisted_coding_advise.py](#agent_assisted_coding_advisepy) — Tool 3 CLI
- [local-llm/healthcheck.py](#local-llmhealthcheckpy) — Tool 4 health check

---

## `compliance_engine.py`

### `class ControlResult` (dataclass)
Outcome of evaluating one control against one device config. Fields: `control_id, title, status, severity, risk, evidence_found, remediation, explanation="", details=[]`. `status` is one of the module-level constants `STATUS_PASS`/`STATUS_FAIL`/`STATUS_EXCEPTION`/`STATUS_MANUAL_REVIEW`. No side effects — pure data.

### `class ControlEvaluator`
Evaluates controls loaded from `controls.yaml` against a device/golden config pair. Holds an optional `exceptions: dict[str, str]` (control_id → reason) passed at construction.

| Method | Inputs | Output | Side effects |
|---|---|---|---|
| `__init__(exceptions=None)` | Optional `{control_id: reason}` dict, typically loaded from a `--exceptions` YAML file. | — | Stores `self.exceptions`. |
| `evaluate_control(control, device_config, golden_config) -> ControlResult` | `control`: one control dict from `controls.yaml`. `device_config`/`golden_config`: raw config text (not file paths). | A `ControlResult`. | None (pure). Dispatches by `control["control_id"]` to a `_check_control_XXXXX` method via `getattr`; only when no such method exists does it check `control["manual_review"]` and, if true, return `MANUAL_REVIEW` without any automated check (raises `ValueError` if neither exists). A checker method always wins when both are present — `control_00012`'s presence-only banner check is the one control this applies to today. |
| `_result(control, status, evidence_found, details) -> ControlResult` (static) | The pieces of a result. | Assembled `ControlResult`, copying `title`/`severity`/`risk`/`remediation`/`explanation` straight from `control`. | None. |
| `_check_control_00001` through `_check_control_00018` (17 methods, one per control except `00007`, which doesn't exist) | `device`, `golden`: `ConfigTree` instances (parsed once per `evaluate_control` call). `control`: the control dict (used for its `not_compliance_conditions` text in some checkers' failure messages, not for `command_template`). | `list[str]` of human-readable failure reasons; empty list = compliant. | None (pure) — each one runs regex checks against `device`/`golden` and returns findings. **Design note**: these do *not* parse `command_template` — each control's compliance logic is hand-written against the actual config syntax, because several controls (AAA group consistency, VTY/TACACS nested blocks, hash-type consistency across N usernames) don't reduce to "does this template match" cleanly. See `ARCHITECTURE_OVERVIEW.md`. |

Module-level constants also defined here: `STATUS_PASS`, `STATUS_FAIL`, `STATUS_EXCEPTION`, `STATUS_MANUAL_REVIEW`, `ACTIVE_CONTROL_IDS` (the set `{control_00001..00015}`, applied unconditionally by `main.py` and `golden_config_builder.py.build()` - there's no flag, this is the only mode; control_00016-00018 stay defined in `controls.yaml` but are never part of it).

---

## `config_parser.py`

### `class ConfigTree`
Thin wrapper around `ciscoconfparse2.CiscoConfParse`, giving the rest of the codebase a small regex-based query surface instead of raw parse-tree access.

| Method | Inputs | Output | Side effects |
|---|---|---|---|
| `__init__(config_text)` | Raw config text (string). | — | Parses immediately via `CiscoConfParse(config_text.splitlines(), syntax="ios")`; stores the result and the original text. |
| `find(pattern) -> list` | Regex string. | List of `ciscoconfparse2` line objects matching `pattern` at **any depth** (parent or child line), not just top level. | None. |
| `exists(pattern) -> bool` | Regex string. | Whether any line matches. | None. |
| `first_text(pattern) -> str \| None` | Regex string. | Stripped text of the first match, or `None`. | None. |
| `all_text(pattern) -> list[str]` | Regex string. | Stripped text of every match. | None. |
| `blocks(parent_pattern) -> list[list[str]]` | Regex matching a parent line. | One list per matching parent: `[parent_text, child1_text, child2_text, ...]`. | None. |

---

## `report_generator.py`

Builds HTML, PDF, JSON, and fleet-summary reports from `list[ControlResult]`.

| Function | Inputs | Output | Side effects |
|---|---|---|---|
| `build_summary(results)` | `list[ControlResult]`. | `dict` with `total`, `counts` (per-status), `compliance_pct`. | None. |
| `group_by_severity(results)` | `list[ControlResult]`. | `list[(severity, [results])]`, ordered High → Medium → Low. | None. |
| `render_html(results, output_path, device_name="")` | Results, a `Path`, an optional label (used as the report title, typically the device config's filename stem). | The `Path` written to. | **Writes `output_path`.** Renders `templates/report_template.html`. |
| `build_fleet_summary(results_by_device)` | `{device_name: [ControlResult]}`. | `dict`: per-device summaries, fleet totals (avg compliance %, fully-compliant count), and `top_failures` (control → fail count/severity/affected devices, sorted worst-first). | None. |
| `render_fleet_html(results_by_device, report_links, output_path)` | Results by device, `{device_name: relative_html_link}` (computed by the caller from its own output-dir layout), a `Path`. | The `Path` written to. | **Writes `output_path`.** Renders `templates/fleet_report_template.html`, sorted worst-compliance-first. |
| `build_report_json(results, device_name="", device_config_path="", golden_config_path="")` | Results plus three optional labels. | A `ComplianceReport` (pydantic model, see `report_schema.py`). | None. |
| `render_json(results, output_path, device_name="", device_config_path="", golden_config_path="")` | Same as above, plus a `Path`. | The `Path` written to. | **Writes `output_path`** (`ComplianceReport.model_dump_json(indent=2)`). |
| `render_pdf(html_path, output_path)` | Path to an already-rendered HTML file, output `Path`. | The `Path` written to. | **Writes `output_path`.** Lazily `import weasyprint` inside this function. |

Module-level constants: `TEMPLATE_DIR`, `TEMPLATE_NAME`, `FLEET_TEMPLATE_NAME`, `SEVERITY_ORDER`, `STATUS_LABELS`.

---

## `report_schema.py`

Pure data, no functions.

| Class | Fields | Notes |
|---|---|---|
| `ControlReportEntry(BaseModel)` | `control_id, title, status (Literal), severity (Literal), risk, evidence_found, remediation, explanation="", details=[]` | Mirrors `ControlResult` field-for-field; `status`/`severity` are constrained to the same literal sets as `compliance_engine.py`'s constants, so a malformed report fails validation immediately instead of silently. |
| `ComplianceReport(BaseModel)` | `device_name, generated_at (datetime), results (list[ControlReportEntry]), device_config_path="", golden_config_path=""` | The two path fields default to `""` (not required) so a `report.json` written before they existed still loads without a validation error. |

---

## `main.py`

Tool 1's CLI. See `RUNNING_THE_APP.md` §2 for usage.

| Function | Inputs | Output | Side effects |
|---|---|---|---|
| `load_controls(path)` | Path to `controls.yaml`. | `list[dict]`. | Reads the file. |
| `load_exceptions(path)` | Path or `None`. | `dict[str, str]` (empty if `path` is `None`). | Reads the file if given. |
| `_evaluate_device(device_config_path, golden_config_path, golden_config, controls, exceptions, report_dir, requested_formats)` | A device config path, the golden config's *path* (for recording in the JSON report) and *text* (already read once by the caller, to avoid re-reading it per device in batch mode), the controls list, exceptions dict, an output directory, and the set of requested formats. | `list[ControlResult]`. | **Writes** `report.html`/`.pdf`/`.json` into `report_dir` per the requested formats (via `report_generator.py`'s render functions). |
| `main(...)` (the `@click.command()`) | All CLI flags (see `--help`). | None (calls `raise SystemExit(...)`). | Orchestrates: validates exactly one of `--device-config`/`--device-config-dir` is given, loads inputs, runs `_evaluate_device` once (single mode) or once per `*.txt` file in the directory plus one fleet report (batch mode), prints status lines, exits `1` if any FAIL exists anywhere. |

---

## `golden_config_builder.py`

Tool 2's rendering engine. See `ARCHITECTURE_OVERVIEW.md` for the design rationale behind several of these (the `<MISSING:...>` mechanism, the TACACS special case, the "subsumed" controls).

| Function/Method | Inputs | Output | Side effects |
|---|---|---|---|
| `class RenderedControl` (dataclass) | `control_id, text, missing=[]` | — | Pure data — one control's rendered text plus any missing-variable names found while rendering it. |
| `_make_marking_undefined(missing_sink)` | A `list` to append to. | A `jinja2.Undefined` subclass. | The returned class's `__str__` appends the undefined variable's name to `missing_sink` *as a side effect of being stringified during rendering* and returns `<MISSING:name>` instead of raising or going blank. |
| `_load_yaml(path)` / `_load_json(path)` | A path. | Parsed YAML/JSON. | Reads the file. |
| `class GoldenConfigBuilder` | | | |
| `__init__(controls_path, device_vars_path, order_path=None, schema_path="schemas/device_vars.schema.json", strict=False)` | Paths to `controls.yaml`, `device_vars.json`, an optional render-order YAML, the JSON Schema, and a strict flag. | — | Loads and validates all inputs immediately (raises `ValueError` on schema violation — see `_validate_device_vars`). `self.order` defaults to `controls.yaml`'s own key order if no `order_path` given. |
| `_validate_device_vars(schema_path)` | Schema path. | None. | Raises `ValueError` with a human-readable location if `device_vars.json` doesn't match the schema's *shape* rules. |
| `render_control(control_id) -> RenderedControl \| None` | A control ID. | `None` if the ID isn't in `controls.yaml` at all (any typo/unknown ID - every real control_00001-00018 ID has an entry today). Otherwise a `RenderedControl`. Not filtered by `ACTIVE_CONTROL_IDS` itself - can render an inactive control (`00016`-`00018`) directly on request. | Appends to `self.missing`. Dispatches to one of two paths: (1) `control_00012`/`control_00016`/`control_00018` (manual-review or policy-checklist-only, hardcoded by ID regardless of what `controls.yaml` carries) render `config_example` verbatim inside a `! MANUAL REVIEW REQUIRED` comment block; (2) everything else (including `control_00007`/`control_00008`) goes through `_render_tacacs` (only `control_00004`) or `_render_generic`. `_SUBSUMED_BY` is currently empty - no control is pointer-comment-only. |
| `_manual_review_block(control, reason)` (static) | A control dict, a reason string. | Formatted comment block. | None. |
| `_render_generic(control_id, control, values)` | A control ID, its dict, and `device_vars.json`'s section for it. | `(rendered_text, missing_names)`. | None (pure). Extracts required tokens by **regex-scanning `command_template` for `<word>` occurrences directly**, not from the `variables` metadata field (several controls' `variables` lists include documentation-only names never actually used in the template - see `ARCHITECTURE_OVERVIEW.md`). Also strips any line matching `_LINES_DROPPED_ON_RENDER[control_id]` before rendering — currently just `control_00006`'s `crypto key zeroize rsa`, dropped because it's destructive if this file is ever re-applied to an already-provisioned device. |
| `_render_tacacs(control, values)` | `control_00004`'s dict and values. | `(rendered_text, missing_names)`. | None (pure). The one control with a genuinely repeating structure (N TACACS servers) - its `command_template` is pre-converted real Jinja (`{% for server in tacacs_servers %}`), not `<word>` tokens, so it's handled as a hand-rolled special case: a missing `tacacs_servers` list produces one synthetic `<MISSING:tacacs_servers>` entry; a present entry missing a sub-field (`name`/`address`/`key`/`timeout`) gets a per-field `<MISSING:tacacs_servers[i].field>` marker. |
| `build() -> str` | None. | The full rendered config text. | Resets and repopulates `self.missing`. Iterates `self.order` unconditionally filtered to `compliance_engine.ACTIVE_CONTROL_IDS` (control_00001-00015), calling `render_control` for each and concatenating, with a generated header (device hostname pulled from `device_vars["control_00001"]["hostname"]` if present, plus a timestamp). |
| `save(output_path="golden_config.txt") -> str` | Output path. | The rendered text (also returned by `build`). | **Writes `output_path`** (creating parent directories if needed). |

---

## `golden_config_main.py`

| Function | Inputs | Output | Side effects |
|---|---|---|---|
| `main(...)` (the `@click.command()`) | All CLI flags (see `--help`). | None. | Builds a `GoldenConfigBuilder`, calls `.build()`, prints every missing variable if any. In `--strict` mode with anything missing: prints the list, prints an abort message to stderr, **exits `1` without writing any file**. Otherwise: **writes `--output`** regardless of missing variables (with `<MISSING:...>` markers in place), prints a summary. |

---

## `llm_client.py`

Tool 3's pluggable local-LLM client. See `ARCHITECTURE_OVERVIEW.md` for why this is a named registry rather than a hardcoded vLLM-vs-llama.cpp choice.

| Function/Method | Inputs | Output | Side effects |
|---|---|---|---|
| `class BackendUnavailableError(RuntimeError)` | — | — | Raised when no requested/registered backend could be reached. |
| `_config_path(config_path=None)` | Optional explicit path. | A `Path`: the explicit path if given, else `$AGENT_ASSISTED_CODING_LLM_CONFIG` if set, else `<repo_root>/local-llm/config.yaml`. | None. |
| `load_backends_registry(config_path=None)` | Optional path override. | `dict[str, dict]` — the `backends:` map from the config file, or `{}` if the file doesn't exist yet. | Reads the file if it exists. |
| `_is_reachable(base_url, timeout=2.0)` | A base URL. | `bool`. | Makes a real `GET <base_url>/models` HTTP request (via `httpx`). Module-level (not a method) specifically so tests can monkeypatch it directly instead of mocking HTTP. |
| `_launch_hint(name)` | A backend name. | A string: `local-llm/serve_<name>.sh` if that file exists, else `local-llm/serve_<name-with-underscores-stripped>.sh` if *that* exists (handles the `phi4_mini` config-key vs. `serve_phi4mini.sh` filename mismatch - both spellings come from the same spec and don't agree with each other), else `"see local-llm/README.md"`. | Checks the filesystem. |
| `_unavailable_message(registry, note="")` | The loaded registry, optional context string. | A multi-line error message listing every registered backend's name/role/URL/launch hint (or a "no backends configured at all" message if the registry is empty). | None. |
| `select_backend(requested, device_count=1, config_path=None)` | `"auto"` or a specific registered name; how many devices this briefing run covers (affects `auto`'s preference); optional config override. | `(backend_name, base_url, model_name)`. | Pings backend(s) via `_is_reachable`. Raises `BackendUnavailableError` if nothing usable is reachable, or `ValueError`-adjacent via the same exception type if `requested` names an unknown backend. `auto` logic: among reachable backends, prefers `role == "fast_default"` when `device_count > 1` (many LLM calls, latency compounds) and `role == "specialist"` otherwise (quality matters more for a one-off call) - a single reachable backend wins regardless of role. |
| `class LLMClient` | | | |
| `__init__(base_url, backend_name, client=None, model=None)` | A base URL, a backend name (for logging/labeling), an optional pre-built OpenAI-SDK-compatible client object (constructor-injectable so tests can pass a fake without a real server), an optional model name override. | — | Defaults `self.client` to `openai.OpenAI(base_url=base_url, api_key="not-needed")` if not injected. Defaults `self.model` to `backend_name` if not given. |
| `explain(control, finding_details) -> str` | A control dict (uses `title`, `control_id`, `severity`, `risk`, `explanation` — **never `config_example`/`remediation`**), the specific finding's failure-reason strings from the Compliance Checker's report. | The model's response text, stripped. | Makes a real (or fake-injected) chat-completion call. **This is the architectural guarantee**: because `explain()` is never given the command block, its return value can never become remediation command text - it only ever becomes `Finding.explanation`. |

---

## `remediation_advisor.py`

Tool 3's core logic: turns a `ComplianceReport` + `controls.yaml` + an `LLMClient` into a severity-ordered briefing.

| Function/Method | Inputs | Output | Side effects |
|---|---|---|---|
| `class Finding` (dataclass) | `control_id, title, severity, risk, remediation_recommendation, command_block, still_needed_variables, explanation, finding_details=[]` | — | Pure data. `remediation_recommendation`/`command_block` are copied verbatim from `controls.yaml`'s `remediation`/`config_example` fields in `build_finding` - never from the LLM. |
| `load_report(path)` | Path to a `report.json`. | A validated `ComplianceReport`. | Reads and pydantic-validates the file; raises on malformed status/severity. |
| `load_controls_by_id(path)` | Path to `controls.yaml`. | `dict[control_id, control_dict]`. | Reads the file (same load-and-index pattern as `golden_config_builder.py`). |
| `missing_variables(control, device_vars)` | A control dict, an optional `device_vars.json`-shaped dict. | `list[str]` of `<word>` tokens from `control["command_template"]` not already resolved. | None (pure). A value counts as "resolved" if the key is present and is neither `None` nor `""` - a legitimately falsy-but-real value like `0` (e.g. `start_line_number: 0`) is **not** treated as missing (this was a real bug caught by a live end-to-end run, since a naive truthiness check flags `0` as unresolved). |
| `select_findings(report, controls_by_id, severity_min=None)` | The loaded report, the controls dict, an optional minimum severity string (case-insensitive `"low"/"medium"/"high"`). | `list[ControlReportEntry]`: FAIL-status entries only, whose control exists in `controls_by_id`, filtered to severity ≥ the threshold, sorted High → Medium → Low. | None. |
| `build_finding(control, report_entry, device_vars, llm_client)` | A control dict, its `ControlReportEntry` from the report, optional `device_vars.json` dict, an `LLMClient`. | A `Finding`. | Calls `llm_client.explain(...)` (a real network/inference call unless a fake client was injected). |
| `_group_by_severity(findings)` | `list[Finding]`. | `list[(severity, [findings])]`, High → Medium → Low, omitting empty severities. | None. |
| `render_markdown(findings, device_name, backend_label, output_path, generated_at, device_config_path="", golden_config_path="")` | Findings plus labeling/path strings, an output path. | The `Path` written to. | **Writes `output_path`.** Renders `templates/briefing_template.md.j2`; the `device_config_path`/`golden_config_path` lines are omitted entirely from the output if either string is empty (backward compatible with a `report.json` that predates those fields). |
| `render_briefing_json(findings, device_name, backend_label, output_path, generated_at, device_config_path="", golden_config_path="")` | Same as above. | The `Path` written to. | **Writes `output_path`.** Also builds `suggested_device_vars_patch: {control_id: {var: null, ...}}` from every finding's `still_needed_variables`, shaped exactly like `device_vars.json` so it can eventually be merged in directly to pre-fill Tool 2's input. |

---

## `agent_assisted_coding_advise.py`

| Function | Inputs | Output | Side effects |
|---|---|---|---|
| `_backend_label(backend_name, model)` | Strings. | `"<backend_name> (<model>)"`. | None. |
| `main(...)` (the `@click.command()`) | All CLI flags (see `--help`). | None. | Loads and validates the report and controls, resolves a backend (raising a `click.ClickException` wrapping `BackendUnavailableError` on failure — this is what produces the CLI's clean `Error: ...` output instead of a Python traceback), builds every selected `Finding` (each one a real LLM call), writes both output files, prints a summary. |

---

## `local-llm/healthcheck.py`

| Function | Inputs | Output | Side effects |
|---|---|---|---|
| `main() -> int` | None (reads `local-llm/config.yaml` via `llm_client.load_backends_registry`, and adds the repo root to `sys.path` first so it can import `llm_client` from one directory up). | Exit code: `0` if at least one backend is reachable, `1` otherwise. | Prints one `UP`/`DOWN` line per registered backend; if none are up, prints launch hints (reusing `llm_client._launch_hint`, not a separate implementation) and returns `1`. |
