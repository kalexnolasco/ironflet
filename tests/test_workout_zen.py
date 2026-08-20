"""Guards for zen mode — the focused layout the exercise screen wears.

What Alex asked for has two halves and the second one bounds the first: while he
trains he wants nothing on screen but the training, **but** he must still be able
to walk out to Spotify. So the tests here are as much about what zen mode does
*not* do as about what it does. In particular `test_zen_is_only_a_layout` pins
the promise that this feature never asks the operating system for anything —
no foreground pinning, no immersive fullscreen, no swallowed back gesture.

None of this needs PostgreSQL. Zen mode reads and writes one preference and
renders controls, so a dict-backed fake covers it exactly and the whole file
runs in milliseconds even on a machine with no database.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import flet as ft
import pytest

from components.timer import DISPLAY_PT, DISPLAY_PT_LARGE, RING_PX, RING_PX_LARGE
from data import set_active_routine
from views.workout import ZEN_PREF, WorkoutView

# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    """The three `Storage` methods a `WorkoutView` reaches for on this path.

    `fail_get` / `fail_set` reproduce an unreachable database, which in web mode
    is a normal Tuesday: the app talks to PostgreSQL over the network.
    """

    def __init__(self, fail_get: bool = False, fail_set: bool = False):
        self.prefs: dict[str, str] = {}
        self.fail_get = fail_get
        self.fail_set = fail_set

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        if self.fail_get:
            raise RuntimeError("database unreachable")
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        if self.fail_set:
            raise RuntimeError("database unreachable")
        self.prefs[key] = value

    def get_last_sets(self, key: str, before=None):
        return [{"weight": 60.0, "reps": 10}, {"weight": 60.0, "reps": 8}]


@pytest.fixture
def page():
    p = MagicMock()
    p.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "set_routine": lambda r: None,
    }
    return p


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def view(page, store):
    """A view sitting on the first exercise of the first day, zen armed."""
    set_active_routine("cambiatufisico")
    page.data["store"] = store
    v = WorkoutView(page, store)
    v.phase_id = 1
    v._start_day(0)
    return v


# ── walking a built control tree ─────────────────────────────────────────


def _walk(control, seen=None):
    """Yield every control in a built tree.

    Flet has no traversal helper and the tree is heterogeneous — children hide
    under `content`, `controls`, `actions` and `title` depending on the widget —
    so this is the only honest way to assert on what a `build()` produced.
    """
    if seen is None:
        seen = set()
    if control is None or id(control) in seen:
        return
    seen.add(id(control))
    yield control
    for attr in ("content", "title", "leading", "trailing"):
        child = getattr(control, attr, None)
        if isinstance(child, ft.Control):
            yield from _walk(child, seen)
    for attr in ("controls", "actions"):
        children = getattr(control, attr, None)
        if isinstance(children, (list, tuple)):
            for child in children:
                if isinstance(child, ft.Control):
                    yield from _walk(child, seen)


def _texts(control) -> list[str]:
    return [c.value for c in _walk(control) if isinstance(c, ft.Text) and c.value]


def _tooltips(control) -> list[str]:
    return [t for c in _walk(control) if isinstance(t := getattr(c, "tooltip", None), str)]


def _images(control) -> list[ft.Control]:
    return [c for c in _walk(control) if isinstance(c, ft.Image)]


# ── entering and leaving ─────────────────────────────────────────────────


def test_starting_a_day_turns_zen_on_and_remembers_it(view, store):
    """'Al momento de poner una rutina se tendría que poner en modo ZEN.'"""
    assert view.zen is True
    assert store.prefs[ZEN_PREF] == "on"


def test_toggle_flips_it_and_writes_the_choice_down(view, store):
    view._toggle_zen()
    assert view.zen is False
    assert store.prefs[ZEN_PREF] == "off"
    view._toggle_zen()
    assert view.zen is True
    assert store.prefs[ZEN_PREF] == "on"


def test_resuming_the_same_workout_keeps_the_choice(view, store):
    """Stepping out to the day list and back is not a new workout.

    He turned zen off to look something up; coming back to the same session
    must not silently turn it on again under him.
    """
    view._toggle_zen()
    view.show_day_list = True
    view._resume_day()
    assert view.zen is False


def test_the_next_workout_starts_focused_again(view, store):
    """The opt-out lasts the session, not forever.

    Otherwise one peek at the food diary would cost him zen mode for good, and
    the thing he actually asked for would quietly stop happening.
    """
    view._toggle_zen()
    assert view.zen is False
    view._start_day(1)
    assert view.zen is True
    assert store.prefs[ZEN_PREF] == "on"


def test_a_restored_session_keeps_the_choice(page, store):
    """The crash path. Android kills the process mid-set; the draft brings the
    workout back, and it must bring the layout he was using back with it."""
    set_active_routine("cambiatufisico")
    page.data["store"] = store
    first = WorkoutView(page, store)
    first.phase_id = 1
    first._start_day(0)
    first._toggle_zen()  # zen off, and written down
    first._update_set(0, "weight", "62.5")
    first._persist_draft()

    revived = WorkoutView(page, store)
    revived.on_show()
    assert revived.day_idx == 0, "the draft did not restore — the rest proves nothing"
    assert revived.zen is False


# ── the navigation bar ───────────────────────────────────────────────────


def test_zen_hides_the_bottom_bar_on_the_exercise_screen(view):
    assert view.hides_nav() is True


@pytest.mark.parametrize(
    "field, value",
    [("show_day_list", True), ("show_phase_list", True), ("finished", True)],
)
def test_every_other_screen_keeps_the_bar(view, field, value):
    """Zen mode can never be a room with no door.

    Back leads to the day list, and the day list has the navigation bar. That
    is the escape hatch, and it is why `hides_nav` is deliberately narrow.
    """
    setattr(view, field, value)
    assert view.hides_nav() is False


def test_zen_off_keeps_the_bar(view):
    view._toggle_zen()
    assert view.hides_nav() is False


# ── what the screen shows ────────────────────────────────────────────────


def test_zen_drops_the_last_session_chips(view):
    """The last-session chips: useful when planning a workout, clutter at rep
    seven. The numbers are not lost — they are already prefilled into the
    fields as suggestions, which is where they get used."""
    zen_screen = view.build()
    assert "LAST SESSION" not in _texts(zen_screen)

    view._toggle_zen()
    normal_screen = view.build()
    assert "LAST SESSION" in _texts(normal_screen)


def test_zen_keeps_the_form_photo(view):
    """It used to be dropped here too, on the same reasoning as the chips.

    The reasoning was fine and the outcome was wrong: **zen is on by default**,
    so hiding the photo there meant it was never visible at all, and that is
    how Alex reported it — "en modo ZEN no muestra las imagenes". A reference
    the user says he wants during the set is not clutter.
    """
    assert _images(view.build()), "the exercise photo is invisible in the mode he trains in"


def test_zen_keeps_every_control_that_does_the_work(view):
    """Save, Finish, both arrows and the set fields survive the diet.

    Zen mode removes reference material, never function. If any of this ever
    disappears, logging a set becomes impossible in the mode Alex trains in.
    """
    screen = view.build()
    labels = _texts(screen)
    assert "Save" in labels
    assert any(label.startswith("Finish session") for label in labels)
    assert "Back" in labels
    assert any(isinstance(c, ft.TextField) for c in _walk(screen))


def test_the_way_out_of_zen_is_always_on_screen(view):
    """One tap, labelled, at 40 px — not a long-press or a settings screen."""
    for _ in range(2):
        screen = view.build()
        assert any("Zen mode" in t for t in _tooltips(screen))
        view._toggle_zen()


def test_zen_is_only_a_layout(view):
    """The half of the request that bounds the other half.

    'Lo que sí, puede que cambie de música.' Zen mode must never make leaving
    the app harder, so it is forbidden from touching anything the OS owns. This
    asserts the page was left alone: no fullscreen, no always-on-top, no
    prevent_close, and no keyboard handler stolen from `main.py`.
    """
    page = view.page
    view.build()
    view._toggle_zen()
    view.build()
    touched = {call[0] for call in page.method_calls}
    assert not any(
        name in touched for name in ("set_fullscreen", "window_to_front", "close_in_app_web_view")
    )
    for forbidden in ("prevent_close", "on_keyboard_event", "on_app_lifecycle_state_change"):
        assert forbidden not in page.__dict__, f"zen mode wrote page.{forbidden}"


# ── the line you read from a metre away ──────────────────────────────────


def test_next_set_hint_points_at_the_first_unclaimed_row(view):
    """The first unclaimed row, carrying last session's numbers.

    The total is read off the view rather than written in: how many rows an
    exercise opens with is `session_plan`'s answer now (the phase prescribes
    `3×12` here, last session logged two sets), and pinning the number in this
    file would be this test asserting something it is not about.
    """
    assert view._next_set_hint() == f"SET 1 OF {len(view.sets)} · 60 kg × 10"


def test_next_set_hint_advances_as_sets_are_confirmed(view):
    view._confirm_set(0)
    assert view._next_set_hint().startswith(f"SET 2 OF {len(view.sets)}")


def test_next_set_hint_stops_guessing_when_the_work_is_done(view):
    for i in range(len(view.sets)):
        view._confirm_set(i)
        # The plan can open more rows than last session had numbers for, and an
        # empty row is not claimable — typing in it is what claims it.
        view._update_set(i, "reps", "8")
    assert view._next_set_hint() == "ALL SETS IN — SAVE THIS EXERCISE"


def test_next_set_hint_says_nothing_it_does_not_know(view):
    """A first-ever exercise has no numbers to suggest, so it offers none
    rather than inventing a weight."""
    view._sets_by_ex[view.ex_idx] = [view._blank_set()]
    assert view._next_set_hint() == "SET 1 OF 1"


def test_next_set_hint_reports_an_exercise_already_written(view):
    view._logged_ex.add(view.ex_idx)
    assert view._next_set_hint() == "LOGGED — MOVE ON"


def test_the_hint_is_on_the_zen_screen_and_only_there(view):
    assert view._next_set_hint() in _texts(view.build())
    view._toggle_zen()
    assert view._next_set_hint() not in _texts(view.build())


# ── the rest countdown ───────────────────────────────────────────────────


def test_switching_layouts_restores_the_timer_geometry(view):
    """`build()` and `build_large()` share the same control objects, so each
    has to restate every size the other changes. Miss one and switching zen off
    leaves a 36 pt countdown clipped inside a 56 px ring."""
    timer = view.timer
    view.build()  # zen: the large dial
    assert timer.ring.width == RING_PX_LARGE
    assert timer.display.size == DISPLAY_PT_LARGE

    view._toggle_zen()
    view.build()  # back to the compact one
    assert timer.ring.width == RING_PX
    assert timer.ring.height == RING_PX
    assert timer.display.size == DISPLAY_PT


def test_the_large_dial_shows_the_live_countdown(view):
    """Not a copy of the display — the same control the tick loop mutates."""
    timer = view.timer
    timer.seconds, timer.total, timer.running = 95, 120, True
    timer.display.value = "1:35"
    assert "1:35" in _texts(timer.build_large())


def test_muting_stays_reachable_in_zen(view):
    """With the screen dark and the phone on the floor, the beep is the only
    thing telling him the rest is over — so its switch cannot be a casualty
    of the decluttering."""
    assert view.timer.sound_btn in list(_walk(view.build()))


# ── degrading ────────────────────────────────────────────────────────────


def test_an_unreachable_database_leaves_him_focused(page):
    """Failing open, in the direction he asked for. A storage hiccup must not
    put the food diary back in front of him mid-set."""
    set_active_routine("cambiatufisico")
    broken = FakeStore(fail_get=True, fail_set=True)
    page.data["store"] = broken
    v = WorkoutView(page, broken)
    v.phase_id = 1
    v._start_day(0)
    assert v.zen is True
    v._toggle_zen()  # must not raise even though the write fails
    assert v.zen is False
    v.build()


@pytest.mark.parametrize("stored", ["off", "OFF", " off ", "0", "false", "no"])
def test_off_is_recognised_however_it_was_written(view, store, stored):
    store.prefs[ZEN_PREF] = stored
    assert view._zen_pref() is False


@pytest.mark.parametrize("stored", ["on", "", "yes", "banana", None])
def test_anything_else_reads_as_on(view, store, stored):
    store.prefs[ZEN_PREF] = stored
    assert view._zen_pref() is True
