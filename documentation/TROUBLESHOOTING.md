# Troubleshooting Guide

Every issue below is organized as **Symptom → Cause → Resolution**. If you just want the fast lookup, use the index; if you're debugging something that isn't a crash (a report says something you didn't expect), skip to [§9 Data & content pitfalls](#9-data--content-pitfalls) or [§10 "Why did my report say that?"](#10-why-did-my-report-say-that--a-debugging-method) — those cover the issues that don't announce themselves with an error message.

For flag references and usage examples, see [`RUNNING_THE_APP.md`](RUNNING_THE_APP.md). For what each file/folder is, see [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md). For internal function behavior, see [`FUNCTION_REFERENCE.md`](FUNCTION_REFERENCE.md).

## Index

| I'm seeing... | Go to |
|---|---|
| `ModuleNotFoundError` / venv problems | [§1](#1-environment--installation) |
| PDF output fails or WeasyPrint errors | [§1](#1-environment--installation) |
| `Provide exactly one of --device-config or --device-config-dir` (or similar) | [§2](#2-tool-1--compliance-checker-mainpy) |
| `<MISSING:...>` markers in a generated golden config | [§3](#3-tool-2--golden-config-creator-golden_config_mainpy) |
| `device_vars.json is invalid at ...` | [§3](#3-tool-2--golden-config-creator-golden_config_mainpy) |
| `No local LLM backend is reachable` | [§4](#4-tool-3--compliance-remediation-advisor-cra) and [§5](#5-local-llm-backend-local-llm) |
| llama-server won't start / OOM / no GPU offload | [§5](#5-local-llm-backend-local-llm) |
| A CRA batch run skips devices | [§4](#4-tool-3--compliance-remediation-advisor-cra) |
| A control's risk statement fails validation (Tool 5) | [§6](#6-tool-5--compliance-report-generator-compliance_report_mainpy) |
| `No report.json found directly under <dir>` | [§4](#4-tool-3--compliance-remediation-advisor-cra) or [§7](#7-tool-6--executive-compliance-dashboard-compliance_dashboard_mainpy) |
| A control PASSes/FAILs when you expected the opposite | [§9](#9-data--content-pitfalls) and [§10](#10-why-did-my-report-say-that--a-debugging-method) |
| `pytest` failures after editing `controls.yaml`/`device_vars.json`/a fixture | [§11](#11-running-the-test-suite) |

---

## 1. Environment & Installation

| Symptom | Cause | Resolution |
|---|---|---|
| `ModuleNotFoundError: No module named 'click'` (or any package) | The venv isn't activated, or dependencies were never installed. | `source .venv/bin/activate` first — every command in this project assumes it. If the venv doesn't exist yet: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`. |
| `python3 -m venv .venv` fails with `ensurepip is not available` | Common on minimal Debian/Ubuntu installs. | `sudo apt install python3-venv`, or bootstrap manually: `python3 -m venv --without-pip .venv && curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && .venv/bin/python3 /tmp/get-pip.py`. |
| PDF requested (`--formats pdf`, `--out`, etc.) but WeasyPrint raises an import error | Pango/Cairo/GDK-Pixbuf system libraries aren't installed — pip installing `WeasyPrint` alone isn't enough. | Debian/Ubuntu: `sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0`. HTML/JSON/Markdown output need nothing beyond the pip packages, so this only bites when you ask for PDF. |
| `yaml.scanner.ScannerError` / `yaml.parser.ParserError` | Malformed `controls.yaml`, `render_order.yaml`, or an `--exceptions`/`device_vars.json`-adjacent YAML file. | The traceback includes a line/column — open the file at that exact spot. Common causes: an unquoted colon inside a string value, inconsistent indentation, a tab character (YAML requires spaces). |
| Everything works but is slower than expected / feels "off" on non-Linux | The four Python tools (`main.py`, `golden_config_main.py`, `compliance_report_main.py`, `compliance_dashboard_main.py`) aren't Linux-specific, but `local-llm/`'s scripts are bash and fetch a Linux binary release, and the whole project is only tested on Ubuntu-based Linux (Python 3.14.4). | Nothing to fix per se — if you're on macOS/Windows, expect to run everything except `local-llm/` fine; the LLM backend needs a Linux (or WSL2) environment. |

## 2. Tool 1 — Compliance Checker (`main.py`)

| Symptom | Cause | Resolution |
|---|---|---|
| `Provide exactly one of --device-config or --device-config-dir.` | Both flags given, or neither. | Pass exactly one — a single file for one device, a directory for batch mode. |
| `No *.txt device config files found in <dir>.` | `--device-config-dir` points at an empty folder, or one whose files aren't named `*.txt`. | Check the path and extension; only files directly inside the directory are picked up (not recursive). |
| A control shows status `ASSESSMENT_ERROR` instead of PASS/FAIL | That control's checker (`compliance_engine.py::_check_control_XXXXX`) hit an unexpected exception — usually a device config with a structure the regex/block parser didn't anticipate (e.g. a malformed line, an unusual indentation). | This is a per-control isolation, not a crash — the rest of the run completes normally (see `main.py`'s batch loop). Open the control's `details` field in the JSON report for the exception message and traceback-adjacent text; fix the device config or, if the config is legitimately valid Cisco syntax the checker doesn't handle, that's a real bug in `compliance_engine.py` worth reporting. |
| Exit code is `1` and you expected `0` (or vice versa) | This is deliberate, not a bug: exit code `1` means at least one control FAILed (single-device) or at least one device had a FAIL (batch) — it's meant to be wired into CI/scripts. | Check `$?` after the run, or look at the console's closing summary line (`Evaluated N controls: M FAIL.` / `Audited N device(s): M total FAIL.`). An `EXCEPTION`-status control doesn't count toward this — only real FAILs do. |
| An exception you granted in `--exceptions` doesn't seem to apply | Exceptions only override a control that would otherwise FAIL — a control that already PASSes is unaffected, and the `control_id` key must match exactly (typo-sensitive). | Confirm the control actually FAILs without the exceptions file first, and that the YAML key matches the control_id verbatim (`control_00004`, not `Control_00004` or `control_4`). |

## 3. Tool 2 — Golden Config Creator (`golden_config_main.py`)

| Symptom | Cause | Resolution |
|---|---|---|
| `<MISSING:some_variable>` appears in the rendered `golden_config.txt` | `device_vars.json` doesn't supply that control's variable (partial input is expected in non-strict mode). | Add the missing key under the right `control_XXXXX` section in `device_vars.json`. The console also prints every missing entry after writing the file (e.g. `control_00002.company_name`) — use that list rather than hunting through the output by eye. |
| `ValueError: device_vars.json is invalid at '<path>': ...` | `device_vars.json` was validated against `schemas/device_vars.schema.json` and failed — either a wrong type (e.g. a string where an integer is expected) or a key the schema doesn't recognize. | The message names the exact path (e.g. `control_00004.tacacs_servers.0.timeout`) and what's wrong. Fix the value's type, or remove/rename the unrecognized key. This check is shape-only — it does **not** catch missing values, only malformed ones. |
| `Aborting: --strict mode requires every variable to be resolved. No file was written.` | You passed `--strict` and at least one variable is still missing. | Either supply the missing values in `device_vars.json`, or drop `--strict` if you're fine with a `<MISSING:...>`-marked file for now (e.g. while iterating). Never feed a `--strict`-failing (or unresolved) golden config into Tool 1 for a real audit — every `<MISSING:...>` marker will be compared literally against device text and never match. |
| The rendered `golden_config.txt` doesn't match `support_files/NCM Configuration Script.txt` (the real production reference) even though `--strict` succeeds | `--strict` only proves every variable was *resolved* — it says nothing about whether `controls.yaml`'s `command_template` for a given control is itself structurally correct (right line order, right repeating-structure shape, no stray/missing lines). This is a real gap found and fixed once already (`GOLDEN_CONFIG_CREATOR.md` §12's "Golden Config Creator realignment" entry) — TACACS key type, the ACL rule list, and the VTY line-range structure had all drifted from the real script before that fix. | Diff the generated file against the reference, ignoring comments/blank lines (`!`-prefixed lines and blank lines carry no meaning to Cisco or to this project's own `ConfigTree`): `diff <(grep -v '^!' golden_config.txt | sed '/^\s*$/d') <(grep -v '^!' "support_files/NCM Configuration Script.txt" | sed '/^\s*$/d')`. Any remaining difference points at a `command_template` in `controls.yaml` that needs fixing, not a `device_vars.json` problem. |
| A control renders with the wrong content even though its `command_template` in `controls.yaml` looks right | Three controls (`control_00004` TACACS, `control_00008` ACL, `control_00014` VTY) have a genuinely repeating structure and are rendered by dedicated special-case methods in `golden_config_builder.py` (`_render_tacacs`, `_render_acl`, `_render_vty`) rather than the generic `<word>`-token engine — they read a **list** from `device_vars.json` (`tacacs_servers`, `acl_rules`, `vty_ranges` respectively), not scalar tokens. | Check `device_vars.json`'s list field for that control is present and shaped correctly (an array of objects/strings, not a single value) — see `schemas/device_vars.schema.json` for the exact shape each expects. |

## 4. Tool 3 — Compliance Remediation Advisor (CRA)

| Symptom | Cause | Resolution |
|---|---|---|
| `Error: No local LLM backend is reachable. ...` (lists every registered backend with a launch hint) | No `local-llm/serve_*.sh` script is currently running, or it hasn't finished loading the model yet. | Start one: `./local-llm/serve_qwen_coder.sh` or `./local-llm/serve_phi4mini.sh` (only one at a time — see [§5](#5-local-llm-backend-local-llm)). **Wait for it to finish loading** (10-30s for a 7B GGUF model) before retrying — `python local-llm/healthcheck.py` confirms readiness without guessing. This message is informational, not a bug: the text after each backend's colon (e.g. `local-llm/serve_qwen_coder.sh`) *is* the fix it's telling you to run. |
| `Error: Unknown backend '<name>'. Known backends: ...` | `--backend <name>` doesn't match any entry in `local-llm/config.yaml`'s registry (typo, or a custom backend never added there). | Check spelling against `local-llm/config.yaml`, or use `--backend auto` to let it pick whichever registered backend is actually reachable. |
| `pydantic.ValidationError` while loading `--report` | The JSON file isn't a valid `ComplianceReport` — wrong tool produced it, it's from an incompatible/older version, or it's corrupted/truncated. | Regenerate it with `main.py --formats json`. If you're loading an old archived report after a `report_schema.py` change, it may genuinely be incompatible — re-run Tool 1 against the same device/golden config to get a fresh one. |
| `Provide exactly one of --report or --reports-dir.` | Both flags given, or neither. | Use `--report <file>` for one device, `--reports-dir <dir>` for a batch (see the next row for the expected directory shape). |
| `No report.json found directly under <dir> ...` | `--reports-dir` doesn't have `report.json` (single-device layout) or `*/report.json` (Tool 1 batch layout) directly inside it. This check is deliberately non-recursive. | Point it at a specific run directory (e.g. `reports/latest`), not the whole `reports/` archive root — the archive root has `reports/<timestamp>/<device>/report.json`, one directory level too deep, and would otherwise silently pull in every historical run's devices if it *were* recursive. |
| `--output-md/--output-json are single-device only - not valid with --reports-dir.` | Those two flags write to one fixed filename, which can't hold N devices' output. | Drop them in batch mode (batch always uses `--output-dir`'s timestamped/`latest/` archive), or switch to `--report` for a single device if you specifically need a fixed filename. |
| A batch run's summary says some devices were skipped (`Briefed 74/75 device(s) (1 skipped due to errors).`) | One device's `report.json` failed to load (malformed/corrupted JSON) or its LLM call failed mid-request — this is caught per-device so it doesn't abort the other 74. | Check stderr for the `WARNING: skipped <path> - <ExceptionType>: <message>` line naming which device and why. Re-run CRA with just that one device's `--report` to see the full error without the batch's other output interleaved. |
| A batch run exits with code `1` even though most devices were briefed fine | Exit code `1` only fires when **every** device failed (nothing usable was written) — partial success (some briefed, some skipped) exits `0`, since CRA is advisory, not pass/fail. If you're seeing `1`, check whether the backend itself dropped mid-run (e.g. OOM-killed) rather than each device failing independently. | Check whether the LLM backend process is still alive (`ps aux | grep llama-server`) — if it died partway through a large batch, every subsequent device would fail identically. Restart it and re-run. |
| The briefing's explanation text seems generic or slightly off-topic | The LLM is only ever given the control's title/severity/risk/purpose text and that device's specific finding details — never the remediation commands themselves (by design, see `remediation_advisor.py`'s module docstring: commands are sourced verbatim from `controls.yaml`, never LLM-generated). A small/fast model (Phi-4-mini, auto-preferred for batches) can produce blander prose than the larger specialist model. | For higher-quality single-device explanations, force the specialist backend: `--backend qwen_coder`. This never affects the remediation **commands** shown, which are always the literal `config_example` text regardless of backend. |

## 5. Local LLM Backend (`local-llm/`)

| Symptom | Cause | Resolution |
|---|---|---|
| `llama-server not found at .../bin/llama-server` | The binary was never fetched. | `./local-llm/install_llama_server.sh` (one-time, ~15MB download). |
| `Model file not found: ...` | The GGUF model files were never downloaded. | `./local-llm/download_models.sh` (one-time, ~6.7GB total — needs ~7GB free disk). |
| Both `serve_qwen_coder.sh` and `serve_phi4mini.sh` running at once, one OOMs or both perform badly | Combined VRAM (~4.5-4.8GB + ~2.2-2.5GB ≈ 7GB) exceeds a 6GB card even before OS/display overhead — this project's target hardware. | Run only one at a time. `pkill -f llama-server` to stop whichever is running, then start the one you actually need. `--backend auto` already only ever expects one to be up. |
| Model fails to load (out-of-memory) even running alone | VRAM is tighter than the ~4.5-4.8GB (Qwen) / ~2.2-2.5GB (Phi-4-mini) budget on your specific card (display compositor overhead, other GPU processes, etc.). | Work down this ladder (env vars, no script editing needed): (1) `LLAMA_CTX_SIZE=2048 ./serve_qwen_coder.sh` — cheapest fix; (2) download the smaller `Q3_K_M` quant (`hf download Qwen/Qwen2.5-Coder-7B-Instruct-GGUF qwen2.5-coder-7b-instruct-q3_k_m.gguf --local-dir local-llm/models`) and point at it with `LLAMA_MODEL_FILE`; (3) `LLAMA_NGL=20 ./serve_qwen_coder.sh` for partial GPU/CPU split (slower, last resort). Combine as needed. |
| Server starts but the "GPU offload confirmed" line is replaced by a "GPU memory usage barely changed" warning | Running on CPU only — a Vulkan driver issue, or `-ngl` set too low. | Confirm your GPU driver exposes a working Vulkan ICD (`vulkaninfo` if available). Check `LLAMA_NGL` hasn't been set low from a previous session's env var leaking into this shell. See `local-llm/README.md`'s fallback ladder if Vulkan genuinely isn't available on this machine. |
| "Not confirmed ready" warning fires even though the server comes up fine moments later | A cold disk cache makes model loading slower than the default 180s readiness timeout. | `LLAMA_READY_TIMEOUT=300 ./serve_qwen_coder.sh` (or higher). |
| `huggingface-cli not found` / `hf: command not found` during `download_models.sh` | `huggingface_hub` (which provides the `hf` CLI) isn't installed, or you're outside the venv. | `source .venv/bin/activate` (it's in `requirements.txt`), or re-run `pip install -r requirements.txt` if the venv is stale. |
| `python local-llm/healthcheck.py` exits `1` | Neither backend is reachable. | Start one of the two `serve_*.sh` scripts and wait for it to finish loading, then re-run the healthcheck. |

## 6. Tool 5 — Compliance Report Generator (`compliance_report_main.py`)

| Symptom | Cause | Resolution |
|---|---|---|
| `'<path>' is not a valid Compliance Checker report: ...` | `--report` isn't a `ComplianceReport` JSON — same root cause class as Tool 3's `pydantic.ValidationError`. | Regenerate with `main.py --formats json`. |
| A control's risk statement fails deterministic validation, tool exits non-zero | The `risk` text for that control in `controls.yaml` doesn't meet the report's writing-quality rules (e.g. hedging language like "may" or "could" where the rules require a direct statement). | Either edit that control's `risk:` field in `controls.yaml` directly to satisfy the rule, or re-run with `--llm-polish` to let a local LLM rewrite it (the rewrite is re-validated against the same rules before being accepted — never trusted blindly). `--llm-polish` needs a backend running, same as Tool 3 (§4/§5). |
| PDF requested but WeasyPrint import fails | Same as [§1](#1-environment--installation)'s WeasyPrint entry. | Install the system libraries listed there. |

## 7. Tool 6 — Executive Compliance Dashboard (`compliance_dashboard_main.py`)

| Symptom | Cause | Resolution |
|---|---|---|
| `No report.json found directly under <dir> ...` | Same non-recursive directory-discovery rule as Tool 3's `--reports-dir` — see [§4](#4-tool-3--compliance-remediation-advisor-cra)'s matching row for the full explanation. | Point at a specific run (e.g. `reports/latest`), not the archive root. |
| The dashboard has no breakdown by site/country/model/OS/vendor | Not a bug — this project has no device metadata anywhere in the pipeline beyond a filename-derived device name. Documented as a known gap, not silently faked. | If you need this, it requires adding a real device-inventory data source upstream of Tool 1; out of scope for a config-only pipeline. |
| `Owner`/`Ticket`/`Due Date` columns in the findings table/CSV are always empty | No workflow-assignment system exists to populate them. `Ticket` is the one exception — it populates for an `APPROVED_EXCEPTION` row if that control's `exceptions.yaml` entry has a `ticket:` field. | Add `ticket:` (and the other approval metadata fields — `approver`, `approval_date`, `expiration_date`, `compensating_control`) to the relevant entries in your `exceptions.yaml`. |
| No control ever shows as `Critical` severity | `controls.yaml` only assigns Low/Medium/High by default — `Critical` is fully wired (KPI cards, the "Critical Non-Compliant" posture bucket, risk-override logic) but nothing is elevated to it out of the box, since deciding which controls are business-critical isn't this tool's call. | Set `severity: Critical` on the relevant control(s) in `controls.yaml` yourself. |
| An expired exception still looks "accepted" | Check you're reading the right KPI — an expired exception is excluded from "Accepted Posture" but still counts toward "Assessment Coverage" (it was assessed, it just isn't accepted anymore) and was never counted toward "Strict Compliance" to begin with. This is by design, not a bug. | Check the `expiration_date` in `exceptions.yaml` is actually in the past if you expected it to show as expired, and look at the specific KPI card rather than a general "is this fine" impression. |
| PDF requested but WeasyPrint import fails | Same as [§1](#1-environment--installation). | Install the system libraries listed there. |

## 8. Cross-tool: output collisions and archiving

| Symptom | Cause | Resolution |
|---|---|---|
| A tool's `latest/` folder seems to be missing files a previous run produced | Tools 1, 3, and 5 default to **different** `--output-dir` names (`reports`, `briefings`, `compliance_reports`) deliberately — `refresh_latest()` fully *replaces* `<output-dir>/latest/` on every run rather than merging into it, and both Tool 1 and Tool 5 independently produce a file named `report.pdf`. Pointing two tools at the same `--output-dir` makes the second tool's run silently delete the first tool's `latest/` output. | Don't share `--output-dir` between tools unless you deliberately want one unified, chronologically-interleaved archive — and even then, know that only the timestamped subfolders are collision-safe; `latest/` is not. If you already did this and lost a `latest/` mirror, the timestamped subfolder from the original run is still there (never overwritten) — look under `<output-dir>/<timestamp>/`. |
| A run using `--output-md`/`--output-json`/`--out`/`--out-md` didn't create a `latest/` folder or timestamped archive at all | This is intentional — explicit output-path flags bypass the archive entirely, for scripting/automation that needs one fixed, predictable filename. | If you want the archive behavior, drop those flags and use `--output-dir` instead (or both together — `--output-dir` is still accepted, but is only used as a fallback default when the explicit path flags are absent). |

## 9. Data & content pitfalls

These don't produce an error message — the tool runs fine and produces a report, but the report's content is wrong or misleading. Harder to catch than a crash, so look here whenever a PASS/FAIL looks surprising and nothing above explains it.

| Symptom | Cause | Resolution |
|---|---|---|
| A golden config file (generated or hand-edited) has duplicate `hostname`/`tacacs server`/`line vty`/etc. blocks | Two versions of the same config got concatenated into one file (e.g. a stale auto-generated header block left in place after a hand edit was pasted above it). Some of `compliance_engine.py`'s golden-value lookups use the *first* match (`ConfigTree.blocks()[0]`, `first_text()`), so this can silently "work" as long as the correct copy happens to come first — until any check that behaves differently (counts blocks, uses `all_text()`, etc.) exposes the ambiguity. | Verify structurally before trusting a golden file: `python -c "from config_parser import ConfigTree; t = ConfigTree(open('golden_config.txt').read()); print(len(t.all_text(r'^hostname')), len(t.blocks(r'^tacacs server')), len(t.blocks(r'^line vty')))"` — each should be the number of *real* occurrences (1 hostname, 2 TACACS servers, 2 VTY ranges in this project's convention). If any count is doubled, find and delete the stale duplicate section. |
| A device that should FAIL a control PASSes instead (or vice versa) right after regenerating or hand-editing the golden config | The golden config the checker compared against wasn't what you thought it was — either it's stale (predates a `controls.yaml`/production-reference update) or it's the wrong file (`samples/golden_config.txt` vs. the real fleet golden `golden_config.txt` vs. an old dated snapshot — this project has had more than one golden file in play at different points; check `main.py`'s `--golden-config` argument in the exact command you ran). | Confirm which file was actually used (the JSON report's `golden_config_path` field records it exactly — `jq .golden_config_path report.json`). If it's the Golden Config Creator's own output, regenerate it fresh (§3's `--strict` scenario) and diff it against `support_files/NCM Configuration Script.txt` per §3's row on that. |
| `controls.yaml` and `device_vars.json`/`schemas/device_vars.schema.json` disagree about what a control needs | A `command_template` was edited without updating the matching `device_vars.json` value or the schema's shape for it (or vice versa) — these three files have no automatic cross-validation beyond what `golden_config_builder.py`'s render-time checks catch. | Re-run `golden_config_main.py --strict` after any `controls.yaml` template edit — it's the fastest way to surface a schema/template mismatch immediately rather than discovering it later as a wrong-looking golden config. |
| A whole category of test fixtures (`device_configs/*.txt`) starts failing/passing differently than before, with no code change | The fixture files themselves changed — they're plain text files checked into the repo, not generated at test time, so a `git pull`/manual edit/regeneration of the dataset changes test behavior even though `compliance_engine.py` didn't change. | `git log --oneline -- device_configs/` (or the specific file) to see if/when it last changed and by whom. If a fixture's own header comment (`! Expected finding: ...`) disagrees with what the file's body actually contains, that's a fixture authoring bug, not a checker bug — verify by reading the checker's logic against the file's real content directly (§10) before assuming the code is wrong. |
| A specific known limitation looks like a bug: TACACS `key 0` (cleartext) isn't flagged as non-compliant | This is a deliberate, documented decision (see `documentation/CONTROL_UPDATE_REPORT.md`'s Discrepancies section, item G1) — only Type 7 (weakly-reversible) is currently flagged by `_check_control_00004`, not Type 0. | Not a bug to fix silently — if you want Type 0 flagged too, that's a real control-logic change to `_check_control_00004`, worth doing deliberately (and documenting) rather than assuming it's an oversight. |
| Banner content (wording, company name) is never flagged even though it's clearly wrong/generic | `control_00012` deliberately does **not** check wording quality — `manual_review: true` exists specifically because that's a human judgment call. Tool 1's deterministic score only checks the banner exists and is well-formed (matching opening/closing delimiter). | This is by design, not a gap — see `compliance_engine.py`'s module docstring and `_check_control_00012`. If you want wording checked, that's a new, deliberate scope decision (dictionary of banned generic phrases? required company-name token?), not a bug fix. |

## 10. "Why did my report say that?" — a debugging method

When a control's PASS/FAIL doesn't match your expectation and none of the above explains it, this is the fastest way to find the actual cause — the same technique used throughout this project's own development to verify claims empirically rather than guess:

```bash
source .venv/bin/activate
python3 -c "
import yaml
from compliance_engine import ControlEvaluator

controls = {c['control_id']: c for c in yaml.safe_load(open('controls.yaml'))}
golden = open('golden_config.txt').read()          # the exact golden file you used
device = open('device_configs/some_file.txt').read()  # the exact device config you used

evaluator = ControlEvaluator()
result = evaluator.evaluate_control(controls['control_00004'], device, golden)
print(result.status)
for d in result.details:
    print(' -', d)
"
```

This runs the real checker directly, with no reporting/archiving/CLI machinery in the way, and prints exactly why it reached its verdict (`result.details` is the same text that ends up in the report). From there:

- If the reason cites a **golden value** you didn't expect, check §9's golden-file rows above.
- If the reason cites the **device text**, `grep -n` the exact pattern in `result.details` against the device config file directly — often the fixture doesn't contain what its filename/header comment implies.
- If you don't understand *why* the checker looks for what it looks for, read the corresponding `_check_control_XXXXX` method's body and comments in `compliance_engine.py` — every checker has inline comments explaining non-obvious logic (e.g. why VTY and console use different `login` methods, why a control identifies "the emergency user" by the presence of one keyword and "the admin user" by its absence).

## 11. Running the Test Suite

| Symptom | Cause | Resolution |
|---|---|---|
| `pytest` fails immediately with `ModuleNotFoundError` | Same as [§1](#1-environment--installation) — venv not activated. | `source .venv/bin/activate` before `pytest`. |
| Tests fail after editing `controls.yaml`, `device_vars.json`, or a `device_configs/*.txt` fixture | Many tests assert exact PASS/FAIL/content against real files, not just synthetic strings (deliberately — synthetic-only tests would miss real integration issues). Editing shared data can legitimately change what several tests expect. | Read the failing assertion's message — it usually names the exact expected-vs-actual status/text. Decide whether the test's expectation is now wrong (update it to match a deliberate content change) or the content change itself is the bug (revert or fix it) — don't reflexively update the test without checking which one is actually correct. |
| A test using `tmp_path` fixtures still seems to read/write the real repo files | A few tests intentionally load the *real* `controls.yaml`/`device_vars.json`/`samples/*.txt` as read-only input (to catch real integration issues) while writing their own output only under `tmp_path` — this is by design, not a leak. Check the specific test's fixture setup before assuming it's writing somewhere it shouldn't. | If a test is genuinely writing outside `tmp_path`, that's a real bug worth fixing — but confirm first by reading what path it's actually targeting. |
| PDF-related tests fail only in this environment | Same WeasyPrint system-library gap as [§1](#1-environment--installation) — the tests don't skip on missing system libraries, they fail the same way the CLI would. | Install the libraries listed in §1, or run `pytest -k "not pdf"` (approximate — check actual test names) to skip that subset while diagnosing something else. |
