"""Unit tests for llm_client.py: registry loading, backend selection, and
LLMClient.explain. No real network or LLM server required."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import llm_client
from llm_client import BackendUnavailableError, LLMClient, load_backends_registry, select_backend

QWEN_URL = "http://fake-qwen:8080/v1"
PHI4_URL = "http://fake-phi4:8081/v1"

REGISTRY = {
    "qwen_coder": {"role": "specialist", "base_url": QWEN_URL, "model_name": "qwen2.5-coder-7b-instruct-q4_k_m"},
    "phi4_mini": {"role": "fast_default", "base_url": PHI4_URL, "model_name": "phi-4-mini-instruct-q4_k_m"},
}


def _write_config(tmp_path: Path, backends: dict) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"backends": backends}), encoding="utf-8")
    return config_path


def _patch_reachability(monkeypatch, up: dict[str, bool]) -> None:
    def fake_is_reachable(base_url: str, timeout: float = 2.0) -> bool:
        for name, cfg in REGISTRY.items():
            if cfg["base_url"] == base_url:
                return up.get(name, False)
        raise AssertionError(f"unexpected base_url: {base_url}")

    monkeypatch.setattr(llm_client, "_is_reachable", fake_is_reachable)


# ---- load_backends_registry ---------------------------------------------------

def test_load_backends_registry_reads_backends_key(tmp_path):
    config_path = _write_config(tmp_path, REGISTRY)
    registry = load_backends_registry(config_path)
    assert registry == REGISTRY


def test_load_backends_registry_missing_file_returns_empty_dict(tmp_path):
    registry = load_backends_registry(tmp_path / "does_not_exist.yaml")
    assert registry == {}


# ---- select_backend: auto ------------------------------------------------------

def test_auto_both_up_single_device_prefers_specialist(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": True, "phi4_mini": True})
    name, url, model = select_backend("auto", device_count=1, config_path=config_path)
    assert (name, url, model) == ("qwen_coder", QWEN_URL, "qwen2.5-coder-7b-instruct-q4_k_m")


def test_auto_both_up_multi_device_prefers_fast_default(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": True, "phi4_mini": True})
    name, url, model = select_backend("auto", device_count=5, config_path=config_path)
    assert (name, url, model) == ("phi4_mini", PHI4_URL, "phi-4-mini-instruct-q4_k_m")


def test_auto_only_specialist_up_is_selected_regardless_of_device_count(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": True, "phi4_mini": False})
    name, url, model = select_backend("auto", device_count=5, config_path=config_path)
    assert name == "qwen_coder"


def test_auto_only_fast_default_up_is_selected(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": False, "phi4_mini": True})
    name, url, model = select_backend("auto", device_count=1, config_path=config_path)
    assert name == "phi4_mini"


def test_auto_neither_up_raises_listing_both_backends(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": False, "phi4_mini": False})
    with pytest.raises(BackendUnavailableError) as exc_info:
        select_backend("auto", device_count=1, config_path=config_path)
    message = str(exc_info.value)
    assert "qwen_coder" in message
    assert "phi4_mini" in message


def test_auto_no_backends_configured_raises_helpful_message(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, {})
    with pytest.raises(BackendUnavailableError) as exc_info:
        select_backend("auto", device_count=1, config_path=config_path)
    assert "no backends are configured" in str(exc_info.value).lower()


# ---- select_backend: explicit named backend ------------------------------------

def test_explicit_named_backend_ignores_others_reachability(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": True, "phi4_mini": False})
    name, url, model = select_backend("qwen_coder", device_count=1, config_path=config_path)
    assert (name, url) == ("qwen_coder", QWEN_URL)


def test_explicit_named_backend_unreachable_raises(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": False, "phi4_mini": True})
    with pytest.raises(BackendUnavailableError):
        select_backend("qwen_coder", device_count=1, config_path=config_path)


def test_unknown_backend_name_raises_listing_known_names(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": True, "phi4_mini": True})
    with pytest.raises(BackendUnavailableError) as exc_info:
        select_backend("ollama", device_count=1, config_path=config_path)
    message = str(exc_info.value)
    assert "qwen_coder" in message
    assert "phi4_mini" in message


# ---- LLMClient.explain --------------------------------------------------------

class _FakeCompletions:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        message = SimpleNamespace(content=self._response_text)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class _FakeOpenAIClient:
    def __init__(self, response_text: str):
        completions = _FakeCompletions(response_text)
        self.chat = SimpleNamespace(completions=completions)


CONTROL = {
    "control_id": "control_00011",
    "title": "SNMP",
    "severity": "High",
    "risk": "SNMPv1/v2c transmit community strings in clear text.",
    "explanation": "Configures SNMPv3 with encryption and authentication.",
}


def test_explain_returns_fake_response_verbatim():
    fake_client = _FakeOpenAIClient("  This is the model's explanation.  ")
    client = LLMClient(base_url=QWEN_URL, backend_name="qwen_coder", client=fake_client)

    result = client.explain(CONTROL, ["SNMP trap host is missing."])

    assert result == "This is the model's explanation."


def test_explain_prompt_includes_grounding_context():
    fake_client = _FakeOpenAIClient("explanation")
    client = LLMClient(base_url=QWEN_URL, backend_name="qwen_coder", client=fake_client)

    client.explain(CONTROL, ["SNMP trap host is missing.", "'snmp-server enable traps' command is missing."])

    kwargs = fake_client.chat.completions.last_call_kwargs
    system_message, user_message = kwargs["messages"]
    assert system_message["role"] == "system"
    assert "senior Cisco IOS-XE network security engineer" in system_message["content"]
    assert user_message["role"] == "user"
    assert CONTROL["title"] in user_message["content"]
    assert CONTROL["risk"] in user_message["content"]
    assert "SNMP trap host is missing." in user_message["content"]
    assert "'snmp-server enable traps' command is missing." in user_message["content"]


def test_explain_never_receives_command_block():
    # The control dict passed to explain() carries no config_example/remediation
    # fields at all in this test, proving explain() doesn't need or use them -
    # architectural guarantee that the LLM's output can't be the command text.
    control_without_commands = {k: v for k, v in CONTROL.items() if k not in ("config_example", "remediation")}
    fake_client = _FakeOpenAIClient("explanation")
    client = LLMClient(base_url=QWEN_URL, backend_name="qwen_coder", client=fake_client)

    client.explain(control_without_commands, ["some finding"])  # must not raise KeyError


def test_llm_client_model_defaults_to_registry_model_name(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, REGISTRY)
    _patch_reachability(monkeypatch, {"qwen_coder": True, "phi4_mini": False})
    name, url, model = select_backend("auto", device_count=1, config_path=config_path)
    fake_client = _FakeOpenAIClient("x")
    client = LLMClient(url, name, client=fake_client, model=model)
    assert client.model == "qwen2.5-coder-7b-instruct-q4_k_m"
