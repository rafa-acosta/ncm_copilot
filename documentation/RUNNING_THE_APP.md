# Running the App

This project (VibeCoding) is four separate command-line tools that share one file, `controls.yaml`, as their single source of truth. This guide covers installing them and every way to invoke each one. For what each file/folder is and how the tools relate, see [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md). For what each Python function actually does internally, see [`FUNCTION_REFERENCE.md`](FUNCTION_REFERENCE.md).

## Prerequisites

- **Python 3.11+** is the declared target (see `CLAUDE.md` §8). In practice the code only uses syntax that works on 3.8+ (the newest feature used is the walrus operator `:=` in `compliance_engine.py`); every module opens with `from __future__ import annotations`, which defers evaluation of modern type hints like `str | None` so they don't require a newer interpreter at import time. This repo has been developed and tested against **Python 3.14.4** on Ubuntu-based Linux.
- **Linux** is assumed throughout (the `local-llm/` scripts are bash and fetch a Linux binary release). Nothing about the four Python tools themselves is Linux-specific, but they haven't been tested elsewhere.
- **A virtual environment.** Every command in this guide assumes you've activated the project's `.venv` — none of the third-party packages are installed system-wide, and running with a bare `python`/`python3` outside the venv will fail with `ModuleNotFoundError`.
- **WeasyPrint's system libraries** if you want PDF output (`--formats pdf`): Pango, Cairo, and GDK-Pixbuf. On Debian/Ubuntu: `sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0`. HTML and JSON output need nothing beyond the pip packages.
- **A GPU is not required** for the Compliance Checker or Golden Config Creator. It's only relevant to the Compliance Remediation Advisor's local LLM backend (see §6 below) — that was built and tested against an NVIDIA RTX 4050 (6GB VRAM), but any machine that can run `llama-server` works.

## 1. Installation

```bash
cd /path/to/ncm_copilot

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install everything
pip install -r requirements.txt
```

If `python3 -m venv .venv` fails with an `ensurepip is not available` error (happens on some minimal Debian/Ubuntu installs), either install `python3-venv` (`sudo apt install python3-venv`) or bootstrap manually:

```bash
python3 -m venv --without-pip .venv
curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
.venv/bin/python3 /tmp/get-pip.py
source .venv/bin/activate
pip install -r requirements.txt
```

From here on, every command assumes `source .venv/bin/activate` has already been run in that shell — or you call `.venv/bin/python` directly instead of `python`.

## 2. Tool 1 — Compliance Checker (`main.py`)

Audits one or more device configs against a golden config baseline, using `controls.yaml` as the rulebook. See [`FUNCTION_REFERENCE.md#compliance_enginepy`](FUNCTION_REFERENCE.md#compliance_enginepy) for the evaluation logic and [`GLOSSARY.md`](GLOSSARY.md) for what PASS/FAIL/EXCEPTION/MANUAL_REVIEW mean.

### All flags

```
--device-config FILE           Path to a single device's running-config (plain text).
                                Mutually exclusive with --device-config-dir.
--device-config-dir DIRECTORY  Directory of *.txt device configs to audit in batch.
                                Mutually exclusive with --device-config.
--golden-config FILE           Path to the golden config baseline.               [required]
--controls FILE                Path to controls.yaml.                            [required]
--output-dir DIRECTORY         Directory to write the generated report(s) into.  [required]
--formats TEXT                 Comma-separated: html, pdf, json.        [default: html,pdf]
--priority-only                Limit evaluation to control_00001-control_00015.
--exceptions FILE               Optional YAML file mapping control_id -> exception reason.
--help
```

Exactly one of `--device-config` / `--device-config-dir` must be given, or the tool exits with a usage error.

### Scenario: single device, HTML + PDF report

```bash
python main.py \
  --device-config samples/device_config.txt \
  --golden-config samples/golden_config.txt \
  --controls controls.yaml \
  --output-dir ./reports \
  --formats html,pdf
```
**Output:** `reports/report.html` and `reports/report.pdf`. Console prints `HTML report written to ...`, `PDF report written to ...`, then `Evaluated N controls: M FAIL.` **Exit code:** `1` if any control FAILed, `0` otherwise (this is deliberate — wire it into CI or a script and check `$?`).

### Scenario: single device, JSON report (feeds the Remediation Advisor)

```bash
python main.py \
  --device-config samples/device_config.txt \
  --golden-config samples/golden_config.txt \
  --controls controls.yaml \
  --output-dir ./reports \
  --formats json
```
**Output:** `reports/report.json` — a `ComplianceReport` (see `report_schema.py`), including `device_config_path` and `golden_config_path` recording exactly which two files were compared. This is the input `vibecoding_advise.py --report` expects.

### Scenario: batch mode (a folder of devices)

```bash
python main.py \
  --device-config-dir ./device_configs \
  --golden-config samples/golden_config.txt \
  --controls controls.yaml \
  --output-dir ./reports \
  --formats html,json
```
Every `*.txt` file directly inside `./device_configs/` is audited against the same golden config. **Output:** `reports/<device_stem>/report.html` and `.json` per device, plus one `reports/fleet_report.html` summarizing all devices (worst-compliance-first, with a "most common failures across the fleet" table). Console prints one `<name>: N controls, M FAIL` line per device, then `Audited N device(s): M total FAIL across the fleet.` **Exit code:** `1` if any device has any FAIL.

### Scenario: only the priority controls (00001–00015)

Add `--priority-only` to either command above. Controls 00016–00018 (policy-checklist controls without single deterministic commands) are excluded.

### Scenario: granting an exception instead of a hard FAIL

Create a YAML file mapping control IDs to a reason:
```yaml
# exceptions.yaml
control_00004: "No TACACS+ infrastructure in this lab environment."
```
```bash
python main.py --device-config samples/device_config.txt --golden-config samples/golden_config.txt \
  --controls controls.yaml --output-dir ./reports --exceptions exceptions.yaml
```
Any control that would have FAILed and has a matching entry becomes status `EXCEPTION` instead (a control that already PASSes is unaffected — an exception can't turn a pass into anything else).

### Common errors

| Symptom | Cause |
|---|---|
| `Provide exactly one of --device-config or --device-config-dir.` | Gave both flags, or neither. |
| `No *.txt device config files found in <dir>.` | `--device-config-dir` pointed at an empty/wrong folder. |
| `yaml.scanner.ScannerError` / `yaml.parser.ParserError` | Malformed `controls.yaml` or `--exceptions` file — the traceback includes a line/column. |
| `ModuleNotFoundError: No module named 'click'` (etc.) | Venv not activated, or `pip install -r requirements.txt` never ran. |
| PDF requested but WeasyPrint import fails | System libraries (Pango/Cairo/GDK-Pixbuf) missing — see Prerequisites. |

## 3. Tool 2 — Golden Config Creator (`golden_config_main.py`)

Renders `controls.yaml` + a `device_vars.json` into a `golden_config.txt` — the file Tool 1 consumes as `--golden-config`. See [`FUNCTION_REFERENCE.md#golden_config_builderpy`](FUNCTION_REFERENCE.md#golden_config_builderpy).

### All flags

```
--controls FILE     Path to controls.yaml.                                [required]
--device-vars FILE  Path to device_vars.json.                             [required]
--output FILE       Output path.                       [default: golden_config.txt]
--priority-only     Render only control_00001-control_00015.
--order FILE        Render-order YAML.                  [default: render_order.yaml]
--strict             Abort and list every missing variable, write nothing.
--help
```

### Scenario: normal render (non-strict / "write mode")

```bash
python golden_config_main.py \
  --controls controls.yaml \
  --device-vars device_vars.json \
  --output golden_config.txt
```
**Output:** `golden_config.txt` is always written. If any control's template needs a variable `device_vars.json` doesn't supply, that spot gets a literal `<MISSING:variable_name>` marker instead of failing the whole run, and the console prints a list of every missing entry (e.g. `control_00002.company_name`) after writing the file — this is the "iterate without regenerating everything" mode.

### Scenario: strict / "dry-run-if-incomplete" mode

```bash
python golden_config_main.py --controls controls.yaml --device-vars device_vars.json --strict
```
If anything is missing, the tool prints the same missing-variable list, prints `Aborting: --strict mode requires every variable to be resolved. No file was written.` to stderr, and exits `1` — **no file is written at all.** Use this before feeding the output to Tool 1, so you don't accidentally audit against a golden config full of `<MISSING:...>` placeholders.

### Scenario: device_vars.json is invalid (wrong shape)

`device_vars.json` is validated against `schemas/device_vars.schema.json` before rendering starts. A wrong-typed value or an unrecognized key raises immediately — for example, setting a `tacacs_servers` entry's `timeout` to a string instead of a number:
```
ValueError: device_vars.json is invalid at 'control_00004.tacacs_servers.0.timeout': 'ten' is not of type 'integer'
```
or adding a key the schema doesn't recognize:
```
ValueError: device_vars.json is invalid at 'control_00002': Additional properties are not allowed ('bogus_extra_field' was unexpected)
```
Note this only checks *shape/type*, not completeness — a whole control section, or an individual field within one (e.g. a `tacacs_servers` entry missing its `key`), can be legitimately absent from `device_vars.json` (partial input is expected); that's caught by the missing-variable mechanism above, not schema validation.

### Common errors

| Symptom | Cause |
|---|---|
| `ValueError: device_vars.json is invalid at '<path>': ...` | A present section has the wrong shape (wrong type, unexpected key). |
| `<MISSING:some_var>` in the output | A control section is present but that specific variable isn't. |
| Aborts with no file written | `--strict` and something's missing — see above. |

## 4. Tool 3 — Compliance Remediation Advisor (`vibecoding_advise.py`)

Turns a Compliance Checker JSON report into an LLM-written remediation briefing. Requires a local LLM backend to be running (§6). See [`FUNCTION_REFERENCE.md#remediation_advisorpy`](FUNCTION_REFERENCE.md#remediation_advisorpy).

### All flags

```
--report FILE                    Compliance Checker JSON report (main.py --formats json). [required]
--controls FILE                  Path to controls.yaml.                                   [required]
--backend TEXT                   'auto', or a name from local-llm/config.yaml's backends
                                  registry (e.g. qwen_coder, phi4_mini).        [default: auto]
--output-md FILE                 Markdown output path.                    [default: briefing.md]
--output-json FILE               JSON output path.                      [default: briefing.json]
--severity-min [low|medium|high] Only include findings at or above this severity.
--device-vars FILE                Optional - variables already set there aren't flagged as missing.
--help
```

### Scenario: basic briefing

```bash
python main.py --device-config samples/device_config.txt --golden-config samples/golden_config.txt \
  --controls controls.yaml --output-dir ./reports --formats json

python vibecoding_advise.py \
  --report reports/report.json \
  --controls controls.yaml \
  --backend auto \
  --output-md briefing.md \
  --output-json briefing.json
```
**Output:** `briefing.md` (human-readable, severity-grouped) and `briefing.json` (structured, includes a `suggested_device_vars_patch` block shaped like `device_vars.json` for feeding back into Tool 2). Console prints which backend was auto-selected and `N finding(s) briefed.` **Exit code:** `0` on success.

### Scenario: only brief High-severity findings, skip variables already known

```bash
python vibecoding_advise.py --report reports/report.json --controls controls.yaml \
  --severity-min high --device-vars device_vars.json \
  --output-md briefing_high.md --output-json briefing_high.json
```

### What the LLM does and doesn't do

The LLM only ever writes the 2–3 sentence "what's missing and why" explanation. It is **never shown the remediation command text** — the tool inserts `controls.yaml`'s `config_example` field into the briefing verbatim itself. This is a deliberate strengthening beyond a literal reading of the original spec (`COMPLIANCE_ANALYZER_PROMPT.md`), which described the LLM "restating" the commands; giving the LLM the commands to restate would only be a probabilistic guarantee against alteration, whereas never showing them to it at all makes "no LLM-generated command text" true by construction. See `remediation_advisor.py`'s module docstring and `tests/test_remediation_advisor.py`'s command-block-verbatim tests.

### Common errors

| Symptom | Cause |
|---|---|
| `Error: No local LLM backend is reachable. ...` (lists launch hints) | No `local-llm/serve_*.sh` is running — see §6. |
| `Error: Unknown backend '<name>'. Known backends: ...` | Typo'd `--backend`, or that name isn't in `local-llm/config.yaml`. |
| `pydantic.ValidationError` while loading `--report` | The JSON file isn't a valid `ComplianceReport` (wrong tool produced it, or it's corrupted). |

## 5. Batch reports and the LLM advisor

The Remediation Advisor currently reads **one** device's `report.json` at a time — `main.py`'s batch mode produces a `report.json` per device (no combined multi-device JSON yet; only the HTML `fleet_report.html` is a true fleet-level artifact today). To brief multiple devices, run `vibecoding_advise.py` once per device's `report.json`.

## 6. Local LLM backend (`local-llm/`)

Provisions and runs the model `vibecoding_advise.py` talks to. See `local-llm/README.md` and `LOCAL_LLM_SETUP_PROMPT.md` for the full rationale (why llama.cpp, why Vulkan not CUDA on Linux, the 6GB-VRAM "one model at a time" constraint).

```bash
cd local-llm
./install_llama_server.sh      # fetches the llama-server binary into ./bin/ (~15MB, one-time)
./download_models.sh           # fetches both GGUF models into ./models/ (~6.7GB total, one-time)

./serve_qwen_coder.sh          # OR ./serve_phi4mini.sh - starts one server, blocks this terminal
```
Startup prints a line confirming GPU offload actually happened (measured via GPU memory delta, not by parsing the server's own log — see `ARCHITECTURE_OVERVIEW.md`'s "Key design decisions"):
```
GPU offload confirmed - GPU memory usage grew by 2969MiB (now 2982MiB).
```
If that warns instead (`GPU memory usage barely changed`), it's likely running on CPU only — check `-ngl` and Vulkan drivers (`local-llm/README.md`'s fallback ladder).

In another terminal:
```bash
python local-llm/healthcheck.py     # confirms which backend(s) are UP/DOWN; exits 1 if none are
```

### Environment variable overrides (no script editing needed)

| Variable | Effect |
|---|---|
| `LLAMA_MODEL_FILE` | Use a different GGUF (e.g. the smaller `Q3_K_M` quant if VRAM is tight). |
| `LLAMA_CTX_SIZE` | Reduce context (default 4096) — e.g. `LLAMA_CTX_SIZE=2048`. |
| `LLAMA_NGL` | Reduce GPU layer offload (default 99 = full) — e.g. `LLAMA_NGL=20` for partial CPU/GPU split. |
| `VIBECODING_LLM_CONFIG` | Point `llm_client.py` at an alternate backend-registry YAML instead of `local-llm/config.yaml`. |

### Common errors

| Symptom | Cause |
|---|---|
| `llama-server not found at .../bin/llama-server` | Run `./install_llama_server.sh` first. |
| `Model file not found: ...` | Run `./download_models.sh` first (or set `LLAMA_MODEL_FILE`). |
| Server starts but `GPU offload` warning fires | Vulkan driver issue, or `-ngl` too low — see `local-llm/README.md`. |
| `huggingface-cli not found` / `hf: command not found` | `pip install -r requirements.txt` didn't run, or an old shell has a stale PATH. |
