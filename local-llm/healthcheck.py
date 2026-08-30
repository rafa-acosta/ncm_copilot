#!/usr/bin/env python3
"""Pings every backend in local-llm/config.yaml and reports up/down status.

Exit code: 0 if at least one backend is reachable, 1 otherwise - mirrors the
condition llm_client.select_backend's BackendUnavailableError raises on, so
this can be used as a pre-flight check before running agent_assisted_coding_advise.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from llm_client import _launch_hint, is_reachable, load_backends_registry  # noqa: E402

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def main() -> int:
    registry = load_backends_registry(CONFIG_PATH)
    if not registry:
        print(f"No backends configured in {CONFIG_PATH}.")
        return 1

    any_up = False
    for name, cfg in registry.items():
        up = is_reachable(cfg["base_url"])
        any_up = any_up or up
        status = "UP" if up else "DOWN"
        role = cfg.get("role", "?")
        print(f"{name:15s} [{role:12s}] {cfg['base_url']:30s} {status}")

    if not any_up:
        print()
        print("No backend is reachable. Start one with:")
        for name in registry:
            print(f"  {_launch_hint(name)}   ({name})")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
