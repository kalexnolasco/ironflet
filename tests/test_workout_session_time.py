"""How long the session lasted — proposed when honest, asked for when not.

Alex asked for two things and this is the second: *"seteo hasta tiempos"*. The
chronometer already existed, but it was pixels — it ticked, it was read, and it
died with the view. `duraciones_sesion` gives it somewhere to go.

The whole difficulty is that the same clock means two different things:

* **trained live** — it measured the session, and the number is real;
* **filled in two days later** — it measured how long the typing took, which is
  not a datum. Averaged in with the real ones it never comes back out.

So the rule is: *the clock is only ever written when it timed training.* Every
other case opens an empty field and says why it is empty. That is what most of
this file pins, and `test_a_backdated_session_never_stores_the_clock` is the one
that matters most — a wrong duration is not visibly wrong afterwards.

The other half is "not timed" being a real answer rather than a gap: no row,
`format_duration` returns `""`, and nothing is painted. Every session logged
before this table existed, and everything the Telegram coach writes, is in that
state and must stay readable.

Dict-backed fake, no PostgreSQL: `tests/test_session_duration.py` owns the
storage contract, and this file owns what the two views do with it.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from unittest.mock import MagicMock

import flet as ft
import pytest

from data import set_active_routine
from storage import MAX_SESSION_SECONDS, format_duration
from views.history import HistoryView
from views.workout import WorkoutView

DEFAULT_ROUTINE = "cambiatufisico"
MONDAY = date.today() - timedelta(days=2)


# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    """`Storage`'s duration surface over a dict, with the real refusal.

    `set_session_duration` raises exactly where the real one does — over
    `MAX_SESSION_SECONDS` — because "the message reaches the user unchanged" is
    a claim about this view and cannot be tested against a double that never
    refuses.
    """

    def __init__(self):
        self.prefs: dict[str, str] = {}
        self.saved: list = []
        self.durations: dict[str, int] = {}
        self.writes: list[tuple] = []

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        self.prefs[key] = value

    def get_last_sets(self, key: str, before=None):
        return None

    def get_exercise_history(self, key: str, limit: int = 20):
        return []

    def get_all(self):
        return []

    def save_workout(self, entry) -> None:
        self.saved.append(entry)

    # ── durations ──
    def get_duration_map(self) -> dict[str, int]:
        return dict(self.durations)

    def get_session_duration(self, on_date=None):
        day = on_date or date.today()
        iso = day if isinstance(day, str) else day.isoformat()
        return self.durations.get(iso)

    def set_session_duration(self, seconds, on_date=None):
        day = on_date or date.today()
        iso = day if isinstance(day, str) else day.isoformat()
        self.writes.append((iso, seconds))
        if seconds is not None and seconds > MAX_SESSION_SECONDS:
            raise ValueError(
                f"A session cannot last {format_duration(seconds)} — "
                f"the longest accepted is {format_duration(MAX_SESSION_SECONDS)}"
            )
        if not seconds or seconds < 1:
            self.durations.pop(iso, None)
            return None
        self.durations[iso] = int(seconds)
        return int(seconds)


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
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store
    v = WorkoutView(page, store)
    v.phase_id = 1
    v._start_day(0)
    return v


def _walk(control, seen=None):
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


def _said(control, needle: str) -> bool:
    return any(needle.lower() in t.lower() for t in _texts(control))


def _last_dialog(page):
    return page.open.call_args_list[-1][0][0]


def _field(dialog) -> ft.TextField:
    return next(c for c in _walk(dialog) if isinstance(c, ft.TextField))


def _button(dialog, label: str):
    for c in _walk(dialog):
        if isinstance(c, ft.Container) and c.on_click is not None and _said(c, label):
            return c
    raise AssertionError(f"no button labelled {label!r} in the dialog")


def _log_one(view, idx: int = 0, on: date | None = None):
    """Put a real row in, optionally on a chosen day."""
    if on is not None:
        view._set_exercise_date(idx, on)
    view.ex_idx = idx
    view._update_set(0, "weight", "80")
    view._update_set(0, "reps", "8")
    view._save_exercise(idx)


def _ran_for(view, seconds: int):
    """Pretend the chronometer has been running for `seconds`."""
    view.session_started_at = time.time() - seconds
    view.session_ended_at = None


# ── the clock is only written when it timed training ─────────────────────


def test_a_live_session_stores_what_the_clock_measured(view, store):
    """Trained today, timed today: the number is real and is kept.

    Written rather than offered in a dialog nobody opens — the alternative to
    storing an honest measurement is losing it.
    """
    _log_one(view)
    _ran_for(view, 4320)
    view._finish_session()

    assert store.durations == {date.today().isoformat(): 4320}


def test_a_backdated_session_never_stores_the_clock(view, store):
    """**The one that matters.** Monday filled in today: the clock timed typing.

    A duration is not visibly wrong afterwards — 1h 12m looks exactly like a
    session and exactly like three minutes of thumbing numbers in — so this can
    only be caught here.
    """
    _log_one(view, on=MONDAY)
    _ran_for(view, 300)
    view._finish_session()

    assert store.durations == {}
    assert view._duration_is_measured() is False


def test_a_session_across_two_days_proposes_nothing_to_either(view, store):
    """No arithmetic divides one chronometer between two sessions honestly.

    The sum leaves out the gap between them, the maximum is the part for the
    whole, and half each is invented. So neither day gets a number.
    """
    _log_one(view, idx=0, on=MONDAY)
    _log_one(view, idx=1)
    _ran_for(view, 4320)
    view._finish_session()

    assert store.durations == {}


def test_a_mis_tap_is_not_a_session(view, store):
    """Under a minute of clock is a tab left open, not a workout."""
    _log_one(view)
    _ran_for(view, 0)
    view._finish_session()

    assert store.durations == {}


def test_a_time_already_stored_is_never_overwritten(view, store):
    """Two sessions in one day, or a figure Alex typed himself.

    `set_session_duration` upserts, so the row on disk — the better answer in
    both cases — can only be protected here.
    """
    store.durations[date.today().isoformat()] = 5400
    _log_one(view)
    _ran_for(view, 600)
    view._finish_session()

    assert store.durations == {date.today().isoformat(): 5400}


def test_a_session_that_logged_nothing_is_not_timed(view, store):
    """Finish is reachable from exercise 1, so a session can end empty.

    There was no session, so there is nothing for a duration to be about.
    """
    _ran_for(view, 4320)
    view._finish_session()

    assert store.durations == {}
    assert _texts(view._duration_block()) == []


def test_the_clock_is_stopped_before_it_is_read(view, store):
    """Otherwise it keeps counting for as long as the summary is on screen.

    The "it measured the typing" failure at one remove, and the reason
    `_stop_session_timer` comes first in `_finish_session`.
    """
    _log_one(view)
    _ran_for(view, 3600)
    view._finish_session()
    stored = store.durations[date.today().isoformat()]

    time.sleep(0.05)
    assert view._session_elapsed_s() == stored


def test_a_failed_write_does_not_break_finishing(view, store):
    """A duration is decoration on the summary. The session is not."""

    def boom(*a, **k):
        raise RuntimeError("database unreachable")

    store.set_session_duration = boom
    _log_one(view)
    _ran_for(view, 4320)
    view._finish_session()

    assert view.finished is True


# ── the summary asks, and says why it is asking ──────────────────────────


def test_the_summary_shows_the_measured_time(view, store):
    _log_one(view)
    _ran_for(view, 4320)
    view._finish_session()

    block = view._duration_block()
    assert _said(block, "1h 12m")
    assert _said(block, "measured by the timer")


def test_the_summary_asks_when_the_clock_could_not_be_trusted(view, store):
    """The asking Alex wanted, with the reason attached.

    "Not timed" plus a sentence saying the timer ran while he typed. A field
    that simply opened empty would read as a bug.
    """
    _log_one(view, on=MONDAY)
    _ran_for(view, 300)
    view._finish_session()

    block = view._duration_block()
    assert _said(block, "not timed")
    assert _said(block, "while you typed")


def test_the_summary_offers_a_row_for_every_day_it_wrote_to(view, store):
    """Two days, two questions. One figure for both would belong to neither."""
    _log_one(view, idx=0, on=MONDAY)
    _log_one(view, idx=1)
    view._finish_session()

    block = view._duration_block()
    from views.workout import _date_label

    assert _said(block, _date_label(MONDAY))
    assert _said(block, _date_label(date.today()))


def test_the_duration_reaches_the_built_summary_screen(view, store):
    """A control nothing renders is a control nobody fills in."""
    _log_one(view)
    _ran_for(view, 4320)
    view._finish_session()

    assert _said(view.build(), "session time")


def test_the_finish_dialog_says_what_the_clock_will_be_allowed_to_claim(view, page):
    """Before trusting a number, not after."""
    _log_one(view)
    _ran_for(view, 4320)
    view._ask_finish(None)
    assert _said(_last_dialog(page), "will be saved")

    view._set_exercise_date(2, MONDAY)
    view._ask_finish(None)
    assert _said(_last_dialog(page), "not saved as your session time")


# ── typing one in ────────────────────────────────────────────────────────


def test_typing_minutes_stores_seconds(view, store, page):
    view._open_duration_dialog(MONDAY)
    dlg = _last_dialog(page)
    _field(dlg).value = "72"
    dlg.actions[-1].on_click(None)

    assert store.durations[MONDAY.isoformat()] == 4320


def test_an_empty_field_clears_the_row(view, store, page):
    """ "Not timed" is a real answer, and the honest one for an unclocked session."""
    store.durations[MONDAY.isoformat()] = 4320
    view._open_duration_dialog(MONDAY)
    dlg = _last_dialog(page)
    _field(dlg).value = ""
    dlg.actions[-1].on_click(None)

    assert MONDAY.isoformat() not in store.durations


def test_the_dialog_opens_on_what_is_already_stored(view, store, page):
    store.durations[MONDAY.isoformat()] = 4320
    view._open_duration_dialog(MONDAY)
    assert _field(_last_dialog(page)).value == "72"


def test_an_impossible_time_is_refused_in_the_storage_layers_own_words(view, store, page):
    """Shown as-is, not paraphrased and not clamped.

    Trimming 14 h to 8 h would store a number nobody measured wearing the face
    of one that was — the same stance the date picker takes on future dates.
    """
    view._open_duration_dialog(MONDAY)
    dlg = _last_dialog(page)
    _field(dlg).value = "840"
    dlg.actions[-1].on_click(None)

    assert _said(dlg, "the longest accepted is")
    assert MONDAY.isoformat() not in store.durations


def test_a_refused_write_leaves_the_stored_value_alone(view, store, page):
    store.durations[MONDAY.isoformat()] = 4320
    view._open_duration_dialog(MONDAY)
    dlg = _last_dialog(page)
    _field(dlg).value = "840"
    dlg.actions[-1].on_click(None)

    assert store.durations[MONDAY.isoformat()] == 4320


def test_something_that_is_not_a_number_is_refused(view, store, page):
    view._open_duration_dialog(MONDAY)
    dlg = _last_dialog(page)
    _field(dlg).value = "an hour"
    dlg.actions[-1].on_click(None)

    assert _said(dlg, "minutes, as a number")
    assert store.writes == []


def test_the_clock_shortcut_is_offered_only_when_it_measured_this_session(view, store, page):
    """The single most likely way a wrong number gets into the table.

    A "use the clock" button on a back-dated day pastes the typing time in one
    tap, so it is not there — and the space it would occupy says why.
    """
    _log_one(view)
    _ran_for(view, 4320)
    view._open_duration_dialog(date.today())
    assert _said(_last_dialog(page), "use the clock")

    view._set_exercise_date(1, MONDAY)
    view.completed = []
    _log_one(view, idx=1, on=MONDAY)
    view._open_duration_dialog(MONDAY)
    dlg = _last_dialog(page)
    assert not _said(dlg, "use the clock")
    assert _said(dlg, "not offered here")


def test_the_clock_shortcut_fills_the_field(view, store, page):
    _log_one(view)
    _ran_for(view, 4320)
    view._open_duration_dialog(date.today())
    dlg = _last_dialog(page)
    _button(dlg, "use the clock").on_click(None)

    assert _field(dlg).value == "72"


# ── it is read back: History ─────────────────────────────────────────────


class HistoryStore:
    """The `Storage` surface `HistoryView` touches, with durations on top."""

    def __init__(self, durations: dict[str, int] | None = None, entries=None):
        self.durations = dict(durations or {})
        self.entries = list(entries or [])

    def get_duration_map(self) -> dict[str, int]:
        return dict(self.durations)

    def get_session_notes(self):
        return []

    def get_exercise_summary(self):
        return [{"name": "Squat", "count": 1, "last_date": "2026-08-17", "max_weight": 100.0}]

    def get_all(self):
        return list(self.entries)

    def get_exercise_history(self, name: str, limit: int = 20):
        return list(self.entries)


@pytest.fixture
def history_page():
    p = MagicMock()
    p.data = {"navigate_to": lambda i, **k: None, "refresh_current": lambda: None}
    return p


def _entry(day: str):
    from storage import WorkoutEntry

    return WorkoutEntry(
        date=day,
        exercise="Squat",
        muscle_group="Legs",
        phase=1,
        sets=[{"weight": 100.0, "reps": 5}],
    )


def test_history_shows_the_time_on_the_session_card(history_page):
    """A duration written and never read again is not worth writing."""
    store = HistoryStore({"2026-08-17": 4320}, [_entry("2026-08-17")])
    view = HistoryView(history_page, store)
    view.selected = "Squat"

    assert _said(view.build(), "1h 12m")


def test_history_lists_recent_session_times_without_drilling_in(history_page):
    """A time you have to go looking for is a time nobody compares."""
    store = HistoryStore({"2026-08-17": 4320}, [_entry("2026-08-17")])
    view = HistoryView(history_page, store)

    built = view.build()
    assert _said(built, "session times")
    assert _said(built, "1h 12m")


def test_history_says_nothing_when_nothing_was_timed(history_page):
    """The state of every row written before this table existed.

    An untimed day is not a hole in a calendar, so it takes no height and gets
    no apology — and above all no `0m`, which would claim a session that lasted
    no time.
    """
    store = HistoryStore({}, [_entry("2026-08-17")])
    view = HistoryView(history_page, store)

    assert not _said(view.build(), "session times")
    view.selected = "Squat"
    assert not _said(view.build(), "0m")


def test_history_survives_a_database_that_will_not_answer_about_durations(history_page):
    """This number is context on a card whose sets are the point."""
    store = HistoryStore({}, [_entry("2026-08-17")])

    def boom():
        raise RuntimeError("database unreachable")

    store.get_duration_map = boom
    view = HistoryView(history_page, store)
    view.selected = "Squat"

    assert _said(view.build(), "Squat")
