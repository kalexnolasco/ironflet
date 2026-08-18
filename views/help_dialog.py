"""The legend for the two cryptic columns of the set table: TYPE and RIR.

The training screen shows a single letter under TYPE (`N` / `W` / `D` / `F`)
and a bare number under RIR, and nothing on screen says what either means.
Whoever did not build the table cannot know that a `W` quietly removes the set
from volume and from records, and RIR is the most commonly inverted concept in
the gym — *reps in reserve* is what you left, not what you did.

Three shapes, so the training view spends one line on this:

* `help_icon(page, topic)` — the tappable `?` to drop next to a column header.
  Defaults to 30 px so it lands exactly in the header row's trailing slot.
* `open_set_help(page, topic)` — opens the dialog from anywhere else.
* `build_set_help_dialog(page, topic)` — the dialog itself, so tests can build
  it without a running app.

Two rules this file obeys, both of them things that broke before:

* **No colour is stored at module level.** A `dict` of `C.accent` written up
  here would freeze whichever palette was active at import time, exactly like
  the deleted `theme` aliases did; badge colours are resolved inside
  `_badge_color()` at render time.
* **No number is retyped.** The letters come from `SHORT_LABELS`, the cycle
  order from `CYCLE_ORDER` and the rest times from the `REST_*` constants, so
  the help cannot drift away from the behaviour it describes.
"""

from __future__ import annotations

import flet as ft

from set_types import (
    CYCLE_ORDER,
    LABELS,
    REST_AFTER_WARMUP_S,
    REST_COMPOUND_S,
    REST_ISOLATION_S,
    SHORT_LABELS,
    SetType,
    format_rest,
    help_for,
)
from theme import C

# Which half of the legend to show. `None` shows both, which is what a single
# `?` in the header should do.
TOPIC_TYPE = "type"
TOPIC_RIR = "rir"

TYPE_HEADING = "TYPE — what kind of set"
RIR_HEADING = "RIR — reps in reserve"

#: The one sentence that fixes the usual misreading. Kept first and kept blunt.
RIR_LEAD = "How many more reps you could have done — not how many you did."

RIR_EXAMPLE = (
    "You rack the bar at 10 reps and two clean reps were still in you: "
    "reps 10, RIR 2. If a single extra rep was not there, that is RIR 0."
)

#: The scale, as (value, meaning). Four rows is the most that stays readable on
#: a phone held between sets; anything finer is guesswork anyway.
RIR_SCALE: tuple[tuple[str, str], ...] = (
    ("0", "Nothing left. That is failure — mark the set F."),
    ("1–2", "Where working sets should land. The growth zone."),
    ("3–4", "Comfortable. Fine early in a block or on technique days."),
    ("5+", "That is a warm-up, not a working set."),
)

RIR_FOOTER = "Optional: leave it blank and nothing is stored."

# Layout constants. The phone is 420 px wide and every other dialog in the app
# is 340 px, so this one is too. The height is fixed because the body scrolls,
# and a scrolling Column needs a bounded box to scroll inside.
_DIALOG_W = 340
_BODY_W = 320
_HEIGHT_BOTH = 520
_HEIGHT_ONE = 380


def _badge_color(set_type: SetType) -> str:
    """Badge background for one type — resolved on every call, never cached.

    The mapping is semantic, not decorative: the accent is the default work
    set, warning marks the one type that does *not* count, and danger marks
    the one that costs recovery.
    """
    return {
        SetType.NORMAL: C.accent,
        SetType.WARMUP: C.warning,
        SetType.DROPSET: C.accent_2,
        SetType.FAILURE: C.danger,
    }[set_type]


def _badge(text: str, bg: str, width: int = 26) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            text,
            size=12,
            color=C.on_accent,
            weight=ft.FontWeight.W_900,
            text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=bg,
        border_radius=6,
        width=width,
        height=22,
        alignment=ft.alignment.center,
    )


def _type_card(set_type: SetType) -> ft.Container:
    entry = help_for(set_type)
    color = _badge_color(set_type)
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        _badge(SHORT_LABELS[set_type], color),
                        ft.Text(
                            LABELS[set_type],
                            size=13,
                            color=C.text,
                            weight=ft.FontWeight.W_800,
                        ),
                    ],
                    spacing=8,
                    tight=True,
                ),
                ft.Text(entry.what, size=11, color=C.text_secondary, width=_BODY_W - 24),
                # The consequence carries the badge colour: it is the line that
                # tells you what the letter does to your numbers, and on a
                # warm-up it is the only warning that the set will not count.
                ft.Text(
                    entry.consequence,
                    size=11,
                    color=color,
                    weight=ft.FontWeight.W_700,
                    width=_BODY_W - 24,
                ),
            ],
            spacing=5,
            tight=True,
        ),
        bgcolor=C.bg_page,
        border=ft.border.all(1, C.border),
        border_radius=10,
        padding=10,
        width=_BODY_W,
    )


def _cycle_hint() -> ft.Text:
    """ "Tap the letter to cycle N → W → D → F", spelled from `CYCLE_ORDER`."""
    order = " → ".join(SHORT_LABELS[t] for t in CYCLE_ORDER)
    return ft.Text(
        f"Tap the letter in the TYPE column to cycle {order}.",
        size=11,
        color=C.text_muted,
        italic=True,
        width=_BODY_W,
    )


def _rest_hint() -> ft.Text:
    """The rest consequence, read off the constants instead of retyped."""
    working = f"{format_rest(REST_ISOLATION_S)}–{format_rest(REST_COMPOUND_S)}"
    return ft.Text(
        f"Rest timer: {format_rest(REST_AFTER_WARMUP_S)} after a warm-up, "
        f"{working} after a working set.",
        size=11,
        color=C.text_muted,
        italic=True,
        width=_BODY_W,
    )


def _heading(text: str) -> ft.Text:
    return ft.Text(text, size=13, color=C.accent, weight=ft.FontWeight.W_900)


def _rir_row(value: str, meaning: str) -> ft.Row:
    # Colour walks the scale the way the advice does: 0 is failure, 1–2 is the
    # target, and by 5 you are warming up.
    tone = {
        "0": C.danger,
        "1–2": C.success,
        "3–4": C.warning,
        "5+": C.text_muted,
    }.get(value, C.text_secondary)
    return ft.Row(
        [
            _badge(value, tone, width=38),
            ft.Text(meaning, size=11, color=C.text_secondary, width=_BODY_W - 52),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _rir_block() -> list[ft.Control]:
    return [
        _heading(RIR_HEADING),
        ft.Text(RIR_LEAD, size=12, color=C.text, weight=ft.FontWeight.W_700, width=_BODY_W),
        ft.Container(
            content=ft.Text(RIR_EXAMPLE, size=11, color=C.text_secondary, width=_BODY_W - 24),
            bgcolor=C.bg_page,
            border=ft.border.all(1, C.border),
            border_radius=10,
            padding=10,
            width=_BODY_W,
        ),
        *[_rir_row(value, meaning) for value, meaning in RIR_SCALE],
        ft.Text(RIR_FOOTER, size=11, color=C.text_muted, italic=True, width=_BODY_W),
    ]


def _type_block() -> list[ft.Control]:
    return [
        _heading(TYPE_HEADING),
        *[_type_card(t) for t in CYCLE_ORDER],
        _cycle_hint(),
        _rest_hint(),
    ]


def _title_for(topic: str | None) -> str:
    if topic == TOPIC_TYPE:
        return "Set types"
    if topic == TOPIC_RIR:
        return "RIR"
    return "Set types & RIR"


def build_set_help_dialog(page, topic: str | None = None) -> ft.AlertDialog:
    """The legend as an `AlertDialog`, without opening it.

    `topic` selects one half (`TOPIC_TYPE` / `TOPIC_RIR`) so a `?` sitting on a
    column header can answer about that column only; anything else — including
    `None` — shows both. Unknown strings fall back to both on purpose: this is
    help, and showing too much beats showing an empty dialog.

    `page` is only used to close the dialog, so it is not annotated as
    `ft.Page`: any object with `.close()` works, which is what lets the tests
    build this with a stub.
    """
    body: list[ft.Control] = []
    if topic != TOPIC_RIR:
        body += _type_block()
    if topic != TOPIC_TYPE:
        if body:
            body.append(ft.Divider(height=16, color=C.border))
        body += _rir_block()

    content = ft.Column(body, scroll=ft.ScrollMode.AUTO, spacing=8, width=_DIALOG_W)
    height = _HEIGHT_ONE if topic in (TOPIC_TYPE, TOPIC_RIR) else _HEIGHT_BOTH

    dialog = ft.AlertDialog(
        # Not modal: it opens mid-session, and a stray tap outside must give
        # Alex his sets back rather than trap him behind a help screen.
        modal=False,
        bgcolor=C.bg_surface,
        title=ft.Text(_title_for(topic), size=18, weight=ft.FontWeight.W_900, color=C.text),
        content=ft.Container(
            content=content,
            width=_DIALOG_W,
            height=height,
            alignment=ft.alignment.top_left,
        ),
        actions=[
            ft.TextButton(
                "Got it",
                on_click=lambda _: page.close(dialog),
                style=ft.ButtonStyle(color=C.accent),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dialog


def open_set_help(page, topic: str | None = None) -> None:
    """One call: build the legend and show it."""
    page.open(build_set_help_dialog(page, topic))


def help_icon(page, topic: str | None = None, size: int = 30) -> ft.Container:
    """The `?` to sit next to a column header.

    Default width is 30 px because that is the width of the trailing slot in
    the set table's header row — dropping this in place of that empty spacer
    costs no horizontal space on a 420 px phone.
    """
    tooltip = {
        TOPIC_TYPE: "What do N, W, D and F mean?",
        TOPIC_RIR: "What is RIR?",
    }.get(topic, "What do TYPE and RIR mean?")
    return ft.Container(
        content=ft.Icon(ft.Icons.HELP_OUTLINE, size=15, color=C.text_muted),
        width=size,
        alignment=ft.alignment.center,
        on_click=lambda _: open_set_help(page, topic),
        tooltip=tooltip,
        ink=True,
        border_radius=999,
    )
