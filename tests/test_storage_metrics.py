"""End-to-end guards for the two home-screen numbers that used to lie.

These write real rows into the test database and read them back through the
public `Storage` API, because both bugs lived in the seam between the schema
and the label: `entrenos` holds one row *per exercise*, and the plan trains
5 days on / 2 days off. A pure unit test over `analytics` (tests/test_analytics.py)
cannot see either of those.

Each test also reproduces the *old* implementation inline and asserts what it
would have shown, so the regression is documented, not just fixed.

Nothing here imports the Telegram coach in ../agente/.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from data import ROUTINES, set_active_routine
from storage import Entreno, Storage, WorkoutEntry, weekly_session_minimum

DEFAULT_ROUTINE = "cambiatufisico"


@pytest.fixture(autouse=True)
def use_routine():
    """Pins the active routine, and yields the setter for tests wanting another.

    `data` holds the active routine in a module-level global and the streak
    minimum is read off it, so without this a routine left selected by another
    suite would silently decide the numbers asserted here.
    """
    set_active_routine(DEFAULT_ROUTINE)
    yield set_active_routine
    set_active_routine(DEFAULT_ROUTINE)


@pytest.fixture
def store():
    """Storage against `entrenador_test`, with the workout table emptied.

    Same URL resolution as tests/test_smoke.py. Rows are deleted rather than
    tables dropped: other suites share this database and dropping would take
    their fixtures with it.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ.get("DATABASE_URL")
        if not base:
            pytest.skip("no DATABASE_URL: there is no database to test against")
        # render_as_string, not str(): str() masks the password.
        url = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)

    if make_url(url).database == "entrenador":
        pytest.skip("points at the production database: leave it alone")

    almacen = Storage(url)
    with almacen._Session() as s:
        s.execute(delete(Entreno))
        s.commit()
    return almacen


# ── helpers ──────────────────────────────────────────────────────────────

TODAY = date.today()
THIS_MONDAY = TODAY - timedelta(days=TODAY.weekday())


def s(weight, reps, **extra):
    return {"weight": weight, "reps": reps, **extra}


def log(store, day: date, exercise: str, sets: list[dict]):
    store.save_workout(
        WorkoutEntry(
            date=day.isoformat(),
            exercise=exercise,
            muscle_group="Test",
            phase=1,
            sets=sets,
        )
    )


def log_session(store, day: date, exercises: int = 6):
    """One training day, one row per exercise — how the app really writes."""
    for i in range(exercises):
        log(store, day, f"Exercise {i}", [s(100, 5)])


def old_streak(store) -> int:
    """The previous `get_streak()`, verbatim: consecutive calendar days."""
    days = {w.date for w in store.get_all()}
    streak, d = 0, TODAY
    while d.isoformat() in days:
        streak += 1
        d -= timedelta(days=1)
    return streak


def full_week(store, weeks_ago: int, days: int = 5):
    """Mon–Fri of a past week, one 6-exercise session per day."""
    monday = THIS_MONDAY - timedelta(days=7 * weeks_ago)
    for d in range(days):
        log_session(store, monday + timedelta(days=d))


# ── get_week_stats: sessions are days, not rows ──────────────────────────


def test_week_stats_keys_are_unchanged(store):
    """views/home.py indexes all three by name — renaming one blanks the row."""
    assert set(store.get_week_stats()) == {"sessions", "sets", "volume"}


def test_one_session_of_six_exercises_is_one_session(store):
    """THE BUG: six rows, one training day, and home read "6 Sessions"."""
    log_session(store, TODAY, exercises=6)

    assert len(store.get_all()) == 6  # what the old code counted
    assert store.get_week_stats()["sessions"] == 1


def test_sessions_count_distinct_days(store):
    log_session(store, TODAY, exercises=6)
    log_session(store, TODAY - timedelta(days=2), exercises=4)
    log_session(store, TODAY - timedelta(days=3), exercises=5)

    stats = store.get_week_stats()
    assert len(store.get_all()) == 15
    assert stats["sessions"] == 3


def test_empty_database_is_all_zeros(store):
    assert store.get_week_stats() == {"sessions": 0, "sets": 0, "volume": 0}


# ── get_week_stats: volume and sets skip warm-ups ────────────────────────


def test_volume_excludes_warmup_sets(store):
    log(store, TODAY, "Squat", [s(60, 10, type="warmup"), s(100, 5), s(100, 5)])

    # The old sum over every stored set, verbatim.
    old = sum((x["weight"] or 0) * (x["reps"] or 0) for w in store.get_all() for x in w.sets)
    assert old == 1600.0

    stats = store.get_week_stats()
    assert stats["volume"] == 1000.0  # the 600 kg of warm-up is not tonnage
    assert stats["sets"] == 2


def test_untyped_sets_still_count_as_work(store):
    """Every set written before the set-type feature has no `type` key."""
    log(store, TODAY, "Bench", [s(80, 10), s(80, 10)])

    stats = store.get_week_stats()
    assert stats["sets"] == 2
    assert stats["volume"] == 1600.0


def test_window_is_the_last_seven_days(store):
    log(store, TODAY, "Squat", [s(100, 5)])
    log(store, TODAY - timedelta(days=10), "Squat", [s(200, 5)])

    stats = store.get_week_stats()
    assert stats["sessions"] == 1
    assert stats["volume"] == 500.0


# ── get_streak: weeks, not days ──────────────────────────────────────────


def test_streak_survives_the_two_rest_days(store):
    """THE BUG: after three flawless Mon–Fri weeks the old code showed 🔥 0.

    Nothing is logged in the current week, so this asserts the same numbers on
    whichever weekday the suite happens to run.
    """
    for weeks_ago in (1, 2, 3):
        full_week(store, weeks_ago)

    assert old_streak(store) == 0  # no row dated today → streak over
    assert store.get_streak() == 3


def test_unfinished_current_week_does_not_break_the_streak(store):
    """One session so far this week is a week in progress, not a failed one."""
    for weeks_ago in (1, 2, 3):
        full_week(store, weeks_ago)
    log_session(store, TODAY)

    assert old_streak(store) == 1  # old code: today only, three weeks erased
    assert store.get_streak() == 3


def test_a_missed_week_ends_the_streak(store):
    full_week(store, 1)
    full_week(store, 2)
    # week 3 skipped entirely
    full_week(store, 4)

    assert store.get_streak() == 2


def test_streak_tolerates_one_missed_day_a_week(store):
    """4 of 5 days still counts: one skipped session is not a broken streak."""
    for weeks_ago in (1, 2):
        full_week(store, weeks_ago, days=4)

    assert store.get_streak() == 2


def test_three_days_a_week_counts_on_the_default_routine(store):
    """THE BUG: 3 days a week is the *whole* prescription in phases 1-4.

    The minimum was hardcoded at 4, and CambiaTuFísico — the routine every
    new install starts on — prescribes 3 days a week for weeks 1 to 10. Ten
    weeks of flawless adherence therefore rendered as 🔥 0. `push-pull-legs`
    is a 3-day routine end to end, so its streak could never have left 0
    at all.

    Removing the four `women-*` routines on 2026-08-17 did NOT cost this test
    its boundary case: `women-home` was a 3-day routine, but so are
    CambiaTuFísico's phases 1-4 and both phases of `push-pull-legs`, so 3
    remains the lowest `weekly_session_minimum()` of any shipped routine and
    the "below the old hardcoded 4" case is still genuinely exercised.
    """
    for weeks_ago in (1, 2, 3, 4, 5):
        full_week(store, weeks_ago, days=3)

    assert store.get_streak(min_sessions=4) == 0  # the hardcoded old minimum
    assert store.get_streak() == 5


def test_the_minimum_comes_from_the_active_routine(store, use_routine):
    """A heavier routine asks for more: the same 3 weeks stop qualifying."""
    for weeks_ago in (1, 2, 3):
        full_week(store, weeks_ago, days=3)

    use_routine(DEFAULT_ROUTINE)  # lightest phase: 3 days
    assert store.get_streak() == 3

    use_routine("recomp-ppl-ul")  # 5 days in every phase
    assert store.get_streak() == 0


@pytest.mark.parametrize("routine_id", [r.id for r in ROUTINES])
def test_perfect_adherence_is_never_a_zero_streak(store, use_routine, routine_id):
    """The bar, for every shipped routine: doing the plan cannot read 0.

    Each week logs exactly what the routine's lightest phase prescribes —
    the least a fully adherent user can ever do — and the streak has to see
    it. This is the assertion that breaks if the minimum ever goes back to
    being a constant.

    It caught 4 of the 8 routines when the hardcoded minimum was 4; with the
    `women-*` routines gone it catches 2 of the 4 — `cambiatufisico` and
    `push-pull-legs`, the two whose lightest phase is 3 days. Recalculate the
    per-routine minima with:
      for r in ROUTINES: set_active_routine(r.id); print(r.id, weekly_session_minimum())
    """
    use_routine(routine_id)
    prescribed = weekly_session_minimum()

    for weeks_ago in (1, 2):
        full_week(store, weeks_ago, days=prescribed)

    assert store.get_streak() == 2


def test_streak_is_zero_without_workouts(store):
    assert store.get_streak() == 0
