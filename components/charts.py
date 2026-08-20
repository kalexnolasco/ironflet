"""Simple charts built from ft.Container (no external dependencies)."""

from __future__ import annotations

import flet as ft

from theme import C

#: Fraction of the value range left as breathing room above and below the bars
#: when the baseline is computed. Without it the smallest reading is a 2 px
#: stub and the largest touches the ceiling, which reads as "off the chart".
_PAD = 0.15


def _floor_for(values: list[float], baseline: str) -> float:
    """Where the bars grow from.

    `"zero"` is the honest default for a magnitude — volume, sets, reps — where
    the height of the bar *is* the quantity and a cropped axis would exaggerate
    a small change.

    `"auto"` exists for series that live in a narrow band far from zero, where
    a zero baseline is honest and useless in equal measure. Body weight is the
    example that forced this: seven weigh-ins spanning 82.0-84.2 kg drew as
    110, 109, 109, 108, 107, 108, 107 px — 2.2 kg of change rendered as **three
    pixels**, on the one chart a recomposition is actually steered by. The
    estimated-1RM progression in History had the same problem for the same
    reason: nobody's bench moves from zero.

    A cropped axis can mislead, so callers using `"auto"` are expected to label
    it — `bar_chart` returns the floor it used via `chart_floor` on the control
    so the caller can say so.
    """
    if baseline != "auto" or not values:
        return 0.0
    low, high = min(values), max(values)
    span = high - low
    if span <= 0:
        # Every reading identical: a floor just under them keeps the bars
        # visible instead of collapsing the whole chart to zero height.
        return max(0.0, low - max(abs(low) * 0.01, 0.5))
    return max(0.0, low - span * _PAD)


def bar_chart(
    values: list[float],
    labels: list[str] | None = None,
    color: str | None = None,
    height: int = 120,
    baseline: str = "zero",
) -> ft.Control:
    # Default is None and resolved here: a colour evaluated in the `def` would
    # freeze whichever palette was active at import time.
    color = color or C.chart_bar
    if not values:
        # Reached by the default route — the detail view opens on "Est. 1RM",
        # which is empty for bodyweight or warm-up-only exercises.
        empty = ft.Container(
            content=ft.Text("No data", color=C.text_muted, size=11, italic=True),
            alignment=ft.alignment.center,
            height=height,
        )
        empty.chart_floor = 0.0
        return empty

    labels = labels or []
    floor = _floor_for(values, baseline)
    top = max(values)
    span = (top - floor) or 1
    bars = []
    for i, v in enumerate(values):
        # `max(2, ...)` keeps the shortest bar visible; `max(0, ...)` before it
        # guards a value below the floor, which cannot happen from `_floor_for`
        # but can if a caller passes its own baseline later.
        bar_h = max(2, int(max(0.0, v - floor) / span * height))
        lbl = labels[i] if i < len(labels) else ""
        bars.append(
            ft.Column(
                [
                    ft.Container(height=max(0, height - bar_h)),
                    ft.Container(
                        height=bar_h,
                        width=16,
                        bgcolor=color,
                        border_radius=ft.border_radius.only(top_left=4, top_right=4),
                        tooltip=f"{v:g}",
                    ),
                    ft.Text(f"{v:g}", size=8, color=color, weight=ft.FontWeight.W_700),
                    ft.Text(lbl, size=7, color=C.text_muted),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=1,
            )
        )
    chart = ft.Row(
        bars,
        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
        spacing=2,
        scroll=ft.ScrollMode.AUTO,
    )
    # Reported, not hidden: a chart whose axis does not start at zero has to be
    # able to say so, or it is just a nicer-looking lie.
    chart.chart_floor = floor
    return chart


def axis_note(chart: ft.Control) -> str | None:
    """ "Scale starts at 82 kg" — or None when the chart starts at zero.

    Small helper rather than each caller reaching for `chart_floor`: the note
    is the other half of `baseline="auto"`, and the half that gets forgotten.
    """
    floor = getattr(chart, "chart_floor", 0.0) or 0.0
    if floor <= 0:
        return None
    # One decimal, trailing zeros dropped: the floor is a computed number and
    # "81.67" in a caption reads like a measurement rather than an axis label.
    texto = f"{floor:.1f}".rstrip("0").rstrip(".")
    return f"Scale starts at {texto}, not 0"
