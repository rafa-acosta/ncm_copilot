"""Reads exceptions.yaml's optional richer metadata for the compliance dashboard.

main.py's load_exceptions() deliberately only ever extracts the plain reason
string for ControlEvaluator - the core engine has no concept of approval
metadata or expiration. This module re-reads the same file independently for
everything else, and is the only place expiration is actually enforced.

exceptions.yaml entries may be a plain string (unattributed, non-expiring -
the original format, unchanged) or a dict:

    control_00004:
      reason: "No TACACS+ infrastructure in this lab environment."
      approver: "jane.doe"
      ticket: "CHG-1234"
      approval_date: "2026-01-01"
      expiration_date: "2026-12-31"
      compensating_control: "Site has no external network access."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


@dataclass
class ExceptionMetadata:
    """One control's exception, with whatever approval metadata was given."""

    control_id: str
    reason: str
    approver: str | None = None
    ticket: str | None = None
    approval_date: str | None = None
    expiration_date: str | None = None
    compensating_control: str | None = None

    @property
    def is_expired(self) -> bool:
        if not self.expiration_date:
            return False
        return date.fromisoformat(self.expiration_date) < date.today()


def load_exception_metadata(path: Path | None) -> dict[str, ExceptionMetadata]:
    """Load control_id -> ExceptionMetadata from an optional exceptions.yaml.

    A plain string entry becomes an ExceptionMetadata with only `reason` set
    (unattributed, non-expiring) - the same acceptance main.py.load_exceptions
    gives that format.
    """
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    result: dict[str, ExceptionMetadata] = {}
    for control_id, entry in data.items():
        if isinstance(entry, dict):
            result[control_id] = ExceptionMetadata(
                control_id=control_id,
                reason=entry["reason"],
                approver=entry.get("approver"),
                ticket=entry.get("ticket"),
                approval_date=entry.get("approval_date"),
                expiration_date=entry.get("expiration_date"),
                compensating_control=entry.get("compensating_control"),
            )
        else:
            result[control_id] = ExceptionMetadata(control_id=control_id, reason=entry)
    return result
