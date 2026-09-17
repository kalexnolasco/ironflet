"""Notes: the one thing in the database that nothing else can reconstruct.

A weight is a number the plan can re-derive; a note is not. "Hole 4 on the
backrest", "left wrist complains in supination", "slept 5 h and that is why the
weight dropped" — six weeks later that is the only thing separating a bad
session from a bad night, and there is no metric that implies it.

There are two of them and they are not the same shape:

* an **exercise note** belongs to one `entrenos` row, and dies with it;
* a **session note** belongs to the day, explains every exercise at once, and
  must survive re-logging or deleting any single one of them.

Both are optional everywhere. Alex has logged nothing at all yet, and every row
the Telegram coach writes has no note and never will, so **absent is the normal
answer** — the same contract as `rir` and `type` inside a set dict. Half of what
is below is about absence behaving well.

The `store` fixture is parametrised over both engines, like
`tests/test_sqlite_backend.py`: the APK runs SQLite and the desktop runs
PostgreSQL, and a note that round-trips on one and not on the other is exactly
the silent divergence the shared schema exists to prevent. The Postgres half
skips without `DATABASE_URL`, so judge a run by the skip count.

Nothing here imports the Telegram coach in ../agente/.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from storage import (
    NOTE_MAX_LEN,
    Entreno,
    NotaSesion,
    Storage,
    WorkoutEntry,
    clean_note,
    sqlite_url,
)

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


# ── fixtures ─────────────────────────────────────────────────────────────


def _postgres_url() -> str | None:
    """`entrenador_test` on the configured server, or None if unavailable."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ.get("DATABASE_URL")
        if not base:
            return None
        # render_as_string, not str(): str() masks the password.
        url = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)
    if make_url(url).database == "entrenador":
        return None  # production: leave it alone
    return url


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path) -> Storage:
    """A `Storage` on each backend, with the training tables emptied."""
    if request.param == "sqlite":
        return Storage(sqlite_url(tmp_path / "ironflet.db"))

    url = _postgres_url()
    if not url:
        pytest.skip("no DATABASE_URL: the PostgreSQL half of the parity check cannot run")
    almacen = Storage(url)
    with almacen._Session() as s:
        s.execute(delete(Entreno))
        s.execute(delete(NotaSesion))
        s.commit()
    return almacen


def log(store: Storage, day: date, exercise: str, *, note: str | None = None):
    store.save_workout(
        WorkoutEntry(
            date=day.isoformat(),
            exercise=exercise,
            muscle_group="Test",
            phase=1,
            sets=[{"weight": 100.0, "reps": 5}],
            note=note,
        )
    )


# ── the first-time case: nothing logged, nothing written ─────────────────


def test_a_database_with_no_history_answers_none_everywhere(store):
    """Alex has not logged a single workout yet. Nothing here may raise."""
    assert store.get_session_note() is None
    assert store.get_session_note(TODAY) is None
    assert store.get_exercise_note("Squat") is None
    assert store.get_session_notes() == []
    assert store.get_day_notes() == {"session": None, "exercises": {}}


def test_a_workout_logged_without_a_note_has_none(store):
    """The shape of every row that already exists and everything the bot writes."""
    log(store, TODAY, "Squat")

    (entry,) = store.get_all()
    assert entry.note is None
    assert store.get_exercise_note("Squat", TODAY) is None
    assert store.get_day_notes(TODAY)["exercises"] == {}


def test_notes_are_absent_from_the_day_map_not_present_as_none(store):
    """`get_day_notes()["exercises"]` is read with `.get()`, so absence is a miss.

    Filling it with `None` for every exercise would make "has a note" a truthiness
    test over a dict that always has the key — the same trap as assuming `"rir"`
    is in a set dict.
    """
    log(store, TODAY, "Squat", note="Belt on.")
    log(store, TODAY, "Deadlift")

    notes = store.get_day_notes(TODAY)
    assert notes["exercises"] == {"Squat": "Belt on."}
    assert notes["exercises"].get("Deadlift") is None


# ── exercise notes ───────────────────────────────────────────────────────


def test_a_note_can_be_logged_with_the_workout(store):
    log(store, TODAY, "Squat", note="Hole 4 on the backrest.")

    assert store.get_exercise_note("Squat", TODAY) == "Hole 4 on the backrest."
    (entry,) = store.get_all()
    assert entry.note == "Hole 4 on the backrest."


def test_a_note_can_be_attached_after_the_fact(store):
    log(store, TODAY, "Squat")

    assert store.set_exercise_note("Squat", "Left wrist complains in supination.", TODAY) is True
    assert store.get_exercise_note("Squat", TODAY) == "Left wrist complains in supination."


def test_writing_a_note_for_an_exercise_that_is_not_logged_returns_false(store):
    """The note lives in the `entrenos` row, so it cannot invent one.

    `False` rather than an exception: the caller has a real choice to make (log
    the exercise, or write a session note instead) and a `try` at every call site
    would bury it.
    """
    assert store.set_exercise_note("Squat", "Nowhere to put this.", TODAY) is False
    assert store.get_exercise_note("Squat", TODAY) is None
    assert store.get_all() == []


def test_an_exercise_note_belongs_to_one_date_only(store):
    """Two sessions of the same exercise keep their own notes.

    This is the difference between a note and a property of the exercise: what
    happened on Monday did not happen on Tuesday.
    """
    log(store, YESTERDAY, "Squat", note="Felt heavy.")
    log(store, TODAY, "Squat", note="Moved well.")

    assert store.get_exercise_note("Squat", YESTERDAY) == "Felt heavy."
    assert store.get_exercise_note("Squat", TODAY) == "Moved well."


def test_clearing_an_exercise_note_leaves_the_workout(store):
    log(store, TODAY, "Squat", note="Typed by mistake.")

    assert store.set_exercise_note("Squat", "", TODAY) is True

    assert store.get_exercise_note("Squat", TODAY) is None
    assert len(store.get_all()) == 1  # the sets are not the note


def test_deleting_the_history_takes_the_exercise_note_with_it(store):
    log(store, TODAY, "Squat", note="Hole 4 on the backrest.")

    store.clear_workouts()

    assert store.get_all() == []
    assert store.get_exercise_note("Squat", TODAY) is None


# ── session notes ────────────────────────────────────────────────────────


def test_a_session_note_needs_no_workout(store):
    """It is about the day. A day with nothing logged can still have one."""
    assert store.set_session_note("Gym closed, walked instead.", TODAY) == (
        "Gym closed, walked instead."
    )

    assert store.get_session_note(TODAY) == "Gym closed, walked instead."
    assert store.get_all() == []


def test_one_session_note_per_day_the_second_corrects_the_first(store):
    """The date is the primary key, so this is an upsert on both engines."""
    store.set_session_note("First go.", TODAY)
    store.set_session_note("Slept 5 h, that is why the weight dropped.", TODAY)

    assert store.get_session_note(TODAY) == "Slept 5 h, that is why the weight dropped."
    with store._Session() as s:
        assert len(list(s.scalars(select(NotaSesion)))) == 1


def test_a_session_note_survives_relogging_every_exercise(store):
    """The whole reason it is not a column on `entrenos`.

    Re-logging the session — a correction, a duplicate row, a deletion — must not
    take "slept 5 h" with it, because that sentence explains the day, not the
    squat.
    """
    log(store, TODAY, "Squat")
    store.set_session_note("Slept 5 h.", TODAY)

    store.clear_workouts()
    log(store, TODAY, "Squat")

    # `clear_workouts()` is the documented exception: it drops the training
    # history, and a session note with no session left to explain goes with it.
    assert store.get_session_note(TODAY) is None

    store.set_session_note("Slept 5 h.", TODAY)
    with store._Session() as s:
        s.execute(delete(Entreno).where(Entreno.ejercicio == "Squat"))
        s.commit()
    assert store.get_session_note(TODAY) == "Slept 5 h."


def test_clearing_a_session_note_deletes_the_row(store):
    """`nota` is NOT NULL: no note means no row, never a row holding nothing."""
    store.set_session_note("Written and then thought better of.", TODAY)

    assert store.set_session_note(None, TODAY) is None

    assert store.get_session_note(TODAY) is None
    with store._Session() as s:
        assert list(s.scalars(select(NotaSesion))) == []


def test_clearing_a_session_note_that_never_existed_is_not_an_error(store):
    assert store.set_session_note("", TODAY) is None
    assert store.get_session_note(TODAY) is None


def test_session_notes_come_back_in_date_order(store):
    for offset in (5, 1, 3):
        store.set_session_note(f"Day -{offset}", TODAY - timedelta(days=offset))

    notes = store.get_session_notes()

    assert [n["date"] for n in notes] == [
        (TODAY - timedelta(days=d)).isoformat() for d in (5, 3, 1)
    ]
    assert notes[0]["note"] == "Day -5"
    assert notes[0]["timestamp"] > 0


def test_session_notes_limit_keeps_the_most_recent(store):
    """Same contract as `get_weights`: the tail of the list, not the head."""
    for offset in range(5):
        store.set_session_note(f"Day -{offset}", TODAY - timedelta(days=offset))

    notes = store.get_session_notes(limit=2)

    assert [n["note"] for n in notes] == ["Day -1", "Day -0"]


# ── the whole day, in one call ───────────────────────────────────────────


def test_get_day_notes_returns_both_kinds(store):
    log(store, TODAY, "Squat", note="Hole 4 on the backrest.")
    log(store, TODAY, "Deadlift", note="Mixed grip.")
    log(store, YESTERDAY, "Overhead Press", note="Another day entirely.")
    store.set_session_note("Slept 5 h.", TODAY)

    notes = store.get_day_notes(TODAY)

    assert notes == {
        "session": "Slept 5 h.",
        "exercises": {"Squat": "Hole 4 on the backrest.", "Deadlift": "Mixed grip."},
    }


def test_get_day_notes_defaults_to_today(store):
    store.set_session_note("Today's note.")
    log(store, TODAY, "Squat", note="Today's exercise note.")

    assert store.get_day_notes() == {
        "session": "Today's note.",
        "exercises": {"Squat": "Today's exercise note."},
    }


def test_a_date_can_be_given_as_a_string_or_a_date(store):
    """Views hold ISO strings (`WorkoutEntry.date`), queries hold `date` objects."""
    store.set_session_note("Either spelling.", TODAY.isoformat())

    assert store.get_session_note(TODAY) == "Either spelling."
    assert store.get_session_note(TODAY.isoformat()) == "Either spelling."


# ── what happens when Alex writes an essay ───────────────────────────────


def test_a_very_long_note_is_trimmed_not_refused(store):
    """A paragraph is trimmed at `NOTE_MAX_LEN`; nothing raises, nothing is lost
    that the user can see happening — `set_session_note` returns what was stored.

    Enforced in Python rather than as `String(n)`: Postgres would reject the
    write and SQLite would accept it whole, so the APK and the desktop would
    disagree about the same note and only find out when a backup crossed.
    """
    essay = "The wrist thing again. " * 200
    assert len(essay) > NOTE_MAX_LEN

    stored = store.set_session_note(essay, TODAY)
    log(store, TODAY, "Squat", note=essay)

    assert len(stored) <= NOTE_MAX_LEN
    assert store.get_session_note(TODAY) == stored
    assert stored == essay[:NOTE_MAX_LEN].rstrip()
    assert store.get_exercise_note("Squat", TODAY) == stored


def test_whitespace_only_is_the_same_as_no_note(store):
    """An emptied box means "no note", not "a note that says nothing"."""
    log(store, TODAY, "Squat", note="   \n  ")
    store.set_session_note("\t\n ", TODAY)

    assert store.get_exercise_note("Squat", TODAY) is None
    assert store.get_session_note(TODAY) is None


def test_surrounding_whitespace_is_stripped(store):
    log(store, TODAY, "Squat", note="  Hole 4 on the backrest.\n")

    assert store.get_exercise_note("Squat", TODAY) == "Hole 4 on the backrest."


def test_clean_note_is_the_single_definition(store):
    """One implementation, so the writers and `backup.py` cannot drift apart."""
    assert clean_note(None) is None
    assert clean_note("") is None
    assert clean_note("   ") is None
    assert clean_note("  kept  ") == "kept"
    assert len(clean_note("x" * (NOTE_MAX_LEN * 2))) == NOTE_MAX_LEN
