"""CLI entrypoint for the Golden Config Creator.

Named `golden_config_main.py` rather than `main.py`: this repo already has a
`main.py` for the companion Compliance Checker (see CLAUDE.md /
GOLDEN_CONFIG_CREATOR.md section 12).

Usage:
    python golden_config_main.py \\
        --controls controls.yaml \\
        --device-vars device_vars.json \\
        --output golden_config.txt \\
        [--order render_order.yaml] \\
        [--strict]

Renders control_00001-control_00015 only - render_order.yaml also lists
control_00016-00018, but they're excluded unconditionally (see
compliance_engine.ACTIVE_CONTROL_IDS) and never rendered in this version.
"""

from __future__ import annotations

from pathlib import Path

import click

from golden_config_builder import GoldenConfigBuilder


@click.command()
@click.option(
    "--controls", "controls_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to controls.yaml.",
)
@click.option(
    "--device-vars", "device_vars_path", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to device_vars.json.",
)
@click.option(
    "--output", "output_path", default="golden_config.txt", show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to write the rendered golden config to.",
)
@click.option(
    "--order", "order_path", default="render_order.yaml", show_default=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the render-order YAML file.",
)
@click.option(
    "--strict", is_flag=True, default=False,
    help="Abort and list every missing variable instead of writing a file with <MISSING:...> markers.",
)
def main(
    controls_path: Path,
    device_vars_path: Path,
    output_path: Path,
    order_path: Path,
    strict: bool,
) -> None:
    """Render controls.yaml + device_vars.json into a golden_config.txt."""
    builder = GoldenConfigBuilder(
        controls_path=controls_path,
        device_vars_path=device_vars_path,
        order_path=order_path,
        strict=strict,
    )

    text = builder.build()

    if builder.missing:
        click.echo(f"Missing {len(builder.missing)} variable(s):")
        for name in builder.missing:
            click.echo(f"  - {name}")

    if strict and builder.missing:
        click.echo("Aborting: --strict mode requires every variable to be resolved. No file was written.", err=True)
        raise SystemExit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    click.echo(f"Golden config written to {output_path}")

    if builder.missing:
        click.echo(f"{len(builder.missing)} value(s) unresolved - see <MISSING:...> markers above.")


if __name__ == "__main__":
    main()
