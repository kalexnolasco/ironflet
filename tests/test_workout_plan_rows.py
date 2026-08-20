"""The rows an exercise opens with now come from the plan, not from last time.

The bug this closes is small to describe and expensive to have: a first-ever
exercise opened **one** empty row while the routine prescribed three, and phase
6 — the one literally named "Drop Sets + Compound" — opened four identical rows
with its drop set nowhere on screen. Both were invisible: nothing was wrong on
the screen, there was simply less of it than the plan asked for.

`session_plan.py` owns every rule about how many rows and of what kind; this
file only checks that `views/workout.py` asks it and shows the answer. So the
assertions here are deliberately about *shape* — a drop row exists and is typed
as a drop, an unmatched row arrives empty, the count follows the prescription —
and never about a number this view could have invented, because there is no
number in this view to invent.

The invariant guarded at the end is the expensive one: **a proposed row is
persisted as an empty slot.** A row the app suggested and the user never touched
must not come back from a draft looking like a set he performed, because one tap
then turns it into history and into a personal record.

None of this needs PostgreSQL: a dict-backed fake covers the five `Storage`
methods this path reaches for.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import flet as ft
import pytest

from data import set_active_routine
from set_types import SetType, set_type_of
from storage import WorkoutEntry
from views.workout import WorkoutView
from workout_draft import is_blank_row

# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    def __init__(self, history: dict[str, list[WorkoutEntry]] | None = None):
        self.prefs: dict[str, str] = {}
        self.history = history or {}
        self.saved: list[WorkoutEntry] = []

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        self.prefs[key] = value

    def get_last_sets(self, exercise: str, before=None):
        entries = self.history.get(exercise)
        return list(entries[-1].sets) if entries else None

    def get_exercise_history(self, exercise: str, limit: int = 20):
        return list(self.history.get(exercise, []))[-limit:]

    def save_workout(self, entry: WorkoutEntry):
        self.saved.append(entry)


def session(exercise: str, sets: list[dict], days_ago: int = 3) -> WorkoutEntry:
    return WorkoutEntry(
        date=(date.today() - timedelta(days=days_ago)).isoformat(),
        exercise=exercise,
        muscle_group="Chest",
        phase=1,
        sets=sets,
    )


@pytest.fixture
def page():
    p = MagicMock()
    p.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": MagicMock(),
        "set_routine": lambda r: None,
    }
    return p


def make_view(page, store, *, routine: str = "cambiatufisico", phase: int = 1, day: int = 0):
    set_active_routine(routine)
    page.data["store"] = store
    view = WorkoutView(page, store)
    view.phase_id = phase
    view._start_day(day)
    page.data["refresh_current"].reset_mock()
    return view


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


def _dialogs_opened(page) -> list:
    return [
        call.args[0]
        for call in page.open.call_args_list
        if call.args and isinstance(call.args[0], ft.AlertDialog)
    ]


BENCH = "Barbell Bench Press"

#: CambiaTuFísico phase 6, day 1: `Barbell Bench Press [4×10,10,8,6+12↓]`.
#: The only phase in the routine that prescribes drop sets, and therefore the
#: only place the drop row can be checked against a real prescription.
DROP_PHASE = 6


# ── 1. the plan decides how many rows ────────────────────────────────────


def test_a_first_ever_exercise_opens_the_rows_the_plan_asks_for(page):
    """The whole complaint in one assertion.

    Alex has logged nothing at all, so every exercise in the app is in this
    state today. Phase 1 prescribes `3×12` and the screen used to open a single
    row, leaving two thirds of the session to be added by hand.
    """
    view = make_view(page, FakeStore())
    assert len(view.sets) == 3
    # And nothing is filled in: there is no history to fill it from, and a
    # weight this screen made up is the one thing it must never write.
    assert all(is_blank_row(row) for row in view.sets)


def test_the_plan_beats_a_shorter_last_session(page):
    """Phase 2 adds a set to the opening exercise: that is the plan, not a slip.

    The periodisation is the point of the routine — copying last session's set
    count copies the *previous phase's* prescription, which is precisely what
    the next phase exists to change.
    """
    store = FakeStore(
        {"Smith Bench Press": [session("Smith Bench Press", [{"weight": 60, "reps": 10}] * 2)]}
    )
    view = make_view(page, store)
    assert len(view.sets) == 3


def test_the_row_the_plan_added_arrives_empty(page):
    """Visibly empty, not quietly pre-filled.

    Copying set 2's numbers into the row last session never had would be this
    screen inventing a set. An empty row says "the plan asks for a third set and
    there is nothing to copy into it", which is the truth.
    """
    store = FakeStore(
        {"Smith Bench Press": [session("Smith Bench Press", [{"weight": 60, "reps": 10}] * 2)]}
    )
    view = make_view(page, store)
    assert view.sets[0]["weight"] == "60"
    assert view.sets[1]["weight"] == "60"
    assert is_blank_row(view.sets[2])


def test_last_session_still_fills_the_rows_it_lines_up_with(page):
    """The prefill is untouched: the plan chooses the rows, history fills them."""
    store = FakeStore(
        {"Smith Bench Press": [session("Smith Bench Press", [{"weight": 62.5, "reps": 9}] * 3)]}
    )
    view = make_view(page, store)
    assert [r["weight"] for r in view.sets] == ["62.5"] * 3
    # Suggestions, not work: nothing is logged until he vouches for it.
    assert all(view._is_suggested(r) for r in view.sets)


def test_a_routine_that_prescribes_nothing_keeps_the_old_behaviour(page):
    """No readable scheme must not *cost* rows.

    `session_plan` answers an unreadable prescription with a single row, which
    is right for a first-ever exercise and wrong for one with four sets of
    history behind it. A user routine whose phases state no scheme is a real
    thing, so the pre-plan seeding stands wherever the plan has nothing to say.
    """
    view = make_view(page, FakeStore())
    view._current_exercise_raw = lambda: "Something With No Scheme"
    view._phase = lambda: type("Bare", (), {"id": 1, "scheme": "", "notes": "", "name": "Bare"})()
    view._plan_cache.clear()
    view._sets_by_ex.clear()
    view._last_sets_cache[0] = [{"weight": 50.0, "reps": 10}] * 4
    assert len(view.sets) == 4


# ── 2. the drop set is a drop set ────────────────────────────────────────


def test_the_prescribed_drop_set_gets_its_own_row(page):
    """`[4×10,10,8,6+12↓]` is four sets *and* a drop, and the drop is a row."""
    view = make_view(page, FakeStore(), phase=DROP_PHASE)
    types = [set_type_of(r) for r in view.sets]
    assert types == [SetType.NORMAL] * 4 + [SetType.DROPSET]


def test_the_drop_row_says_what_it_is_aiming_at(page):
    """`→ 12` under the drop, and the reps of the set above it under that one.

    The row is the only place a per-set target can be read mid-exercise, and a
    drop with no target is indistinguishable from a fifth working set.
    """
    view = make_view(page, FakeStore(), phase=DROP_PHASE)
    targets = [view._row_target(i, r) for i, r in enumerate(view.sets)]
    assert targets[3].startswith("→ 6")
    assert targets[4] == "→ 12"


def test_last_session_cannot_relabel_the_drop_as_a_normal_set(page):
    """The type belongs to the plan.

    The Telegram coach writes sets with no `"type"` at all, and a session logged
    before this feature existed has five untyped rows. Reading the type off them
    would quietly turn phase 6 back into five identical sets.
    """
    store = FakeStore({BENCH: [session(BENCH, [{"weight": 80, "reps": 10}] * 5)]})
    view = make_view(page, store, phase=DROP_PHASE)
    assert set_type_of(view.sets[4]) is SetType.DROPSET
    # And the numbers from that row are still offered, as a suggestion.
    assert view.sets[4]["weight"] == "80"
    assert view._is_suggested(view.sets[4])


def test_an_amrap_row_is_typed_to_failure_and_given_no_number(page):
    """`[3×failure]` is an instruction, not a rep target.

    Double progression has no ceiling to progress towards here, so the plan
    opens the rows and states nothing — a made-up number would be worse than
    none, and an RIR beside "to failure" would contradict it.
    """
    view = make_view(page, FakeStore(), phase=DROP_PHASE)
    # Push-ups [3×failure] is the last exercise of this day.
    view.ex_idx = len(view._current_day().exercises) - 1
    assert view._current_exercise_raw().startswith("Push-ups")
    assert all(set_type_of(r) is SetType.FAILURE for r in view.sets)
    assert all("RIR" not in view._row_target(i, r) for i, r in enumerate(view.sets))


# ── 3. the disagreement is reported, not hidden ──────────────────────────


def test_the_screen_says_when_the_plan_and_last_session_differ(page):
    """Both numbers, one line. The plan is followed; the other is not lost."""
    store = FakeStore(
        {"Smith Bench Press": [session("Smith Bench Press", [{"weight": 60, "reps": 10}] * 2)]}
    )
    view = make_view(page, store)
    assert "Plan · 3 sets · last session 2 sets" in _texts(view.build())


def test_the_drop_set_is_announced_above_the_rows(page):
    view = make_view(page, FakeStore(), phase=DROP_PHASE)
    assert any(t.startswith("Plan · 4 sets + 1 drop") for t in _texts(view.build()))


def test_none_of_this_opens_a_dialog(page):
    """The rule the whole screen lives by: nothing may block a set."""
    view = make_view(page, FakeStore(), phase=DROP_PHASE)
    view.build()
    view._go_next_exercise()
    view.build()
    assert _dialogs_opened(page) == []


# ── 4. the draft invariant ───────────────────────────────────────────────


def test_a_proposed_row_is_persisted_as_an_empty_slot(page):
    """The expensive one.

    Every row on screen is a proposal until it is claimed. If any of them
    reached the draft carrying numbers, restoring would hand back a set Alex
    never performed — one tap from `entrenos`, and from a personal record built
    on a lift that did not happen.
    """
    store = FakeStore({BENCH: [session(BENCH, [{"weight": 80, "reps": 10}] * 5)]})
    view = make_view(page, store, phase=DROP_PHASE)
    kept = view._rows_for_draft(view.sets)
    assert len(kept) == len(view.sets)
    assert all(is_blank_row(row) for row in kept), kept


def test_the_drop_survives_a_draft_round_trip_without_gaining_numbers(page):
    """What comes back is the same shape, still empty, still typed as a drop."""
    store = FakeStore({BENCH: [session(BENCH, [{"weight": 80, "reps": 10}] * 5)]})
    view = make_view(page, store, phase=DROP_PHASE)
    restored = view._rows_from_draft(view._rows_for_draft(view.sets), 0)
    assert [set_type_of(r) for r in restored] == [SetType.NORMAL] * 4 + [SetType.DROPSET]
    assert all(view._is_suggested(r) for r in restored)


def test_an_untouched_plan_is_not_a_workout_in_progress(page):
    """Opening five rows must not make the app think a session is under way.

    Rows nobody has typed in are the app's proposal, and a proposal is not work:
    treating it as work would put a discard confirmation in front of every
    accidental tap on the Train tab.
    """
    view = make_view(page, FakeStore(), phase=DROP_PHASE)
    assert len(view.sets) == 5
    assert view._workout_in_progress() is False
    assert view._unsaved_exercises() == []


def test_saving_writes_only_the_rows_that_were_claimed(page):
    """The blank rows the plan opened are not sets, and never reach `entrenos`."""
    store = FakeStore()
    view = make_view(page, store, phase=DROP_PHASE)
    view._update_set(0, "weight", "80")
    view._update_set(0, "reps", "10")
    view._save(None)
    assert len(store.saved) == 1
    assert store.saved[0].sets == [{"weight": 80.0, "reps": 10}]
