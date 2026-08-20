"""Notes on the training screen, and swapping an exercise when the machine is busy.

Two features, one shared constraint taken from where they are used: standing up,
between two sets, with wet hands and the rest timer running. So the tests here
assert as much about *how* these behave as about what they store.

**Notes.** The exercise note is one tap from the rows and unfolds in place —
never a dialog, never a rebuild, because a rebuild under an open keyboard takes
the caret out of whatever is being typed. It ends up in `entrenos.nota`, the
column that belongs to the row it describes. The session note is the other kind
entirely: it is about the day, it needs no workout row (`notas_sesion` is keyed
by date alone), and it is written at the end, on the screen the session ends on.

**Swapping.** The rule that makes it safe is that the set is written under the
exercise that was *actually performed* — `substitutions.key_to_log` decides that
and nothing here re-derives it. The rest is making the swap impossible to miss
on screen, because three weeks later the gap in the Leg Press history has to be
explainable and this is the only moment it can be explained.

No PostgreSQL: a dict-backed fake covers every `Storage` method both paths use,
which is also what makes the "the database refused" cases honest.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import flet as ft
import pytest

from data import set_active_routine
from storage import NOTE_MAX_LEN, WorkoutEntry
from substitutions import Scope
from views.workout import NOTES_PREF, WorkoutView

# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    """`Storage` for the note and swap paths, with its failure modes.

    `session_notes` and `exercise_notes` mirror the two real destinations: a
    table keyed by date, and a column on an `entrenos` row that has to exist
    first — `set_exercise_note` returning False is the real method's way of
    saying "that exercise is not logged on that date".
    """

    def __init__(self, history: dict[str, list[WorkoutEntry]] | None = None, fail: bool = False):
        self.prefs: dict[str, str] = {}
        self.history = history or {}
        self.saved: list[WorkoutEntry] = []
        self.session_notes: dict[str, str] = {}
        self.exercise_notes: dict[tuple[str, str], str | None] = {}
        self.fail = fail

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        if self.fail:
            raise RuntimeError("database unreachable")
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("database unreachable")
        self.prefs[key] = value

    def get_last_sets(self, exercise: str, before=None):
        entries = self.history.get(exercise)
        return list(entries[-1].sets) if entries else None

    def get_exercise_history(self, exercise: str, limit: int = 20):
        return list(self.history.get(exercise, []))[-limit:]

    def save_workout(self, entry: WorkoutEntry):
        self.saved.append(entry)

    def get_session_note(self, on_date=None) -> str | None:
        if self.fail:
            raise RuntimeError("database unreachable")
        return self.session_notes.get(str(on_date))

    def set_session_note(self, note: str | None, on_date=None) -> str | None:
        if self.fail:
            raise RuntimeError("database unreachable")
        key = str(on_date)
        if note:
            self.session_notes[key] = note
        else:
            self.session_notes.pop(key, None)
        return note

    def set_exercise_note(self, exercise: str, note: str | None, on_date=None) -> bool:
        if self.fail:
            raise RuntimeError("database unreachable")
        self.exercise_notes[(exercise, str(on_date))] = note
        return True


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


def _fields(control) -> list[ft.TextField]:
    return [c for c in _walk(control) if isinstance(c, ft.TextField)]


def _dialogs_opened(page) -> list:
    return [
        call.args[0]
        for call in page.open.call_args_list
        if call.args and isinstance(call.args[0], ft.AlertDialog)
    ]


#: First exercise of CambiaTuFísico phase 1 day 1, and the substitute the
#: derived catalogue offers for it. Both come from the app's own data rather
#: than being invented here: a key the catalogue does not know is exactly what
#: `substitutions.py` refuses to store.
SMITH = "Smith Bench Press"
SWAP_TO = "Barbell Bench Press"


# ── 1. the note on one exercise ──────────────────────────────────────────


def test_the_note_box_opens_without_a_dialog_or_a_rebuild(page):
    """Requirement's real constraint: it must not block, and must not rebuild.

    A dialog here would go up while the rest timer runs with the phone on the
    floor, and a `refresh_current()` would mount a fresh text field and hand the
    keyboard to neither copy.
    """
    view = make_view(page, FakeStore())
    view.build()
    view._toggle_note()
    assert view._note_body.visible is True
    assert page.data["refresh_current"].call_count == 0
    assert _dialogs_opened(page) == []


def test_a_note_typed_on_an_unsaved_exercise_is_written_with_its_sets(page):
    """It lives *in* the `entrenos` row, so it goes in with the INSERT.

    Writing it afterwards through `set_exercise_note` would be a second
    statement that can fail on its own and leave the note on the floor.
    """
    store = FakeStore()
    view = make_view(page, store)
    view._update_set(0, "weight", "60")
    view._update_set(0, "reps", "10")
    view._note_typed("Left shoulder complained on set 2")
    view._save(None)
    assert store.saved[0].note == "Left shoulder complained on set 2"


def test_a_note_on_an_already_logged_exercise_updates_its_row(page):
    """`_save_exercise` refuses a second write, so the note takes the other door."""
    store = FakeStore()
    view = make_view(page, store)
    view._update_set(0, "weight", "60")
    view._update_set(0, "reps", "10")
    view._save(None)
    view._set_note(view.ex_idx, "Bar felt slow today")
    assert store.exercise_notes[(SMITH, view.log_date.isoformat())] == "Bar felt slow today"


def test_a_blank_note_is_no_note(page):
    """An emptied box means "no note", not "a note that says nothing"."""
    store = FakeStore()
    view = make_view(page, store)
    view._note_typed("something")
    view._note_typed("   ")
    assert view._note_for(view.ex_idx) == ""
    view._update_set(0, "weight", "60")
    view._update_set(0, "reps", "10")
    view._save(None)
    assert store.saved[0].note is None


def test_a_wall_of_text_is_trimmed_by_storage_not_by_this_screen(page):
    """`storage.clean_note` is the single definition of that rule.

    The cap is enforced in Python rather than as a `String(1000)` column
    precisely because Postgres and SQLite disagree about widths, and a second
    trimming rule in a view would be a third opinion.
    """
    view = make_view(page, FakeStore())
    view._note_typed("x" * (NOTE_MAX_LEN + 500))
    assert len(view._note_for(view.ex_idx)) == NOTE_MAX_LEN


def test_an_unsaved_note_survives_the_app_being_killed(page):
    """Same promise the draft makes about numbers, made about words.

    The note cannot live in `WorkoutDraft` — that payload is versioned and named
    in `backup.py`'s skip list — so it gets its own preference, stamped with the
    day it belongs to.
    """
    store = FakeStore()
    view = make_view(page, store)
    view._update_set(0, "weight", "60")  # something for the draft to hold
    view._set_note(0, "Bench felt heavy")

    revived = WorkoutView(page, store)
    revived.on_show()
    assert revived._note_for(revived.ex_idx) == "Bench felt heavy"


def test_a_note_stamped_with_another_day_is_dropped(page):
    """A forgotten note expires by itself instead of surfacing tomorrow."""
    store = FakeStore()
    view = make_view(page, store)
    view._update_set(0, "weight", "60")
    view._set_note(0, "yesterday's note")
    store.prefs[NOTES_PREF] = store.prefs[NOTES_PREF].replace(
        view.log_date.isoformat(), (view.log_date - timedelta(days=1)).isoformat()
    )

    revived = WorkoutView(page, store)
    revived.on_show()
    assert revived._note_for(revived.ex_idx) == ""


def test_a_dead_database_costs_the_note_and_not_the_session(page):
    """Nothing about a note may raise into a `build()` mid-set."""
    store = FakeStore(fail=True)
    view = make_view(page, store)
    view._set_note(0, "still typing")
    assert view._note_for(0) == "still typing"
    view.build()


# ── 2. the note on the whole session ─────────────────────────────────────


def test_the_session_note_is_on_the_screen_the_session_ends_on(page):
    """Not on the exercise screen: it is written once, at the end, about the day."""
    view = make_view(page, FakeStore())
    assert "Nota de la sesión" not in _texts(view.build())
    view.finished = True
    assert "Nota de la sesión" in _texts(view.build())


def test_the_session_note_is_written_straight_to_its_own_table(page):
    """`notas_sesion` needs no workout row, so there is nothing to wait for."""
    store = FakeStore()
    view = make_view(page, store)
    view._save_session_note("Slept badly, everything felt heavy")
    assert store.session_notes[view.log_date.isoformat()] == "Slept badly, everything felt heavy"


def test_a_session_note_needs_no_logged_exercise(page):
    """The session most worth explaining is the one where nothing got logged."""
    store = FakeStore()
    view = make_view(page, store)
    view._finish_session()
    view._save_session_note("Gym shut at eight, only got through half of it")
    assert store.saved == []
    assert view._session_note() == "Gym shut at eight, only got through half of it"


def test_clearing_the_box_deletes_the_note(page):
    store = FakeStore()
    view = make_view(page, store)
    view._save_session_note("first thought")
    view._save_session_note("")
    assert view.log_date.isoformat() not in store.session_notes


# ── 3. swapping the exercise ─────────────────────────────────────────────


def test_the_set_is_logged_under_the_exercise_actually_performed(page):
    """The rule the whole feature rests on.

    Logging a Barbell Bench Press as a Smith Bench Press because that is what
    the plan said would poison both histories at once, and `progression` reads
    those histories to decide the next weight.
    """
    store = FakeStore()
    view = make_view(page, store)
    view._apply_substitution(SWAP_TO, Scope.TODAY)
    view._update_set(0, "weight", "80")
    view._update_set(0, "reps", "8")
    view._save(None)
    assert store.saved[0].exercise == SWAP_TO


def test_the_screen_says_which_exercise_is_being_done_instead(page):
    """Loud, naming both, naming the scope, naming the key it will be logged as."""
    view = make_view(page, FakeStore())
    view._apply_substitution(SWAP_TO, Scope.TODAY)
    shown = _texts(view.build())
    assert f"SUSTITUTO · {SWAP_TO}" in shown
    assert any(SMITH in t and "En lugar de" in t for t in shown)
    assert any(f"va a tu historial como {SWAP_TO}".lower() in t.lower() for t in shown)


def test_the_banner_is_there_in_zen_mode_too(page):
    """Zen removes reference material, not the answer to "what am I logging"."""
    view = make_view(page, FakeStore())
    view._apply_substitution(SWAP_TO, Scope.TODAY)
    view.zen = True
    assert f"SUSTITUTO · {SWAP_TO}" in _texts(view.build())


def test_the_substitute_carries_the_slot_prescription(page):
    """`swap_prescription` moves the `[4×10]` across, so the plan is unchanged.

    The sets and reps belong to the slot in the routine; only the movement
    changed, because the machine was occupied.
    """
    view = make_view(page, FakeStore(), phase=6)
    prescribed = view._prescribed_raw()
    view._apply_substitution("Incline Machine Press", Scope.TODAY)
    assert view._current_exercise_raw().startswith("Incline Machine Press")
    assert view._current_exercise_raw().endswith(prescribed[prescribed.index("[") :])


def test_the_draft_is_still_keyed_by_what_the_routine_prescribes(page):
    """Otherwise `workout_draft.fit_to_routine` would not recognise the rows.

    It re-points a restored draft by matching names against the routine's own
    exercises, so a draft filed under the substitute would come back "dropped"
    and take the typed sets with it.
    """
    view = make_view(page, FakeStore())
    view._apply_substitution(SWAP_TO, Scope.TODAY)
    assert view._exercise_keys()[0] == SMITH


def test_an_illegal_pairing_is_refused_without_taking_the_screen_down(page):
    """`set_substitution` raises on a pair it would not offer. Nothing crashes."""
    store = FakeStore()
    view = make_view(page, store)
    view._apply_substitution("Not A Real Exercise", Scope.TODAY)
    assert view._substitution_at(0) is None
    view.build()


def test_clearing_the_swap_puts_the_prescribed_exercise_back(page):
    view = make_view(page, FakeStore())
    view._apply_substitution(SWAP_TO, Scope.PHASE)
    assert view._substitution_at(0) is not None
    view._clear_current_substitution()
    assert view._substitution_at(0) is None
    assert view._current_exercise_raw() == SMITH


def test_the_swap_dialog_offers_only_exercises_the_app_knows(page):
    """A key with no image, no muscles and no meaning for the coach is refused.

    The list is derived from movement pattern and equipment rather than written
    out by hand, so this checks the boundary rather than the contents: whatever
    is offered has to be storable.
    """
    from substitutions import is_valid_substitution

    view = make_view(page, FakeStore())
    view._open_swap_dialog()
    dialogs = _dialogs_opened(page)
    assert len(dialogs) == 1
    offered = [t for t in _texts(dialogs[0]) if t in (SWAP_TO, "Push-ups", "Decline Press")]
    assert offered, _texts(dialogs[0])
    assert all(is_valid_substitution(SMITH, name) for name in offered)


def test_the_swapped_exercise_reads_its_own_history(page):
    """The prefill has to come off the machine actually being used.

    Filling a Barbell Bench Press from the Smith machine it replaced would put a
    number from different mechanics in the box, one tap from the history.
    """
    store = FakeStore(
        {
            SMITH: [
                WorkoutEntry(
                    date=(date.today() - timedelta(days=3)).isoformat(),
                    exercise=SMITH,
                    muscle_group="Chest",
                    phase=1,
                    sets=[{"weight": 60.0, "reps": 12}] * 3,
                )
            ]
        }
    )
    view = make_view(page, store)
    assert view.sets[0]["weight"] == "60"
    view._apply_substitution(SWAP_TO, Scope.TODAY)
    assert all(not r["weight"] for r in view.sets), view.sets
