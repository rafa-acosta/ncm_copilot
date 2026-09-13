# Claude Code Implementation Prompt

## NCM Copilot - Executive Network Configuration Compliance Reporting

You are working on an existing **NCM Copilot / Network Configuration Management** Python application. Your task is to inspect the current codebase and implement a new **executive compliance reporting layer** for all network devices processed by the application (for example, a fleet of approximately 75 devices evaluated against the current 15 controls).

The new reporting capability must transform the existing per-device/per-control validation results into an executive, audit-oriented compliance experience with interactive charts, tables, drill-down analysis, historical trends, and exportable reports.

The visual inspiration is a modern executive dashboard: KPI cards, donut charts, horizontal bar charts, trends, heatmaps, risk summaries, and compact tables. The supplied dashboard image is **visual inspiration only**; do not copy its business metrics or unrelated content.

The intended result is not just a visually attractive dashboard. It should behave like a **Network Configuration Compliance & Audit Platform**: executives must understand the fleet posture in seconds, while engineers and auditors must be able to drill down from a high-level finding to the exact device, control, current configuration, expected configuration, and remediation guidance.

---

## 1. Important implementation constraints

Before modifying code:

1. Inspect the full repository and identify:
   - application framework and entry points;
   - current data flow;
   - device inventory representation;
   - control definitions;
   - validation result structures;
   - existing severity/risk metadata, if any;
   - current report generation logic;
   - persistence/storage mechanisms;
   - reusable UI components;
   - existing export functions.
2. Do not rewrite the application unnecessarily. Extend the current architecture and reuse existing components where practical.
3. Preserve all existing validation behavior unless a change is required to support reporting.
4. Do not hard-code the number of devices. The dashboard must work for any fleet size.
5. The current application version uses controls 1 through 15. Read the actual control names and logic from the codebase and project source-of-truth documentation rather than inventing or renaming them.
6. If a required field is not currently produced by the validation engine, add it in a backward-compatible way.
7. Avoid introducing heavy dependencies unless clearly justified. Prefer libraries already used by the project.
8. The reporting layer must be deterministic. Do not use an LLM to calculate compliance metrics that can be calculated directly from structured data.
9. Keep calculations centralized in a reporting/analytics service or module so the UI, exports, and future APIs use exactly the same definitions.
10. Add clear comments and docstrings around compliance formulas, status definitions, and risk logic.

---

## 2. Reporting objective

Create a reporting system that answers these questions immediately:

- What is the overall network configuration compliance posture?
- How many devices were assessed successfully?
- How many are fully compliant?
- How many contain findings?
- How many critical/high-risk findings exist?
- Which controls fail most often?
- Which devices are least compliant?
- Are failures isolated or systemic across the fleet?
- Which site, country, platform, model, OS version, or device type is driving the risk?
- Is compliance improving or deteriorating over time?
- Which findings are approved exceptions versus true unresolved failures?
- What should the remediation team work on first?
- Can an auditor trace a dashboard metric down to the exact evidence that produced it?

The design should support two audiences simultaneously:

- **Executive / management:** fast interpretation, risk posture, trends, priorities.
- **Engineering / audit:** evidence, affected devices, exact failed controls, configuration differences, remediation, and traceability.

---

## 3. Status taxonomy

Do not reduce all outcomes to PASS/FAIL. Normalize the result model so that each device-control evaluation can represent at least:

| Status | Meaning |
|---|---|
| PASS | The device satisfies the control. |
| FAIL | The device violates the control. |
| APPROVED_EXCEPTION | The device deviates from the baseline, but the deviation has documented approval. |
| N_A | The control is not applicable to this device. |
| MANUAL_REVIEW | Automated logic cannot safely determine compliance and human review is required. |
| ASSESSMENT_ERROR | Parsing, input, collection, or evaluation failed. |
| NOT_ASSESSED | No valid result exists yet for this device/control combination. |

If the existing application uses different names, create a mapping layer rather than breaking current behavior.

### Approved exception metadata

When status is `APPROVED_EXCEPTION`, support fields such as:

- device identifier;
- control identifier;
- reason;
- approver;
- ticket/change/reference number;
- approval date;
- expiration date;
- compensating control;
- notes.

Expired exceptions must be clearly visible and should no longer silently improve the compliance posture.

---

## 4. Compliance calculations

Implement centralized formulas and document them in code.

### 4.1 Applicable expected checks

For a reporting period:

`applicable_expected_checks = all device/control evaluations excluding N_A`

Do not let `N_A` inflate or reduce the compliance denominator.

### 4.2 Strict verified compliance

Recommended primary compliance metric:

`strict_compliance_pct = PASS / applicable_expected_checks * 100`

This is intentionally conservative: unassessed or errored checks must not silently increase compliance.

### 4.3 Accepted posture

Provide a secondary metric when approved exceptions exist:

`accepted_posture_pct = (PASS + valid APPROVED_EXCEPTION) / applicable_expected_checks * 100`

Label this clearly so it cannot be confused with strict compliance.

### 4.4 Assessment coverage

Show coverage separately from compliance:

`assessment_coverage_pct = evaluations_with_a_meaningful_result / applicable_expected_checks * 100`

A meaningful result normally includes PASS, FAIL, APPROVED_EXCEPTION, and MANUAL_REVIEW, while excluding NOT_ASSESSED and ASSESSMENT_ERROR. If the existing data model requires a slightly different definition, document it explicitly.

The dashboard must never present a high compliance percentage without also showing coverage.

### 4.5 Finding counts

Track at minimum:

- total FAIL evaluations;
- total devices containing one or more FAILs;
- critical/high/medium/low failures;
- approved exceptions;
- manual reviews;
- assessment errors;
- unassessed checks.

### 4.6 Device compliance score

For each device, calculate strict compliance across applicable controls. Preserve the raw counts beside the percentage.

Example:

`13 PASS / 15 applicable controls = 86.7%`

Do not allow the percentage to hide a critical failure.

---

## 5. Risk and severity model

Each control should support a severity classification such as:

- CRITICAL
- HIGH
- MEDIUM
- LOW

Use existing project metadata if present. If severity is not yet modeled, add it to the control definition/schema rather than scattering severity values throughout the UI.

The severity must be configurable because organizations may classify the same control differently.

### Risk behavior

A critical control failure should be visually prominent and may override an otherwise high device compliance score. For example, a device with 14/15 PASS should not appear healthy if the only failure is a critical management-plane access control.

Where device/business criticality metadata exists, design the scoring/prioritization layer so future logic can combine:

`control severity x affected device count x device/business criticality`

Do not invent business criticality when it does not exist.

---

## 6. Executive Dashboard - primary landing page

Build a fleet-level executive dashboard as the default reporting view.

### 6.1 Header

Display:

- report title, for example **Network Configuration Compliance**;
- assessment date/time;
- reporting period if applicable;
- fleet/device count;
- policy/baseline version if available;
- last successful data refresh.

### 6.2 KPI cards

Include prominent KPI cards for at least:

| KPI | Purpose |
|---|---|
| Strict Compliance | Primary verified compliance percentage. |
| Accepted Posture | PASS plus valid approved exceptions. Show only when exceptions exist. |
| Devices Assessed | Number successfully represented in the assessment. |
| Fully Compliant Devices | Devices with no unresolved applicable failures. |
| Devices With Findings | Devices containing at least one unresolved FAIL. |
| Critical Findings | Count of critical failures. |
| Failed Checks | Total failed device-control evaluations. |
| Approved Exceptions | Active approved deviations. |
| Assessment Coverage | Percentage of applicable checks successfully evaluated. |
| Assessment Errors | Parsing/evaluation/collection failures. |

Do not hard-code sample values.

### 6.3 Device posture donut

Create a donut/pie visualization showing device posture. Use categories that are meaningful and mutually exclusive, for example:

- Fully Compliant
- Compliant With Approved Exceptions
- Needs Remediation
- Critical Non-Compliant
- Not Fully Assessed

Display counts and percentages in tooltips and/or labels.

### 6.4 Findings by severity

Create a clear visual summary of:

- Critical
- High
- Medium
- Low

Show both finding count and affected-device count when possible.

### 6.5 Compliance by control

Create one horizontal bar per current control. Show:

- control ID;
- control name;
- compliance percentage;
- PASS count;
- FAIL count;
- severity;
- affected-device count.

Allow sorting by:

- lowest compliance first;
- highest number of failures;
- severity;
- control ID.

Default to a prioritization-friendly view such as lowest compliance or highest risk first.

### 6.6 Top failing controls / Pareto

Add a ranked chart showing the controls responsible for the most failures. This is intended to expose systemic baseline/template issues.

Where practical, include a cumulative Pareto percentage or at least descending failure counts.

### 6.7 Top non-compliant devices

Show a compact table or bar chart with the devices requiring the most attention, including:

- hostname/device name;
- compliance percentage;
- failed controls;
- critical/high failures;
- site/country/type when available.

### 6.8 Compliance trend

Show fleet compliance over time. At minimum support:

- strict compliance trend;
- assessment coverage trend;
- critical findings trend.

Historical trend logic must use persisted assessment snapshots rather than reconstructing history from the latest state.

---

## 7. Security-domain summary

For executive readability, allow controls to be grouped into higher-level security/configuration domains.

Do not hard-code a final mapping without checking the actual 15 controls. Create a configurable mapping structure.

Possible domain concepts include:

- Device Identity & Baseline
- Authentication & Authorization
- Secure Management Plane
- Credential Protection
- Logging & Monitoring
- Time Synchronization
- Legal / Access Notification

For each domain show:

- compliance percentage;
- failed checks;
- affected devices;
- highest severity finding;
- trend where historical data exists.

Use a horizontal bar chart or other easy-to-read visual. Avoid radar charts if they reduce readability.

---

## 8. Compliance heatmap

Create a fleet heatmap/matrix:

- rows = devices;
- columns = controls;
- cells = normalized control status.

Suggested status visualization:

- PASS - green
- FAIL - red
- APPROVED_EXCEPTION - amber/yellow
- N_A - neutral gray
- MANUAL_REVIEW - blue/purple
- ASSESSMENT_ERROR - dark/outlined warning state
- NOT_ASSESSED - muted/empty state

Requirements:

- support scrolling for large fleets;
- sticky row/column headers if possible;
- filters must affect the matrix;
- hover/click must show device, control, status, severity, and relevant evidence summary;
- allow sorting devices by compliance/risk;
- allow clicking a FAIL cell to open the corresponding device-control detail view.

The heatmap is a primary diagnostic tool for recognizing systemic patterns such as an entire control column failing across many devices.

---

## 9. Device analysis view

When the user selects a device, show a detailed compliance card/page.

### Device summary

Display:

- hostname/device identifier;
- IP address if available and safe to display;
- site/country;
- device type/model;
- OS/version;
- assessment timestamp;
- strict compliance percentage;
- accepted posture percentage when relevant;
- PASS/FAIL/EXCEPTION/N_A/MANUAL/ERROR counts;
- overall risk state.

### Per-control table

Show every applicable control with:

- control ID;
- control name;
- status;
- severity;
- short reason/finding;
- remediation availability;
- evidence availability.

### Control drill-down for a device

For a selected failed or reviewed control, show:

**Control**
- control ID and name;
- description/objective;
- severity;
- source/baseline reference if available.

**Assessment result**
- status;
- explanation;
- parser/evaluator details when useful.

**Expected configuration**
- expected commands or normalized rule.

**Detected/current configuration**
- relevant configuration extracted from the device.

**Difference**
- clear diff or structured comparison.

**Remediation**
- recommended configuration commands or corrective guidance generated by existing deterministic logic/source-of-truth rules;
- do not invent remediation when the project does not define it.

**Evidence and traceability**
- input/config file reference;
- assessment timestamp;
- policy/control version;
- exception/ticket information when applicable.

---

## 10. Control analysis view

When the user selects a control, show fleet-wide information for that control:

- control ID/name;
- description;
- severity;
- fleet compliance percentage;
- PASS/FAIL/EXCEPTION/N_A/ERROR counts;
- number of affected devices;
- trend over time;
- distribution by site/country/device type/model/OS where metadata exists;
- table of affected devices;
- ability to drill down to each device finding.

This view should make it easy to determine whether a failure is isolated or systemic.

---

## 11. Findings and remediation view

Create an actionable findings table. Suggested columns:

| Field | Description |
|---|---|
| Priority | Derived from severity and available context. |
| Device | Affected device. |
| Site/Country | If metadata exists. |
| Control | Control ID and name. |
| Finding | Concise failure reason. |
| Severity | Critical/High/Medium/Low. |
| Status | Open, exception, manual review, etc. |
| Owner | Optional if the application supports assignment. |
| Ticket/Change | Optional traceability reference. |
| Due Date | Optional remediation target. |
| Last Assessed | Timestamp. |

Support:

- filtering;
- sorting;
- CSV/Excel export if the project already supports tabular exports or can add this cleanly;
- clicking a row to open evidence/details.

If workflow fields such as owner/ticket/due date do not currently exist, architect them as optional and do not fake values.

---

## 12. Breakdown analysis

When metadata is available, allow fleet compliance to be analyzed by:

- site;
- country;
- region;
- device type;
- vendor;
- model;
- OS/firmware version;
- business/service group.

Only expose dimensions that actually exist in the application data.

Each breakdown should show at least:

- device count;
- compliance percentage;
- failed checks;
- critical/high findings;
- assessment coverage.

The UI must make it obvious when a group contains very few devices so small samples are not overinterpreted.

---

## 13. Historical snapshots and trend persistence

If the application does not already persist historical assessment results, implement a lightweight, maintainable history mechanism appropriate for the existing architecture.

Each assessment snapshot should preserve enough information to reproduce historical metrics, including where practical:

- assessment/run ID;
- timestamp;
- policy/baseline version;
- device identifier;
- control identifier;
- status;
- severity at time of assessment;
- relevant result/finding summary;
- exception state;
- key device metadata.

Do not overwrite the only copy of previous assessment data.

Provide a reasonable retention strategy/configuration if needed, but do not delete history silently.

---

## 14. Executive risk statement

Generate a short deterministic executive summary from structured metrics. Example style:

> Overall Configuration Posture: MODERATE RISK. 75 network devices were evaluated against 15 configuration controls. Strict verified compliance is 91.7% with 98.4% assessment coverage. 17 devices contain unresolved deviations and 4 critical findings remain open. Management-plane access controls represent the largest systemic gap.

Requirements:

- derive all values from actual data;
- no hallucinated causes;
- only describe a control as the largest systemic gap when the data proves it;
- include coverage with compliance;
- identify critical findings when present;
- keep the summary short enough for an executive report.

This can be generated from templates/rules and does not require an LLM.

---

## 15. Filters and interaction

Provide a coherent filter bar, depending on available metadata:

- assessment date/run;
- site/country/region;
- device type/model/vendor;
- OS version;
- control;
- security domain;
- severity;
- status;
- compliant/non-compliant;
- exception state.

Requirements:

- all dashboard components should update consistently when filters are applied;
- display the active filter context clearly;
- provide a reset/clear-filters action;
- preserve usability with approximately 75 devices and scale reasonably beyond that;
- do not reload/reprocess raw device configuration files just to change a visualization filter if results are already available in memory/storage.

---

## 16. Visual design requirements

Use the supplied executive dashboard image only as aesthetic inspiration.

Design goals:

- modern executive cybersecurity/compliance appearance;
- strong visual hierarchy;
- compact but not crowded;
- dark navy/charcoal surfaces are acceptable if compatible with the current application;
- restrained accent colors;
- consistent card spacing;
- clear typography;
- responsive layout;
- charts must remain readable on typical laptop/desktop screens;
- avoid decorative elements that do not convey information;
- avoid 3D charts;
- avoid excessive pie charts;
- use donut/pie charts only for simple part-to-whole summaries;
- prefer horizontal bars for ranked controls/devices;
- use line charts for trends;
- use heatmaps for device-control matrices;
- use tables when exact values matter.

### Status colors

Use a consistent and accessible semantic palette. Do not rely on color alone: include icons, labels, text, patterns, or tooltips where appropriate.

Recommended semantics:

- PASS / healthy: green
- FAIL / critical problem: red
- approved exception / warning: amber
- manual review: blue/purple
- N_A / neutral: gray
- unknown/error: distinct warning/neutral state

If the existing application has a design system, integrate with it rather than creating conflicting styles.

---

## 17. Report export

Add an executive export capability if the architecture supports it cleanly.

Preferred outputs:

1. **PDF executive report** for management/audit distribution.
2. **HTML report** when practical for interactive/local review.
3. **CSV/Excel findings export** for engineering remediation tracking.

The PDF should contain, at minimum:

- title and assessment metadata;
- executive risk statement;
- KPI summary;
- device posture chart;
- severity summary;
- compliance by control;
- top failing controls;
- top non-compliant devices;
- compliance trend when history exists;
- concise findings summary;
- optional appendix with control/device details.

Do not attempt to place all 75 x 15 raw results on the first page. Keep the executive section concise and move technical detail to an appendix or separate section.

---

## 18. Audit traceability requirements

Every high-level metric must be reproducible from underlying results.

For any displayed number, the application should be able to trace the result through this chain:

`Executive metric -> filtered evaluation set -> device/control results -> evidence/current configuration -> expected baseline -> remediation/reference`

Avoid calculations performed only in UI components with no reusable service/module behind them.

Where possible, retain:

- run ID;
- timestamp;
- source configuration file/device;
- control version;
- policy/baseline version;
- evaluation result;
- exception metadata;
- evidence excerpt/reference.

---

## 19. Recommended architecture

Adapt this concept to the actual repository; do not force these exact filenames if the current structure suggests a better design.

A clean separation could resemble:

```text
ncm/
  compliance/
    models.py             # Normalized statuses, finding/result models
    metrics.py            # Centralized calculations
    risk.py               # Severity/prioritization logic
    aggregation.py        # Fleet/control/device/site aggregations
    history.py            # Snapshot persistence/access
    executive_summary.py  # Deterministic summary text
    exports.py            # PDF/HTML/tabular report export
  ui/
    compliance_dashboard.py
    device_compliance.py
    control_compliance.py
    findings.py
    components/
      kpi_cards.py
      charts.py
      heatmap.py
      filters.py
```

If equivalent modules already exist, extend them instead of duplicating them.

---

## 20. Performance and robustness

The reporting layer should not significantly slow configuration analysis.

Requirements:

- calculate aggregations from normalized results, not by reparsing configs repeatedly;
- cache/reuse safe intermediate results when the framework supports it;
- gracefully handle missing metadata;
- gracefully handle zero-device/zero-result states;
- avoid division-by-zero errors;
- surface assessment errors rather than discarding them;
- validate status values;
- provide deterministic ordering for tables and reports;
- preserve the ability to run the application offline/local if that is a project requirement.

---

## 21. Testing requirements

Add or update tests for the reporting logic.

At minimum test:

- strict compliance formula;
- accepted posture formula;
- assessment coverage formula;
- N_A denominator behavior;
- approved exception handling;
- expired exception behavior if implemented;
- severity counts;
- device aggregation;
- control aggregation;
- filter behavior;
- zero-result/empty dataset behavior;
- assessment-error handling;
- historical snapshot calculations;
- executive summary correctness.

Create small synthetic fixtures representing mixed PASS/FAIL/EXCEPTION/N_A/MANUAL/ERROR states.

Do not use only visual/manual testing for metric correctness.

---

## 22. Implementation workflow

Follow this sequence:

### Phase 1 - Repository assessment

Inspect the current codebase and produce a concise implementation plan describing:

- current architecture;
- current result model;
- gaps versus this specification;
- files/modules to modify;
- files/modules to add;
- dependency changes, if any;
- migration/backward-compatibility considerations.

### Phase 2 - Data model and analytics

Implement or normalize:

- statuses;
- control severity;
- evaluation records;
- fleet metrics;
- device metrics;
- control metrics;
- security-domain aggregation;
- risk summaries;
- assessment coverage.

### Phase 3 - Historical persistence

Add/reuse snapshot storage and history queries.

### Phase 4 - UI

Implement:

- executive dashboard;
- heatmap;
- device view;
- control view;
- findings/remediation view;
- filters and drill-down navigation.

### Phase 5 - Export

Add PDF/HTML/tabular export as appropriate for the current architecture.

### Phase 6 - Tests and validation

Run the full test suite, add reporting tests, and verify calculated totals manually on a small fixture.

### Phase 7 - Final review

Check:

- no existing functionality was unintentionally removed;
- metrics are consistent across dashboard and export;
- charts use the same filtered dataset as tables;
- no sample/demo values remain hard-coded;
- UI works with the real device count;
- errors/unknown states are visible rather than silently ignored.

---

## 23. Minimum acceptance criteria

The implementation is considered complete only when all of the following are true:

- [ ] The application provides a fleet-level executive compliance dashboard.
- [ ] All current devices are included dynamically; the fleet size is not hard-coded.
- [ ] All current controls 1-15 are represented dynamically from the actual control definitions.
- [ ] Strict compliance and assessment coverage are shown separately.
- [ ] PASS, FAIL, APPROVED_EXCEPTION, N_A, MANUAL_REVIEW, ASSESSMENT_ERROR, and NOT_ASSESSED can be represented or mapped cleanly.
- [ ] Critical/high/medium/low finding counts are available.
- [ ] Device posture donut/summary is available.
- [ ] Compliance-by-control visualization is available.
- [ ] Top failing controls visualization is available.
- [ ] Top non-compliant devices view is available.
- [ ] Device x control heatmap is available.
- [ ] Device drill-down is available.
- [ ] Control drill-down is available.
- [ ] Findings/remediation table is available.
- [ ] Historical compliance trend is available when at least two snapshots exist.
- [ ] Filters update all relevant dashboard components consistently.
- [ ] Executive summary text is generated from structured data.
- [ ] PDF executive export is available, or a clearly documented technical blocker is identified if the current stack makes it unreasonable.
- [ ] Metrics are covered by automated tests.
- [ ] Existing NCM validation functionality continues to work.

---

## 24. Deliverables expected from you

After implementation, provide:

1. A concise summary of the architecture changes.
2. A list of created/modified files.
3. Any new dependency and why it was required.
4. Exact definitions/formulas used for compliance and coverage.
5. Description of the persistence/history model.
6. Screens/views implemented.
7. Tests added and test results.
8. Known limitations or recommended follow-up improvements.
9. Instructions to run the application and generate/export the compliance report.

Do not stop after creating mockups. Implement the reporting functionality in the existing application, test it, and leave the repository in a runnable state.
