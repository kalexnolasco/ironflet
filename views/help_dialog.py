"""The legend for everything on screen that is a letter or a bare number.

Two families of help live here, and they are one file because they are one
pattern — a `?` you can hit with a thumb, a non-modal dialog, and prose that is
read off the constants it describes rather than retyped next to them.

**Set types and RIR.** The training screen shows a single letter under TYPE
(`N` / `W` / `D` / `F`) and a bare number under RIR, and nothing on screen says
what either means. Whoever did not build the table cannot know that a `W`
quietly removes the set from volume and from records, and RIR is the most
commonly inverted concept in the gym — *reps in reserve* is what you left, not
what you did.

* `help_icon(page, topic)` — the tappable `?` to drop next to a column header.
  Defaults to 30 px so it lands exactly in the header row's trailing slot.
* `open_set_help(page, topic)` / `build_set_help_dialog(page, topic)`.

**The metrics.** History and Home print `est. 1RM`, `🏆 vol` and `12.3k` with no
unit and no definition anywhere on the screen. Same treatment, same shapes:

* `metric_help_icon(page, topic)` — the `?` for a section heading.
* `open_metric_help(page, topic)` / `build_metric_help_dialog(page, topic)`.
* `METRIC_HELP` — the glossary as data, so a test can assert every metric the
  views print has an entry.

Three rules this file obeys, all of them things that broke before:

* **No colour is stored at module level.** A `dict` of `C.accent` written up
  here would freeze whichever palette was active at import time, exactly like
  the deleted `theme` aliases did; badge colours are resolved inside
  `_badge_color()` at render time.
* **No number is retyped.** The letters come from `SHORT_LABELS`, the cycle
  order from `CYCLE_ORDER` and the rest times from the `REST_*` constants, so
  the help cannot drift away from the behaviour it describes.
* **No width is pinned.** Sizes come from `shared_ui.dialog_width/height`,
  which read the real window. The old `_DIALOG_W = 340` was a guess about the
  phone and it clipped the scale rows on the device it was guessing about.
"""

from __future__ import annotations

from typing import NamedTuple

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
from views.shared_ui import dialog_height, dialog_width

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

# How tall the body would *like* to be. `dialog_height()` cuts it down to what
# the window actually has, so these are ceilings rather than sizes: the body
# scrolls, and a scrolling Column still needs a bounded box to scroll inside.
_HEIGHT_BOTH = 520
_HEIGHT_ONE = 380
_HEIGHT_METRICS = 520
_HEIGHT_METRIC_ONE = 340


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


def _panel(*children: ft.Control) -> ft.Container:
    """The bordered box the dialogs build every explanation out of.

    No width: it takes the width of the body Column, which takes it from the
    window. A `width=` here is the whole bug this file was rewritten for.
    """
    return ft.Container(
        content=ft.Column(list(children), spacing=5, tight=True),
        bgcolor=C.bg_page,
        border=ft.border.all(1, C.border),
        border_radius=10,
        padding=10,
    )


def _body_text(text: str, color: str | None = None, **kw) -> ft.Text:
    """A wrapping line of dialog prose. `expand` where it sits in a Row."""
    return ft.Text(text, size=11, color=color or C.text_secondary, **kw)


def _type_card(set_type: SetType) -> ft.Container:
    entry = help_for(set_type)
    color = _badge_color(set_type)
    return _panel(
        ft.Row(
            [
                _badge(SHORT_LABELS[set_type], color),
                # `expand`, not a fixed width: a long label must wrap inside
                # whatever the row has, not run off the edge of the card.
                ft.Text(
                    LABELS[set_type],
                    size=13,
                    color=C.text,
                    weight=ft.FontWeight.W_800,
                    expand=True,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        _body_text(entry.what),
        # The consequence carries the badge colour: it is the line that tells
        # you what the letter does to your numbers, and on a warm-up it is the
        # only warning that the set will not count.
        _body_text(entry.consequence, color=color, weight=ft.FontWeight.W_700),
    )


def _cycle_hint() -> ft.Text:
    """ "Tap the letter to cycle N → W → D → F", spelled from `CYCLE_ORDER`."""
    order = " → ".join(SHORT_LABELS[t] for t in CYCLE_ORDER)
    return ft.Text(
        f"Tap the letter in the TYPE column to cycle {order}.",
        size=11,
        color=C.text_muted,
        italic=True,
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
            # `expand`, never a computed width: a constant is a guess about how
            # wide the dialog will be, and on a 1080px phone it guessed high —
            # the scale rows read "That is failure — mark the set" with the rest
            # clipped off. Let the Row divide its real width instead. Every
            # other body line in this file now follows the same rule.
            ft.Text(meaning, size=11, color=C.text_secondary, expand=True),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _rir_block() -> list[ft.Control]:
    return [
        _heading(RIR_HEADING),
        ft.Text(RIR_LEAD, size=12, color=C.text, weight=ft.FontWeight.W_700),
        _panel(_body_text(RIR_EXAMPLE)),
        *[_rir_row(value, meaning) for value, meaning in RIR_SCALE],
        ft.Text(RIR_FOOTER, size=11, color=C.text_muted, italic=True),
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


def help_dialog(
    page, title: str, body: list[ft.Control], preferred_height: int, close_label: str = "Got it"
) -> ft.AlertDialog:
    """The shell every help dialog in the app is built from.

    One place decides the geometry, so no caller can go back to pinning 340 px:
    the width comes from the real window and the height is a *ceiling* the
    window may cut down. `STRETCH` is what lets the panels inside be
    width-less — without it a Column shrink-wraps its children and every card
    comes out as narrow as its shortest line.

    `page` is only used for sizing and to close the dialog, so it is not
    annotated as `ft.Page`: anything with `.width`, `.height` and `.close()`
    works, which is what lets the tests build these with a stub.
    """
    width = dialog_width(page)
    content = ft.Column(
        body,
        scroll=ft.ScrollMode.AUTO,
        spacing=8,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    dialog = ft.AlertDialog(
        # Not modal: it opens mid-session, and a stray tap outside must give
        # Alex his sets back rather than trap him behind a help screen.
        modal=False,
        bgcolor=C.bg_surface,
        title=ft.Text(title, size=18, weight=ft.FontWeight.W_900, color=C.text),
        content=ft.Container(
            content=content,
            width=width,
            height=dialog_height(page, preferred_height),
            alignment=ft.alignment.top_left,
        ),
        actions=[
            ft.TextButton(
                close_label,
                on_click=lambda _: page.close(dialog),
                style=ft.ButtonStyle(color=C.accent),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dialog


def build_set_help_dialog(page, topic: str | None = None) -> ft.AlertDialog:
    """The legend as an `AlertDialog`, without opening it.

    `topic` selects one half (`TOPIC_TYPE` / `TOPIC_RIR`) so a `?` sitting on a
    column header can answer about that column only; anything else — including
    `None` — shows both. Unknown strings fall back to both on purpose: this is
    help, and showing too much beats showing an empty dialog.
    """
    body: list[ft.Control] = []
    if topic != TOPIC_RIR:
        body += _type_block()
    if topic != TOPIC_TYPE:
        if body:
            body.append(ft.Divider(height=16, color=C.border))
        body += _rir_block()

    height = _HEIGHT_ONE if topic in (TOPIC_TYPE, TOPIC_RIR) else _HEIGHT_BOTH
    return help_dialog(page, _title_for(topic), body, height)


def open_set_help(page, topic: str | None = None) -> None:
    """One call: build the legend and show it."""
    page.open(build_set_help_dialog(page, topic))


def _question_mark(on_click, tooltip: str, size: int) -> ft.Container:
    """The tappable `?`. Round, inked, and a real target for a wet thumb."""
    return ft.Container(
        content=ft.Icon(ft.Icons.HELP_OUTLINE, size=15, color=C.text_muted),
        width=size,
        height=size,
        alignment=ft.alignment.center,
        on_click=on_click,
        tooltip=tooltip,
        ink=True,
        border_radius=999,
    )


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
    return _question_mark(lambda _: open_set_help(page, topic), tooltip, size)


# ── the metrics glossary ────────────────────────────────────────────────
#
# Everything History and Home print as a number with no unit and no definition.
# Alex asked for this once already, for N/W/D/F and RIR; these are the same
# question asked about the other half of the app. The rule the entries follow:
# say what the number *is* in one sentence, then say the thing that makes it
# easy to misread.

TOPIC_E1RM = "e1rm"
TOPIC_RECORDS = "records"
TOPIC_VOLUME = "volume"
TOPIC_MUSCLE = "muscle"

#: Every metric the views print without spelling it out. Ordered as the eye
#: meets them: the big number on the list, the trophies on a session, the
#: shortened total, then the muscle card.
METRIC_TOPICS: tuple[str, ...] = (TOPIC_E1RM, TOPIC_RECORDS, TOPIC_VOLUME, TOPIC_MUSCLE)


class MetricHelp(NamedTuple):
    """One glossary entry.

    `rows` is for entries whose whole point is a set of cryptic short labels —
    the three trophies — rendered as badge-and-meaning the way `RIR_SCALE` is.
    """

    heading: str
    lead: str
    detail: str
    rows: tuple[tuple[str, str], ...] = ()


METRIC_HELP: dict[str, MetricHelp] = {
    TOPIC_E1RM: MetricHelp(
        heading="est. 1RM — estimated one-rep max",
        lead="The weight the app works out you could lift once, in kilos. You have not lifted it.",
        detail=(
            "It is estimated from your best set — weight × (1 + reps ÷ 30) — so it goes up "
            "when you add reps, not only when you add plates. That is what makes it the "
            "fairest way to compare a 5×5 day against a 3×12 day. Read the trend; do not "
            "go and attempt the number."
        ),
    ),
    TOPIC_RECORDS: MetricHelp(
        heading="🏆 — this session still holds a record",
        lead="A trophy marks a session that is still your best ever for this exercise.",
        detail="Warm-up sets count towards none of the three.",
        rows=(
            ("🏆 1RM", "Best estimated 1RM — your best weight-and-reps combination."),
            ("🏆 kg", "Heaviest single set, whatever the reps were."),
            ("🏆 vol", "Biggest session total: every working set's weight × reps, added up."),
        ),
    ),
    TOPIC_VOLUME: MetricHelp(
        heading="Volume, and the k",
        lead="Volume is weight × reps added up over your working sets, and it is always kilos.",
        detail=(
            "Totals past 10,000 are shortened so they fit a tile: 12.3k means 12,300 kg. "
            "The full figure is in the tooltip if you hover or long-press."
        ),
    ),
    TOPIC_MUSCLE: MetricHelp(
        heading="Weekly sets by muscle",
        lead=(
            "How many working sets each muscle got that week — the number that says whether "
            "a muscle is getting enough work, or too much."
        ),
        detail=(
            "An exercise gives a whole set to the muscle it trains directly and half a set to "
            "each muscle that only assists. Some exercises have no muscle data at all, so "
            "their sets belong to nothing; the card says how many rather than quietly "
            "dropping them, which is what the warning line underneath is counting."
        ),
    ),
}

METRICS_TITLE = "What these numbers mean"


def _metric_block(topic: str) -> list[ft.Control]:
    entry = METRIC_HELP[topic]
    rows: list[ft.Control] = [
        ft.Row(
            [
                # A narrow gutter so the three meanings line up, and small
                # enough that it cannot be the thing that overflows a 280 px
                # dialog. It wraps rather than clips if a badge ever grows.
                ft.Text(badge, size=11, color=C.success, weight=ft.FontWeight.W_900, width=58),
                _body_text(meaning, expand=True),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        for badge, meaning in entry.rows
    ]
    return [
        _heading(entry.heading),
        ft.Text(entry.lead, size=12, color=C.text, weight=ft.FontWeight.W_700),
        _panel(_body_text(entry.detail), *rows),
    ]


def _metric_title_for(topic: str | None) -> str:
    entry = METRIC_HELP.get(topic or "")
    return entry.heading if entry else METRICS_TITLE


def build_metric_help_dialog(page, topic: str | None = None) -> ft.AlertDialog:
    """The glossary as an `AlertDialog`, without opening it.

    `topic` picks one entry so a `?` on a section heading answers about that
    section; anything unknown — including `None` — shows all of them, for the
    same reason the set legend does: help that renders empty is worse than help
    that renders long.
    """
    known = topic if topic in METRIC_HELP else None
    topics = (known,) if known else METRIC_TOPICS

    body: list[ft.Control] = []
    for entry_topic in topics:
        if body:
            body.append(ft.Divider(height=16, color=C.border))
        body += _metric_block(entry_topic)

    height = _HEIGHT_METRIC_ONE if known else _HEIGHT_METRICS
    return help_dialog(page, _metric_title_for(known), body, height)


def open_metric_help(page, topic: str | None = None) -> None:
    """One call: build the glossary and show it."""
    page.open(build_metric_help_dialog(page, topic))


def metric_help_icon(page, topic: str | None = None, size: int = 26) -> ft.Container:
    """The `?` for a section heading in History or Home.

    Smaller than `help_icon` by default: it sits beside a title in flowing
    layout rather than in the set table's fixed 30 px slot.
    """
    entry = METRIC_HELP.get(topic or "")
    tooltip = f"What is {entry.heading.split('—')[0].strip()}?" if entry else METRICS_TITLE
    return _question_mark(lambda _: open_metric_help(page, topic), tooltip, size)
