"""Pluggable local LLM backend client for the Compliance Remediation Advisor.

Backends are a named registry loaded from local-llm/config.yaml (e.g.
"qwen_coder", "phi4_mini"), not a hardcoded vLLM-vs-llama.cpp engine choice -
this repo's actual hardware (a 6GB VRAM laptop GPU) only runs llama.cpp in
practice, and the real selection problem is "which model", not "which engine".
See LOCAL_LLM_SETUP_PROMPT.md section "Implementation Notes" for why this
was generalized from COMPLIANCE_ANALYZER_PROMPT.md's original vllm/llamacpp
design. Every backend still exposes an OpenAI-compatible /v1 endpoint, so a
single `LLMClient` built on the `openai` SDK talks to any of them - the only
backend-specific code is the health check and base_url/model lookup in
`select_backend`.

The LLM is deliberately given a narrower job than either spec's literal
wording: it never sees the remediation command block as something to
reproduce, only risk/severity/finding context, and writes just the "what's
missing and why" explanation. remediation_advisor.py inserts controls.yaml's
config_example verbatim itself. This makes "never LLM-generated command
text" true by construction instead of by hoping the model complied.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import yaml
from openai import OpenAI

_REPO_ROOT = Path(__file__).parent
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "local-llm" / "config.yaml"

SYSTEM_PROMPT = """You are a senior Cisco IOS-XE network security engineer performing a post-audit
remediation briefing. You will be given a control's risk, severity, and the
specific non-compliance finding detected on a device. You will NOT be given
the remediation commands themselves - those are inserted separately from the
organization's approved compliance framework, verbatim, and are not your
responsibility.

Your job:
- Explain in 2-3 plain-language sentences what is missing and why it matters,
  as if briefing a network engineer who has 5 minutes before a maintenance window.
- Do not speculate about the device's environment beyond what is given.
- Do not mention or invent specific configuration commands - focus only on the
  risk and operational impact.
- Keep the tone direct and operational, not academic."""

RISK_STATEMENT_SYSTEM_PROMPT = """You rewrite security-control risk statements for an audit report. You will be
given a risk statement that failed an automated check, and the reason(s) it
failed.

Your job:
- Output EXACTLY one sentence, ending in a period.
- Do not use hedging or filler phrasing (e.g. "it is important to note that",
  "these issues need to be addressed to ensure", "in order to").
- Do not add commentary, a preamble, or quotation marks - output only the
  rewritten sentence itself.
- Preserve the original statement's technical meaning; do not soften or
  exaggerate the risk."""


class BackendUnavailableError(RuntimeError):
    """Raised when no requested/registered local LLM backend could be reached."""


def _config_path(config_path: str | Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path)
    env_override = os.environ.get("VIBECODING_LLM_CONFIG")
    if env_override:
        return Path(env_override)
    return _DEFAULT_CONFIG_PATH


def load_backends_registry(config_path: str | Path | None = None) -> dict[str, dict]:
    """Load the `backends:` map from local-llm/config.yaml (or an override path).

    Each entry: {role, base_url, model_name}. Returns {} if the config file
    doesn't exist yet (e.g. a fresh clone before local-llm/ setup has run).
    """
    path = _config_path(config_path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("backends", {}) or {}


def _is_reachable(base_url: str, timeout: float = 2.0) -> bool:
    """True if `base_url`/models responds successfully. Module-level so tests can
    monkeypatch it directly instead of mocking HTTP."""
    try:
        response = httpx.get(f"{base_url}/models", timeout=timeout)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


# Public name for external callers (e.g. local-llm/healthcheck.py) that don't
# need the monkeypatch-by-private-name pattern this module's own tests use.
is_reachable = _is_reachable


def _launch_hint(name: str) -> str:
    """Best-effort path to this backend's serve_<name>.sh, tolerating the
    underscore mismatch between config.yaml's backend keys (e.g. "phi4_mini")
    and this project's literal script filenames (e.g. "serve_phi4mini.sh",
    no underscore) - both spellings come directly from the same spec, so
    an exact match can't be assumed."""
    local_llm_dir = _REPO_ROOT / "local-llm"
    for candidate in (f"serve_{name}.sh", f"serve_{name.replace('_', '')}.sh"):
        if (local_llm_dir / candidate).exists():
            return f"local-llm/{candidate}"
    return "see local-llm/README.md"


def _unavailable_message(registry: dict[str, dict], note: str = "") -> str:
    lines = ["No local LLM backend is reachable." + (f" {note}" if note else "")]
    if not registry:
        lines.append(
            f"No backends are configured at all - see {_DEFAULT_CONFIG_PATH} "
            "(run local-llm/install_llama_server.sh and local-llm/download_models.sh first)."
        )
        return "\n".join(lines)
    lines.append("Start one of the following and try again:")
    for name, cfg in registry.items():
        lines.append(f"  - {name} ({cfg.get('role', '?')}) at {cfg.get('base_url', '?')}: {_launch_hint(name)}")
    return "\n".join(lines)


def select_backend(
    requested: str,
    device_count: int = 1,
    config_path: str | Path | None = None,
) -> tuple[str, str, str]:
    """Resolve `requested` ("auto" or a registered backend name) to
    (backend_name, base_url, model_name).

    "auto" pings every registered backend and, among reachable ones, prefers
    role == "fast_default" when device_count > 1 (many calls, latency
    compounds) and role == "specialist" otherwise (quality matters more for a
    one-off call) - the same spirit as the original vLLM-for-batch /
    llama.cpp-for-single-shot rule, now expressed as roles instead of
    engines. A single reachable backend wins regardless of role. Raises
    BackendUnavailableError, listing every registered backend's launch hint,
    if nothing usable is reachable.
    """
    registry = load_backends_registry(config_path)

    if requested != "auto":
        cfg = registry.get(requested)
        if cfg is None:
            known = ", ".join(sorted(registry)) or "(none configured)"
            raise BackendUnavailableError(f"Unknown backend '{requested}'. Known backends: {known}.")
        if not _is_reachable(cfg["base_url"]):
            raise BackendUnavailableError(
                _unavailable_message(registry, f"--backend {requested} was requested but {cfg['base_url']} did not respond.")
            )
        return requested, cfg["base_url"], cfg.get("model_name", requested)

    reachable = {name: cfg for name, cfg in registry.items() if _is_reachable(cfg["base_url"])}
    if not reachable:
        raise BackendUnavailableError(_unavailable_message(registry))

    preferred_role = "fast_default" if device_count > 1 else "specialist"
    for name, cfg in reachable.items():
        if cfg.get("role") == preferred_role:
            return name, cfg["base_url"], cfg.get("model_name", name)

    # No backend has the preferred role (or roles aren't set) - take whichever
    # is reachable, in a deterministic (sorted) order.
    name = sorted(reachable)[0]
    cfg = reachable[name]
    return name, cfg["base_url"], cfg.get("model_name", name)


class LLMClient:
    """Talks to whichever local backend `select_backend` resolved to."""

    def __init__(self, base_url: str, backend_name: str, client: object | None = None, model: str | None = None):
        self.backend_name = backend_name
        self.base_url = base_url
        self.model = model or backend_name
        # `client` is constructor-injectable so tests pass a fake object
        # implementing .chat.completions.create(...) without needing a real
        # server or an HTTP-mocking library.
        self.client = client if client is not None else OpenAI(base_url=base_url, api_key="not-needed")

    def explain(self, control: dict, finding_details: list[str]) -> str:
        """Return a 2-3 sentence plain-language explanation for one FAILED control.

        Only ever grounded in `control`'s risk/severity/explanation and the
        specific finding details - never given the command block, so its
        output can never become the remediation command text.
        """
        user_prompt = (
            f"Control: {control['title']} ({control['control_id']})\n"
            f"Severity: {control['severity']}\n"
            f"Risk: {control['risk'].strip()}\n"
            f"Control purpose: {control.get('explanation', '').strip()}\n"
            f"Specific finding(s) on this device:\n"
            + "\n".join(f"- {d}" for d in finding_details)
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()

    def polish_statement(self, original: str, violations: list[str]) -> str:
        """Rewrite `original` (a risk statement that failed validation) as one
        clean sentence. Used only by compliance_report_builder.py's optional
        --llm-polish path - the caller re-validates the result against the
        same checks before accepting it, so this method's output is never
        trusted blindly."""
        user_prompt = (
            f"Original risk statement: {original}\n"
            f"Validation failure(s): {'; '.join(violations)}\n"
            "Rewrite it as one clean sentence that fixes these issues."
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": RISK_STATEMENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
