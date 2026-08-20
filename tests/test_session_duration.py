"""How long the session lasted — the one number the chronometer never kept.

`WorkoutView` has always shown a running clock and never written it anywhere: it
lived on the view instance and died with it. That was survivable while every
session was logged as it happened. It stops being survivable the moment a
session can be logged for a past day, because then the clock measures how long
the *typing* took, and that is not a fact about any workout.

The design this suite pins:

* **one duration per training day**, in its own table keyed by date, exactly
  like `pesos` and `notas_sesion` — not one per `entrenos` row. Alex now dates
  each exercise separately, so the rows of one session arrive at different
  moments; the shared `fecha` is the only thing that makes them one session, so
  it is the right key for the one span that was measured;
* **absence is normal.** Everything already logged and everything the Telegram
  coach writes has no duration. `None` is the answer, not zero;
* **an impossible value is refused, never clamped.** 8 h is the ceiling; past it
  `clean_duration` raises rather than storing a number nobody measured in the
  shape of one that was.

The `store` fixture is parametrised over both engines, like
`tests/test_workout_notes.py` and `tests/test_sqlite_backend.py`: the APK runs
SQLite and the desktop runs PostgreSQL, and a duration that round-trips on one
and not the other is the silent divergence the shared schema exists to prevent.
The Postgres half skips without `DATABASE_URL`, so judge a run by the skip
count.

Nothing here imports the Telegram coach in ../agente/.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.engine import make_url

from storage import (
    MAX_SESSION_SECONDS,
    MIN_SESSION_SECONDS,
    DuracionSesion,
    Entreno,
    NotaSesion,
    Storage,
    WorkoutEntry,
    clean_duration,
    format_duration,
    sqlite_url,
)

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
MONDAY = TODAY - timedelta(days=2)


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
        s.execute(delete(DuracionSesion))
        s.commit()
    return almacen


def log(store: Storage, day: date, exercise: str):
    store.save_workout(
        WorkoutEntry(
            date=day.isoformat(),
            exercise=exercise,
            muscle_group="Test",
            phase=1,
            sets=[{"weight": 100.0, "reps": 5}],
        )
    )


# ── absence is the normal answer ─────────────────────────────────────────


def test_a_day_that_was_never_timed_reads_none(store):
    """Not 0. Zero would render as a session that took no time."""
    assert store.get_session_duration(TODAY) is None
    assert store.get_session_durations() == []
    assert store.get_duration_map() == {}


def test_a_logged_session_still_has_no_duration_of_its_own(store):
    """Saving a workout writes nothing here — this is what every past row is."""
    log(store, TODAY, "Barbell Bench Press")
    assert store.get_session_duration(TODAY) is None


def test_reading_defaults_to_today(store):
    store.set_session_duration(3600)
    assert store.get_session_duration() == 3600
    assert store.get_session_duration(TODAY) == 3600
    assert store.get_session_duration(YESTERDAY) is None


# ── the round trip ───────────────────────────────────────────────────────


def test_write_then_read(store):
    assert store.set_session_duration(4320, TODAY) == 4320
    assert store.get_session_duration(TODAY) == 4320


def test_accepts_an_iso_string_for_the_date(store):
    store.set_session_duration(1800, MONDAY.isoformat())
    assert store.get_session_duration(MONDAY.isoformat()) == 1800
    assert store.get_session_duration(MONDAY) == 1800


def test_a_second_write_corrects_the_first(store):
    """The date is the primary key: two writes are a correction, not two rows."""
    store.set_session_duration(1800, TODAY)
    store.set_session_duration(2700, TODAY)
    assert store.get_session_duration(TODAY) == 2700
    assert len(store.get_session_durations()) == 1


def test_seconds_are_whole(store):
    """A chronometer counts seconds; sub-second precision means nothing here."""
    assert store.set_session_duration(1800.7, TODAY) == 1800
    assert store.get_session_duration(TODAY) == 1800


def test_zero_and_none_clear_the_row(store):
    store.set_session_duration(1800, TODAY)
    assert store.set_session_duration(0, TODAY) is None
    assert store.get_session_duration(TODAY) is None

    store.set_session_duration(1800, TODAY)
    assert store.set_session_duration(None, TODAY) is None
    assert store.get_session_duration(TODAY) is None


def test_clearing_a_day_that_has_nothing_is_a_no_op(store):
    assert store.set_session_duration(None, TODAY) is None
    assert store.get_session_durations() == []


# ── the day is the session ───────────────────────────────────────────────


def test_one_duration_covers_every_exercise_of_the_day(store):
    """THE DESIGN. Six exercises, one session, one span — not six copies."""
    for name in ("Squat", "Barbell Bench Press", "Barbell Row"):
        log(store, MONDAY, name)
    store.set_session_duration(4500, MONDAY)

    with store._Session() as s:
        assert len(list(s.scalars(select(DuracionSesion)))) == 1
    assert store.get_session_duration(MONDAY) == 4500


def test_exercises_dated_separately_share_one_duration(store):
    """Per-exercise dating is what makes this the interesting case.

    Alex logs Monday's squats and Monday's bench on Wednesday, in two goes. They
    are one session because they carry one date, and that date is this table's
    key — so there is one duration and no arithmetic to invent.
    """
    log(store, MONDAY, "Squat")
    store.set_session_duration(4500, MONDAY)
    log(store, MONDAY, "Barbell Bench Press")

    assert store.get_session_duration(MONDAY) == 4500
    assert store.get_session_duration(TODAY) is None


def test_the_duration_outlives_re_logging_an_exercise(store):
    """It hangs off the day, not off a row, so a row can go and it stays."""
    log(store, MONDAY, "Squat")
    store.set_session_duration(4500, MONDAY)

    with store._Session() as s:
        s.execute(delete(Entreno).where(Entreno.fecha == MONDAY))
        s.commit()
    log(store, MONDAY, "Squat")

    assert store.get_session_duration(MONDAY) == 4500


def test_a_duration_can_be_written_before_anything_is_logged(store):
    """Needs no `entrenos` row, like `set_session_note`.

    With the date chosen per exercise there is no single moment that is "the end
    of the session", so the duration has to be settable whenever Alex has it.
    """
    store.set_session_duration(3000, MONDAY)
    assert store.get_session_duration(MONDAY) == 3000
    log(store, MONDAY, "Squat")
    assert store.get_session_duration(MONDAY) == 3000


def test_days_are_independent(store):
    store.set_session_duration(3600, MONDAY)
    store.set_session_duration(5400, YESTERDAY)
    assert store.get_session_duration(MONDAY) == 3600
    assert store.get_session_duration(YESTERDAY) == 5400
    assert store.get_session_duration(TODAY) is None


# ── impossible values ────────────────────────────────────────────────────


def test_over_the_cap_is_refused_not_clamped(store):
    """A 14 h session is a slipped finger or a clock left running overnight.

    Refused, because clamping to 8 h stores a number nobody measured wearing the
    face of one that was, and it would then be averaged with the real ones
    forever.
    """
    with pytest.raises(ValueError):
        store.set_session_duration(14 * 3600, TODAY)
    assert store.get_session_duration(TODAY) is None


def test_the_cap_itself_is_accepted(store):
    assert store.set_session_duration(MAX_SESSION_SECONDS, TODAY) == MAX_SESSION_SECONDS


def test_one_second_past_the_cap_is_not(store):
    with pytest.raises(ValueError):
        store.set_session_duration(MAX_SESSION_SECONDS + 1, TODAY)


def test_the_refusal_says_what_the_limit_is(store):
    """The message is user-facing English and a view can show it unchanged."""
    with pytest.raises(ValueError) as exc:
        store.set_session_duration(20 * 3600, TODAY)
    assert format_duration(MAX_SESSION_SECONDS) in str(exc.value)


def test_a_refusal_leaves_an_existing_value_alone(store):
    """The rejected write must not take the good number down with it."""
    store.set_session_duration(3600, TODAY)
    with pytest.raises(ValueError):
        store.set_session_duration(50 * 3600, TODAY)
    assert store.get_session_duration(TODAY) == 3600


def test_junk_is_refused(store):
    with pytest.raises(ValueError):
        store.set_session_duration("about an hour", TODAY)


def test_negative_is_absence_not_an_error(store):
    """A backwards clock is nothing to record, and nothing to complain about."""
    assert clean_duration(-30) is None


# ── clean_duration in isolation ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        (0, None),
        (-1, None),
        (MIN_SESSION_SECONDS, MIN_SESSION_SECONDS),
        (1, 1),
        (59, 59),
        (3600, 3600),
        ("3600", 3600),
        (3600.99, 3600),
        (MAX_SESSION_SECONDS, MAX_SESSION_SECONDS),
    ],
)
def test_clean_duration(raw, expected):
    assert clean_duration(raw) == expected


def test_the_cap_is_eight_hours():
    """Frozen deliberately: moving it changes what counts as a real session."""
    assert MAX_SESSION_SECONDS == 8 * 3600


# ── format_duration ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, ""),
        (0, ""),
        (-5, ""),
        # Under a minute is "<1m", never "0m": something happened.
        (1, "<1m"),
        (59, "<1m"),
        (60, "1m"),
        (90, "1m"),
        (3540, "59m"),
        (3600, "1h 00m"),
        (4320, "1h 12m"),
        (MAX_SESSION_SECONDS, "8h 00m"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_format_duration_is_not_the_running_clock():
    """No seconds field. A finished session is not precise to the second."""
    assert ":" not in format_duration(4325)


# ── the list and the map ─────────────────────────────────────────────────


def test_get_session_durations_is_oldest_first(store):
    store.set_session_duration(3600, TODAY)
    store.set_session_duration(1800, MONDAY)
    store.set_session_duration(2700, YESTERDAY)

    rows = store.get_session_durations()
    assert [r["date"] for r in rows] == [
        MONDAY.isoformat(),
        YESTERDAY.isoformat(),
        TODAY.isoformat(),
    ]
    assert [r["seconds"] for r in rows] == [1800, 2700, 3600]
    assert all(r["timestamp"] > 0 for r in rows)


def test_get_session_durations_limit_keeps_the_newest(store):
    for i in range(5):
        store.set_session_duration(600 * (i + 1), TODAY - timedelta(days=i))
    rows = store.get_session_durations(limit=2)
    assert [r["date"] for r in rows] == [
        (TODAY - timedelta(days=1)).isoformat(),
        TODAY.isoformat(),
    ]


def test_get_duration_map_is_keyed_by_iso_date(store):
    store.set_session_duration(3600, TODAY)
    store.set_session_duration(1800, MONDAY)
    mapa = store.get_duration_map()
    assert mapa == {TODAY.isoformat(): 3600, MONDAY.isoformat(): 1800}
    # Read with .get(): a day with no row was not timed.
    assert mapa.get(YESTERDAY.isoformat()) is None


def test_get_duration_map_has_no_limit(store):
    """History renders a year of cards; a limit would blank the oldest ones."""
    for i in range(80):
        store.set_session_duration(600, TODAY - timedelta(days=i))
    assert len(store.get_duration_map()) == 80


# ── destructive operations ───────────────────────────────────────────────


def test_clear_workouts_takes_the_durations_with_it(store):
    """ "1h 12m" for a day with no exercises left describes nothing."""
    log(store, MONDAY, "Squat")
    store.set_session_duration(4500, MONDAY)
    store.clear_workouts()
    assert store.get_all() == []
    assert store.get_duration_map() == {}


def test_clear_all_takes_them_too(store):
    store.set_session_duration(4500, MONDAY)
    store.clear_all()
    assert store.get_duration_map() == {}


# ── the schema ───────────────────────────────────────────────────────────


def test_the_table_is_created_on_both_engines(store):
    assert "duraciones_sesion" in inspect(store._engine).get_table_names()


def test_seconds_is_not_null(store):
    """Same design as `notas_sesion.nota`: the row exists because there is one.

    Safe as a new **table** where it would not be as a new column —
    `create_all()` creates missing tables, and `add_missing_columns()` refuses
    NOT NULL columns on purpose.
    """
    columna = DuracionSesion.__table__.columns["segundos"]
    assert columna.nullable is False
    assert DuracionSesion.__table__.primary_key.columns.keys() == ["fecha"]


def test_entrenos_gained_no_duration_column():
    """The duration is per day. A column here would be six copies of one number."""
    assert not [c for c in Entreno.__table__.columns if "dur" in c.name]
