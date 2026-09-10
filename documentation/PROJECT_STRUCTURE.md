# Project Structure

## Directory tree

Generated/downloaded content (`.venv/`, `local-llm/bin/`, `local-llm/models/`, `reports/`, `output/`, `__pycache__/`) is omitted — see each entry's note for why it's not checked in.

```
ncm_copilot/
├── controls.yaml                    # THE single source of truth - 17 security controls (see GLOSSARY.md)
├── render_order.yaml                # Control rendering order for the Golden Config Creator only
├── device_vars.json                 # Sample/real per-device variable values, keyed by control_id
├── requirements.txt                 # All four tools' dependencies in one file (not split per-tool)
│
├── main.py                          # Tool 1 entrypoint: Compliance Checker CLI
├── compliance_engine.py             # Tool 1: per-control PASS/FAIL/EXCEPTION/MANUAL_REVIEW logic
├── config_parser.py                 # Tool 1: ConfigTree, a ciscoconfparse2 wrapper used by compliance_engine.py
├── report_generator.py              # Tool 1: HTML/PDF/JSON/fleet report rendering
├── report_schema.py                 # Pydantic schema for the JSON report - shared with Tool 3
│
├── golden_config_main.py            # Tool 2 entrypoint: Golden Config Creator CLI
├── golden_config_builder.py         # Tool 2: GoldenConfigBuilder - renders controls.yaml + device_vars.json
├── schemas/
│   └── device_vars.schema.json      # JSON Schema validating device_vars.json's shape (Tool 2)
│
├── agent_assisted_coding_advise.py             # Tool 3 entrypoint: Compliance Remediation Advisor CLI
├── remediation_advisor.py           # Tool 3: report parsing, finding assembly, briefing rendering
├── llm_client.py                    # Tool 3: LLMClient + named-backend registry/selection logic
│
├── local-llm/                       # Tool 4: provisions and runs the local LLM Tool 3 talks to
│   ├── config.yaml                  #   backend registry (name -> role/base_url/model_name)
│   ├── install_llama_server.sh      #   fetches the prebuilt llama-server binary (Vulkan Linux build)
│   ├── download_models.sh           #   fetches both GGUF model files from Hugging Face
│   ├── serve_qwen_coder.sh          #   launches llama-server for the "specialist" model, port 8080
│   ├── serve_phi4mini.sh            #   launches llama-server for the "fast_default" model, port 8081
│   ├── _serve_common.sh             #   shared launch/GPU-offload-detection logic sourced by both serve_*.sh
│   ├── healthcheck.py               #   pings every registered backend, exits nonzero if none are up
│   ├── bin/, models/                #   gitignored - populated by the two scripts above
│   └── README.md                    #   VRAM budget, Vulkan-vs-CUDA rationale, fallback steps
│
├── templates/
│   ├── report_template.html         # Tool 1: per-device HTML report (Jinja2)
│   ├── fleet_report_template.html   # Tool 1: batch-mode fleet summary HTML (Jinja2)
│   └── briefing_template.md.j2      # Tool 3: Markdown briefing (Jinja2)
│
├── samples/
│   ├── device_config.txt            # Reference audited device (deliberately non-compliant, for demos/tests)
│   └── golden_config.txt            # Reference golden baseline matching it
├── device_configs/                  # Real device configs for batch-mode auditing (user-populated; not a
│                                     #   tool requirement, just the conventional drop-folder for --device-config-dir)
├── support_files/                   # Original source documents the controls/samples were transcribed from
│
├── tests/                           # pytest suite, one file roughly per module above
│
├── CLAUDE.md                        # Tool 1's original spec + "Implementation Notes" on deviations
├── GOLDEN_CONFIG_CREATOR.md         # Tool 2's original spec + Implementation Notes
├── COMPLIANCE_ANALYZER_PROMPT.md    # Tool 3's original spec + Implementation Notes
├── LOCAL_LLM_SETUP_PROMPT.md        # Tool 4's original spec + Implementation Notes
└── documentation/                   # This documentation set
```

## How `controls.yaml` flows through the system

```
                              ┌────────────────┐
                              │  controls.yaml │   18 controls (15 active), each with:
                              │ (single source  │   command_template, variables,
                              │   of truth)     │   not_compliance_conditions,
                              └───────┬─────────┘   severity, risk, remediation,
                                      │              config_example, ...
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
             ▼                        ▼                        ▼
   ┌───────────────────┐   ┌────────────────────┐   ┌──────────────────────┐
   │ compliance_engine  │   │ golden_config_      │   │ remediation_advisor  │
   │ .py                │   │ builder.py          │   │ .py                  │
   │                    │   │                     │   │                       │
   │ Reads: severity,   │   │ Reads: command_     │   │ Reads: risk, severity,│
   │ not literally the  │   │ template, variables  │   │ remediation,          │
   │ command_template - │   │ (regex-extracted     │   │ config_example        │
   │ each control has   │   │ <word> tokens, not   │   │ (never the LLM -      │
   │ its own hand-       │   │ the metadata field)  │   │ inserted verbatim by  │
   │ written regex       │   │                      │   │ the tool itself)      │
   │ checker instead     │   │                      │   │                       │
   └─────────┬──────────┘   └──────────┬───────────┘   └──────────┬────────────┘
             │                          │                          │
             ▼                          ▼                          ▼
     ControlResult list         golden_config.txt          Finding list (LLM
     -> report_generator.py    (feeds back into Tool 1      explanation +
     -> HTML/PDF/JSON report    as --golden-config)          verbatim commands)
                                                              -> briefing.md/.json
```

The key point: **`command_template` is not interpreted the same way by all three consumers.** `compliance_engine.py` doesn't read it at all — every control has its own hand-written checker function using its own regexes against the actual device/golden config text (see `ARCHITECTURE_OVERVIEW.md` for why). `golden_config_builder.py` is the one place `command_template` is actually rendered, by scanning it for `<word>` tokens (except `control_00004`, which uses real pre-converted Jinja `{% for %}` syntax instead, for its repeating TACACS-server list). `remediation_advisor.py` doesn't touch `command_template` either — it uses `config_example` and `remediation` instead, and only for controls the Compliance Checker found FAILed.

## How the four tools relate

| | Reads | Produces | Consumed by |
|---|---|---|---|
| **Tool 1** Compliance Checker | `controls.yaml`, a device config, a golden config | HTML/PDF report, `report.json` | Tool 3 (`--report`) |
| **Tool 2** Golden Config Creator | `controls.yaml`, `device_vars.json` | `golden_config.txt` | Tool 1 (`--golden-config`) |
| **Tool 3** Remediation Advisor | `controls.yaml`, Tool 1's `report.json` | `briefing.md`/`briefing.json` | A human; `suggested_device_vars_patch` in the JSON output is shaped to eventually feed Tool 2's `device_vars.json` |
| **Tool 4** Local LLM setup | Hugging Face, GitHub releases | A running `llama-server` process | Tool 3, over HTTP (OpenAI-compatible `/v1` API) |

Tools 1 and 2 are otherwise fully independent of each other except for sharing `controls.yaml` — neither imports the other's Python modules. Tool 3 imports `report_schema.py` (shared with Tool 1's `report_generator.py`) but not Tool 1's or Tool 2's other modules. Tool 4 is pure infrastructure (bash + one Python health-check script) with no imports from Tools 1–3 at all; the connection is purely "an HTTP server Tool 3's `llm_client.py` calls."

## Templates and generated output

- **Templates** (`templates/*.html`, `templates/*.md.j2`) are Jinja2 source, loaded via `jinja2.Environment(loader=FileSystemLoader(...))` in `report_generator.py`/`remediation_advisor.py`. They are the only place HTML/Markdown structure is defined — no output formatting happens in the Python code itself beyond building the data dict passed to `.render()`.
- **Generated output** (gitignored, created on demand): `reports/` (Tool 1), `output/` and any `--output` path (Tool 2), `briefing.md`/`briefing.json` (Tool 3), `local-llm/bin/` and `local-llm/models/` (Tool 4's downloaded binary/weights).
