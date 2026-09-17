"""Every dialog in the app, built at a real window width, with nothing pinned.

This is the regression test for the bug that shipped four times: a dialog sized
around "the phone is 420 px wide", with its paragraphs pinned to `width=320`
inside it. On the device the app is actually used on, the box came out narrower
than the guess and the text was cut off mid-sentence — the RIR scale read "That
is failure — mark the set" with the rest gone, the exercise how-to lost its last
steps, and the guide cards ran past their own border.

The rule it enforces is blunt on purpose, because a subtler one is what let the
bug back in: **inside a dialog, nothing that holds prose may declare a width.**
Small fixed widths are fine and necessary — a badge, a gutter, an icon's tap
target — so anything up to `MAX_PINNED_W` passes. Above that, a control is wide
enough to be holding text, and it must be elastic (`expand=True`, or nothing at
all, letting the STRETCH Column hand it the real width).

`float("inf")` is explicitly allowed: in Flet that means "fill the parent",
which is the opposite of the bug.

360 px is the width the audit asked for — a common Android logical width, and
narrower than the 420 px every one of these dialogs was designed against.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import flet as ft
import pytest

from guides import guide_ids
from theme import LIGHT, set_palette
from views.exercise_dialog import build_exercise_detail
from views.guide_dialog import build_guide_dialog
from views.help_dialog import (
    METRIC_TOPICS,
    TOPIC_RIR,
    TOPIC_TYPE,
    build_metric_help_dialog,
    build_set_help_dialog,
)
from views.shared_ui import DIALOG_CHROME_H, DIALOG_MARGIN, dialog_width

#: The window the audit named. Every dialog below is built against it.
NARROW_W = 360
NARROW_H = 740

#: The widest a pinned width may be before it counts as "this is holding text".
#: The real pinned widths left in the app are a 26 px type badge, a 38 px RIR
#: badge, a 58 px trophy gutter and a 30 px `?` target.
MAX_PINNED_W = 80


@pytest.fixture(autouse=True)
def light_palette():
    set_palette(LIGHT)
    yield
    set_palette(LIGHT)


@pytest.fixture
def page():
    """A page that reports a real, narrow window."""
    p = MagicMock()
    p.width = NARROW_W
    p.height = NARROW_H
    return p


def walk(node, seen=None):
    """Every control in the tree, once."""
    seen = seen if seen is not None else set()
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item, seen)
        return
    yield node
    for attr in ("content", "controls", "actions", "title"):
        yield from walk(getattr(node, attr, None), seen)


def describe(control) -> str:
    """Enough of a control to find it in the source when this test fails."""
    value = getattr(control, "value", None)
    if isinstance(value, str) and value:
        return f"{type(control).__name__}({value[:60]!r})"
    return type(control).__name__


def pinned_widths(dialog) -> list[tuple[str, float]]:
    """Every fixed width inside the dialog's *body*, ignoring the body itself.

    The body container is supposed to carry a width — that is the whole point
    of `dialog_width`. Everything under it is not.
    """
    body = dialog.content
    offenders = []
    for control in walk(body.content):
        width = getattr(control, "width", None)
        if not isinstance(width, (int, float)) or isinstance(width, bool):
            continue
        if math.isinf(width):  # Flet's "fill the parent" — the opposite of the bug
            continue
        offenders.append((describe(control), float(width)))
    return offenders


def all_dialogs(page) -> list[tuple[str, ft.AlertDialog]]:
    """Every dialog this app can put on screen, named for the failure message.

    Deliberately built from the real data — every guide, every metric topic, an
    exercise that actually has a how-to — rather than from one happy sample:
    the exercise dialog only overflowed on the exercises with long instructions.
    """
    dialogs: list[tuple[str, ft.AlertDialog]] = [
        ("set help (both)", build_set_help_dialog(page)),
        ("set help (type)", build_set_help_dialog(page, TOPIC_TYPE)),
        ("set help (rir)", build_set_help_dialog(page, TOPIC_RIR)),
        ("metric help (all)", build_metric_help_dialog(page)),
    ]
    dialogs += [
        (f"metric help ({topic})", build_metric_help_dialog(page, topic)) for topic in METRIC_TOPICS
    ]
    dialogs += [(f"guide ({gid})", build_guide_dialog(page, gid)) for gid in guide_ids()]
    key = _wordiest_exercise()
    dialogs.append((f"exercise detail ({key})", build_exercise_detail(page, key)))
    return dialogs


def _wordiest_exercise() -> str:
    """The exercise with the longest how-to — the one that overflowed first."""
    from exercise_details import details_for
    from exercise_images import EXERCISE_IMAGE

    best, best_len = None, -1
    for key in EXERCISE_IMAGE:
        det = details_for(key)
        if not det:
            continue
        length = len("".join(det.get("instructions") or []))
        if length > best_len:
            best, best_len = key, length
    assert best, "no exercise carries instructions — the fixture is wrong, not the code"
    return best


# ── the actual guard ────────────────────────────────────────────────────


def test_every_dialog_exists_at_a_narrow_width(page):
    """A smoke check, so a build failure below is not mistaken for a layout one."""
    for name, dialog in all_dialogs(page):
        assert isinstance(dialog, ft.AlertDialog), name


def test_no_dialog_pins_a_width_to_its_text(page):
    for name, dialog in all_dialogs(page):
        offenders = [(what, w) for what, w in pinned_widths(dialog) if w > MAX_PINNED_W]
        assert not offenders, (
            f"{name}: these carry a fixed width wide enough to be holding text, "
            f"so they will clip on a narrower window — use expand=True or no "
            f"width at all: {offenders}"
        )


def test_every_dialog_fits_the_window_it_was_built_for(page):
    """The box itself: as wide as the window allows, never wider."""
    expected = NARROW_W - DIALOG_MARGIN
    for name, dialog in all_dialogs(page):
        box = dialog.content
        assert box.width == expected, f"{name} is {box.width} px on a {NARROW_W} px window"
        if box.height is not None:
            assert box.height <= NARROW_H - DIALOG_CHROME_H, (
                f"{name} is {box.height} px tall on a {NARROW_H} px window — its "
                f"Close button lands below the fold"
            )


def test_dialogs_grow_with_the_window(page):
    """The other half of elastic: a desktop window must not keep the phone box."""
    wide = MagicMock()
    wide.width = 1280
    wide.height = 900
    for name, dialog in all_dialogs(wide):
        assert dialog.content.width == dialog_width(wide), name
        assert dialog.content.width > NARROW_W - DIALOG_MARGIN, name


def test_scrolling_dialogs_still_have_a_bounded_box(page):
    """A scrolling Column inside an unbounded Container does not scroll."""
    for name, dialog in all_dialogs(page):
        body = dialog.content.content
        if getattr(body, "scroll", None):
            assert dialog.content.height is not None, f"{name} scrolls with no bounded height"


def test_dialog_bodies_stretch_their_children(page):
    """STRETCH is what lets the cards inside be width-less.

    Without it a Column shrink-wraps, and every panel comes out as narrow as its
    shortest line — which looks like a different bug and gets "fixed" by pinning
    a width again.
    """
    for name, dialog in all_dialogs(page):
        body = dialog.content.content
        if isinstance(body, ft.Column):
            assert body.horizontal_alignment == ft.CrossAxisAlignment.STRETCH, name


def test_the_start_date_dialog_is_elastic_too(page):
    """Plan's dialog is opened, not returned, so it is checked through `page.open`."""
    from views.plan import open_start_date_dialog

    store = MagicMock()
    store.get_pref.return_value = None
    open_start_date_dialog(page, store)
    page.open.assert_called_once()
    dialog = page.open.call_args[0][0]
    assert dialog.content.width == NARROW_W - DIALOG_MARGIN
    offenders = [(w, v) for w, v in pinned_widths(dialog) if v > MAX_PINNED_W]
    assert not offenders, offenders
