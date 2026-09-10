"""Renders controls.yaml + device_vars.json into a fully rendered golden_config.txt.

Design notes (see GOLDEN_CONFIG_CREATOR.md section 12 for the full rationale):

- Required substitution variables are extracted by scanning each control's
  `command_template` for `<word>` tokens directly, not read from the `variables`
  metadata field: several controls' `variables` lists include documentation-only
  names that never appear in the template itself.
- control_00004 (TACACS) is the one control with a genuinely repeating structure
  (N servers). Its `command_template` in controls.yaml is pre-converted, real
  Jinja (a `{% for %}` loop over a `tacacs_servers` list), not `<word>` tokens,
  and is handled as a special case rather than via the generic <word> engine.
- control_00012 (manual_review: true) and the two policy-checklist controls
  (control_00016, control_00018 - hardcoded by id, regardless of what
  controls.yaml happens to carry for them) all render as a `config_example`
  wrapped in a `! MANUAL REVIEW REQUIRED` block instead of being substituted.
- Missing values are tracked via a custom Jinja Undefined subclass that renders
  as `<MISSING:name>` and records the name, rather than raising or silently
  rendering blank - this is what powers --strict and the non-strict summary.
- `build()` only renders control_00001-00015 (see compliance_engine.ACTIVE_CONTROL_IDS).
  control_00016-00018 stay defined in controls.yaml/render_order.yaml for future
  use, but are unconditionally excluded from a default build; `render_control()`
  can still render one directly if needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import jsonschema
import yaml
from jinja2 import Environment, Undefined

# These two controls are policy checklists (mandatory/prohibited command lists),
# not renderable command blocks, regardless of what controls.yaml carries for
# them (controls.yaml gives control_00016 a real command_template for the
# Compliance Checker's own CoPP evaluation - the Golden Config Creator ignores it).
_MANUAL_REVIEW_ONLY_IDS = {"control_00016", "control_00018"}

_TOKEN_RE = re.compile(r"<(\w+)>")

_MANUAL_REVIEW_REASONS = {
    "control_00016": "Mandatory Commands is a policy checklist, not a renderable template.",
    "control_00018": "Prohibited Commands is a policy checklist, not a renderable template.",
}

# Lines dropped from a control's command_template before rendering: 'crypto key
# zeroize rsa' is a documented one-time bootstrap step in the source doc (see
# controls.yaml/config_example for control_00006), but golden_config.txt is a
# reusable baseline that may be re-applied to an already-provisioned device -
# zeroizing there deletes working RSA keys and breaks SSH. controls.yaml's
# command_template/config_example keep the full documented sequence for
# reference; only rendering drops it.
_LINES_DROPPED_ON_RENDER = {
    "control_00006": [r"^crypto key zeroize rsa\s*$"],
}

# No controls are currently subsumed. control_00008 (ACL for VTY) used to render
# a pointer comment to control_00014 (VTY Lines) when both covered the same VTY
# transport-input concern; control_00008 now defines a standalone ACL block
# (existence-only check, doesn't target 'line vty' at all) and renders normally.
_SUBSUMED_BY: dict[str, str] = {}


@dataclass
class RenderedControl:
    """The rendered output for one control, plus any missing-variable names found."""

    control_id: str
    text: str
    missing: list[str] = field(default_factory=list)


def _make_marking_undefined(missing_sink: list[str]) -> type[Undefined]:
    """Build an Undefined subclass that renders `<MISSING:name>` and records `name`."""

    class MarkingUndefined(Undefined):
        def __str__(self) -> str:
            name = self._undefined_name or "unknown"
            marker = f"<MISSING:{name}>"
            missing_sink.append(str(name))
            return marker

        __repr__ = __str__

    return MarkingUndefined


def _load_yaml(path: str | Path) -> object:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class GoldenConfigBuilder:
    """Renders a golden_config.txt from controls.yaml + device_vars.json."""

    def __init__(
        self,
        controls_path: str | Path,
        device_vars_path: str | Path,
        order_path: str | Path | None = None,
        schema_path: str | Path = "schemas/device_vars.schema.json",
        strict: bool = False,
    ):
        self.controls: dict[str, dict] = {c["control_id"]: c for c in _load_yaml(controls_path)}
        self.device_vars: dict = _load_json(device_vars_path)
        self._validate_device_vars(schema_path)
        self.order: list[str] = _load_yaml(order_path) if order_path else list(self.controls.keys())
        self.strict = strict
        self.missing: list[str] = []

    def _validate_device_vars(self, schema_path: str | Path) -> None:
        schema = _load_json(schema_path)
        try:
            jsonschema.validate(self.device_vars, schema)
        except jsonschema.ValidationError as exc:
            location = ".".join(str(p) for p in exc.absolute_path) or "<root>"
            raise ValueError(f"device_vars.json is invalid at '{location}': {exc.message}") from exc

    def render_control(self, control_id: str) -> RenderedControl | None:
        """Render a single control's command block. Returns None if `control_id`
        has no entry in controls.yaml (e.g. a typo, or a truly unknown ID)."""
        control = self.controls.get(control_id)
        if control is None:
            return None

        header = f"! {control_id} - {control['title']}"

        if control_id in _SUBSUMED_BY:
            note = f"! Covered by {_SUBSUMED_BY[control_id]} - no separate commands rendered here.\n"
            return RenderedControl(control_id=control_id, text=f"{header}\n{note}")

        if control_id in _MANUAL_REVIEW_ONLY_IDS or control.get("manual_review"):
            reason = _MANUAL_REVIEW_REASONS.get(
                control_id, "This control requires human review/customization before use."
            )
            body = self._manual_review_block(control, reason)
            return RenderedControl(control_id=control_id, text=f"{header}\n{body}")

        values = self.device_vars.get(control_id, {})

        if control_id == "control_00004":
            text, missing = self._render_tacacs(control, values)
        else:
            text, missing = self._render_generic(control_id, control, values)

        for name in missing:
            self.missing.append(f"{control_id}.{name}")

        return RenderedControl(control_id=control_id, text=f"{header}\n{text.strip()}\n", missing=missing)

    @staticmethod
    def _manual_review_block(control: dict, reason: str) -> str:
        example = (control.get("config_example") or "NA").strip()
        lines = [
            "! MANUAL REVIEW REQUIRED",
            f"! {reason}",
            *example.splitlines(),
        ]
        return "\n".join(lines) + "\n"

    def _render_generic(self, control_id: str, control: dict, values: dict) -> tuple[str, list[str]]:
        raw_template = control["command_template"]
        for pattern in _LINES_DROPPED_ON_RENDER.get(control_id, []):
            raw_template = "\n".join(
                line for line in raw_template.splitlines() if not re.match(pattern, line.strip())
            )
        required = sorted(set(_TOKEN_RE.findall(raw_template)))
        jinja_template = _TOKEN_RE.sub(lambda m: "{{ " + m.group(1) + " }}", raw_template)

        missing: list[str] = []
        undefined_cls = _make_marking_undefined(missing)
        env = Environment(undefined=undefined_cls, keep_trailing_newline=True)
        rendered = env.from_string(jinja_template).render(**values)

        # de-dupe while preserving order, and only report names that were actually
        # required by this template (guards against accidental extra keys in `values`)
        seen = set()
        missing = [name for name in missing if name in required and not (name in seen or seen.add(name))]
        return rendered, missing

    def _render_tacacs(self, control: dict, values: dict) -> tuple[str, list[str]]:
        missing: list[str] = []
        servers = values.get("tacacs_servers")
        if not servers:
            missing.append("tacacs_servers")
            servers = [
                {
                    "name": "<MISSING:tacacs_servers>",
                    "address": "<MISSING:tacacs_servers>",
                    "key": "<MISSING:tacacs_servers>",
                    "timeout": "<MISSING:tacacs_servers>",
                }
            ]
        else:
            filled_servers = []
            for i, server in enumerate(servers):
                filled = dict(server)
                for field_name in ("name", "address", "key", "timeout"):
                    if not filled.get(field_name) and filled.get(field_name) != 0:
                        filled[field_name] = f"<MISSING:tacacs_servers[{i}].{field_name}>"
                        missing.append(f"tacacs_servers[{i}].{field_name}")
                filled_servers.append(filled)
            servers = filled_servers

        tacacs_group_name = values.get("tacacs_group_name")
        if not tacacs_group_name:
            tacacs_group_name = "<MISSING:tacacs_group_name>"
            missing.append("tacacs_group_name")

        source_interface = values.get("source_interface")
        if not source_interface:
            source_interface = "<MISSING:source_interface>"
            missing.append("source_interface")

        env = Environment(keep_trailing_newline=True)
        rendered = env.from_string(control["command_template"]).render(
            tacacs_servers=servers,
            tacacs_group_name=tacacs_group_name,
            source_interface=source_interface,
        )
        # collapse the blank lines the {% for %}/{% endfor %} lines leave behind
        rendered = "\n".join(line for line in rendered.splitlines() if line.strip() != "")
        return rendered, missing

    def build(self) -> str:
        """Render every control_00001-00015 control in `self.order` and concatenate
        into the final config text. Populates `self.missing`. control_00016-00018
        stay defined in controls.yaml/render_order.yaml for future use, but are
        unconditionally excluded here (see compliance_engine.ACTIVE_CONTROL_IDS) -
        use `render_control(control_id)` directly to render one of them by hand."""
        from compliance_engine import ACTIVE_CONTROL_IDS

        self.missing = []
        control_ids = [cid for cid in self.order if cid in ACTIVE_CONTROL_IDS]

        hostname = self.device_vars.get("control_00001", {}).get("hostname", "")
        header_lines = [
            "! =========================================",
            "! GOLDEN CONFIG - Generated by Golden Config Creator",
            f"! Device: {hostname}" if hostname else "! Device: <unset>",
            f"! Generated: {datetime.now().isoformat(timespec='seconds')}",
            "! =========================================",
            "",
        ]

        blocks = []
        for control_id in control_ids:
            rendered = self.render_control(control_id)
            if rendered is None:
                continue  # not defined in controls.yaml - skip
            blocks.append(rendered.text.rstrip("\n"))

        return "\n".join(header_lines) + "\n\n".join(blocks) + "\n"

    def save(self, output_path: str | Path = "golden_config.txt") -> str:
        """Render (see `build`) and write the result to `output_path`. Returns the text."""
        text = self.build()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        return text
