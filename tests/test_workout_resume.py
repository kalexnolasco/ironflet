"""The safety net: a workout must survive the app being killed outright.

`flet_reconnect.py` fixes the black screen, but no patch can stop Android from
reclaiming the process while the user is in another app. When that happens the
next launch is a cold start — new process, empty memory — and the only thing
standing between Alex and a lost session is the draft in the database.

The machinery for that already existed (`workout_draft.py` writes it,
`WorkoutView.on_show()` restores it). What was missing was the trigger: start-up
always landed on Home, so the sets were sitting there and the user had no way to
know. `main.initial_view_index()` is that trigger, and these tests are its
guards.

The important one is `test_a_killed_app_comes_back_to_the_workout`, which does
the whole thing across **two separate Python processes** over one SQLite file —
the closest thing to "Android killed the app and Alex opened it again" that a
machine with no phone can run. Nothing is shared between them but the file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import main
from data import ROUTINES, active_routine, set_active_routine
from exercises import exercise_key
from workout_draft import DRAFT_TTL_S, DraftStore, WorkoutDraft

REPO = Path(__file__).resolve().parents[1]


# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    """`get_pref`/`set_pref` and nothing else — all `DraftStore` may use."""

    def __init__(self):
        self.prefs: dict[str, str] = {}

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        self.prefs[key] = value


@pytest.fixture
def routine():
    """The default routine, made active — `fit_to_routine` compares against it."""
    previous = active_routine()
    set_active_routine("cambiatufisico")
    try:
        yield active_routine()
    finally:
        set_active_routine(previous.id)


def a_live_draft(routine, *, saved_at: float | None = None) -> WorkoutDraft:
    """A believable half-done session on the first day of the first phase."""
    phase_id = routine.phases[0].id
    day = routine.days_for_phase(phase_id)[0]
    keys = [exercise_key(x) for x in day.exercises]
    return WorkoutDraft(
        routine_id=routine.id,
        phase_id=phase_id,
        day_idx=0,
        day_name=day.name,
        ex_idx=1,
        exercise=keys[1],
        pending={keys[1]: [{"weight": "82.5", "reps": "8", "rir": "1", "type": "normal"}]},
        completed=[],
        started_at=time.time() - 600,
        saved_at=time.time() if saved_at is None else saved_at,
    )


# ── where start-up lands ─────────────────────────────────────────────────


def test_no_draft_means_home(routine):
    assert main.initial_view_index(FakeStore()) == 0


def test_a_live_draft_lands_on_train(routine):
    store = FakeStore()
    DraftStore(store).save(a_live_draft(routine), force=True)
    assert main.initial_view_index(store) == main.TRAIN_VIEW_IDX


def test_train_is_still_view_index_two():
    """Indices are frozen (home.py navigates by number). Pin the one used here."""
    from views.workout import WorkoutView

    assert main.TRAIN_VIEW_IDX == 2
    assert WorkoutView is not None  # the view that index has to mean


def test_an_expired_draft_lands_on_home(routine):
    """Yesterday's session must not hijack this morning's launch."""
    store = FakeStore()
    stale = a_live_draft(routine, saved_at=time.time() - DRAFT_TTL_S - 60)
    # Written straight into the row: `DraftStore.save` would re-stamp `saved_at`.
    store.prefs["workout_draft"] = json.dumps(stale.to_payload())
    assert main.initial_view_index(store) == 0


def test_a_draft_for_another_routine_lands_on_home(routine):
    """Switching routine is deliberate; the old session is not resumed."""
    other = next(r for r in ROUTINES if r.id != routine.id)
    store = FakeStore()
    draft = a_live_draft(routine)
    draft.routine_id = other.id
    DraftStore(store).save(draft, force=True)
    assert main.initial_view_index(store) == 0


def test_a_corrupt_row_lands_on_home_instead_of_raising(routine):
    """Start-up may never be the thing that takes the app down."""
    store = FakeStore()
    store.prefs["workout_draft"] = "{not json at all"
    assert main.initial_view_index(store) == 0


def test_a_store_that_throws_lands_on_home(routine):
    class Broken:
        def get_pref(self, *a, **k):
            raise RuntimeError("database unreachable")

        def set_pref(self, *a, **k):
            raise RuntimeError("database unreachable")

    assert main.initial_view_index(Broken()) == 0


# ── the real thing: two processes, one file ──────────────────────────────

CHILD = r'''
"""Run inside a fresh interpreter: `write` saves a draft, `read` restores it."""
import json
import sys
import time
from unittest.mock import MagicMock

from data import active_routine, set_active_routine
from exercises import exercise_key
from routine_builder import ensure_tables, sync_user_routines
from storage import Storage
from workout_draft import DraftStore, WorkoutDraft


def start_up():
    """The first lines of `main.main()`, in the same order."""
    store = Storage()
    ensure_tables(store)
    sync_user_routines(store)
    set_active_routine(store.get_pref("routine", "cambiatufisico") or "cambiatufisico")
    return store


def write():
    store = start_up()
    store.set_pref("routine", "cambiatufisico")
    routine = active_routine()
    phase_id = routine.phases[0].id
    day = routine.days_for_phase(phase_id)[0]
    keys = [exercise_key(x) for x in day.exercises]
    draft = WorkoutDraft(
        routine_id=routine.id,
        phase_id=phase_id,
        day_idx=0,
        day_name=day.name,
        ex_idx=1,
        exercise=keys[1],
        pending={keys[1]: [{"weight": "82.5", "reps": "8", "rir": "1", "type": "normal"}]},
        completed=[],
        started_at=time.time() - 600,
    )
    assert DraftStore(store).save(draft, force=True)
    return {"day": day.name, "exercise": keys[1], "phase_id": phase_id}


def read():
    """A cold start: does the app land on the workout, with the numbers?"""
    import main
    from views.workout import WorkoutView

    store = start_up()
    index = main.initial_view_index(store)

    page = MagicMock()
    page.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "store": store,
    }
    view = WorkoutView(page, store)
    view.on_show()
    return {
        "index": index,
        "phase_id": view.phase_id,
        "day_idx": view.day_idx,
        "ex_idx": view.ex_idx,
        "rows": view.sets,
        "started_at": view.session_started_at,
    }


print(json.dumps({"write": write, "read": read}[sys.argv[1]]()))
'''


def run_child(script: Path, action: str, db_path: Path) -> dict:
    """One short-lived process against `db_path`, sharing nothing else."""
    env = dict(os.environ)
    # The phone's configuration: SQLite in the app's storage directory. Both
    # PostgreSQL URLs have to go or `resolve_db_url` would prefer them and the
    # test would run against the shared database instead of its own file.
    env.pop("DATABASE_URL", None)
    env.pop("TEST_DATABASE_URL", None)
    env["IRONFLET_SQLITE"] = str(db_path)
    env["PYTHONPATH"] = str(REPO)
    done = subprocess.run(
        [sys.executable, str(script), action],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert done.returncode == 0, done.stderr
    # `flet_reconnect.record()` prints to stdout on import of `main`; the JSON
    # is the last line.
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_killed_app_comes_back_to_the_workout(tmp_path):
    """Process A logs a set and dies. Process B must open on that set.

    This is the scenario no patch can prevent — Android reclaiming the process
    while the user is in Spotify — and the one that used to look like lost work.
    """
    script = tmp_path / "child.py"
    script.write_text(CHILD)
    db_path = tmp_path / "ironflet.db"

    written = run_child(script, "write", db_path)
    # The draft is now nothing but bytes in a file: no shared memory, no
    # engine, no Python object survives between these two calls.
    restored = run_child(script, "read", db_path)

    assert restored["index"] == 2, "a cold start with a live workout must open on Train"
    assert restored["phase_id"] == written["phase_id"]
    assert restored["day_idx"] == 0
    assert restored["ex_idx"] == 1
    assert restored["started_at"], "the session chronometer resumes where it was"
    weights = [row.get("weight") for row in restored["rows"]]
    assert "82.5" in weights, f"the logged set did not come back: {restored['rows']}"


def test_a_cold_start_with_no_workout_opens_on_home(tmp_path):
    """The other half: an untouched install must not open on Train."""
    script = tmp_path / "child.py"
    script.write_text(CHILD)

    restored = run_child(script, "read", tmp_path / "ironflet.db")

    assert restored["index"] == 0
    assert restored["day_idx"] == -1
