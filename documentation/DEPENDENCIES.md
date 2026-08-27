# Dependencies

## Cross-check: `requirements.txt` vs. actual imports

Every package declared in `requirements.txt` is genuinely imported somewhere in the codebase, and every third-party package imported anywhere is declared in `requirements.txt`. **No mismatches found** as of this writing (verified by grepping every `import`/`from` line across all `.py` files and comparing against the declared list). One nuance worth knowing:

- **`huggingface_hub`** is declared and installed, but never `import`ed by any `.py` file in this repo — it's used purely as a *command-line tool* (`hf download ...`, with a fallback to the deprecated `huggingface-cli download ...`) inside `local-llm/download_models.sh`. It's still a correct dependency to declare, since `pip install -r requirements.txt` is what puts the `hf`/`huggingface-cli` executables on the venv's `PATH` in the first place.
- **`WeasyPrint`** *is* declared and used, but the `import weasyprint` statement is deliberately placed **inside** `report_generator.render_pdf()`, not at module load time — a lazy import, because WeasyPrint pulls in a heavier native-library dependency chain (Pango/Cairo) than the rest of the project, and most invocations of `report_generator.py` (HTML-only, JSON-only) never need it.

## What each library is used for, in this project specifically

| Library | Used for, here | Where |
|---|---|---|
| `ciscoconfparse2` | Parsing IOS-XE config text into a parent/child object tree so control checks can ask "does `line vty 0 15` have a `login local` child line" instead of doing this with raw regex/string splitting. | `config_parser.py` (the only place it's imported) |
| `PyYAML` | Loading `controls.yaml`, `render_order.yaml`, `local-llm/config.yaml`, and any `--exceptions` file. | `main.py`, `golden_config_builder.py`, `llm_client.py`, `remediation_advisor.py` |
| `Jinja2` | Three distinct uses: (1) rendering the HTML/fleet reports and Markdown briefing from templates, (2) the actual golden-config rendering engine in `golden_config_builder.py` — `<word>` tokens in `command_template` are converted to `{{ word }}` and rendered with `device_vars.json`'s values, including a custom `Undefined` subclass that renders as `<MISSING:name>` instead of raising or going blank. | `report_generator.py`, `remediation_advisor.py`, `golden_config_builder.py` |
| `WeasyPrint` | Converting the already-rendered HTML report to PDF, with no headless-browser dependency. Lazily imported (see above). | `report_generator.render_pdf` |
| `click` | All four CLI entrypoints' argument parsing (`@click.command()` / `@click.option()`), plus `click.testing.CliRunner` in the test suite for CLI-level tests without spawning a real subprocess. | `main.py`, `golden_config_main.py`, `vibecoding_advise.py`, all `tests/test_*` files touching a CLI |
| `pytest` | The entire test suite (98 tests across 9 files). | `tests/` |
| `jsonschema` | Validating `device_vars.json`'s *shape* (not completeness — see `PROJECT_STRUCTURE.md`) against `schemas/device_vars.schema.json` before rendering starts. | `golden_config_builder.py` |
| `openai` | The Python SDK used purely as a generic OpenAI-compatible HTTP client, pointed at a local `base_url` (either backend in `local-llm/config.yaml`) — no OpenAI API key or external network call is ever made. | `llm_client.LLMClient` |
| `httpx` | The backend health-check ping (`GET <base_url>/models`) that both `llm_client.select_backend`'s `auto` mode and `local-llm/healthcheck.py` use to decide which backend is actually up. | `llm_client.py`, `local-llm/healthcheck.py` |
| `pydantic` | Validating the Compliance Checker's JSON report (`ComplianceReport`/`ControlReportEntry`) both when it's written (`report_generator.render_json`) and when it's read back in (`remediation_advisor.load_report`) — malformed status/severity values are rejected immediately rather than causing a confusing failure downstream. | `report_schema.py` |
| `huggingface_hub` | Provides the `hf` (and legacy `huggingface-cli`) command-line tool used to fetch the two GGUF model files. Not imported by any Python module - CLI-only usage. | `local-llm/download_models.sh` |

## Minimum Python version

The project declares **Python 3.11+** (`CLAUDE.md` §8, `GOLDEN_CONFIG_CREATOR.md` §9). Auditing the actual syntax used:

- Every module starts with `from __future__ import annotations`, so modern annotation syntax (`str | None`, `list[dict]`, `dict[str, str] | None`) is stored as unevaluated strings and works even on interpreters that predate PEP 604 (3.10) — this alone doesn't force a 3.11 floor.
- The one runtime (non-annotation) modern-syntax feature actually used is the **walrus operator** (`:=`) in `compliance_engine.py`'s `_check_control_00005`, which requires **Python 3.8+**.
- No `match`/`case` statements, no runtime `X | Y` type unions outside annotations, no `tomllib` or other 3.11-only stdlib usage.

In practice the code would likely run on 3.9+ without changes. The declared 3.11+ floor appears to be a forward-looking choice made when the project started rather than one forced by a specific language feature — worth confirming with whoever set that target if it matters for your deployment environment. Tested and developed against **3.14.4**.

## External / system requirements

| Requirement | Needed for | Notes |
|---|---|---|
| Pango, Cairo, GDK-Pixbuf (system libraries) | WeasyPrint (`--formats pdf` in Tool 1) | Debian/Ubuntu: `libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0`. Not needed for `html`/`json` formats. |
| `curl`, `tar` | `local-llm/install_llama_server.sh` | Downloads and extracts the prebuilt `llama-server` release. |
| A Vulkan-capable GPU + driver (or CPU fallback via `-ngl 0`) | Running the local LLM backend (Tool 4) | This project deliberately targets llama.cpp's prebuilt **Vulkan** Linux release rather than CUDA - llama.cpp's official GitHub releases don't ship a Linux CUDA binary at all (only Windows does), and Vulkan needs no CUDA toolkit, just the GPU driver's own Vulkan ICD. See `local-llm/README.md` and `LOCAL_LLM_SETUP_PROMPT.md`'s Implementation Notes. |
| No C/C++ compiler is required anywhere in this project | — | `local-llm/install_llama_server.sh` exists specifically to avoid needing one (fetches a prebuilt binary rather than building from source). |
