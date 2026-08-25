"""Unit tests for GoldenConfigBuilder.build / save, using the repo's real sample device_vars.json."""

from __future__ import annotations

from pathlib import Path

from compliance_engine import PRIORITY_CONTROL_IDS
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
    assert "hostname ACME_USA_RT_INT_BLN_01" in text
    assert "aaa new-model" in text
    assert "tacacs server ACME_TACACS_01" in text
    assert "tacacs server ACME_TACACS_02" in text
    assert "MANUAL REVIEW REQUIRED" in text  # banners + 16/18


def test_full_build_follows_render_order():
    builder = _builder()
    text = builder.build()
    idx_hostname = text.index("! control_00001 - Hostname")
    idx_domain = text.index("! control_00002 - Domain")
    idx_passwords = text.index("! control_00013 - Passwords")
    idx_aaa = text.index("! control_00003 - AAA")
    assert idx_hostname < idx_domain < idx_passwords < idx_aaa


def test_priority_only_excludes_16_17_18():
    builder = _builder()
    text = builder.build(priority_only=True)
    assert "control_00016" not in text
    assert "control_00017" not in text
    assert "control_00018" not in text
    for cid in PRIORITY_CONTROL_IDS:
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
    # golden config. A self-consistent baseline should PASS itself everywhere
    # except two known, deliberate gaps:
    #  - control_00012 is manual_review by design (banner wording).
    #  - control_00016's mandatory-command items (e.g. 'no ip http server')
    #    are never auto-rendered (GOLDEN_CONFIG_CREATOR.md section 12); only its
    #    CoPP line renders, so the Compliance Checker's fuller check still fails.
    # Note: this also does not define the ACL content that control_00014's
    # 'access-class' references by name - no control in controls.yaml renders
    # 'ip access-list' bodies - so control_00014 is expected to FAIL here too.
    # That's a known scope gap, not asserted as a silent pass.
    import yaml as _yaml

    from compliance_engine import STATUS_FAIL, STATUS_MANUAL_REVIEW, STATUS_PASS, ControlEvaluator

    builder = _builder()
    golden = builder.build()
    controls = _yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))
    evaluator = ControlEvaluator()

    expected_non_pass = {
        "control_00012": STATUS_MANUAL_REVIEW,
        "control_00014": STATUS_FAIL,  # references an ACL whose body is never rendered
        "control_00016": STATUS_FAIL,  # mandatory-command items deliberately not auto-rendered
    }
    for control in controls:
        result = evaluator.evaluate_control(control, golden, golden)
        expected = expected_non_pass.get(control["control_id"], STATUS_PASS)
        assert result.status == expected, f"{control['control_id']}: {result.status} - {result.details}"
