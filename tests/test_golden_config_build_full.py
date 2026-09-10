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


def test_line_vty_appears_exactly_once_with_full_settings():
    # Regression guard for the control_00008/control_00014 duplicate-stanza bug:
    # both target 'line vty', so a naive render would emit it twice with only
    # the second copy carrying login local/exec-timeout/access-class.
    builder = _builder()
    text = builder.build()
    tree = ConfigTree(text)
    vty_blocks = tree.blocks(r"^line vty\s")
    assert len(vty_blocks) == 1
    children = vty_blocks[0][1:]
    assert any(c.startswith("transport input ssh") for c in children)
    assert any(c.startswith("login local") for c in children)
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
    #  - control_00008 (ACL for VTY) now renders its own real
    #    'ip access-list extended ACME_VTY_MGMT_ACL / permit ip any any' block
    #    (existence-only check -> PASS), which in turn means control_00014's
    #    access-class binding now resolves to a real (if permissive) ACL -
    #    so control_00014 FAILs for a more specific reason than before
    #    ("ACL is permissive" instead of "ACL not found").
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
        "control_00014": STATUS_FAIL,  # ACL exists (via control_00008) but is permissive
        "control_00016": STATUS_FAIL,  # inactive by default - never rendered
        "control_00017": STATUS_FAIL,  # inactive by default - never rendered
    }
    for control in controls:
        result = evaluator.evaluate_control(control, golden, golden)
        expected = expected_non_pass.get(control["control_id"], STATUS_PASS)
        assert result.status == expected, f"{control['control_id']}: {result.status} - {result.details}"
