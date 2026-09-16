# Control Spec Update Report

Delivered per the task "Update Compliance Controls Based on New Control Specification and Production Configuration." Sources used: `Prompt Agent Assisted Copilot Project.pdf` (functional spec, priority 1 for *what* each control validates) and `support_files/NCM Configuration Script.txt` (production reference, priority 1 for *which commands* represent the expected configuration).

Net result: `controls.yaml` now defines all 18 controls (control_00007 is no longer a gap); `control_00001`-`control_00015` are the unconditional active/scored set in this version; `control_00016`-`control_00018` stay defined for future use but are never evaluated, scored, or rendered by default; `control_00007` (new) and `control_00008` (rebuilt) got real deterministic checkers; `control_00015` was found to already match the new spec, so it's unchanged functionally.

---

## A. Control Mapping (control_00001–control_00015)

### control_00001 — Hostname
- **Purpose:** Enforce the corporate hostname naming convention.
- **Functional requirement:** Underscore-separated `COMPANY_COUNTRY_TYPE_FUNCTION_SITE_DEVICENUMBER`; not generic (router/switch/etc).
- **Production commands:** `hostname ACME_USA_RT_INT_GOLDEN_01` (NCM script) — matches convention.
- **Evaluated by:** `_check_control_00001` — regex-splits on `_`, checks ≥6 parts and not a generic name.
- **PASS:** ≥6 underscore parts, not a generic name. **FAIL:** missing, generic, or too few parts.
- **Evidence:** the `hostname` line. **Remediation:** apply the naming convention.
- **Change:** none — spec/production match current implementation exactly.

### control_00002 — Domain
- **Purpose:** Domain name required for RSA key generation.
- **Functional requirement:** `ip domain name <company_name>` present.
- **Production commands:** `ip domain name acme.com`.
- **Evaluated by:** `_check_control_00002` — presence + literal match against golden's domain (a genuinely shared infrastructure value, not a per-device placeholder).
- **PASS:** present and matches golden. **FAIL:** missing or mismatched.
- **Change:** none.

### control_00003 — AAA
- **Purpose:** Full AAA (authentication/authorization/accounting) framework.
- **Functional requirement:** All 12 `aaa ...` lines present, all referencing the same TACACS group.
- **Production commands:** matches verbatim (`aaa new-model`, `aaa authentication password-prompt LOCAL_PASS:`, ... all referencing `ACME_TACACS_SERVER_GROUP`).
- **Evaluated by:** `_check_control_00003` — 12 required regex patterns + group-name consistency check.
- **Change:** none.

### control_00004 — TACACS
- **Purpose:** External TACACS+ server communication.
- **Functional requirement:** `aaa new-model`, ≥2 `tacacs server` blocks with address/key/timeout, `aaa group server tacacs+` block with matching server names + source-interface.
- **Production commands:** two `tacacs server` blocks, `address ipv4 ...`, `key 0 ...` (see Discrepancies — G1), `timeout 10`, `aaa group server tacacs+ ACME_TACACS_SERVER_GROUP`.
- **Evaluated by:** `_check_control_00004` (unchanged this pass) — presence, ≥2 servers, per-server address (presence + no duplicates + literal match against golden when golden gives a real IP), key/timeout presence, Type-7-key rejection, group name literal match, source-interface presence.
- **Change:** none functionally — see Discrepancies (G1) for the `key 0` finding that surfaced but wasn't acted on.

### control_00005 — Local and emergency users
- **Purpose:** Local break-glass admin account + enable secret, strong hashing.
- **Functional requirement:** username present, enable secret present, strong (scrypt) hashing.
- **Production commands:** `username admin_bckp privilege 15 algorithm-type scrypt secret 0123456789`.
- **Evaluated by:** `_check_control_00005` — username/enable-secret presence, weak-hash-type (0/4/5/7) rejection, cross-account hash-type consistency.
- **Change:** none.

### control_00006 — SSH
- **Purpose:** RSA keys + SSH hardening for encrypted management.
- **Functional requirement:** hostname + domain prerequisites, 2048-bit RSA keys, SSH version/timeout/retries.
- **Production commands:** `ip ssh time-out 60`, `ip ssh version 2` (no `crypto key generate rsa` — see Discrepancies, this is a pre-existing gap in the checker unrelated to this task, not modified).
- **Evaluated by:** `_check_control_00006` — hostname/domain presence, SSH-version presence, RSA-zeroize-without-regen detection.
- **Change:** none.

### control_00007 — Global password encryption (NEW)
- **Purpose:** AES-128 master key encrypting TACACS+/RADIUS/routing keys to Type-6 at rest.
- **Functional requirement:** `key config-key password-encrypt <device_master_key>` and `password encryption aes` both present.
- **Production commands:** `key config-key password-encrypt 0123456789` / `password encryption aes` (verbatim from `NCM Configuration Script.txt`).
- **Evaluated by:** new `_check_control_00007` — presence of both lines via regex.
- **PASS:** both present. **FAIL:** either missing.
- **Change:** was previously an intentional gap in `controls.yaml` (source doc numbering jumped 00006→00008). Now a real entry with a real checker, and included in `ACTIVE_CONTROL_IDS`.

### control_00008 — ACL for VTY (REBUILT)
- **Purpose:** A named ACL exists to scope administrative access.
- **Functional requirement:** `ip access-list extended <name>` exists — existence only, per the spec's single `not_compliance_condition`.
- **Production commands:** `ip access-list extended ACME_VTY_MGMT_ACL` / `permit ip any any` — see Discrepancies (G2), the production script's own comment flags this ACL body as a "LAB/TESTING ONLY... replace before production" placeholder.
- **Evaluated by:** new `_check_control_00008` — existence-only regex check. **Old logic deleted** (was "Telnet Blocking": VTY `transport input ssh` — fully redundant with `control_00014`'s own transport-input check, which is untouched and still enforces it).
- **PASS:** any `ip access-list extended <name>` block exists. **FAIL:** none exists. Whether it's bound to VTY (`access-class`) or restrictive is `control_00014`'s job, not this control's.
- **Change:** title, purpose, command_template, checker, and Golden Config Creator rendering all rebuilt. `_SUBSUMED_BY` (which made it a pointer-comment to `control_00014`) is now empty — it renders its own real ACL block, using the same `acl_name` (`ACME_VTY_MGMT_ACL`) as `control_00014`'s `vty_acl_name`, so both controls describe one consistent real-world ACL.

### control_00009 — NTP
- **Purpose:** Time sync with authenticated, preferred NTP servers.
- **Functional requirement:** ≥2 NTP servers, `prefer` on primary, authentication configured.
- **Production commands:** matches verbatim.
- **Evaluated by:** `_check_control_00009` (unchanged).
- **Change:** none.

### control_00010 — Syslog
- **Purpose:** Centralized logging.
- **Functional requirement:** `logging on`, host, `trap informational`, `source-interface`.
- **Production commands:** matches verbatim.
- **Evaluated by:** `_check_control_00010` (unchanged).
- **Change:** none.

### control_00011 — SNMP
- **Purpose:** SNMPv3 with auth+priv, no v1/v2c coexistence.
- **Functional requirement:** SNMPv3 group/user/host/traps, SHA+AES.
- **Production commands:** matches verbatim.
- **Evaluated by:** `_check_control_00011` (unchanged).
- **Change:** none.

### control_00012 — Banners
- **Purpose:** Legal/informative access banner.
- **Functional requirement (this spec revision):** `banner motd` configured; content matches corporate policy (`manual_review: true`, `deterministic_validation: false` per the PDF).
- **Production commands:** `banner motd $ ++This is the message of the day++ $` wrapped in a `! MANUAL REVIEW REQUIRED` comment (this is Tool 2's own render style, not raw device output).
- **Evaluated by:** `_check_control_00012` (added earlier this session, **intentionally not reverted** — see below) — presence-only check that now drives PASS/FAIL and the compliance score, even though `manual_review: true` is still set.
- **Change:** none made *in this task*. Flagged here because the spec text (Deterministic Validation: No) doesn't match the current implementation (`deterministic_validation: true`, a checker runs) — this is a deliberate, already-approved, already-documented deviation from an earlier session, not something this task altered. See `CLAUDE.md` §11.

### control_00013 — Passwords length and encryption
- **Purpose:** Global password policy.
- **Functional requirement:** `security passwords min-length ≥10`, `service password-encryption`.
- **Production commands:** matches verbatim.
- **Evaluated by:** `_check_control_00013` (unchanged).
- **Change:** none.

### control_00014 — VTY Lines
- **Purpose:** Console/VTY access hardening.
- **Functional requirement:** passwords, `login local`, `exec-timeout`, secure `transport input`.
- **Production commands:** **does not** include `login local` or `exec-timeout` anywhere (uses `session-timeout` instead — a different, non-equivalent command) — see Discrepancies (G3).
- **Evaluated by:** `_check_control_00014` (unchanged) — also independently validates the bound `access-class` ACL's content for permissiveness.
- **Change:** none. This control correctly FAILs the production reference config on `login local`/`exec-timeout` — that's the documented functional requirement being enforced, not a bug (see G3).

### control_00015 — Local user and enable secret
- **Purpose:** Privileged-mode protection + a priv-15 local admin.
- **Functional requirement:** `enable secret` present, a priv-15 local username present.
- **Production commands:** `username admin privilege 15 secret 0123456789` / `enable secret 0123456789`.
- **Evaluated by:** `_check_control_00015` (unchanged).
- **Change:** **title only** (`"Basic Security"` → `"Local user and enable secret"`, matching the task's control list). No functional/logic difference was found between the new spec and the existing implementation after direct comparison — flagged explicitly per your confirmation that this was expected, not an oversight.

---

## B. Production Command Mapping

| Production command/pattern (`NCM Configuration Script.txt`) | Control | Purpose | Validation implemented |
|---|---|---|---|
| `hostname ACME_USA_RT_INT_GOLDEN_01` | 00001 | Asset naming | Convention regex |
| `ip domain name acme.com` | 00002 | SSH key prereq | Presence + golden match |
| `security passwords min-length 10` / `service password-encryption` | 00013 | Password policy | Presence + min value |
| `key config-key password-encrypt 0123456789` / `password encryption aes` | 00007 | Encrypt stored keys at rest | Presence (both lines) |
| `username admin_bckp privilege 15 algorithm-type scrypt secret ...` | 00005 | Break-glass admin | Presence + strong-hash check |
| `username admin privilege 15 secret ...` / `enable secret ...` | 00015 | Privileged-mode protection | Presence |
| `aaa new-model` + `tacacs server ...` + `aaa group server tacacs+ ...` | 00004 (+00003 for the AAA lines) | Centralized AuthN/Z/Acct | See 00003/00004 above |
| `crypto key generate rsa` / `ip ssh version 2` | 00006 | Encrypted mgmt | Presence (see 00006 note - RSA-generate presence isn't independently required by the current checker, pre-existing, out of scope) |
| `ip access-list extended ACME_VTY_MGMT_ACL` / `permit ip any any` | 00008 (defines it) + 00014 (binds/validates it) | Admin-plane scoping | 00008: existence. 00014: binding + permissiveness |
| `line con 0` / `line vty 0 4` / `line vty 5 15` blocks | 00014 | Console/VTY hardening | login local, exec-timeout, transport input, ACL binding |
| `ntp authentication-key ...` / `ntp server ... prefer` | 00009 | Time sync integrity | Presence + prefer + auth |
| `logging on` / `logging host 30.30.30.100` / `logging trap informational` | 00010 | Centralized logging | Presence |
| `snmp-server group ... v3 priv` / `snmp-server user ...` | 00011 | Encrypted monitoring | Presence + SHA/AES |
| `banner motd $ ... $` | 00012 | Legal notice | Presence (see A/00012 note) |

A command can and does serve more than one control here (the TACACS block feeds both 00003's group-consistency check and 00004's server/key/address checks; the VTY ACL feeds both 00008 and 00014) — no 1:1 assumption was made.

---

## C. Differences Found

| # | Control | Spec (PDF) | Production script | Prior code | Resolution |
|---|---|---|---|---|---|
| 1 | 00007 | Defines it for real | Matches spec verbatim | Absent (intentional gap) | Added — see A/00007 |
| 2 | 00008 | "ACL for VTY", existence-only | Has the ACL, flags its own body as a lab-only placeholder | "Telnet Blocking", VTY transport check | Rebuilt — see A/00008, G2 |
| 3 | 00014 | Requires `login local` + `exec-timeout` | Has neither (uses `session-timeout`) | Already enforces the spec's requirement | Left as-is — see G3 |
| 4 | 00004 | Not_compliance text is now generic ("commands executed with assigned variables") | Uses `key 0` (cleartext) | Extension flags only Type 7 | Left as-is — see G1 |
| 5 | 00015 | Same wording as before | Matches spec | Already matches | No change — title refreshed only |
| 6 | 16–18 | Still defined, "must not participate in the current execution flow" | N/A | Were included in every non-`--priority-only` run | Unconditionally excluded now (`ACTIVE_CONTROL_IDS`) |

---

## D. Code Changes

| File | Function/Class | Reason | Before | After |
|---|---|---|---|---|
| `controls.yaml` | control_00007 entry | New control per spec | absent | full entry, `deterministic_validation: true` |
| `controls.yaml` | control_00008 entry | Redefined per spec | "Telnet Blocking" / VTY transport template | "ACL for VTY" / existence-only ACL template |
| `controls.yaml` | control_00015 entry | Title refresh only | title `"Basic Security"` | title `"Local user and enable secret"` |
| `compliance_engine.py` | `_check_control_00007` | New checker | n/a | presence check for master key + AES encryption |
| `compliance_engine.py` | `_check_control_00008` | Rebuilt checker | VTY transport-input/Telnet logic | existence-only ACL check |
| `compliance_engine.py` | `PRIORITY_CONTROL_IDS` → `ACTIVE_CONTROL_IDS` | 1-15 now contiguous (00007 exists); renamed since "priority within everything" is now just "the active set" | `{1-6, 8-15}` | `{1-15}` |
| `main.py` | CLI options, `main()` | Remove `--priority-only`; active-set filter is now unconditional | `if priority_only: controls = [...]` | `controls = [c for c in load_controls(...) if c["control_id"] in ACTIVE_CONTROL_IDS]` always |
| `golden_config_main.py` | CLI options, `main()` | Remove `--priority-only` | `builder.build(priority_only=priority_only)` | `builder.build()` |
| `golden_config_builder.py` | `build()`, `save()` | Unconditional active-set filter; drop `priority_only` param | `if priority_only: control_ids = [...]` | `control_ids = [cid for cid in self.order if cid in ACTIVE_CONTROL_IDS]` always |
| `golden_config_builder.py` | `_SUBSUMED_BY` | control_00008 no longer a pointer-comment to control_00014 | `{"control_00008": "..."}` | `{}` (empty) |
| `device_vars.json` | control_00007/00008 sections | New/changed variables | 00008 had `vty_line_numbers`; no 00007 | 00007: `device_master_key`; 00008: `acl_name` (= `ACME_VTY_MGMT_ACL`, matching 00014's `vty_acl_name`) |
| `device_vars.json` | control_00015 | Pre-existing gap found while validating 00015 (unrelated to this task's edits, but directly blocked its own rendering) | missing `enable_password` | added |
| `schemas/device_vars.schema.json` | control_00007/00008 properties | Match new variables | 00008: `vty_line_numbers`; no 00007 | 00007: `device_master_key`; 00008: `acl_name` |
| `render_order.yaml` | ordering list | Insert control_00007; refresh comments | 00007 absent | 00007 inserted (right before AAA/TACACS, since it protects those keys) |
| `samples/golden_config.txt` | TACACS/password block | Add control_00007 content (hand-authored fixture, not a Tool-2 output) | no 00007 block | `key config-key password-encrypt <DEVICE_MASTER_KEY>` / `password encryption aes` added |

---

## E. Controls Disabled

Confirmed: `control_00016`, `control_00017`, `control_00018` are **not** part of the active execution flow.
- `main.py`: `controls = [c for c in load_controls(...) if c["control_id"] in ACTIVE_CONTROL_IDS]` — 16-18 never reach `ControlEvaluator`, never appear in a report, never affect the compliance score. Confirmed live: a real run against `samples/device_config.txt` evaluated exactly 15 controls, 16/17/18 absent from the JSON.
- `golden_config_builder.py.build()`: same unconditional filter — 16-18 never render, not even as placeholder comments. Confirmed live: a real render of `golden_config.txt` contains zero occurrences of `control_00016`/`00017`/`00018`.
- They **remain defined** in `controls.yaml`, `render_order.yaml`, and `schemas/device_vars.schema.json` (per the task's explicit instruction to keep them for future use) — `render_control("control_00016")` still works if called directly (existing tests for this still pass), it's just never reached by the default build/evaluate loop.

---

## F. Testing

- **Tests executed:** full suite, `pytest -q`.
- **Tests added:** `test_global_password_encryption_present_passes`, `test_global_password_encryption_missing_key_fails`, `test_global_password_encryption_missing_aes_fails`, `test_acl_for_vty_present_passes`, `test_acl_for_vty_missing_fails` (`tests/test_compliance_engine.py`); `test_control_00008_renders_its_own_acl_block`, `test_control_00007_renders_normally` (`tests/test_golden_config_render_control.py`, replacing the now-obsolete "control_00007 is absent" and "control_00008 is subsumed" tests).
- **Tests updated:** `tests/test_golden_config_build_full.py` (`PRIORITY_CONTROL_IDS`→`ACTIVE_CONTROL_IDS`, `--priority-only` test rewritten as a default-behavior test, self-evaluation `expected_non_pass` re-derived — `control_00017` newly FAILs since it's no longer rendered by default, `control_00014`'s FAIL reason changes from "ACL not found" to "ACL is permissive"); `tests/test_compliance_report_builder.py` (17→18 real controls in `controls.yaml` now, since `_real_report()` evaluates every raw entry unfiltered); `tests/test_compliance_report_main.py` ("17 controls" → "15 controls" in a live-CLI-output assertion, since that path does go through `main.py`'s active-set filter).
- **Tests passed:** 146/146.
- **Tests failed:** 0.
- **Edge cases validated live (not just unit tests):** `main.py --help`/`golden_config_main.py --help` confirm `--priority-only` is gone; a real audit of `samples/device_config.txt` shows exactly 15 controls evaluated, control_00007 correctly FAILs (master key genuinely absent), control_00008 correctly PASSes (device already has a differently-named ACL, `VTY-OPEN`); a real Golden Config Creator render shows control_00007/00008 rendering real content and 16-18 fully absent; a self-consistency check (freshly-rendered golden audited against itself) shows all 15 active controls PASS except control_00014, which correctly FAILs on the ACL-permissiveness reason once control_00008 supplies a real (if permissive) ACL body.

---

## G. Discrepancies and Risks

### G1. control_00004 — TACACS key stored as Type 0 (cleartext)
- **Functional specification:** now generic ("commands executed with assigned variables") — no longer explicitly calls out a weak key type.
- **Production configuration:** `key 0 0123456789` on both TACACS servers — Type 0 is **fully cleartext**, stored and transmitted as typed with no obfuscation at all, arguably worse than the already-flagged Type 7 (which is at least reversible-but-obfuscated).
- **Current implementation:** `_check_control_00004` only flags Type 7 specifically (a pre-existing extension documented in `CLAUDE.md` §11, itself driven by the *original* acceptance criteria, not this spec revision). Type 0 is currently accepted as compliant by the checker.
- **Recommended resolution:** per your direction this pass, left unchanged and just documented here. If you want it fixed later: extend `_check_control_00004`'s `key 7` regex check to also match `key 0`, with the same remediation message pointing at Type 6.

### G2. control_00008 — spec/production example is a known-bad "permit ip any any" placeholder
- **Functional specification:** literal command example is `ip access-list extended <ACL_name>` / `permit ip any any`.
- **Production configuration:** the exact same body, with the script's own comment reading `"ACL dummy - permite todo el tráfico (SOLO LAB/TESTING)"` and `"PERMIT-ALL placeholder, replace before production"` — i.e. operations explicitly flagged this as not-production-ready.
- **Current implementation:** `control_00008`'s new existence-only check (matching the spec literally) would mark this ACL as compliant regardless of content — by design, since content/permissiveness is `control_00014`'s responsibility, and it correctly catches this exact case (flags it as "permissive instead of restrictive").
- **Recommended resolution:** none needed functionally (the two-control split already catches this at the `control_00014` layer), but worth knowing the `control_00008` config_example in `controls.yaml` is intentionally *not* a "good" example — it's the literal spec/production text, used per the source-priority rules rather than silently upgraded to something safer.

### G3. control_00014 — production config lacks `login local` and `exec-timeout`
- **Functional specification:** explicitly requires both (`not_compliance_conditions` #2 and #3).
- **Production configuration:** neither exists anywhere in the VTY/console blocks; `session-timeout 10` is used instead, which is a different, non-equivalent IOS-XE command (an absolute session-length knob on some platforms, not the same as the idle-timeout `exec-timeout` the spec requires).
- **Current implementation:** unchanged, correctly enforces the documented requirement — a real audit of the production script genuinely FAILs `control_00014` on this.
- **Recommended resolution:** none taken (per the source-priority rule: functional spec text > production config for *what* to validate) — this is a real, legitimate finding for whoever owns that production router to remediate, not a bug in the checker.

### G4. control_00006 — RSA key generation presence isn't independently checked (pre-existing, out of scope) — **RESOLVED in Pass 3**
- The current checker only flags missing RSA keys if `crypto key zeroize rsa` was run without a matching `crypto key generate rsa modulus ...` afterward — it doesn't independently require key generation to have happened at all. `samples/device_config.txt` has no `crypto key generate rsa` line and isn't flagged for it. This predates this task and control_00006 wasn't in scope for a rebuild, so it was left untouched — noted here for visibility only.
- Fixed in Pass 3 (see below): `_check_control_00006` now unconditionally requires `crypto key generate rsa modulus <bits>` regardless of zeroize history.

### G5. `samples/golden_config.txt` — duplicate, conflicting ACL definitions — **RESOLVED in Pass 2**
- This hand-authored fixture had **two** `ip access-list extended ACME_VTY_MGMT_ACL` blocks: a restrictive one and, near the end of the file, a second "SOLO LAB/TESTING" permit-all duplicate under the identical name. Fixed in Pass 2 (see below) as part of rebuilding this fixture's ACL to match the new production-style content — the duplicate is gone, replaced by one real ACL block.

### G6. control_00012 — spec says "Deterministic Validation: No", implementation says otherwise
- Not something this task changed — an earlier session (same day) deliberately made `control_00012` (Banners) get a real presence-only checker so a missing banner counts against the compliance score, while `manual_review: true` still governs Tool 2's rendering (wording/legal-language approval stays human). The new spec's literal text (`Deterministic Validation: No` / `Manual Review: Yes`) doesn't reflect this, since it predates that decision. Documented in `CLAUDE.md` §11 both times.

---

## Pass 2 — Re-alignment with the further-updated PDF + NCM script (2026-09-12)

Both reference documents changed again (PDF grew to ~20 pages covering every control in full; `NCM Configuration Script.txt` gained real multi-range VTY lines, NTP key references, and a full production ACL). Per your instructions this pass, a new `Fixed_value: yes/no` field in the PDF (present on nearly every control except Hostname) is taken **literally**: where `yes`, the documented/golden value is the *required* value on every device, not a placeholder. `device_configs/_index.csv` (your 75 fixtures) was **not** used to drive scope directly, though most of its scenarios end up covered anyway as a side effect of the `Fixed_value` work.

### Updated control mapping

| Control | Change this pass |
|---|---|
| 00001, 00002, 00007, 00013, 00015 | No change (`Fixed_value: no`/already-matching, or — for 00012 — deliberately not applying `Fixed_value` per its manual-review rationale, see G6). |
| 00003 AAA | Added: TACACS group name now also compared literally to golden (previously only self-consistency across the 12 AAA lines). |
| 00004 TACACS | Added: server **name** and **timeout** compared literally to golden (address already was). Added: each `server name X` reference under `aaa group server tacacs+` must correspond to a real `tacacs server X` block (a referential-integrity gap found via live spot-checking, not from the PDF/CSV directly — analogous to control_00014's existing "ACL referenced by access-class must exist" check). Key type-0 (cleartext) still unflagged, per your explicit choice, again. |
| 00005 Local emergency users | Rebuilt: the emergency user is now identified by its `algorithm-type scrypt` keyword (distinguishing it from control_00015's plainer admin line); privilege level must be exactly 15; username compared literally to golden. Missing/wrong `algorithm-type` (e.g. `md5`) now correctly fails. |
| 00006 SSH | Added: `ip ssh version`/`time-out`/`authentication-retries` compared literally to golden instead of presence-only. |
| 00008 ACL for VTY | Rebuilt: now parses the device's named ACL and golden's same-named ACL and compares rule-by-rule, in order (via `ConfigTree.blocks()`, which preserves line order), reporting the first point of divergence. Replaces the old existence-only check. `controls.yaml`'s `config_example` now shows the real production ACL (explicit Cloudflare-range denies, restricted SSH permit, terminal `deny ip any any log`). |
| 00009 NTP | Added: `ntp trusted-key <id>` must match `ntp authentication-key <id>`, and each `ntp server ... key <id>` must reference that same id (a real bug in my own new code was caught here mid-implementation — see Testing below). Server IPs compared literally to golden. |
| 00010 Syslog | Added: syslog host IP compared literally to golden (closes a gap between the module's own docstring, which already claimed this, and the code, which never actually did it). |
| 00011 SNMP | Added: SNMP group name, user name, and trap host IP compared literally to golden. |
| 00014 VTY Lines | Rebuilt: VTY now requires `login authentication default` (was `login local` — console keeps `login local`, since PDF's Command block and the NCM script agree this is intentionally different, not a typo: VTY should invoke the AAA method list control_00003 sets up, console keeps a working local fallback). Added password-presence check, `transport output` restriction (alongside existing `transport input`), and `access-class <name>` must end with the literal `in` keyword. ACL **content** checking removed entirely from this control (moved to 00008) — this control now only confirms VTY binds to a real, existing ACL. Already iterated every `line vty` block found (0-4 and 5-15 both) before this pass, so multi-range handling needed no change. |

### Code changes

| File | Change |
|---|---|
| `compliance_engine.py` | `_check_control_00003/04/05/06/08/09/10/11/14` all rebuilt/extended per the table above; module docstring updated (expanded "shared infrastructure values" list, new note on `login local` vs `login authentication default`). |
| `controls.yaml` | Matching `not_compliance_conditions`/`command_template`/`config_example` text refresh for the same 9 controls; fixed a pre-existing typo in 00004's `config_example` (`192.138.100.102` → `192.168.100.102`). |
| `samples/golden_config.txt` | NTP `key 1` added to both server lines; VTY split into `line vty 0 4` / `line vty 5 15` (matching the real NCM script structure) with explicit passwords and `login authentication default`; the duplicate/conflicting ACL (see G5, now resolved) replaced with one real Cloudflare-deny/SSH-permit/deny-log ACL matching the new `config_example`; header comment's "shared infrastructure values" list expanded to match. |
| `tests/test_compliance_engine.py` | ~25 tests added/updated across the 9 controls above (see Testing). |
| `tests/test_golden_config_build_full.py` | `test_line_vty_appears_exactly_once_with_full_settings` updated for `login authentication default`; self-evaluation's `expected_non_pass` no longer includes `control_00014` (it now correctly self-PASSes, since ACL content is 00008's job and 00008's Tool-2-rendered content trivially matches itself). |

### Discrepancies and risks (Pass 2)

- **A real bug was found and fixed during implementation, not by you**: my first draft of the NTP key-ID check indexed `"ntp authentication-key 1 md5 ...".split()[1]`, which is `"authentication-key"` (a hyphenated single token), not the ID — the ID is at index 2. Caught immediately by the self-evaluation test failing with an obviously-wrong message and fixed before any other testing.
- **`login local` → `login authentication default` on VTY** is a real, non-ambiguous behavior change (both PDF and NCM script agree) — worth knowing since it inverts prior behavior: a device using `login local` on VTY (bypassing the AAA method list control_00003 configures) now correctly FAILs where it used to PASS.
- Per your "no CSV scope" choice, `VTY exec-timeout` value thresholds (`0 0` disabling timeout, or exceeding a policy maximum) and TACACS `key 0` (cleartext) remain unflagged — both are still only exercised by `device_configs/*.txt` fixtures, not the PDF/NCM script text. **`exec-timeout` thresholds RESOLVED in Pass 3** (found live while testing the `device_configs/` fixture set — see below); TACACS `key 0` remains unflagged, unchanged, per your original explicit choice (G1).

### Testing (Pass 2)

- **Tests added:** ~25 new/updated tests in `tests/test_compliance_engine.py` across control_00003/04/05/06/08/09/10/11/14 (golden-literal-comparison cases, the new ACL rule-by-rule comparison, NTP key-ID consistency, the TACACS server-name referential-integrity check, VTY `login authentication default`/`transport output`/`access-class in` cases).
- **Tests updated:** `_COMPLETE_AAA_BLOCK` and 2 dependent tests (group name changed to match golden literally); `_COMPLIANT_SNMP` tests (added a matching golden fixture); NTP "authenticated with prefer" test (added `key 1`); both VTY control_00014 tests rewritten (ACL-permissiveness assertions moved to new 00008 tests).
- **Tests passed:** 169/169 (up from 168 baseline + 1 net after consolidating/replacing some).
- **Live verification:** `samples/device_config.txt` audited against the updated `samples/golden_config.txt` — all new checks fire correctly (group/server-name/timeout/SSH-value/ACL-content/NTP-key/syslog-host/SNMP/VTY-login mismatches all correctly FAIL). Self-consistency (`samples/golden_config.txt` against itself) — all 15 controls PASS cleanly. Spot-checked 6 of your 75 `device_configs/*.txt` fixtures targeting now-covered scenarios (`ssh_config_02`, `emergency_user_config_02`, `acl_vty_config_05`, `vty_lines_config_05`, `ntp_config_05`, `tacacs_config_05`) — all 6 now correctly FAIL for their intended reason.

---

## Pass 3 — Control Validation Review and Remediation (2026-09-15)

You ran the full 75-config `device_configs/` fixture set through the tool and reported 16 named observations across 9 categories where PASS/FAIL didn't match the fixture's own documented "Expected finding." Per your review's own instructions, every observation below was **independently re-verified live against the current codebase before any fix was written** — not assumed from the review text — and categorized into one of four buckets: genuine code gap (fixed), stale golden data (blocked on a data fix, described below), fixture bug (documented, not touched), or intentional prior design decision (documented, not re-litigated). Two additional gaps were found live while testing the named files that weren't in the original 16 (the `enable secret` command-order/precedence issue on control_00015, and the `exec-timeout` value-threshold gap already flagged as open in Pass 2's G4/discrepancies) — both are included below since they're within the review's own "VTY Configuration (broadly)" and "control_00015" categories.

### Blocking data issue found and fixed first: `golden_config_11_08_2026.txt` was duplicated

Before any checker fix could be verified, `golden_config_11_08_2026.txt` (the root-level golden file used for the real 75-device batch audit, distinct from `samples/golden_config.txt`) was found to have its content **duplicated**: your corrected section (matching `support_files/NCM Configuration Script.txt` — `login authentication default`, `transport output ssh`, the full Cloudflare-range-deny ACL, NTP `key 1`) was followed immediately by the old, stale Tool-2-generated section (`! GOLDEN CONFIG - Generated by Golden Config Creator ... Generated: 2026-09-11T04:50:08`), which still had `login local`, no `transport output`, a 1-line placeholder ACL, and NTP with no `key 1`. Confirmed live via `ConfigTree`: 3 `hostname` lines, 4 `tacacs server` blocks, 2 `ip access-list extended ACME_VTY_MGMT_ACL` blocks (21-rule correct + 1-rule stale), 3 `line vty` blocks. Your corrected content happened to come first, so `ConfigTree.blocks()[0]`/`first_text()` lookups were accidentally reading the right copy — fragile, not correct, and directly at risk from any future edit. **Fixed**: the stale second half (everything from the `GOLDEN CONFIG - Generated by Golden Config Creator` header onward) was deleted, leaving only your corrected section. Re-verified: 1 `hostname` line, 2 `tacacs server` blocks, 1 ACL block (21 rules), 2 `line vty` blocks.

### 1. Root Cause Analysis

| Observation | Control | Bucket | Root Cause | Code Location | Expected Behavior |
|---|---|---|---|---|---|
| `hostname_config_04` — Type field spells out "Router" instead of "RT" | control_00001 | **Fix** | `_check_control_00001` validated part-count and whole-hostname genericness, but never inspected the Type segment (part 3) specifically. A genuine documentation conflict was found and resolved here — see "Conflicts identified" below. | `compliance_engine.py::_check_control_00001` | FAIL: "Type field 'Router' should be a short device-class code..." |
| `aaa_config_01` — "aaa new-model missing" | control_00003 | **Fixture bug, not a code gap** | The file's header comment claims `aaa new-model` was removed, but line 40 of the same file still has it. The checker correctly evaluates the actual text present. | n/a — `device_configs/aaa_config_01.txt` | PASS (current, correct) |
| `ssh_config_01` — RSA key generation missing | control_00006 | **Fix** (previously logged as open, Pass 2 discrepancy G4) | `_check_control_00006` only inferred an RSA problem from a zeroize-without-regen pair; it never independently required `crypto key generate rsa` to exist at all. | `compliance_engine.py::_check_control_00006` | FAIL: "'crypto key generate rsa modulus <bits>' is missing..." |
| `password_encryption_config_02/03/05` | control_00007 | **Already correct** | Live-tested against current code before any change: all three already FAIL for the right reason (missing key line / missing aes line / misspelled command not matching the regex). The review's "Current Result" claim for these three did not match live behavior. | n/a | FAIL (unchanged, already correct) |
| `password_encryption_config_04` — weak master key `111111` | control_00007 | **Fix** | No value-strength check existed for the master key - presence-only. | `compliance_engine.py::_check_control_00007` (new `_is_weak_secret_value` helper) | FAIL: "...uses a weak/guessable master key value." |
| `acl_vty_config_02` — ACL never bound to VTY | control_00008 (as named in the review) | **Already correct, wrong control named** | Live-tested: `control_00014` already FAILs this with "no 'access-class' ACL is bound to this VTY line." ACL *binding* is control_00014's job, not control_00008's, by the Pass-2 architecture split. | n/a | FAIL on `control_00014` (unchanged) |
| `acl_vty_config_04` — no explicit deny-log rule | control_00008 | **Stale-golden symptom** | `control_00008` compares the device ACL rule-by-rule against golden's ACL. Golden's ACL was still the stale 1-line placeholder (identical in shape to this variant's device ACL), so nothing differed. Resolved entirely by the golden-file fix above. | n/a (golden data, not code) | FAIL: rule #1 mismatch against the real Cloudflare-deny-list ACL |
| `acl_vty_config_05` — wildcard mask equivalent to `any` | control_00008 | **Already correct** (hardened further) | Caught before this pass only because the rule happened to differ from golden's literal text — not a real semantic check. Added an independent semantic check (`255.255.255.255` wildcard = unrestricted) so this no longer depends on golden's exact wording. | `compliance_engine.py::_check_control_00008` | FAIL: "...functionally equivalent to 'any'..." (now also semantic, not just textual) |
| `snmp_config_04` — user references mismatched group name | control_00011 | **Fix** | The group line and user line were each checked for well-formed *shape* independently, but the group name embedded in the user line was never cross-checked against an actually-defined `snmp-server group` line. Same referential-integrity gap already fixed for TACACS `server name` in Pass 2. | `compliance_engine.py::_check_control_00011` | FAIL: "...references group '...', which has no matching 'snmp-server group...' definition." |
| `banner_config_02` — generic wording | control_00012 | **Intentional, not a bug** | `manual_review: true` exists specifically because wording/legal-language quality is a human judgment call (documented in the module docstring and `CLAUDE.md` §11). Per your explicit answer this pass, left as a documented non-fix. | n/a | PASS (Tool 1's deterministic score; wording still gated by manual review for Tool 2) |
| `banner_config_03` — delimiter mismatch (`$` ... `%`) | control_00012 | **Fix** | `_check_control_00012` only checked that `banner motd` existed as a line prefix — it never verified the opening and closing delimiter characters matched. | `compliance_engine.py::_check_control_00012` | FAIL: "...opening delimiter '$' has no matching closing '$'..." |
| `banner_config_04` — wrong company name | control_00012 | **Intentional, not a bug** | Same rationale as `banner_config_02` — additionally, golden's own banner has no company-name token to mechanically compare against. Per your explicit answer, left as a documented non-fix. | n/a | PASS |
| VTY broadly (`vty_lines_config_01-05`) | control_00014 | **Split: fixture/spec-version mismatch (baseline) + genuine fix (exec-timeout value)** | See "VTY category" writeup below. | `compliance_engine.py::_check_control_00014` | See below |
| `control_00015` (local admin user / enable secret) | control_00015 | **Split: fixture quirk (01, 04) + fix (02, 03, 05)** | See "control_00015 category" writeup below. | `compliance_engine.py::_check_control_00015` | See below |

#### VTY category detail

All 5 `vty_lines_config_*` fixtures share a VTY baseline (`line vty 0 15` as a single combined range, `login local`) that predates this project's Pass-2 VTY convention (`login authentication default`, split `line vty 0 4`/`5 15` ranges, explicit `transport output ssh`) — confirmed by direct inspection of the fixture files themselves, not just golden. This means the golden-file fix does **not** resolve the "signal buried under 2 generic failures" symptom the review flagged, because `_check_control_00014` never compares VTY structure against golden at all — its `login authentication default` and `transport` requirements are unconditional, not golden-driven. **This is a fixture-authoring/spec-version mismatch, not a code gap**, and is left undisturbed per the task's explicit instruction not to special-case or modify the sample dataset. Each variant's own intended defect is, however, still correctly and distinctly detected alongside that shared baseline noise:

| File | Intended defect | Was it distinctly detected before this pass? |
|---|---|---|
| `vty_lines_config_01` | Telnet allowed alongside SSH | Yes (`'transport input' is not restricted...`) |
| `vty_lines_config_02` | `exec-timeout 0 0` (disabled) | **No** — presence-only check saw *a* value and passed |
| `vty_lines_config_03` | Bare `login` instead of `login local`/`login authentication default` | Yes (`'login authentication default' is missing`) |
| `vty_lines_config_04` | `exec-timeout 20 0` (exceeds 10-min policy) | **No** — presence-only check saw *a* value and passed |
| `vty_lines_config_05` | `access-class` missing the `in` keyword | Yes (`missing the required 'in' direction keyword`) |

The `exec-timeout` value gap for `vty_lines_config_02`/`04` was a genuine, previously-undetected code gap — found live while writing fixture-based tests for this review, not named explicitly in your 16 observations, but squarely within the review's "VTY Configuration (broadly)" category and previously logged as an open item in Pass 2's discrepancies section. **Fixed**: `_check_control_00014` now validates the `exec-timeout` *value*, not just presence — `0 0` always fails (Cisco IOS's own "never time out" special case), and any value exceeding golden's own minutes value (policy maximum, not literal equality — stricter than golden is not a violation) fails. Applied to both console and VTY blocks.

#### control_00015 category detail

`_check_control_00015` previously checked "does *any* username anywhere have privilege 15" / "does *any* enable secret exist anywhere" — both were satisfied by control_00005's own, entirely separate emergency-user section regardless of what control_00015's own section actually configured. Fixed by identifying "the admin-standard user" as the username line **without** `algorithm-type scrypt` — the inverse of how control_00005's emergency user is identified (which always has it) — and checking that specific line's privilege, username, and secret value; plus checking the effective `enable secret` value (the **last** occurrence in file order, matching real Cisco sequential-config-apply semantics — see below) for weakness.

- `local_admin_config_02` (privilege 1 instead of 15) and `local_admin_config_05` (username `administrator` instead of `admin`) are now correctly caught — genuine fixes.
- `local_admin_config_03` (enable secret `1234`) required an additional fix beyond just identifying the right username line: the file has **two** `enable secret` lines (one in control_00005's section with a strong value, one in control_00015's own section with the weak `1234`), and `device.first_text()` was picking up the earlier, unrelated, strong one. Real Cisco IOS applies configuration sequentially, so the **last** `enable secret` line in the file is the one actually in effect — switched from `first_text()` to `all_text()[-1]` to match. Now correctly FAILs.
- `local_admin_config_01` (enable secret entirely absent from control_00015's own section) and `local_admin_config_04` (`enable password` used instead of `enable secret` in control_00015's own section) both still have a working `enable secret` from control_00005's independent section elsewhere in the same file. Per your explicit answer this pass, these are **documented as fixture quirks, not fixed**: real Cisco IOS always prefers `enable secret` over `enable password` when both exist, regardless of declaration order or which control's section it "belongs" to — the device genuinely has a working enable secret, so PASS is technically correct for what these files actually contain.

### 2. Changes Implemented

| File | Function / Class | Previous Behavior | New Behavior | Reason |
|---|---|---|---|---|
| `golden_config_11_08_2026.txt` | (data file) | Contained a fully duplicated, stale second copy of itself (Sept-11 Tool-2-generated) after your corrected section. | Stale duplicate removed; only your corrected section remains. | Data integrity — the duplication was silently relying on `[0]`-index/`first_text()` accidentally picking the right copy. |
| `compliance_engine.py` | `_check_control_00001` | Checked part-count (≥6) and whole-hostname genericness only. | Also inspects part 3 (Type): flags it if alphabetic and >4 characters (a spelled-out word, not a short device-class code). | Catch `hostname_config_04`'s "Router" vs "RT" case, generically (not hardcoded to "Router"). |
| `compliance_engine.py` | `_check_control_00006` | RSA key issues only inferred from a zeroize-without-regen pair. | Unconditionally requires `crypto key generate rsa modulus <bits>` to exist. | Close Pass 2's logged G4 gap; catch `ssh_config_01`. |
| `compliance_engine.py` | `_check_control_00007`, `_check_control_00015` (new: `_is_weak_secret_value`) | Master key / enable secret checked for presence only, never value strength. | New generic helper (`_is_weak_secret_value`): flags all-identical-character values, values shorter than 8 characters, and a small set of known-weak literals (`password`, `changeme`, `admin`, `cisco`, etc.) — explicitly not tuned to any single known test value (`0123456789`, this project's 10-digit placeholder, is intentionally NOT flagged). Wired into both controls. | Catch `password_encryption_config_04` (`111111`) and `local_admin_config_03` (`1234`) without hardcoding either literal. |
| `compliance_engine.py` | `_check_control_00008` | Rule-by-rule comparison against golden only — a wildcard-equivalent-to-`any` rule was only caught if it happened to differ from golden's literal text. | Added an independent semantic check: a wildcard mask of `255.255.255.255` is always flagged as functionally equivalent to `any`, regardless of golden's wording. | Harden `acl_vty_config_05`'s detection so it doesn't depend on golden's exact content. |
| `compliance_engine.py` | `_check_control_00011` | Group line and user line checked independently for shape only. | Extracts the group name embedded in the `snmp-server user` line and confirms a matching `snmp-server group <name> v3 priv` line actually exists (referential integrity), mirroring the TACACS `server name` check already in `_check_control_00004`. | Catch `snmp_config_04`'s mismatched-group-name typo. |
| `compliance_engine.py` | `_check_control_00012` | Checked only that a `banner motd` line existed. | Also parses `device.text` (raw config, not the line-object view) for the opening delimiter character and confirms the same character closes the banner on the same line. | Catch `banner_config_03`'s `$`...`%` mismatch. `banner_config_02`/`04` (wording/company-name) deliberately left unfixed — see category detail above. |
| `compliance_engine.py` | `_check_control_00014`, new `_exec_timeout_policy_failure` helper | `exec-timeout` checked for presence only, on both console and VTY blocks. | New value check: `exec-timeout 0 0` always fails (disables timeout entirely); otherwise the minutes value is compared against golden's own value as a policy maximum. | Catch `vty_lines_config_02`/`04` — found live while testing this review, not in the original 16, but the same "presence-only vs semantic" pattern as everything else this pass. |
| `compliance_engine.py` | `_check_control_00015` | Checked "any username anywhere with privilege 15" and "any enable secret anywhere" — both satisfiable by control_00005's independent section. | Identifies the admin-standard user as the username line *without* `algorithm-type scrypt`; checks that specific line's privilege (`==15`) and username (vs. golden); checks the **last** `enable secret` line in file order (sequential-config-apply semantics) for weak value via `_is_weak_secret_value`. | Close the referential-integrity gap; catch `local_admin_config_02/03/05`; correctly explain (not "fix") `01`/`04`. |
| `controls.yaml` | `control_00001/00007/00008/00011/00012/00014/00015` | — | `not_compliance_conditions` text refreshed to describe the new checks above; control_00001's `explanation` prose corrected (it previously listed "router" as a valid Type-field example, contradicting its own `config_example` of `RT` — see "Conflicts identified" below). | Keep the human-readable spec in sync with the checkers, per this project's established convention. |
| `tests/test_compliance_engine.py` | (tests) | — | ~35 tests added/updated: synthetic unit tests per fix (including two non-hardcoded weak-value cases, e.g. `"0000"`, to prove the helper generalizes), plus a new fixture-driven regression section evaluating the real named `device_configs/*.txt` files against the real (now de-duplicated) `golden_config_11_08_2026.txt`. One stale test (`test_hostname_matching_convention_passes`, using the pre-spec-revision full-word "ROUTER" Type segment) and three SSH tests (missing the now-required `crypto key generate rsa` line) updated to remain valid under the new checks. | See Testing below. |
| `documentation/CONTROL_UPDATE_REPORT.md` | — | — | This Pass 3 section added; G4 marked resolved; Pass 2's exec-timeout discrepancy bullet annotated resolved. | Keep this report the authoritative history of what changed and why. |

### 3. Validation Logic Changes

- **New regex/structural check**: control_00001's hostname Type-segment short-code heuristic (`isalpha() and len > 4`).
- **New semantic check, independent of golden**: control_00008's wildcard-mask-equivalent-to-`any` detection.
- **New value-strength check**: `_is_weak_secret_value` (generic: uniformity, length, known-weak literals) — new shared logic used by two controls.
- **New referential-integrity check**: control_00011's SNMP user→group cross-reference (second instance of this pattern in the codebase, after TACACS `server name` in Pass 2).
- **New raw-text parsing path**: control_00012's banner delimiter matching, deliberately bypassing `ConfigTree`'s line-object view via `device.text`, since Cisco banner blocks aren't line-structured the way every other command in this project is.
- **New value-threshold check against golden as a policy maximum (not literal equality)**: control_00014's `exec-timeout` minutes value, plus an absolute special-case (`0 0` always fails regardless of golden).
- **New "identify the specific line by distinguishing shape" + config-apply-order semantics**: control_00015 identifies its own username line by the *absence* of a marker (inverse of control_00005's presence-based identification), and resolves ambiguity between multiple `enable secret` lines by taking the last one in file order rather than the first — both are new instances of patterns whose first occurrence (shape-based identification) was already established in the codebase for control_00005.

### Conflicts identified (per the task's Source-of-Truth rule)

1. **control_00001 Type-segment convention**: `controls.yaml`'s own `explanation` prose listed `"router"` (full word) as a valid Type-field example, directly contradicting its own `config_example` (`INTEL_CR_RT_INT_BLN_01`, using the short code `RT`). `samples/golden_config.txt`/`samples/device_config.txt`/`samples/perfect_config.txt` (and one derived unit test) use the full word `"ROUTER"`; the production reference (`support_files/NCM Configuration Script.txt`), the entire 75-file `device_configs/` fixture set (`device_configs/_index.csv`'s own text: *"Type field uses the full word 'Router' rather than the 2-letter code 'RT'"*), and your own corrected `golden_config_11_08_2026.txt` all agree the short code is required. **Resolution**: implemented the short-code requirement (3 sources vs. 1 stale example), fixed the one specifically-affected unit test, and corrected `controls.yaml`'s explanation text. **Left untouched, and flagged as a residual inconsistency** (see Remaining Risks): `samples/golden_config.txt`, `samples/device_config.txt`, `samples/perfect_config.txt`, and `support_files/*` still use the full word — these are boilerplate inputs incidentally referenced by several *other* controls' tests (not testing hostname convention itself), so rewriting them was out of scope for this pass to avoid an untested ripple effect; no test currently exercises control_00001 against them.
2. **VTY baseline convention** (see VTY category detail above): the `vty_lines_config_*` fixture set's shared baseline (`login local`, single-range `line vty 0 15`) conflicts with the Pass-2 controls.yaml/golden convention (`login authentication default`, split ranges). Resolution: the current implementation (Pass 2's convention) is correct per the production reference and your own corrected golden file; the fixture set predates that convention. Documented, not silently special-cased or "fixed" by weakening control_00014.
3. **`local_admin_config_01`/`04`** (see control_00015 category detail above): a genuine ambiguity between "what this control's own config section says" and "what the device's running-config actually has in effect" (Cisco's real `enable secret` > `enable password` precedence, independent of section/order). Resolution: PASS is correct for what these files actually contain; documented as a fixture quirk per your explicit direction, not invented as a new compliance rule.

### 4. Test Results

| Test file | Control | Expected | Before this pass | After this pass | Status |
|---|---|---|---|---|---|
| `hostname_config_04.txt` | control_00001 | FAIL (Type field) | PASS (gap) | FAIL | **Fixed** |
| `aaa_config_01.txt` | control_00003 | PASS (fixture bug) | PASS | PASS | Documented, no change |
| `ssh_config_01.txt` | control_00006 | FAIL (RSA keygen) | PASS (gap) | FAIL | **Fixed** |
| `password_encryption_config_02.txt` | control_00007 | FAIL | FAIL | FAIL | Already correct |
| `password_encryption_config_03.txt` | control_00007 | FAIL | FAIL | FAIL | Already correct |
| `password_encryption_config_04.txt` | control_00007 | FAIL (weak key) | FAIL (wrong reason: presence only, would've missed a present-but-weak key) | FAIL (correct reason: weak value) | **Fixed** |
| `password_encryption_config_05.txt` | control_00007 | FAIL | FAIL | FAIL | Already correct |
| `acl_vty_config_02.txt` | control_00014 | FAIL (binding) | FAIL | FAIL | Already correct (control_00008 misnamed in review) |
| `acl_vty_config_04.txt` | control_00008 | FAIL (deny-log) | PASS (stale golden) | FAIL | **Fixed** (golden data) |
| `acl_vty_config_05.txt` | control_00008 | FAIL (wildcard=any) | FAIL (textual coincidence) | FAIL (semantic, hardened) | Hardened |
| `snmp_config_04.txt` | control_00011 | FAIL (wrong group ref) | PASS (gap) | FAIL | **Fixed** |
| `banner_config_02.txt` | control_00012 | PASS (Tool 1 score; wording is manual review) | PASS | PASS | Documented, no change |
| `banner_config_03.txt` | control_00012 | FAIL (delimiter mismatch) | PASS (gap) | FAIL | **Fixed** |
| `banner_config_04.txt` | control_00012 | PASS (Tool 1 score; wording is manual review) | PASS | PASS | Documented, no change |
| `vty_lines_config_01.txt` | control_00014 | FAIL (telnet) | FAIL (signal present, buried) | FAIL (signal present) | No change needed |
| `vty_lines_config_02.txt` | control_00014 | FAIL (exec-timeout 0 0) | FAIL (wrong/missing signal for the intended defect) | FAIL (correct signal: "disables session timeout entirely") | **Fixed** |
| `vty_lines_config_03.txt` | control_00014 | FAIL (login bypass) | FAIL (signal present) | FAIL (signal present) | No change needed |
| `vty_lines_config_04.txt` | control_00014 | FAIL (exec-timeout 20 0) | FAIL (wrong/missing signal for the intended defect) | FAIL (correct signal: "exceeds ... policy maximum") | **Fixed** |
| `vty_lines_config_05.txt` | control_00014 | FAIL (access-class missing `in`) | FAIL (signal present) | FAIL (signal present) | No change needed |
| `local_admin_config_01.txt` | control_00015 | PASS (fixture quirk) | PASS | PASS | Documented, no change |
| `local_admin_config_02.txt` | control_00015 | FAIL (privilege 1) | PASS (gap) | FAIL | **Fixed** |
| `local_admin_config_03.txt` | control_00015 | FAIL (weak secret) | PASS (gap) | FAIL | **Fixed** |
| `local_admin_config_04.txt` | control_00015 | PASS (fixture quirk) | PASS | PASS | Documented, no change |
| `local_admin_config_05.txt` | control_00015 | FAIL (username mismatch) | PASS (gap) | FAIL | **Fixed** |

- **Full pytest suite**: 243/243 passing (up from 219 baseline before this pass — 24 net new tests: synthetic unit tests per fix, weak-value non-hardcoding proofs, and the fixture-driven regression section).
- **Full 75-device batch audit** (`main.py --device-config-dir device_configs --golden-config golden_config_11_08_2026.txt`): 350 total FAIL across the fleet, **0 `ASSESSMENT_ERROR`** (no checker crashes across any of the 75 × 15 = 1,125 control evaluations). Spot-checked unrelated categories not touched this pass (`domain_config`, `emergency_user_config`, `ntp_config`, `password_policy_config`, `syslog_config`, `tacacs_config`) for regressions — FAIL counts per-file consistent with each category's own intended single-defect-per-variant pattern, no anomalies.

### 5. Remaining Risks

- **Residual hostname convention inconsistency**: `samples/golden_config.txt`, `samples/device_config.txt`, `samples/perfect_config.txt`, and `support_files/golden_config_router_v01.txt`/`support_files/device_config.txt` still use the full word `"ROUTER"` as the Type segment (pre-dating this pass's convention fix). None of these are currently used to test control_00001 specifically, so nothing is broken today — but if a future test starts running control_00001 against these files, it will now correctly (if perhaps unexpectedly) FAIL. Recommend a deliberate follow-up pass to update these four files if/when they're touched for other reasons, rather than as a speculative fix now.
- **`vty_lines_config_*` fixture/spec-version mismatch is permanent** unless the fixture set itself is regenerated against the current Pass-2 VTY convention — not something a code change can resolve, since the checker is correctly enforcing the (correct, production-matching) current convention.
- **TACACS `key 0` (cleartext) remains unflagged** — a pre-existing, explicitly-chosen-by-you gap (Pass 1's G1), unchanged this pass.
- **`_is_weak_secret_value`'s literal list is necessarily incomplete** — it catches uniform/short/common-known-weak values generically, but a weak-but-long-and-non-uniform password (e.g. a real dictionary word padded to 8+ characters) would not be caught. This mirrors real-world password-strength-checker limitations and was scoped to "generic, not hardcoded to the test dataset's specific literals" per your explicit instruction, not to a full complexity-scoring engine.
- **Banner wording/company-name quality remains entirely a manual-review concern** (`banner_config_02`/`04`), per your explicit choice this pass — Tool 1's compliance score does not reflect it.

---

## Pass 4 — Golden Config Creator realignment + source-of-truth switch (2026-09-15)

`golden_config_11_08_2026.txt`'s duplicated content, found and cleaned up in Pass 3, turned out to have a root cause worth fixing at the source: the stale second half **was** the Golden Config Creator's (Tool 2's) actual current output. Several of `controls.yaml`'s `command_template` fields had drifted from `support_files/NCM Configuration Script.txt` (the real production reference) - TACACS `key 6` instead of `key 0`, a `permit ip any any` ACL placeholder instead of the real 21-line Cloudflare-deny-list, one combined VTY range instead of the real split `0 4`/`5 15` ranges (plus a missing `line aux 0` and `exec prompt timestamp`), an extra `enable secret` line rendered under control_00005 that belongs to control_00015, and redundant `hostname`/`ip domain name` lines rendered under control_00006.

Fixed by realigning `controls.yaml`'s command templates for controls 00004/05/06/08/14/15, adding two new special-case renderers to `golden_config_builder.py` (`_render_acl`, `_render_vty`, mirroring the existing `_render_tacacs` `{% for %}`-loop pattern for controls with genuinely repeating structure), updating `schemas/device_vars.schema.json` and `device_vars.json` to match (new `acl_rules`/`vty_ranges` list fields; dropped the now-unused `secret_psswd`/`hostname`/`domain_name` fields; fixed the TACACS server addresses), and reordering `render_order.yaml` to match the script's real control sequence. Full details in `GOLDEN_CONFIG_CREATOR.md` section 12.

`golden_config.txt` (Tool 2's own default output, regenerated at the repo root) now matches every real command in `support_files/NCM Configuration Script.txt` exactly (verified by a new test, `test_full_build_matches_real_ncm_configuration_script`, and confirmed with `--strict` producing zero missing-variable markers). **It is now the Compliance Checker's source of truth for the real fleet audit**, replacing `golden_config_11_08_2026.txt` in that role - `tests/test_compliance_engine.py`'s Pass-3 fixture section (`REAL_GOLDEN_TEXT`) now reads `golden_config.txt`. Per your explicit choice, `golden_config_11_08_2026.txt` stays in the repo untouched rather than being deleted - it's simply no longer referenced by any code or test going forward. `samples/golden_config.txt` (the separate, hand-authored `<PLACEHOLDER>`-style fixture the *original* unit-test suite uses) was out of scope and is unaffected.

**Verification**: full pytest suite 247/247 passing (up from 243 - 4 net new tests: two missing-value tests for `_render_acl`/`_render_vty`, and the NCM-script-fidelity test, offsetting one test renamed/restructured for the 2-VTY-block change). Full 75-device batch audit re-run against `golden_config.txt`: 350 total FAIL across the fleet - identical to the last `golden_config_11_08_2026.txt`-based run, confirming the two files are now functionally equivalent. Tool 6 dashboard rebuilt from that run: 68.9% strict compliance, 100% coverage, 0 critical findings - also identical to the prior run.

**Remaining risk carried forward**: the residual hostname-convention inconsistency in `samples/*.txt`/`support_files/*` (noted in Pass 3) is unaffected by this pass and still open.
