"""History has to show the notes the training screen writes.

A note that is written and never read again is not worth the typing, and there
are two kinds with two different homes: `entrenos.nota`, which belongs to one
exercise on one day, and `notas_sesion`, which belongs to the day itself and
exists whether or not anything was logged. That second one is why there is a
card on the list screen as well as a line on the session cards — a day with a
note and no workouts has no exercise detail view to appear in.

Absence is the ordinary case for both. Every row the Telegram coach writes has
no note at all, and so does every row written before the column existed, so the
tests below check that nothing appears rather than that something empty does.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import flet as ft
import pytest

from storage import WorkoutEntry
from theme import LIGHT, set_palette
from views.history import HistoryView


@pytest.fixture(autouse=True)
def light_palette():
    set_palette(LIGHT)
    yield
    set_palette(LIGHT)


class FakeStore:
    """History's reads, plus the session-note table the notes feature added."""

    def __init__(self, entries: list[WorkoutEntry], notes: list[dict] | None = None):
        self.entries = entries
        self.notes = notes or []

    def get_all(self) -> list[WorkoutEntry]:
        return list(self.entries)

    def get_exercise_summary(self) -> list[dict]:
        summary: dict[str, dict] = {}
        for w in self.entries:
            row = summary.setdefault(
                w.exercise,
                {"name": w.exercise, "count": 0, "last_date": w.date, "max_weight": 0.0},
            )
            row["count"] += 1
            row["last_date"] = max(row["last_date"], w.date)
            for s in w.sets:
                row["max_weight"] = max(row["max_weight"], s.get("weight") or 0)
        return sorted(summary.values(), key=lambda r: r["count"], reverse=True)

    def get_exercise_history(self, name: str) -> list[WorkoutEntry]:
        return [w for w in self.entries if w.exercise == name]

    def get_session_notes(self, limit: int = 60) -> list[dict]:
        return list(self.notes)[-limit:]


class OldStore(FakeStore):
    """A store with no `get_session_notes` at all.

    Not a hypothetical: this screen is also built by tests and by callers that
    predate the notes feature, and a missing method must cost the notes and not
    the screen.
    """

    get_session_notes = None  # type: ignore[assignment]

    def __getattribute__(self, name):
        if name == "get_session_notes":
            raise AttributeError(name)
        return object.__getattribute__(self, name)


def entry(date: str, sets: list[dict], exercise: str = "Squat", note: str | None = None):
    return WorkoutEntry(
        date=date, exercise=exercise, muscle_group="Legs", phase=1, sets=sets, note=note
    )


def make_view(entries, notes=None, store=None) -> HistoryView:
    page = MagicMock()
    page.width = 400
    page.height = 800
    page.data = {"refresh_current": lambda: None}
    return HistoryView(page, store or FakeStore(entries, notes))


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


def texts(control) -> list[str]:
    return [c.value for c in _walk(control) if isinstance(c, ft.Text) and c.value]


WORK = [{"weight": 100.0, "reps": 5}]


# ── the exercise note ────────────────────────────────────────────────────


def test_a_note_on_an_exercise_shows_on_its_session_card():
    view = make_view([entry("2026-08-10", WORK, note="Belt too loose, redid the last set")])
    view.selected = "Squat"
    assert "Belt too loose, redid the last set" in texts(view.build())


def test_a_session_with_no_note_shows_none():
    """The normal case, and the one the coach's rows are always in."""
    view = make_view([entry("2026-08-10", WORK)])
    view.selected = "Squat"
    shown = texts(view.build())
    assert not any("Note on" in t for t in shown)


# ── the whole-session note ───────────────────────────────────────────────


def test_the_days_session_note_shows_under_that_days_sets():
    view = make_view(
        [entry("2026-08-10", WORK)],
        notes=[{"date": "2026-08-10", "note": "Slept four hours", "timestamp": 0.0}],
    )
    view.selected = "Squat"
    assert "Slept four hours" in texts(view.build())


def test_a_note_from_another_day_stays_on_that_day():
    view = make_view(
        [entry("2026-08-10", WORK)],
        notes=[{"date": "2026-08-11", "note": "Different day entirely", "timestamp": 0.0}],
    )
    view.selected = "Squat"
    assert "Different day entirely" not in texts(view.build())


def test_session_notes_are_readable_from_the_list_screen():
    """Where they can be found without guessing which exercise to open."""
    view = make_view(
        [entry("2026-08-10", WORK)],
        notes=[{"date": "2026-08-10", "note": "Gym packed, cut it short", "timestamp": 0.0}],
    )
    assert "Gym packed, cut it short" in texts(view.build())


def test_a_note_on_a_day_with_no_workout_is_still_readable():
    """The session most worth explaining logged nothing at all.

    `notas_sesion` is keyed by date alone, so this note has no exercise, no
    session card and no detail view. Without the list card it would be written
    and never seen again.
    """
    view = make_view(
        [], notes=[{"date": "2026-08-10", "note": "Back tweaked, rested", "timestamp": 0.0}]
    )
    assert "Back tweaked, rested" in texts(view.build())


def test_no_notes_means_no_card():
    view = make_view([entry("2026-08-10", WORK)])
    assert "Session notes" not in texts(view.build())


def test_a_store_that_cannot_answer_still_renders_the_history():
    """A missing or unreachable note table costs the notes, never the sets."""
    entries = [entry("2026-08-10", WORK)]
    view = make_view(entries, store=OldStore(entries))
    assert "Squat" in texts(view.build())
    view.selected = "Squat"
    assert "Detalle de la sesión" in texts(view.build())
