"""Unit + CLI tests for remediation_advisor.py and vibecoding_advise.py.

No real LLM server is used anywhere here: LLMClient is always constructed with
a fake injected `client` object (see tests/test_llm_client.py's _FakeOpenAIClient
pattern), so these tests run fully offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import remediation_advisor as ra
import vibecoding_advise
from llm_client import LLMClient
from report_schema import ComplianceReport

REPO_ROOT = Path(__file__).parent.parent
CONTROLS_PATH = REPO_ROOT / "controls.yaml"
DEVICE_CONFIG_PATH = REPO_ROOT / "samples" / "device_config.txt"
GOLDEN_CONFIG_PATH = REPO_ROOT / "samples" / "golden_config.txt"


class _FakeCompletions:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def create(self, **kwargs):
        message = SimpleNamespace(content=self._response_text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeOpenAIClient:
    def __init__(self, response_text: str = "Fake explanation."):
        self.chat = SimpleNamespace(completions=_FakeCompletions(response_text))


def _fake_llm_client(response_text: str = "Fake explanation.") -> LLMClient:
    return LLMClient(base_url="http://fake/v1", backend_name="llamacpp", client=_FakeOpenAIClient(response_text))


def _real_controls_by_id() -> dict[str, dict]:
    return ra.load_controls_by_id(CONTROLS_PATH)


def _real_report(tmp_path: Path) -> ComplianceReport:
    """Generate a real Compliance Checker JSON report from the sample configs."""
    import yaml

    from compliance_engine import ControlEvaluator
    from report_generator import build_report_json

    controls = yaml.safe_load(CONTROLS_PATH.read_text(encoding="utf-8"))
    device_config = DEVICE_CONFIG_PATH.read_text(encoding="utf-8")
    golden_config = GOLDEN_CONFIG_PATH.read_text(encoding="utf-8")
    evaluator = ControlEvaluator()
    results = [evaluator.evaluate_control(c, device_config, golden_config) for c in controls]
    return build_report_json(
        results,
        device_name="device_config",
        device_config_path=str(DEVICE_CONFIG_PATH),
        golden_config_path=str(GOLDEN_CONFIG_PATH),
    )


# ---- select_findings ---------------------------------------------------------

def test_select_findings_only_includes_fail_status(tmp_path):
    report = _real_report(tmp_path)
    controls_by_id = _real_controls_by_id()
    findings = ra.select_findings(report, controls_by_id)
    assert findings
    assert all(f.status == "FAIL" for f in findings)


def test_select_findings_sorted_high_medium_low(tmp_path):
    report = _real_report(tmp_path)
    controls_by_id = _real_controls_by_id()
    findings = ra.select_findings(report, controls_by_id)
    ranks = [ra.SEVERITY_RANK[f.severity] for f in findings]
    assert ranks == sorted(ranks)


def test_select_findings_severity_min_filters_out_lower_severities(tmp_path):
    report = _real_report(tmp_path)
    controls_by_id = _real_controls_by_id()
    all_findings = ra.select_findings(report, controls_by_id)
    high_only = ra.select_findings(report, controls_by_id, severity_min="high")
    assert any(f.severity == "Medium" for f in all_findings)  # sanity: the unfiltered set has non-High entries
    assert all(f.severity == "High" for f in high_only)
    assert len(high_only) < len(all_findings)


# ---- missing_variables --------------------------------------------------------

def test_missing_variables_with_no_device_vars_returns_all_tokens():
    controls_by_id = _real_controls_by_id()
    control = controls_by_id["control_00011"]  # SNMP
    result = ra.missing_variables(control, None)
    assert set(result) == {"group_name", "user_name", "auth_password", "priv_password", "snmp_server_ip"}


def test_missing_variables_excludes_already_resolved_ones():
    controls_by_id = _real_controls_by_id()
    control = controls_by_id["control_00011"]
    device_vars = {"control_00011": {"group_name": "acme_snmp_grp01", "user_name": "acme_snmp_user"}}
    result = ra.missing_variables(control, device_vars)
    assert "group_name" not in result
    assert "user_name" not in result
    assert "auth_password" in result


def test_missing_variables_ignores_empty_string_as_unresolved():
    controls_by_id = _real_controls_by_id()
    control = controls_by_id["control_00011"]
    device_vars = {"control_00011": {"group_name": ""}}
    result = ra.missing_variables(control, device_vars)
    assert "group_name" in result  # empty string doesn't count as resolved


def test_missing_variables_treats_zero_as_resolved_not_missing():
    # Regression: a legitimately-set 0 (e.g. start_line_number: 0, seconds: 0)
    # is falsy in Python but IS a real resolved value - a naive `not value`
    # check would wrongly flag it as still-needed. Caught via a real end-to-end
    # smoke test against device_vars.json's control_00014.start_line_number: 0.
    controls_by_id = _real_controls_by_id()
    control = controls_by_id["control_00014"]  # VTY Lines
    device_vars = {"control_00014": {"start_line_number": 0, "seconds": 0}}
    result = ra.missing_variables(control, device_vars)
    assert "start_line_number" not in result
    assert "seconds" not in result


# ---- build_finding: the core "no invented commands" guarantee ----------------

def test_build_finding_command_block_matches_controls_yaml_verbatim(tmp_path):
    report = _real_report(tmp_path)
    controls_by_id = _real_controls_by_id()
    findings_entries = ra.select_findings(report, controls_by_id)
    assert findings_entries  # sanity: the sample device has real FAILs

    # A deliberately mangled fake response - if command sourcing ever routed
    # through the LLM, this text would leak into command_block.
    llm_client = _fake_llm_client("HALLUCINATED: no ip domain name evil.example\n")

    for entry in findings_entries:
        control = controls_by_id[entry.control_id]
        finding = ra.build_finding(control, entry, None, llm_client)
        assert finding.command_block == control["config_example"].strip()
        assert finding.remediation_recommendation == control["remediation"].strip()
        assert "HALLUCINATED" not in finding.command_block
        assert "HALLUCINATED" not in finding.remediation_recommendation
        # the fake response is only ever allowed to land in .explanation
        assert finding.explanation == "HALLUCINATED: no ip domain name evil.example"


def test_build_finding_explanation_comes_from_llm_client():
    controls_by_id = _real_controls_by_id()
    control = controls_by_id["control_00001"]
    entry = SimpleNamespace(control_id="control_00001", details=["Hostname is generic."])
    llm_client = _fake_llm_client("Custom explanation text.")

    finding = ra.build_finding(control, entry, None, llm_client)
    assert finding.explanation == "Custom explanation text."


# ---- markdown / json rendering -------------------------------------------------

def test_render_markdown_groups_by_severity_and_shows_command_block(tmp_path):
    controls_by_id = _real_controls_by_id()
    control = controls_by_id["control_00011"]
    finding = ra.Finding(
        control_id="control_00011", title="SNMP", severity="High", risk="Some risk.",
        remediation_recommendation="Some remediation.", command_block=control["config_example"].strip(),
        still_needed_variables=["group_name"], explanation="Some explanation.",
    )
    output_path = tmp_path / "briefing.md"
    ra.render_markdown([finding], "RTR01", "llama.cpp (fake)", output_path, "2026-08-26 12:00")
    text = output_path.read_text(encoding="utf-8")

    assert "RTR01" in text
    assert "HIGH severity" in text
    assert control["config_example"].strip() in text
    assert "`<group_name>`" in text


def test_render_markdown_shows_device_and_golden_config_paths(tmp_path):
    finding = ra.Finding(
        control_id="control_00001", title="Hostname", severity="Low", risk="r",
        remediation_recommendation="m", command_block="c",
        still_needed_variables=[], explanation="e",
    )
    output_path = tmp_path / "briefing.md"
    ra.render_markdown(
        [finding], "RTR01", "llama.cpp (fake)", output_path, "2026-08-26 12:00",
        device_config_path="samples/device_config.txt", golden_config_path="samples/golden_config.txt",
    )
    text = output_path.read_text(encoding="utf-8")
    assert "samples/device_config.txt" in text
    assert "samples/golden_config.txt" in text


def test_render_markdown_omits_path_lines_when_not_given(tmp_path):
    finding = ra.Finding(
        control_id="control_00001", title="Hostname", severity="Low", risk="r",
        remediation_recommendation="m", command_block="c",
        still_needed_variables=[], explanation="e",
    )
    output_path = tmp_path / "briefing.md"
    ra.render_markdown([finding], "RTR01", "llama.cpp (fake)", output_path, "2026-08-26 12:00")
    text = output_path.read_text(encoding="utf-8")
    assert "Device config:" not in text
    assert "Golden config:" not in text


def test_render_briefing_json_includes_device_vars_patch(tmp_path):
    finding = ra.Finding(
        control_id="control_00011", title="SNMP", severity="High", risk="r",
        remediation_recommendation="m", command_block="c",
        still_needed_variables=["group_name", "user_name"], explanation="e",
    )
    output_path = tmp_path / "briefing.json"
    ra.render_briefing_json([finding], "RTR01", "llama.cpp (fake)", output_path, "2026-08-26 12:00")
    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["suggested_device_vars_patch"] == {"control_00011": {"group_name": None, "user_name": None}}
    assert data["findings"][0]["command_block"] == "c"


# ---- CLI smoke test ------------------------------------------------------------

def test_cli_produces_briefing_with_fake_backend(tmp_path, monkeypatch):
    report = _real_report(tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    monkeypatch.setattr(vibecoding_advise, "select_backend", lambda *a, **k: ("llamacpp", "http://fake/v1", "phi-3-mini-4k-instruct"))
    monkeypatch.setattr(vibecoding_advise, "LLMClient", lambda *a, **k: _fake_llm_client())

    md_path = tmp_path / "briefing.md"
    json_path = tmp_path / "briefing.json"
    runner = CliRunner()
    result = runner.invoke(
        vibecoding_advise.main,
        [
            "--report", str(report_path),
            "--controls", str(CONTROLS_PATH),
            "--backend", "auto",
            "--output-md", str(md_path),
            "--output-json", str(json_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert md_path.exists()
    assert json_path.exists()
    assert "finding(s) briefed" in result.output

    md_text = md_path.read_text(encoding="utf-8")
    assert str(DEVICE_CONFIG_PATH) in md_text
    assert str(GOLDEN_CONFIG_PATH) in md_text
    json_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert json_data["device_config_path"] == str(DEVICE_CONFIG_PATH)
    assert json_data["golden_config_path"] == str(GOLDEN_CONFIG_PATH)
