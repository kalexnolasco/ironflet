"""Guards for the TYPE/RIR legend.

Help text is the kind of code that rots without anyone noticing: a new
`SetType` ships with no explanation, the cycle order changes and the hint still
names the old one, or someone writes a hex into the dialog and it stops
following the palette. Everything below is a check that the legend keeps
matching the behaviour it describes.

No database and no running app: `set_types` is pure data and the dialog only
needs an object with `.close()`, so this file runs in milliseconds.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import flet as ft
import pytest

import views.help_dialog as help_dialog
from set_types import (
    CYCLE_ORDER,
    HELP,
    SHORT_LABELS,
    SetType,
    SetTypeHelp,
    help_for,
)
from theme import DARK, LIGHT, C, set_palette
from views.help_dialog import (
    RIR_LEAD,
    RIR_SCALE,
    TOPIC_RIR,
    TOPIC_TYPE,
    _badge_color,
    build_set_help_dialog,
    help_icon,
    open_set_help,
)

MODULE_PATH = Path(help_dialog.__file__)


@pytest.fixture
def page():
    return MagicMock()


@pytest.fixture(autouse=True)
def light_palette():
    """Every test starts on the default palette and leaves it that way."""
    set_palette(LIGHT)
    yield
    set_palette(LIGHT)


def texts(control) -> list[str]:
    """Every string rendered anywhere under `control`.

    Walks the tree generically instead of reaching into a known layout, so
    rearranging the dialog does not break these assertions — only removing
    content does.
    """
    found: list[str] = []
    seen: set[int] = set()

    def walk(node) -> None:
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if isinstance(node, ft.Text) and isinstance(node.value, str):
            found.append(node.value)
        for attr in ("content", "controls", "actions", "title", "spans"):
            walk(getattr(node, attr, None))

    walk(control)
    return found


# ── the legend is total and says something ──────────────────────────────


def test_every_set_type_has_help():
    """A new member of the enum cannot ship without its explanation."""
    assert set(HELP) == set(SetType)


@pytest.mark.parametrize("set_type", list(SetType))
def test_help_entries_are_real_prose(set_type):
    entry = HELP[set_type]
    assert isinstance(entry, SetTypeHelp)
    for field in (entry.what, entry.consequence):
        assert field.strip()
        assert len(field) > 30  # a stub like "TODO" or "Warm-up." would pass a truthy check
        # Written for a phone between sets: two short lines, not a paragraph.
        assert len(field) < 160


def test_help_texts_are_all_different():
    """Copy-pasted entries are worse than none: they teach the wrong thing."""
    lines = [e.what for e in HELP.values()] + [e.consequence for e in HELP.values()]
    assert len(set(lines)) == len(lines)


def test_only_the_warmup_says_it_does_not_count():
    """The one fact the UI hides. If this wording drifts, the help is wrong."""
    assert "not counted" in HELP[SetType.WARMUP].consequence.lower()
    for set_type in (SetType.NORMAL, SetType.DROPSET, SetType.FAILURE):
        consequence = HELP[set_type].consequence.lower()
        assert "counts" in consequence
        assert "not counted" not in consequence


def test_help_for_is_as_forgiving_as_parse_set_type():
    """Rows written by the bot carry no type at all; unknown strings happen."""
    assert help_for(None) is HELP[SetType.NORMAL]
    assert help_for("nonsense") is HELP[SetType.NORMAL]
    assert help_for("warm-up") is HELP[SetType.WARMUP]  # alias spelling
    assert help_for(SetType.FAILURE) is HELP[SetType.FAILURE]
    assert help_for("amrap") is HELP[SetType.FAILURE]


# ── the RIR half ────────────────────────────────────────────────────────


def test_rir_lead_corrects_the_usual_inversion():
    """RIR 2 means two reps left, not two reps done — say so explicitly."""
    lead = RIR_LEAD.lower()
    assert "could have done" in lead
    assert "not how many you did" in lead


def test_rir_scale_is_complete_and_ordered():
    values = [value for value, _ in RIR_SCALE]
    assert values == ["0", "1–2", "3–4", "5+"]
    for _value, meaning in RIR_SCALE:
        assert meaning.strip()
        assert len(meaning) > 20


# ── the dialog ──────────────────────────────────────────────────────────


def test_dialog_builds_with_both_sections(page):
    dialog = build_set_help_dialog(page)
    assert isinstance(dialog, ft.AlertDialog)
    assert dialog.title.value.strip()
    # A tap outside must return Alex to his sets, not trap him behind help.
    assert dialog.modal is False

    rendered = " | ".join(texts(dialog))
    for set_type in SetType:
        assert SHORT_LABELS[set_type] in texts(dialog)  # the badge letter itself
        assert HELP[set_type].what in rendered
        assert HELP[set_type].consequence in rendered
    assert RIR_LEAD in rendered


def test_cycle_hint_is_spelled_from_the_cycle_order(page):
    """The hint must name the order the badge actually walks."""
    expected = " → ".join(SHORT_LABELS[t] for t in CYCLE_ORDER)
    assert any(expected in line for line in texts(build_set_help_dialog(page)))


def test_rest_hint_quotes_the_real_constants(page):
    """`1:00 after a warm-up, 1:30–3:00 after a working set` — from set_types."""
    rendered = " | ".join(texts(build_set_help_dialog(page)))
    assert "1:00" in rendered and "1:30" in rendered and "3:00" in rendered


def test_topic_type_shows_only_the_letters(page):
    rendered = " | ".join(texts(build_set_help_dialog(page, TOPIC_TYPE)))
    assert HELP[SetType.WARMUP].what in rendered
    assert RIR_LEAD not in rendered


def test_topic_rir_shows_only_rir(page):
    rendered = " | ".join(texts(build_set_help_dialog(page, TOPIC_RIR)))
    assert RIR_LEAD in rendered
    assert HELP[SetType.WARMUP].what not in rendered


def test_unknown_topic_falls_back_to_everything(page):
    """Help never renders empty: a bad argument shows more, not less."""
    rendered = " | ".join(texts(build_set_help_dialog(page, "typo")))
    assert RIR_LEAD in rendered
    assert HELP[SetType.WARMUP].what in rendered


def test_dialog_fits_the_phone(page):
    """420 px screen: the dialog matches the other dialogs at 340 px."""
    container = build_set_help_dialog(page).content
    assert container.width == 340
    assert container.height is not None  # a scrolling Column needs a bounded box


def test_close_button_closes_the_dialog(page):
    dialog = build_set_help_dialog(page)
    close = dialog.actions[0]
    close.on_click(None)
    page.close.assert_called_once_with(dialog)


def test_open_set_help_opens_one_dialog(page):
    open_set_help(page, TOPIC_RIR)
    page.open.assert_called_once()
    assert isinstance(page.open.call_args[0][0], ft.AlertDialog)


# ── the entry point the training screen uses ─────────────────────────────


def test_help_icon_fits_the_header_slot_and_opens_the_dialog(page):
    icon = help_icon(page)
    # 30 px is the trailing slot of the set table's header row.
    assert icon.width == 30
    assert icon.tooltip
    icon.on_click(None)
    page.open.assert_called_once()


def test_help_icon_forwards_its_topic(page):
    help_icon(page, TOPIC_RIR).on_click(None)
    opened = page.open.call_args[0][0]
    rendered = " | ".join(texts(opened))
    assert RIR_LEAD in rendered
    assert HELP[SetType.WARMUP].what not in rendered


# ── theme rules ─────────────────────────────────────────────────────────


def test_badge_colours_follow_the_active_palette():
    """Resolved per call, never frozen at import — the deleted theme aliases
    are exactly the bug this prevents."""
    assert _badge_color(SetType.NORMAL) == LIGHT.accent
    set_palette(DARK)
    assert _badge_color(SetType.NORMAL) == DARK.accent
    assert _badge_color(SetType.WARMUP) == C.warning


def test_no_hardcoded_colour_in_the_module():
    """No view may write a hex value; every colour goes through `C`."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b", source)
