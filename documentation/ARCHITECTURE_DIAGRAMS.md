# NCM Copilot — Architecture Diagrams

Mermaid diagrams explaining how the application fits together: the web
frontend, its FastAPI backend, the six existing CLI tools it orchestrates,
the local LLM backend, and the isolated data workspace. These render
natively in GitHub and in VS Code's Markdown preview — no extra tooling
needed. See `documentation/WEBAPP.md` for the prose version of the same
architecture plus the full API reference.

## 1. System overview

Everything under "Existing NCM Copilot Engine" is unmodified, real project
code — the web frontend is a thin orchestration layer on top of it, never a
reimplementation.

```mermaid
graph TB
    subgraph Client["Browser"]
        UI["Web Frontend<br/>HTML / CSS / vanilla JS"]
    end

    subgraph Server["FastAPI Backend (webapp/backend)"]
        Routes["Routes<br/>request/response shape only"]
        Services["Services<br/>thin wrappers, one per screen"]
        Jobs["Background Job Tracker<br/>jobs.py"]
    end

    subgraph Engine["Existing NCM Copilot Engine (repo root, unmodified)"]
        T1["Tool 1: Compliance Checker<br/>compliance_engine.py, main.py"]
        T2["Tool 2: Golden Config Creator<br/>golden_config_builder.py"]
        T3["Tool 3: Remediation Advisor<br/>agent_assisted_coding_advise.py"]
        T5["Tool 5: Compliance Report Generator<br/>compliance_report_builder.py"]
        T6["Tool 6: Executive Dashboard<br/>compliance_dashboard_builder.py"]
        Controls[("controls.yaml<br/>single source of truth")]
    end

    subgraph LLM["Local LLM Backend (optional)"]
        Phi["phi4_mini<br/>llama-server :8081"]
        Qwen["qwen_coder<br/>llama-server :8080"]
    end

    subgraph Storage["webapp/data/ (isolated workspace)"]
        Configs[("device_configs/")]
        Profiles[("golden_profiles/")]
        Runs[("runs/")]
        History[("compliance_history/")]
    end

    UI -- "fetch(): JSON + multipart" --> Routes
    Routes --> Services
    Services --> Jobs
    Services --> T1
    Services --> T2
    Services --> T3
    Services --> T5
    Services --> T6
    T1 --> Controls
    T2 --> Controls
    T3 --> Controls
    T5 --> Controls
    T6 --> Controls
    T3 -.->|HTTP| Phi
    T3 -.->|HTTP| Qwen
    T5 -.->|"optional polish"| Phi
    T5 -.->|"optional polish"| Qwen
    Services -->|start/stop| Phi
    Services -->|start/stop| Qwen
    Services --> Configs
    Services --> Profiles
    Services --> Runs
    Services --> History
```

## 2. Analysis run — end to end

The core user journey: pick configs and a Golden Config, run the real
compliance engine, and land on the downstream screens. One device's
unexpected failure is isolated and never aborts the batch.

```mermaid
sequenceDiagram
    actor User
    participant UI as Web Frontend
    participant API as FastAPI Routes
    participant AS as analysis_service.py
    participant BG as Background Thread (jobs.py)
    participant Eng as main._evaluate_device()<br/>(real compliance engine)
    participant FS as webapp/data/runs/(timestamp)/

    User->>UI: Select configs + Golden Config profile
    UI->>API: POST /api/analysis/run
    API->>AS: start_analysis(files, profile_id)
    AS->>AS: validate files exist + Golden Config<br/>has no unresolved values
    AS->>BG: jobs.start_job("analysis", work)
    AS-->>UI: 200 {job_id}

    activate BG
    BG->>FS: create run dir, write _golden_config_used.txt
    loop for each selected device, in order
        BG->>Eng: _evaluate_device(config, golden_config, controls)
        alt evaluates cleanly
            Eng-->>BG: ControlResult[]
            BG->>FS: write <device>/report.json + report.html
        else unexpected error
            Eng-->>BG: exception
            BG->>BG: record in errored_devices, continue
        end
        BG->>BG: report_progress(index, "Analyzing X of N")
    end
    BG->>FS: fleet_report.html (if more than one device)
    deactivate BG

    loop poll every ~800ms
        UI->>API: GET /api/analysis/jobs/{job_id}
        API-->>UI: {status, processed, total, current_label}
    end
    UI->>API: GET /api/analysis/jobs/{job_id}
    API-->>UI: {status: "done", result}
    UI-->>User: Summary + links to Dashboard / Briefings / Compliance Report
```

## 3. Golden Config Manager — edit, preview, save

"Default" is never stored — it's rendered on demand from the repo's real
`controls.yaml` + `device_vars.json`, so it can never drift from what
`golden_config_main.py` would produce. Live preview calls a non-persisting
endpoint so editing never silently saves.

```mermaid
sequenceDiagram
    actor User
    participant UI as Golden Config page
    participant API as FastAPI Routes
    participant GS as golden_service.py
    participant GCB as GoldenConfigBuilder (real engine)
    participant FS as webapp/data/golden_profiles/

    UI->>API: GET /api/golden/schema
    API->>GS: get_form_schema()
    GS-->>UI: dynamic form fields<br/>(from controls.yaml + device_vars.schema.json)

    UI->>API: GET /api/golden/profiles/{id}
    API->>GS: get_profile(id)
    alt id == "__default__"
        GS->>GCB: build() using the repo's real device_vars.json
    else named profile
        GS->>FS: read device_vars.json
        GS->>GCB: build() using the profile's device_vars
    end
    GCB-->>UI: rendered_text + missing[]

    User->>UI: edits a field
    UI->>UI: debounce ~500ms
    UI->>API: POST /api/golden/preview {device_vars}
    API->>GS: render_preview() — not persisted
    GS->>GCB: build()
    GCB-->>UI: live preview + missing[] + warnings[]

    User->>UI: clicks Save
    UI->>API: PUT /api/golden/profiles/{id} {device_vars}
    API->>GS: update_profile()
    GS->>GCB: build() — validates shape first
    alt valid
        GS->>FS: write device_vars.json + metadata.json
        GS-->>UI: 200 rendered_text
    else shape/jsonschema error
        GS-->>UI: 422 {detail}
    end
```

## 4. Local LLM engine lifecycle

Added so Briefings and Compliance Report polishing can be turned on/off from
the Settings screen instead of a terminal. "Running" means the OS process is
alive — `reachable` (the Online badge) only flips true once the model has
finished loading.

```mermaid
stateDiagram-v2
    [*] --> Stopped: no process, or not started by this app
    Stopped --> Running: POST /api/settings/engines/{name}/start
    Running --> Stopped: POST .../stop (SIGTERM, then SIGKILL after 20s)
    Running --> Failed: process exits unexpectedly
    Failed --> Running: start again

    note right of Running
        reachable=false while the model is
        still loading; log tail shows the
        GPU-offload confirmation once ready
    end note

    note left of Stopped
        Starting is rejected (409) if ANY
        other registered backend is currently
        reachable - only one engine fits in
        VRAM at a time on this hardware
    end note
```

## 5. Screen map

How the eight screens connect. Dotted lines mean "needs the LLM backend
reachable"; everything else works without it.

```mermaid
flowchart LR
    Overview((Overview)) --> ConfigFiles[Configuration Files]
    Overview --> Analysis
    Overview --> Dashboard

    ConfigFiles -- "upload .txt configs" --> Analysis
    GoldenConfig[Golden Config Manager] -- "active profile" --> Analysis
    Analysis -- run_id --> Briefings
    Analysis -- run_id --> ComplianceReport[Compliance Report]
    Analysis -- run_id --> Dashboard

    Briefings -.->|needs| LLM[(Local LLM Backend)]
    ComplianceReport -.->|optional polish| LLM
    Settings -.->|start / stop| LLM

    classDef page fill:#eef,stroke:#88a,color:#111
    class Overview,ConfigFiles,GoldenConfig,Analysis,Briefings,ComplianceReport,Dashboard,Settings page
```
