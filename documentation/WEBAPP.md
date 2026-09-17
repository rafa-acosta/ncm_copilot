# NCM Copilot Web Frontend — Architecture & API Reference

## What this is

A browser UI for the six existing CLI tools (Compliance Checker, Golden
Config Creator, Remediation Advisor, Compliance Report Generator, Executive
Dashboard, plus the local LLM backend), built for demoing the product to
customers. It is **additive**: no existing top-level `.py` module was
modified beyond `requirements.txt` (three new dependencies:
`fastapi`, `uvicorn[standard]`, `python-multipart`). Every CLI tool still
works exactly as before.

Run instructions: `webapp/README.md`.

## Design principle: thin service layer, zero reimplemented logic

Every file under `webapp/backend/services/` imports and calls the real
top-level module(s) directly (via a `sys.path.insert(0, <repo root>)` shim,
since `webapp/` sits one level below them). No service re-derives a
compliance verdict, re-renders a golden config line, or recomputes a
percentage that one of the six tools already computes. Where a service adds
its own logic, that logic is either pure plumbing (file I/O, job tracking,
path safety) or explicitly-scoped UI convenience (e.g. `find_duplicate_value_warnings`
in `golden_service.py`, a non-blocking authoring hint - not a compliance
rule).

| Screen | Backend service | Real modules it calls |
|---|---|---|
| Configuration Files | `configs_service.py` | `config_parser.ConfigTree` (hostname detection only) |
| Golden Config Manager | `golden_service.py` | `golden_config_builder.GoldenConfigBuilder`, `controls.yaml`, `schemas/device_vars.schema.json` |
| Analysis | `analysis_service.py` | `main._evaluate_device`, `main.load_controls`, `compliance_engine.ACTIVE_CONTROL_IDS`, `report_generator.render_fleet_html`, `run_archive` |
| Briefings | `briefings_service.py` | `agent_assisted_coding_advise._brief_device`, `remediation_advisor`, `llm_client` |
| Compliance Report | `reports_service.py` | `compliance_report_builder.build_report_context/render_markdown/render_pdf`, `llm_client` |
| Dashboard | `dashboard_service.py` | `compliance_dashboard_builder.build_dashboard` |
| Settings | `settings_service.py` | `compliance_report_builder.controls_version`, `llm_client.load_backends_registry/_is_reachable` |

## Directory layout

```
webapp/
  backend/
    app.py               FastAPI app factory: router wiring + exception -> HTTP mapping + static mount
    jobs.py               In-memory background-thread job tracker (batch analysis/briefings progress)
    security.py           Filename sanitization, path-traversal guard, upload validation
    routes/                One module per screen; thin - request/response shape only, no logic
    services/              One module per screen; wraps the real top-level tools
  frontend/
    index.html
    css/                   tokens.css (design system) + base/layout/components.css
    js/
      api.js, state.js, router.js, dom.js    Shared infrastructure
      components/                              Reusable UI pieces (toast, modal, error panel, status badge, job progress)
      pages/                                    One module per screen; `export async function render(container)`
  data/                    Gitignored isolated workspace (see below)
tests/test_webapp_*.py      FastAPI TestClient tests
```

## Data workspace

`webapp/data/` is completely separate from the repo-root `device_configs/`,
`golden_config.txt`, `reports/`, `compliance_history/`, etc. that the CLI
tools read/write. Nothing the web app does touches those. Subdirectories:

- `device_configs/` — uploaded `.txt` files (sanitized filenames).
- `golden_profiles/<slug>/{device_vars.json,metadata.json}` — named, editable
  Golden Config profiles. A "Working Copy" profile is auto-seeded from the
  real default on first use.
- `runs/<timestamp>/` — analysis output, in exactly the shape
  `run_archive.py`/`main.py`'s own batch mode already produces
  (`<device>/report.json`, `<device>/report.html`, `_golden_config_used.txt`,
  optional `fleet_report.html`), plus `briefings/<device>/` and
  `<device>/compliance_report/` subtrees added by those screens, and
  `dashboard/compliance_dashboard.html` once built.
- `compliance_history/` — one JSON snapshot per dashboard build, same
  mechanism `compliance_dashboard_builder.py` already uses for the CLI tool.

### The "Default" Golden Config is never stored

`golden_service.py`'s `DEFAULT_PROFILE_ID = "__default__"` is **not** a file
on disk under `webapp/data/`. It is the repo's real, current
`controls.yaml` + `device_vars.json` + `render_order.yaml`, read and
rendered through `GoldenConfigBuilder` on every request. This guarantees it
can never drift from what `python golden_config_main.py` would actually
produce, and it is why "Restore Default" and the Default profile itself are
always recoverable regardless of what edits happen elsewhere.

## Error contract

Every error response (both handled and unexpected) is:

```json
{"detail": "<user-facing message>", "technical": "<ExceptionType>: <message, if safe>"}
```

`app.py` maps each service-layer exception type to an HTTP status code and
builds this response. Two rules enforced there:

1. **Unhandled exceptions** are caught by a catch-all handler, logged
   server-side via `traceback.print_exc()`, and returned as a generic
   500 — the client never sees a raw traceback.
2. **`FileNotFoundError` gets its own handler**, not the generic
   `str(exc)`-based one, because Python's own message for it embeds the
   absolute server-side path (`"[Errno 2] No such file or directory:
   '/home/.../webapp/data/runs/x'"`). Both `detail` and `technical` are
   replaced with a generic "not found" message instead — see the comment in
   `app.py` for the concrete case this guards against.

## Background jobs

Batch operations (Analysis, Briefings) run in a daemon thread tracked by
`webapp/backend/jobs.py` (`Job` dataclass + `threading.Lock`-guarded dict) —
deliberately not a task queue, matching this project's single-operator local
tool design everywhere else. The frontend polls `GET .../jobs/{id}` roughly
every 800ms (`components/jobProgress.js`). One device's unexpected failure
is caught per-item and recorded in the job's `result.errored_devices` (or
`.errors`), never aborting the rest of the batch — mirroring `main.py`'s own
`ASSESSMENT_ERROR` isolation.

## Security

- `security.py`: `sanitize_filename()` collapses any path-traversal attempt
  to a flat basename; `resolve_within()` asserts every disk read/write whose
  final component came from user input still resolves inside its intended
  root, raising `ValueError` otherwise; `validate_upload_bytes()` rejects
  non-`.txt`, empty, oversized (>2 MiB), or non-UTF-8 uploads.
- Extension validation always runs on the **raw** filename before
  sanitization — `sanitize_filename()` force-appends `.txt` to any
  extensionless name (a safety net for edge cases), which would otherwise
  silently turn a rejected `bad.exe` into an accepted `bad.exe.txt` if the
  order were reversed. Regression-tested in `tests/test_webapp_security.py`.
- The frontend's `el()` DOM helper (`dom.js`) only ever sets `textContent`,
  never `innerHTML` with interpolated data — uploaded filenames, config
  text, and LLM-authored briefing/report prose can never be rendered as
  markup. `renderMarkdownLite()` (also in `dom.js`) is a deliberately
  minimal, safe Markdown-to-DOM renderer for the same reason, not a general
  parser.
- No filesystem paths are ever returned to the client (see the
  `FileNotFoundError` handler above).
- Nothing is sent to an external service — the only outbound calls are to
  the locally-configured LLM backend(s) already used by the CLI tools.

## Frontend architecture

Vanilla ES modules, no build step, served as static files by the same
FastAPI app (`StaticFiles` mount at `/assets`) — same-origin, no CORS.
Routing is hash-based (`#/golden-config` etc.), so the server never needs a
SPA path fallback; the only real HTTP requests it sees are `/`, `/api/*`,
and `/assets/*`.

- `api.js` — fetch wrapper; throws `ApiError{status, detail, technical}`.
- `state.js` — minimal cross-page state (active Golden Config profile,
  active run), persisted to `localStorage` as a per-browser convenience
  only; the backend remains the source of truth.
- `router.js` — registers one page module per hash route; calls that
  module's `render(container)` and its returned cleanup function on
  navigation.
- `components/` — `toast.js` (success/warning/error notifications, never
  `alert()`), `modal.js` (`confirmDialog` for every destructive action,
  optionally requiring a typed confirmation string; `openModal` for general
  dialogs), `errorPanel.js` (shows `detail`, puts `technical` behind a
  collapsed `<details>`), `statusBadge.js` (status/severity/compliance-%
  badges — always icon + text + color, never color alone), `jobProgress.js`
  (generic job polling UI, parameterized by which `/jobs/{id}` route to
  poll).

## API Reference

All request/response bodies are JSON unless noted. All routes are under
`/api/`.

### Configuration Files (`routes/configs.py`)

| Method & path | Body | Response |
|---|---|---|
| `GET /api/configs` | — | `[{filename, device_name, size_bytes, modified_at}]` |
| `POST /api/configs/upload` | multipart `files[]` | `{outcomes: [{filename, status, reason}], accepted_count, rejected_count}` |
| `POST /api/configs/delete` | `{filenames: [str]}` or `{all: true}` | `{deleted_count}` |
| `GET /api/configs/{filename}/text` | — | `{filename, text}` |

### Golden Config Manager (`routes/golden.py`)

| Method & path | Body | Response |
|---|---|---|
| `GET /api/golden/schema` | — | `[{control_id, title, explanation, fields: [{name, json_type, required_shape}]}]` |
| `GET /api/golden/profiles` | — | `[{profile_id, name, description, created_at, updated_at, read_only}]` (includes the synthetic `__default__` entry) |
| `POST /api/golden/profiles` | `{name, description?, device_vars?}` | profile detail (below) |
| `GET /api/golden/profiles/{id}` | — | `{profile_id, name, description, read_only, created_at?, updated_at?, device_vars, rendered_text, missing}` |
| `PUT /api/golden/profiles/{id}` | `{device_vars, description?}` | `{rendered_text, missing, warnings}` (422 if the shape fails `GoldenConfigBuilder`'s own validation) |
| `POST /api/golden/profiles/{id}/rename` | `{name, description?}` | profile detail |
| `DELETE /api/golden/profiles/{id}` | — | `{deleted: true}` |
| `POST /api/golden/profiles/{id}/duplicate` | `{new_name}` | profile detail (of the new copy) |
| `POST /api/golden/profiles/{id}/restore-default` | — | profile detail (device_vars replaced with the real Default's; the Default itself is never touched) |
| `GET /api/golden/profiles/{id}/compare-default` | — | `{diff: [{line}]}` (unified diff, `! Generated:` timestamp lines excluded from the comparison) |
| `POST /api/golden/import` | `{text}` | `{is_valid, sections_found, missing_sections, duplicate_sections, raw_text}` — **structural check only**, see Limitations |
| `POST /api/golden/preview` | `{device_vars}` | `{rendered_text, missing, warnings, valid}` — non-persisting, used for the live-preview pane while editing |

`__default__` is read-only: `PUT`/`DELETE` against it return 422.

### Analysis (`routes/analysis.py`)

| Method & path | Body | Response |
|---|---|---|
| `POST /api/analysis/run` | `{device_filenames: [str], golden_profile_id}` | `{job_id}` (400 if no files selected, files don't exist, or the golden profile has unresolved `<MISSING:...>` values) |
| `GET /api/analysis/jobs/{job_id}` | — | `Job.as_dict()`: `{job_id, kind, status, total, processed, current_label, result, error, started_at, finished_at}` |
| `GET /api/analysis/runs` | — | `[{run_id, device_count}]` |
| `GET /api/analysis/runs/latest` | — | `{run_id}` (404 if none yet) |
| `GET /api/analysis/runs/{run_id}/devices` | — | `[device_stem, ...]` — devices this run has a `report.json` for |

Job `result` shape on success: `{run_id, device_count, analyzed_count,
total_fail, errored_devices: [str], golden_profile}`.

### Briefings (`routes/briefings.py`)

| Method & path | Body | Response |
|---|---|---|
| `POST /api/briefings/run` | `{run_id, device_filenames?: [str]\|null, severity_min?, backend?}` | `{job_id}` (`device_filenames: null` briefs every device in the run) |
| `GET /api/briefings/jobs/{job_id}` | — | `Job.as_dict()`; `result` = `{briefed: [{device, finding_count}], errors: [str], backend}` |
| `GET /api/briefings/{run_id}` | — | `[{device, modified_at}]` |
| `GET /api/briefings/{run_id}/{device}` | — | `{device, markdown, data}` |

### Compliance Report (`routes/reports.py`)

| Method & path | Body | Response |
|---|---|---|
| `POST /api/reports/generate` | `{run_id, device, device_role, audit_date?, llm_polish?, backend?}` | report dict (below); synchronous, no job |
| `GET /api/reports/{run_id}/{device}/pdf` | — | PDF file download |

Report dict: `{device, device_role, audit_date, compliance_pct, counts,
findings_detail: [FindingRow], manual_review: [FindingRow], markdown,
pdf_available, backend_used}`. `FindingRow` = `{control_id, title, severity,
status, evidence, risk_statement, remediation_command,
operator_inputs_required, exception_reason}` — the exact shape
`compliance_report_schema.py` defines; nothing renamed or added.

### Dashboard (`routes/dashboard.py`)

| Method & path | Body | Response |
|---|---|---|
| `POST /api/dashboard/build` | `{run_id}` | fleet summary dict (below) — **always writes a new `compliance_history/` snapshot**, so this is only ever called on an explicit user action, never on a passive page view |
| `GET /api/dashboard/{run_id}/html` | — | the self-contained static HTML `compliance_dashboard_builder.py` already produces, embedded directly (404 if not built yet — never triggers a build) |

Build response: `{run_id, html_path, device_count, strict_compliance_pct,
assessment_coverage_pct, critical_finding_count, executive_summary,
device_summaries: [{device_name, strict_compliance_pct, pass_count,
fail_count, has_critical_failure}], control_summaries: [{control_id, title,
compliance_pct, fail_count, affected_device_count}], worst_devices:
[{device_name, strict_compliance_pct}]}`. `fail_count` is derived from each
summary's real `counts["FAIL"]` field — `DeviceSummary`/`ControlSummary`
(`compliance_metrics.py`) have no `fail_count` field of their own.

### Settings (`routes/settings.py`)

| Method & path | Body | Response |
|---|---|---|
| `GET /api/settings/status` | — | `{controls_version, backends: [{name, role, base_url, model_name, reachable}], any_backend_reachable, data_workspace, device_config_count, golden_profile_count, run_count}` |

## Known limitations (deliberately scoped out of this pass)

- **Golden Config import is structural-only.** `POST /api/golden/import`
  checks that every active control's `! control_XXXXX - <Title>` section is
  present, with no duplicates — it does not reverse-parse arbitrary command
  text back into individual `device_vars` fields. Per the project's "do not
  invent Golden Config syntax" constraint, an imported file is shown
  read-only with its validation result, never silently merged into an
  editable profile.
- **No push-based progress.** Job progress is polling-based (~800ms), not
  SSE/WebSockets — simple and reliable for batches that complete in tens of
  seconds.
- **Single-operator, no auth.** Matches every existing CLI tool's own
  design; not multi-user.
- **No dedicated Device/Control detail drill-down routes.** The Dashboard's
  native device/control tables are informational (search/sort), not
  clickable into a separate deep-link page in this pass.
- **Run history browsing is a flat list**, not a searchable archive beyond
  what's on disk under `webapp/data/runs/`.

## Testing

`tests/test_webapp_{security,configs,golden,analysis}.py`, using FastAPI's
`TestClient` against a temporary, isolated workspace (`tests/conftest.py`'s
`webapp_client` fixture monkeypatches each service's storage-path constants
into `tmp_path` — `controls.yaml`/`device_vars.schema.json` are left
pointing at the real repo files, since exercising the real engine end to end
is the point). The Analysis tests run the real `main._evaluate_device`
against real fixtures from `device_configs/`, including one test that
monkeypatches a single device to raise mid-batch and asserts the rest of the
batch still completes.
