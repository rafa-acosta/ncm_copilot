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

### G4. control_00006 — RSA key generation presence isn't independently checked (pre-existing, out of scope)
- The current checker only flags missing RSA keys if `crypto key zeroize rsa` was run without a matching `crypto key generate rsa modulus ...` afterward — it doesn't independently require key generation to have happened at all. `samples/device_config.txt` has no `crypto key generate rsa` line and isn't flagged for it. This predates this task and control_00006 wasn't in scope for a rebuild, so it was left untouched — noted here for visibility only.

### G5. `samples/golden_config.txt` — duplicate, conflicting ACL definitions
- This hand-authored fixture has **two** `ip access-list extended ACME_VTY_MGMT_ACL` blocks: a restrictive one (management-subnet-scoped) and, near the end of the file, a second "SOLO LAB/TESTING" permit-all duplicate under the identical name. Only the first is ever matched by `ConfigTree.blocks()`, so the second is currently inert. Left untouched (out of scope for this task, and not something you asked to have cleaned up) — flagged here in case it was an unintentional leftover from earlier testing.

### G6. control_00012 — spec says "Deterministic Validation: No", implementation says otherwise
- Not something this task changed — an earlier session (same day) deliberately made `control_00012` (Banners) get a real presence-only checker so a missing banner counts against the compliance score, while `manual_review: true` still governs Tool 2's rendering (wording/legal-language approval stays human). The new spec's literal text (`Deterministic Validation: No` / `Manual Review: Yes`) doesn't reflect this, since it predates that decision. Documented in `CLAUDE.md` §11 both times.
