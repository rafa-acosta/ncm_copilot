"""Self-contained inline-SVG chart helpers for the compliance dashboard.

No charting library, consistent with compliance_report_builder.donut_svg()'s
existing precedent for this project - that helper is single-metric only
(colored by a pass/fail threshold), so it isn't reused here; the dashboard
needs a genuine multi-category donut and a trend sparkline, which are new
shapes, not a threshold-color variant of the existing one.
"""

from __future__ import annotations

import math


def multi_segment_donut_svg(segments: list[tuple[str, int, str]], size: int = 220, stroke: int = 28) -> str:
    """`segments` is a list of (label, count, color). Renders one ring slice
    per segment with count > 0, in the given order. Returns an empty-state
    ring (all gray) if every count is 0, rather than dividing by zero."""
    total = sum(count for _, count, _ in segments)
    radius = (size - stroke) / 2
    center = size / 2
    circumference = 2 * math.pi * radius

    parts = [
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" '
        f'aria-label="Device posture breakdown">'
    ]
    if total == 0:
        parts.append(
            f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" '
            f'stroke="#e6e6e6" stroke-width="{stroke}"/>'
        )
    else:
        offset = 0.0
        for _, count, color in segments:
            if count <= 0:
                continue
            length = circumference * (count / total)
            parts.append(
                f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" stroke="{color}" '
                f'stroke-width="{stroke}" stroke-dasharray="{length:.2f} {circumference:.2f}" '
                f'stroke-dashoffset="{-offset:.2f}" stroke-linecap="butt" '
                f'transform="rotate(-90 {center} {center})"/>'
            )
            offset += length
    parts.append(
        f'<text x="{center}" y="{center}" text-anchor="middle" dominant-baseline="middle" '
        f'font-size="{size * 0.16:.0f}" font-family="sans-serif" font-weight="700">{total}</text>'
    )
    parts.append(
        f'<text x="{center}" y="{center + size * 0.14:.0f}" text-anchor="middle" '
        f'font-size="{size * 0.06:.0f}" font-family="sans-serif" fill="#666">devices</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def trend_sparkline_svg(values: list[float], width: int = 480, height: int = 120, color: str = "#2a6f97") -> str:
    """A minimal line chart for `values` (0-100 scale, e.g. a % over time).
    Returns a flat "no data yet" placeholder for 0 or 1 points - a trend
    needs at least two snapshots to mean anything."""
    pad = 12
    if len(values) < 2:
        return (
            f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
            f'aria-label="Not enough history for a trend yet">'
            f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="14" font-family="sans-serif" fill="#888">Not enough history yet (need 2+ runs)</text>'
            f"</svg>"
        )
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = (width - 2 * pad) / (len(values) - 1)

    def _point(i: int, v: float) -> tuple[float, float]:
        x = pad + i * step
        y = height - pad - ((v - lo) / span) * (height - 2 * pad)
        return x, y

    points = [_point(i, v) for i, v in enumerate(values)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>' for x, y in points
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
        f'aria-label="Trend over {len(values)} runs">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2"/>'
        f"{dots}"
        f'<text x="{pad}" y="{pad}" font-size="11" font-family="sans-serif" fill="#666">{hi:.1f}</text>'
        f'<text x="{pad}" y="{height - 2}" font-size="11" font-family="sans-serif" fill="#666">{lo:.1f}</text>'
        f"</svg>"
    )
