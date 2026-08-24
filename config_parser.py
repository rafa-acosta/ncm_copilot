"""IOS-XE configuration parsing helpers built on top of ciscoconfparse2.

Wraps ciscoconfparse2.CiscoConfParse with a small query surface tailored to
what compliance_engine.py needs: regex line lookups and parent/child block
extraction. '!'-prefixed lines are Cisco comment/separator lines; they never
match a real command regex, so no separate stripping step is required.
"""

from __future__ import annotations

from ciscoconfparse2 import CiscoConfParse


class ConfigTree:
    """A parsed IOS-XE configuration with simple regex-based query helpers."""

    def __init__(self, config_text: str):
        self.text = config_text
        self._parse = CiscoConfParse(config_text.splitlines(), syntax="ios")

    def find(self, pattern: str):
        """Return every config line object (at any depth) whose text matches `pattern`."""
        return self._parse.find_objects(pattern)

    def exists(self, pattern: str) -> bool:
        """True if any line (at any depth) matches `pattern`."""
        return bool(self.find(pattern))

    def first_text(self, pattern: str) -> str | None:
        """Text of the first line matching `pattern`, or None."""
        objs = self.find(pattern)
        return objs[0].text.strip() if objs else None

    def all_text(self, pattern: str) -> list[str]:
        """Text of every line (at any depth) matching `pattern`."""
        return [o.text.strip() for o in self.find(pattern)]

    def blocks(self, parent_pattern: str) -> list[list[str]]:
        """For every top-level line matching `parent_pattern`, return
        [parent_text, child_text, ...] — one list per matching parent.
        """
        return [
            [o.text.strip()] + [c.text.strip() for c in o.children]
            for o in self.find(parent_pattern)
        ]
