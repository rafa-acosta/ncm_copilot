# NCM Copilot — Web Frontend

A browser-based frontend for NCM Copilot: upload device configs, manage Golden
Configuration profiles, run compliance analysis, generate LLM-assisted
remediation briefings, compliance reports, and a fleet dashboard — all
backed by the project's existing Python tools (`compliance_engine.py`,
`golden_config_builder.py`, `remediation_advisor.py`,
`compliance_report_builder.py`, `compliance_dashboard_builder.py`). Nothing
under `webapp/` reimplements any compliance/config/reporting logic; every
service in `webapp/backend/services/` is a thin wrapper that imports and
calls the real modules directly. See `documentation/WEBAPP.md` for the full
architecture and API reference.

## Running it

From the repo root, with the project's existing virtual environment active
(the one `requirements.txt` already installs into):

```bash
pip install -r requirements.txt   # adds fastapi, uvicorn, python-multipart
python3 -m uvicorn webapp.backend.app:app --reload
```

Then open **http://127.0.0.1:8000/** in a browser.

`--reload` is optional (useful while developing); drop it for a steadier
demo session. To use a different port: `--port 8791` etc.

## Data workspace

Everything the web app uploads or generates (device configs, Golden Config
profiles, analysis runs, compliance history) lives under `webapp/data/`,
entirely separate from the repo-root `device_configs/`, `golden_config.txt`,
`reports/`, etc. that the CLI tools use. The CLI tools and their sample data
are untouched and remain usable exactly as before — this frontend is
additive, not a replacement.

`webapp/data/` is gitignored (except an empty `.gitkeep` marking the
directory itself) so nothing uploaded through the UI is ever committed.

## Local LLM backend (optional)

Briefings, and optionally the Compliance Report's risk-statement polishing,
call out to a local LLM backend the same way `agent_assisted_coding_advise.py`
and `compliance_report_main.py` already do (see `LOCAL_LLM_SETUP_PROMPT.md`
and `llm_client.py`). If no backend is running, every other screen
(Configuration Files, Golden Config, Analysis, Compliance Report without
polishing, Dashboard) still works fully — the Settings screen shows live
backend reachability, and Briefings clearly disables itself with an
explanation when no backend is reachable.

## Tests

```bash
python3 -m pytest tests/test_webapp_configs.py tests/test_webapp_golden.py \
    tests/test_webapp_analysis.py tests/test_webapp_security.py -v
```

These use FastAPI's `TestClient` against a temporary, isolated data
directory (see `tests/conftest.py`'s `webapp_client` fixture) - they never
touch your real `webapp/data/` workspace, and the Golden Config tests run
against the repo's actual `controls.yaml`/`device_vars.schema.json`, so a
pass means the web API genuinely round-trips through the real engine.
