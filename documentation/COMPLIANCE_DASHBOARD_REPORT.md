# Executive Compliance Dashboard (Tool 6) — Delivery Report

Delivered per `NCM_Claude_Code_Compliance_Dashboard_Prompt.md`. This report follows that prompt's section 24 deliverables list.

## 1. Architecture changes

A new Tool 6 was added following the same pattern as Tools 1/3/5 (a CLI entrypoint over a set of focused modules, timestamped archiving via the existing `run_archive.py`). Nothing about how controls are evaluated changed — Tool 6 reads what Tool 1 already writes (`report.json` per device) and adds an aggregation/analytics/rendering layer on top. No web framework was introduced: the dashboard is one self-contained static HTML file per run, with the fleet's data embedded inline and vanilla JS handling client-side filtering — consistent with how Tools 1 and 5 already produce static Jinja2-rendered HTML/PDF, and honoring the prompt's own preference for reusing existing libraries over adding heavy new ones.

Two small, deliberate changes reached into the existing pipeline:
- `main.py`'s per-device evaluation loop now catches an unexpected checker exception **per control** instead of letting it crash the whole device (and, in batch mode, the rest of the fleet). This is what makes `ASSESSMENT_ERROR` a real, reachable state rather than only a synthetic one in tests.
- `main.py`'s `load_exceptions()` now accepts either the original plain-string form or a dict with approval metadata per control — `ControlEvaluator` itself is unchanged either way (it never sees anything but the reason string), so the core `EXCEPTION` status logic is untouched.

## 2. Files created / modified

**New:**
- `compliance_models.py` — the 7-value status taxonomy + mapping from Tool 1's real statuses, severity tiers, `NormalizedFinding`.
- `compliance_metrics.py` — every formula and aggregation (strict/accepted/coverage %, device/control summaries, severity counts, Pareto, top non-compliant devices, fleet metrics).
- `compliance_history.py` — snapshot write/read for the trend chart.
- `compliance_exceptions.py` — reads `exceptions.yaml`'s optional approver/ticket/expiration metadata (independent of `main.py`'s own simpler read).
- `compliance_svg_charts.py` — the multi-segment donut and trend sparkline (inline SVG, no charting library).
- `compliance_dashboard_builder.py` — orchestration: load reports → normalize → compute → snapshot → summarize → render.
- `compliance_dashboard_main.py` — the Tool 6 CLI entrypoint.
- `templates/compliance_dashboard.html` — the dashboard itself.
- `tests/test_compliance_metrics.py`, `tests/test_compliance_history.py`, `tests/test_compliance_dashboard_builder.py` — 32 new tests.
- `NCM_Claude_Code_Compliance_Dashboard_Prompt.md` — this task's source prompt, checked in per this project's established convention of keeping every tool's originating spec in the repo.

**Modified:**
- `main.py` — per-control try/except → `ASSESSMENT_ERROR`; `load_exceptions()` accepts dict-or-string.
- `compliance_engine.py` — added the `STATUS_ASSESSMENT_ERROR` constant only.
- `report_schema.py` — `ControlReportEntry.status` Literal gained `"ASSESSMENT_ERROR"`.
- `tests/test_main_batch.py` — added a test proving one bad control no longer crashes the run.
- `documentation/RUNNING_THE_APP.md`, `CLAUDE.md` — Tool 6 documented; the `exceptions.yaml` metadata format and `ASSESSMENT_ERROR` behavior documented where Tool 1 is described.

## 3. New dependencies

**None.** Charts are hand-rolled inline SVG (donut, sparkline) and HTML/CSS (bars, heatmap), matching the precedent `compliance_report_builder.donut_svg()` already set for this project. Filtering is vanilla JS. CSV export uses Python's stdlib `csv` module. The PDF export reuses the existing `report_generator.render_pdf` (WeasyPrint) path.

## 4. Formulas (all in `compliance_metrics.py`, this is not duplicated anywhere else)

```
applicable_expected_checks = count of all findings where status != N_A

strict_compliance_pct      = 100 * count(PASS) / applicable_expected_checks

accepted_posture_pct       = 100 * count(PASS or (APPROVED_EXCEPTION and not expired))
                              / applicable_expected_checks
                              (None when no exception exists at all - the KPI is hidden
                               rather than shown identical to strict compliance)

assessment_coverage_pct    = 100 * count(PASS, FAIL, APPROVED_EXCEPTION, MANUAL_REVIEW)
                              / applicable_expected_checks
                              (an expired exception still counts here - it was assessed,
                               it just isn't "accepted" anymore)
```
An expired exception is **never** counted as PASS in `strict_compliance_pct` (it never was) and is excluded from `accepted_posture_pct`'s numerator — verified live: a synthetic expired exception produced identical strict/accepted percentages (40.0% both), i.e. zero benefit from expiring, exactly as required.

## 5. Persistence / history model

One JSON file per dashboard run in `compliance_history/<timestamp>.json` (never overwritten — same timestamped-never-replace convention as every other archive in this project, but note `run_archive.py`'s `latest/` mirror is deliberately **not** reused here since a full-replace mirror is the opposite of what history needs). Each snapshot holds the run's *aggregated* `FleetMetrics` plus `controls_version` (the existing `compliance_report_builder.controls_version()` git-hash helper) — enough to redraw every trend line, not a full per-device/per-control replay of a past run. Only the current run's `reports_dir` supports full drill-down; this tradeoff is stated explicitly rather than silently implied.

## 6. Screens / views implemented

Executive summary text; 10 KPI cards (Accepted Posture hidden when no exceptions exist); device posture donut (5 categories); findings-by-severity bars; compliance-by-control bars (sorted worst-first); top-failing-controls Pareto with cumulative %; top-non-compliant-devices table (critical failures break ties); compliance trend sparkline; device × control heatmap (sticky headers, hover tooltips, text search filter); per-device drill-down (`<details>` per device, every non-passing control with evidence + remediation); per-control drill-down (`<details>` per control, every affected device); findings/remediation table (search + severity + status filters, live count). All of it live-verified against the real 75-device fleet, not just unit-tested.

## 7. Tests added and results

32 new tests (`test_compliance_metrics.py`: 20, `test_compliance_history.py`: 4, `test_compliance_dashboard_builder.py`: 12) plus 1 new test in `test_main_batch.py` for `ASSESSMENT_ERROR`. **Full suite: 205/205 passing.**

Live verification beyond pytest: ran the real 75-device batch audit → built the dashboard → confirmed every KPI/executive-summary number by grep against the source HTML (82.4% strict compliance, 100% coverage, 198 failed checks, 0 critical — all internally consistent); ran it a second time and confirmed `compliance_history/` grew to 2 snapshots and the trend chart rendered "Trend over 2 runs"; constructed a synthetic report with an expired exception and confirmed it's excluded from accepted posture while still counted in strict compliance and coverage; constructed a synthetic report with an `ASSESSMENT_ERROR` entry and confirmed it renders with its own badge and is excluded from coverage. Test-only synthetic snapshots were deleted from `compliance_history/` afterward so the real fleet's history isn't polluted with single-device test data.

## 8. Known limitations / recommended follow-up

Documented explicitly rather than faked, per the prompt's own instruction:
- **No device metadata** (site/country/region/model/OS/vendor) exists anywhere in this pipeline — breakdown-by-dimension (spec §12) is not implemented. Adding it would require a real device inventory source this project doesn't have today.
- **No control is `Critical` severity by default** — the tier is fully wired (KPI, posture bucket, risk-override logic, executive-summary risk label) but nothing is elevated to it, per your explicit answer. Set `severity: Critical` on a control in `controls.yaml` if/when you decide one deserves it.
- **`Owner`/`Ticket`/`Due Date`** columns exist in the findings table/CSV but are always empty (no workflow-assignment system exists) — except `Ticket`, which is populated for an `APPROVED_EXCEPTION` row when its `exceptions.yaml` entry provides one.
- **History snapshots are aggregate-only** — a past run's full heatmap/drill-down can't be reconstructed, only its headline metrics.
- **Filters are scoped to the findings table and heatmap search**, not literally every chart on the page (the KPIs/donut/bars intentionally always reflect the full current run, so nobody misreads a filtered subset as the whole fleet's posture) — this is a narrower reading of the prompt's "filters update all components" than a fully cross-filtered BI tool would give, chosen to keep the implementation a static file with zero new dependencies rather than a live web app.
- **Security-domain grouping (spec §7)** was not implemented this pass — the prompt explicitly says not to hard-code a mapping without more input on how you'd want these 15 controls grouped; happy to add it given a mapping.

## 9. How to run it

```bash
# 1. Audit a fleet (or single device) with Tool 1, requesting JSON output:
python main.py --device-config-dir device_configs --golden-config golden_config.txt \
  --controls controls.yaml --output-dir ./reports --formats json

# 2. Build the dashboard from that run:
python compliance_dashboard_main.py \
  --reports-dir reports/latest \
  --controls controls.yaml \
  --output-dir compliance_dashboards \
  --formats html,pdf,csv

# Open compliance_dashboards/latest/compliance_dashboard.html in a browser.
# Re-run step 2 after any later audit to add another point to the trend chart.
```
See `documentation/RUNNING_THE_APP.md` section 6 for the full flag reference and the `exceptions.yaml` metadata format.
