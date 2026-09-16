"""Unit tests for GoldenConfigBuilder.build / save, using the repo's real sample device_vars.json."""

from __future__ import annotations

from pathlib import Path

from compliance_engine import ACTIVE_CONTROL_IDS
from config_parser import ConfigTree
from golden_config_builder import GoldenConfigBuilder

REPO_ROOT = Path(__file__).parent.parent
CONTROLS_PATH = REPO_ROOT / "controls.yaml"
DEVICE_VARS_PATH = REPO_ROOT / "device_vars.json"
ORDER_PATH = REPO_ROOT / "render_order.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "device_vars.schema.json"


def _builder() -> GoldenConfigBuilder:
    return GoldenConfigBuilder(
        controls_path=CONTROLS_PATH,
        device_vars_path=DEVICE_VARS_PATH,
        order_path=ORDER_PATH,
        schema_path=SCHEMA_PATH,
    )


def test_full_build_has_no_missing_markers_with_complete_sample_vars():
    builder = _builder()
    text = builder.build()
    assert "<MISSING:" not in text
    assert builder.missing == []


def test_full_build_renders_expected_content():
    builder = _builder()
    text = builder.build()
    assert "aaa new-model" in text
    assert "tacacs server ACME_TACACS_01" in text
    assert "tacacs server ACME_TACACS_02" in text
    assert "key config-key password-encrypt" in text  # control_00007
    assert "ip access-list extended" in text  # control_00008
    assert "MANUAL REVIEW REQUIRED" in text  # banners


def test_full_build_matches_real_ncm_configuration_script():
    # The whole point of this pass: golden_config.txt (this build's output) is
    # now the Compliance Checker's source of truth, replacing the previously
    # hand-maintained golden_config_11_08_2026.txt - which means every real
    # command line here must match support_files/NCM Configuration Script.txt
    # (the authoritative production reference, see CLAUDE.md section 11)
    # exactly. Comments ('!'-prefixed, per this project's own convention -
    # see CLAUDE.md section 10) and blank lines are excluded from the
    # comparison since neither Cisco nor this project's ConfigTree parser
    # treat them as meaningful.
    builder = _builder()
    text = builder.build()
    script_text = (REPO_ROOT / "support_files" / "NCM Configuration Script.txt").read_text(encoding="utf-8")

    def _real_lines(config_text: str) -> list[str]:
        return [
            line.strip()
            for line in config_text.splitlines()
            if line.strip() and not line.strip().startswith("!") and "NCM Configuration Script" not in line
        ]

    assert _real_lines(text) == _real_lines(script_text)


def test_full_build_follows_render_order():
    builder = _builder()
    text = builder.build()
    idx_hostname = text.index("! control_00001 - Hostname")
    idx_domain = text.index("! control_00002 - Domain")
    idx_passwords = text.index("! control_00013 - Passwords")
    idx_aaa = text.index("! control_00003 - AAA")
    assert idx_hostname < idx_domain < idx_passwords < idx_aaa


def test_default_build_excludes_16_17_18():
    # control_00016-00018 stay defined in controls.yaml/render_order.yaml for
    # future use, but a default build() unconditionally excludes them now -
    # there's no --priority-only flag to opt into this anymore, it's the only mode.
    builder = _builder()
    text = builder.build()
    assert "control_00016" not in text
    assert "control_00017" not in text
    assert "control_00018" not in text
    for cid in ACTIVE_CONTROL_IDS:
        assert cid in text


def test_generated_config_is_parseable_by_compliance_checker(tmp_path):
    builder = _builder()
    output_path = tmp_path / "golden_config.txt"
    text = builder.save(output_path)
    assert output_path.read_text(encoding="utf-8") == text

    tree = ConfigTree(text)
    assert tree.exists(r"^hostname\s")
    assert tree.exists(r"^aaa new-model")
    assert len(tree.blocks(r"^tacacs server\s")) == 2
    assert tree.exists(r"^snmp-server enable traps")


def test_line_vty_appears_twice_with_full_settings_each_range():
    # Real script structure (NCM Configuration Script.txt): VTY is split into
    # two ranges ('0 4' and '5 15'), rendered via GoldenConfigBuilder._render_vty's
    # {% for r in vty_ranges %} loop - each range must independently carry the
    # full required settings, not just the second/last one rendered.
    builder = _builder()
    text = builder.build()
    tree = ConfigTree(text)
    vty_blocks = tree.blocks(r"^line vty\s")
    assert len(vty_blocks) == 2
    assert vty_blocks[0][0] == "line vty 0 4"
    assert vty_blocks[1][0] == "line vty 5 15"
    for block in vty_blocks:
        children = block[1:]
        assert any(c.startswith("transport input ssh") for c in children)
        assert any(c.startswith("transport output ssh") for c in children)
        assert any(c.startswith("login authentication default") for c in children)
        assert any(c.startswith("access-class") for c in children)


def test_self_evaluation_against_compliance_checker():
    # The strongest interoperability check: run the Compliance Checker's own
    # ControlEvaluator with the generated golden config as BOTH the device and
    # golden config. This loop evaluates EVERY control in controls.yaml
    # (00001-00018 raw from the YAML file, not filtered to ACTIVE_CONTROL_IDS),
    # even though build() only ever renders 00001-00015 into `golden` - so
    # 00016/00017/00018 are expected non-passes here purely because their
    # content was never rendered (they're inactive-by-design in this version),
    # not because of any control_00001-00015 regression:
    #  - control_00008 (ACL for VTY) renders the real corporate Cloudflare-
    #    deny-list ACL (via _render_acl's {% for rule in acl_rules %} loop,
    #    matching NCM Configuration Script.txt - no longer the old 'permit ip
    #    any any' placeholder). Self-compared against itself, its content
    #    trivially matches -> PASS. control_00014 only needs that ACL to
    #    exist (content is control_00008's job) -> PASS.
    #  - control_00016's mandatory-command items (e.g. 'no ip http server')
    #    are never auto-rendered (GOLDEN_CONFIG_CREATOR.md section 12) even
    #    when 16 WAS in the active set, and it's excluded from the active set
    #    entirely now - so it FAILs on every count.
    #  - control_00017 (Recommended Commands) is well-formed and rendered fully
    #    by the generic engine, but is excluded from the active set by default
    #    in this version, so none of its content (login block-for/delay, etc.)
    #    appears in `golden` at all - it FAILs here for that reason alone.
    #  - control_00018 (Prohibited Commands) checks for the ABSENCE of
    #    prohibited command strings, which doesn't depend on being rendered -
    #    it still correctly PASSes.
    # control_00007 (new) and control_00012 (Banners, presence-only checker)
    # both correctly self-evaluate as PASS.
    import yaml as _yaml

    from compliance_engine import STATUS_FAIL, STATUS_PASS, ControlEvaluator

    builder = _builder()
    golden = builder.build()
    controls = _yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))
    evaluator = ControlEvaluator()

    expected_non_pass = {
        "control_00016": STATUS_FAIL,  # inactive by default - never rendered
        "control_00017": STATUS_FAIL,  # inactive by default - never rendered
    }
    for control in controls:
        result = evaluator.evaluate_control(control, golden, golden)
        expected = expected_non_pass.get(control["control_id"], STATUS_PASS)
        assert result.status == expected, f"{control['control_id']}: {result.status} - {result.details}"
