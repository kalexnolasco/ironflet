"""Tests for program_week.py.

No database and no Flet: the arithmetic is pure, and the four store adapters
are duck-typed on `get_pref` / `set_pref` / `get_all`, so `FakeStore` below is
a complete stand-in. That keeps this file running in the 238-test no-Postgres
mode, where the answer to "which week am I in" still has to be right.

Three groups carry the weight:

* **Honest ignorance.** Half the point of the module is that it says "I don't
  know" instead of inventing a week. `test_unknown_*` pins every path that must
  return `WeekStatus.UNKNOWN` with `week is None`.
* **Week borders.** Sunday must still be the week that is ending and Monday
  must be the next one — that single flip decides which distribution Alex sees
  when he checks the app the night before.
* **Agreement with `data.py`.** The phase boundaries, the length of the
  program and the phases the rotation applies to are all read off the real
  routines, never hardcoded here. Edit `PHASES` and this file fails, which is
  the whole idea.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

import data
from data import Phase, Routine, TrainingDay
from program_week import (
    PROGRAM_START_PREF_KEY,
    ProgramStart,
    StartSource,
    WeekStatus,
    clear_program_start,
    current_program_week,
    current_week,
    decode_program_start,
    encode_program_start,
    first_workout_date,
    is_rest_label,
    last_workout_date,
    load_program_start,
    monday_of,
    normalize_day_label,
    parse_week_range,
    phase_for_week,
    program_week_for,
    resolve_program_start,
    restart_date,
    rotation_applies_to,
    rotation_index_for_week,
    set_program_start,
    set_start_date,
    total_program_weeks,
    training_day_for_label,
    week_bounds,
    week_rotation_for,
    weeks_between,
)

# ─────────────────────────────────────────────────────────────────────────
# fixtures and helpers
# ─────────────────────────────────────────────────────────────────────────

#: A Monday, so program week 1 lines up with calendar week 1. Every date in
#: this file is derived from it rather than written out, or a change of anchor
#: would need 40 hand-edited constants.
START = date(2026, 1, 5)


def day_of(week: int, weekday: int = 0) -> date:
    """The `weekday`-th day (Mon = 0) of program week `week`, counting from START."""
    return START + timedelta(weeks=week - 1, days=weekday)


# Colour of a synthetic Phase. Never rendered — fixtures build day
# templates, not screens — but a literal hex in the tree invites a copy
# into a view, where the palette tests would fail it.
PHASE_COLOR_FIXTURE = "#000000"


def routine(rid: str) -> Routine:
    """Look a shipped routine up by id, never by index: `sync_user_routines()`
    splices stored routines into `ROUTINES` and other test files call it."""
    for r in data.ROUTINES:
        if r.id == rid:
            return r
    raise AssertionError(f"routine {rid!r} is gone from data.ROUTINES")


CTF = "cambiatufisico"


@pytest.fixture(autouse=True)
def restore_active_routine():
    """`data._active_routine_id` is a module global that other test files set.
    Leave it exactly as found so test order stays irrelevant."""
    previous = data.active_routine().id
    yield
    data.set_active_routine(previous)


@dataclass
class FakeStore:
    """Enough of `Storage` for the four adapters: two prefs methods and
    `get_all()`. Deliberately not a real `Storage` — these tests must run
    without Postgres."""

    prefs: dict[str, str] | None = None
    entries: list[dict] | None = None

    def __post_init__(self):
        self.prefs = dict(self.prefs or {})
        self.entries = list(self.entries or [])

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        self.prefs[key] = value

    def get_all(self) -> list[dict]:
        return list(self.entries)


def entry(day: date | str) -> dict:
    """A history row in the shape `analytics` and this module accept."""
    return {"date": day if isinstance(day, str) else day.isoformat(), "exercise": "Squat"}


# ─────────────────────────────────────────────────────────────────────────
# reading data.py
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1-3", (1, 3)),
        ("10", (10, 10)),  # phase 4 is a single week
        ("19-24", (19, 24)),
        ("1-4", (1, 4)),  # routine_builder's default
        ("W1-3", (1, 3)),  # a label someone might type in the editor
        ("weeks 11 to 14", (11, 14)),
        ("6-3", (3, 6)),  # reversed: intent is unambiguous, so straighten it
        ("0-3", (1, 3)),  # weeks are 1-based
        ("", None),
        ("   ", None),
        ("deload", None),
        (None, None),
    ],
)
def test_parse_week_range(text, expected):
    assert parse_week_range(text) == expected


def test_every_shipped_phase_declares_a_readable_range():
    """A phase whose `weeks` cannot be parsed is unreachable — it can never be
    the answer to `phase_for_week`. None of the four routines may have one."""
    for r in (routine(CTF), routine("upper-lower"), routine("push-pull-legs")):
        for phase in r.phases:
            assert parse_week_range(phase.weeks) is not None, (r.id, phase.id, phase.weeks)


@pytest.mark.parametrize(
    ("rid", "weeks"),
    [(CTF, 24), ("upper-lower", 12), ("push-pull-legs", 12), ("recomp-ppl-ul", 6)],
)
def test_total_program_weeks_matches_the_routine_description(rid, weeks):
    assert total_program_weeks(routine(rid)) == weeks


def test_phase_for_week_covers_every_week_with_no_gaps():
    r = routine(CTF)
    for week in range(1, total_program_weeks(r) + 1):
        assert phase_for_week(week, r) is not None, week


@pytest.mark.parametrize(
    ("week", "phase_id"),
    [
        (1, 1),
        (3, 1),
        (4, 2),
        (6, 2),
        (7, 3),
        (9, 3),
        (10, 4),
        (11, 5),
        (14, 5),
        (15, 6),
        (19, 7),
        (24, 7),
    ],
)
def test_phase_boundaries(week, phase_id):
    found = phase_for_week(week, routine(CTF))
    assert found is not None and found.id == phase_id


@pytest.mark.parametrize("week", [0, -1, 25, 99])
def test_phase_for_week_outside_the_program_is_none(week):
    assert phase_for_week(week, routine(CTF)) is None


def test_total_weeks_is_zero_when_no_phase_parses():
    """Unknown length, not zero length. `program_week_for` must not call it over."""
    broken = Routine(
        id="broken",
        name="Broken",
        description="",
        phases=[Phase(1, "later", "N", "S", PHASE_COLOR_FIXTURE, "", "", "", "low")],
        days_by_phase={1: [TrainingDay("Day 1", ["Squat"])]},
    )
    assert total_program_weeks(broken) == 0
    result = program_week_for(START, routine=broken, today=day_of(60))
    assert result.status is WeekStatus.ACTIVE
    assert result.week == 60


# ─────────────────────────────────────────────────────────────────────────
# calendar
# ─────────────────────────────────────────────────────────────────────────


def test_monday_of_and_week_bounds():
    sunday = day_of(1, 6)
    assert sunday.weekday() == 6
    assert monday_of(sunday) == START
    assert week_bounds(sunday) == (START, sunday)


def test_weeks_between_is_signed_and_counts_whole_weeks():
    assert weeks_between(START, START) == 0
    assert weeks_between(START, day_of(1, 6)) == 0  # Sunday is still week 1
    assert weeks_between(START, day_of(2)) == 1
    assert weeks_between(day_of(3), START) == -2


def test_restart_date_snaps_to_monday():
    """The "start the program" button must not create a two-day week 1."""
    assert restart_date(day_of(4, 4)) == day_of(4)
    assert restart_date(START) == START


# ─────────────────────────────────────────────────────────────────────────
# no start date: the answer is "I don't know"
# ─────────────────────────────────────────────────────────────────────────


def test_unknown_when_nothing_is_stored_and_nothing_is_logged():
    start = resolve_program_start(None, first_workout=None, routine=routine(CTF))
    assert start.source is StartSource.UNKNOWN
    assert start.day is None
    assert not start.known

    result = program_week_for(start, routine=routine(CTF), today=day_of(5))
    assert result.status is WeekStatus.UNKNOWN
    assert result.week is None
    assert not result.known
    assert result.phase is None
    assert result.rotation is None
    assert result.rotation_index is None
    assert result.week_start is None
    assert result.today_focus is None
    assert result.focus_for(0) is None


def test_unknown_never_becomes_a_number_on_any_routine_or_any_day():
    """The failure this guards against is a view rendering week 0 or week 1 by
    default and sending Alex to the wrong session."""
    for rid in (CTF, "upper-lower", "push-pull-legs", "recomp-ppl-ul"):
        for offset in (0, 1, 40, 200):
            result = program_week_for(
                None, routine=routine(rid), today=START + timedelta(days=offset)
            )
            assert result.week is None
            assert result.status is WeekStatus.UNKNOWN


def test_unreadable_preference_is_treated_as_nothing_stored():
    start = resolve_program_start("not a date at all", routine=routine(CTF))
    assert start.source is StartSource.UNKNOWN

    # …and still falls through to the history when there is one.
    start = resolve_program_start("|||", first_workout=START, routine=routine(CTF))
    assert start.source is StartSource.FIRST_WORKOUT
    assert start.day == START


# ─────────────────────────────────────────────────────────────────────────
# where the start date comes from
# ─────────────────────────────────────────────────────────────────────────


def test_explicit_start_beats_the_history():
    start = resolve_program_start(
        encode_program_start(START, routine(CTF)),
        first_workout=date(2025, 3, 1),
        routine=routine(CTF),
    )
    assert start.source is StartSource.PREF
    assert start.certain
    assert start.day == START


def test_inferred_from_the_first_logged_session():
    start = resolve_program_start(None, first_workout=day_of(1, 2), routine=routine(CTF))
    assert start.source is StartSource.FIRST_WORKOUT
    assert start.known
    assert not start.certain  # a view must qualify anything built on this


def test_a_date_stored_under_another_routine_is_not_reused():
    """Switching routines is starting a new program. Reusing the old date would
    drop Alex into the middle of a plan he has not begun."""
    stored = encode_program_start(START, routine(CTF))
    start = resolve_program_start(stored, first_workout=START, routine=routine("upper-lower"))
    assert start.source is StartSource.OTHER_ROUTINE
    assert not start.known
    assert start.day == START  # carried so a view can offer "use it here too"
    assert start.stored_routine_id == CTF

    result = program_week_for(start, routine=routine("upper-lower"), today=day_of(3))
    assert result.status is WeekStatus.UNKNOWN
    assert result.week is None


def test_a_bare_date_applies_to_whatever_routine_is_active():
    """The hand-editable form: no routine id, so no guard. Written by psql or
    by the coach, never by the app."""
    assert decode_program_start("2026-01-05") == (None, START)
    for rid in (CTF, "upper-lower"):
        start = resolve_program_start("2026-01-05", routine=routine(rid))
        assert start.source is StartSource.PREF
        assert start.day == START


def test_encode_round_trips_a_stored_routine_id():
    stored = Routine(id="user:7", name="Mine", description="", phases=[], days_by_phase={})
    text = encode_program_start(START, stored)
    assert decode_program_start(text) == ("user:7", START)
    assert len(PROGRAM_START_PREF_KEY) <= 60  # preferencias.clave is String(60)


# ─────────────────────────────────────────────────────────────────────────
# the first week, and the borders of every week
# ─────────────────────────────────────────────────────────────────────────


def test_first_week():
    result = program_week_for(START, routine=routine(CTF), today=START)
    assert result.status is WeekStatus.ACTIVE
    assert result.week == 1
    assert result.total_weeks == 24
    assert result.phase is not None and result.phase.id == 1
    assert result.week_in_phase == 1
    assert result.phase_length == 3
    assert result.weeks_left_in_phase == 2
    assert result.week_start == START
    assert result.week_end == day_of(1, 6)
    assert result.rotation_index == 0
    assert result.rotation == tuple(data.WEEK_ROTATION[0])
    assert result.today_focus == "Chest-Biceps"


def test_sunday_still_belongs_to_the_week_that_is_ending():
    """The case that decided Monday-anchoring: checking the app on Sunday night
    must show the week just finished, and the new one at Monday breakfast."""
    sunday = program_week_for(START, routine=routine(CTF), today=day_of(1, 6))
    monday = program_week_for(START, routine=routine(CTF), today=day_of(2))
    assert (sunday.week, monday.week) == (1, 2)
    assert sunday.rotation_index == 0
    assert monday.rotation_index == 1
    assert monday.rotation == tuple(data.WEEK_ROTATION[1])


def test_every_weekday_of_a_week_reports_the_same_week():
    for weekday in range(7):
        result = program_week_for(START, routine=routine(CTF), today=day_of(5, weekday))
        assert result.week == 5, weekday
        assert result.week_start == day_of(5)


def test_a_mid_week_start_spends_the_rest_of_that_week_on_week_one():
    """Documented cost of calendar anchoring, pinned so it is a decision and
    not a surprise. `restart_date()` exists to keep it from happening."""
    friday = day_of(1, 4)
    assert program_week_for(friday, routine=routine(CTF), today=friday).week == 1
    assert program_week_for(friday, routine=routine(CTF), today=day_of(1, 6)).week == 1
    assert program_week_for(friday, routine=routine(CTF), today=day_of(2)).week == 2


def test_a_start_date_in_a_future_week_is_scheduled_not_week_zero():
    result = program_week_for(day_of(3), routine=routine(CTF), today=START)
    assert result.status is WeekStatus.SCHEDULED
    assert result.week is None
    assert result.start.day == day_of(3)


def test_today_focus_is_silent_at_the_weekend():
    """The rotation rows only cover Monday to Friday. Saturday is off-plan, and
    that is different from the Wednesday the plan calls Rest."""
    saturday = program_week_for(START, routine=routine(CTF), today=day_of(1, 5))
    assert saturday.week == 1
    assert saturday.today_focus is None
    wednesday = program_week_for(START, routine=routine(CTF), today=day_of(1, 2))
    assert wednesday.today_focus == "Rest"
    assert is_rest_label(wednesday.today_focus)


def test_accepts_a_bare_date_or_an_iso_string_as_the_start():
    assert program_week_for("2026-01-05", routine=routine(CTF), today=day_of(2)).week == 2
    assert program_week_for(START, routine=routine(CTF), today=day_of(2)).week == 2
    given = program_week_for(START, routine=routine(CTF), today=START)
    assert given.start.source is StartSource.PREF


# ─────────────────────────────────────────────────────────────────────────
# phase changes
# ─────────────────────────────────────────────────────────────────────────


def test_the_phase_changes_on_the_monday_that_starts_week_four():
    last_of_phase_1 = program_week_for(START, routine=routine(CTF), today=day_of(3, 6))
    first_of_phase_2 = program_week_for(START, routine=routine(CTF), today=day_of(4))
    assert last_of_phase_1.phase.id == 1
    assert last_of_phase_1.week_in_phase == 3
    assert last_of_phase_1.weeks_left_in_phase == 0
    assert first_of_phase_2.phase.id == 2
    assert first_of_phase_2.week_in_phase == 1
    assert first_of_phase_2.week == 4


def test_week_in_phase_splits_the_six_weeks_of_phase_seven():
    """Phase 7 names its days `W1-3:` and `W4-6:`. `week_in_phase` is how a
    view picks the right half without parsing those labels."""
    week_19 = program_week_for(START, routine=routine(CTF), today=day_of(19))
    week_22 = program_week_for(START, routine=routine(CTF), today=day_of(22))
    assert (week_19.phase.id, week_19.week_in_phase) == (7, 1)
    assert (week_22.phase.id, week_22.week_in_phase) == (7, 4)
    assert week_19.phase_length == 6


def test_the_deload_week_has_no_rotation():
    """Phase 4 trains three full-body days that the rotation never names."""
    result = program_week_for(START, routine=routine(CTF), today=day_of(10))
    assert result.phase.id == 4
    assert result.rotation is None
    assert result.rotation_index is None
    assert not result.has_rotation
    assert result.today_focus is None


# ─────────────────────────────────────────────────────────────────────────
# the rotation
# ─────────────────────────────────────────────────────────────────────────


def test_rotation_cycles_every_three_weeks_and_never_repeats_a_row():
    r = routine(CTF)
    seen = [
        program_week_for(START, routine=r, today=day_of(w)).rotation_index for w in range(1, 10)
    ]
    assert seen == [0, 1, 2, 0, 1, 2, 0, 1, 2]
    assert all(a != b for a, b in zip(seen, seen[1:], strict=False))


def test_rotation_index_is_program_anchored_but_still_opens_each_phase_on_row_zero():
    """True for `cambiatufisico` because its phases are three weeks long and
    the rotation has three rows. Stated as a test so the coincidence is not
    mistaken for the rule."""
    r = routine(CTF)
    for first_week_of_phase in (1, 4, 7):
        assert rotation_index_for_week(first_week_of_phase, r) == 0


def test_rotation_applies_exactly_to_the_phases_the_plan_view_hardcodes():
    """The tuple `views/plan.py` used to hardcode, kept here as the oracle.

    The view derives this from the day templates now. Comparing against the
    literal tuple on purpose: if the derivation ever drifts for the routine it
    was written against, this is what catches it."""
    r = routine(CTF)
    for phase in r.phases:
        assert rotation_applies_to(phase, r) is (phase.id in (1, 2, 3)), phase.id


def test_normalize_day_label_bridges_the_two_spellings():
    assert normalize_day_label("Chest-Biceps") == normalize_day_label("Chest - Biceps")
    assert normalize_day_label("Back-Triceps + Abs") == normalize_day_label("Back - Triceps")
    assert normalize_day_label("Shoulder-Leg + Abs") == normalize_day_label("Shoulder - Leg")
    # …and does not bridge phase 7's differently-scoped days.
    assert normalize_day_label("W1-3: Chest-Biceps") != normalize_day_label("Chest-Biceps")


def test_training_day_for_label_resolves_the_whole_rotation():
    r = routine(CTF)
    phase = phase_for_week(1, r)
    for row in r.week_rotation:
        for label in row:
            found = training_day_for_label(label, phase, r)
            if is_rest_label(label):
                assert found is None
            else:
                assert found is not None, label
                assert found.exercises


def test_training_day_for_label_refuses_a_phase_that_does_not_have_the_day():
    r = routine(CTF)
    assert training_day_for_label("Chest-Biceps", phase_for_week(19, r), r) is None
    assert training_day_for_label("Chest-Biceps", None, r) is None


# ─────────────────────────────────────────────────────────────────────────
# routines with no rotation
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rid", ["upper-lower", "push-pull-legs", "recomp-ppl-ul"])
def test_a_routine_without_a_rotation_still_knows_its_week_and_phase(rid):
    r = routine(rid)
    assert r.week_rotation is None
    result = program_week_for(START, routine=r, today=day_of(2))
    assert result.status is WeekStatus.ACTIVE
    assert result.week == 2
    assert result.phase is not None
    assert result.rotation is None
    assert result.rotation_index is None
    assert result.today_focus is None
    assert result.focus_for(0) is None
    assert all(not rotation_applies_to(p, r) for p in r.phases)


def test_upper_lower_changes_phase_at_week_seven():
    r = routine("upper-lower")
    assert program_week_for(START, routine=r, today=day_of(6)).phase.id == 1
    assert program_week_for(START, routine=r, today=day_of(7)).phase.id == 2


# ─────────────────────────────────────────────────────────────────────────
# the end of the program
# ─────────────────────────────────────────────────────────────────────────


def test_the_week_after_the_last_one_is_finished_not_recycled():
    r = routine(CTF)
    last = program_week_for(START, routine=r, today=day_of(24))
    over = program_week_for(START, routine=r, today=day_of(25))
    assert last.status is WeekStatus.ACTIVE
    assert last.week == 24
    assert over.status is WeekStatus.FINISHED
    assert over.week == 25  # not clamped: "week 25 of 24" is the message
    assert over.total_weeks == 24
    assert over.phase is None
    assert over.rotation is None
    assert over.week_in_phase is None
    assert over.weeks_left_in_phase is None
    assert over.today_focus is None


def test_finished_stays_finished_a_year_later():
    result = program_week_for(START, routine=routine(CTF), today=day_of(80))
    assert result.status is WeekStatus.FINISHED
    assert result.week == 80


def test_a_six_week_routine_finishes_in_week_seven():
    result = program_week_for(START, routine=routine("recomp-ppl-ul"), today=day_of(7))
    assert result.status is WeekStatus.FINISHED
    assert result.total_weeks == 6


# ─────────────────────────────────────────────────────────────────────────
# skipped weeks: the number holds, the staleness flag speaks
# ─────────────────────────────────────────────────────────────────────────


def test_the_week_advances_with_the_calendar_not_with_the_sessions():
    """Ten days off means two weeks further in, not two weeks behind."""
    result = program_week_for(
        START, routine=routine(CTF), today=day_of(6), last_workout=day_of(4, 1)
    )
    assert result.week == 6
    assert result.weeks_idle == 2
    assert result.stale


def test_a_normal_week_is_not_stale():
    trained = program_week_for(
        START, routine=routine(CTF), today=day_of(6, 3), last_workout=day_of(6, 1)
    )
    assert trained.weeks_idle == 0
    assert not trained.stale

    monday = program_week_for(
        START, routine=routine(CTF), today=day_of(7), last_workout=day_of(6, 4)
    )
    assert monday.weeks_idle == 1
    assert not monday.stale  # Monday morning, before this week's first session


def test_staleness_is_silent_without_a_history():
    result = program_week_for(START, routine=routine(CTF), today=day_of(6))
    assert result.weeks_idle is None
    assert not result.stale


def test_first_and_last_workout_dates():
    rows = [entry(day_of(3, 1)), entry(day_of(1)), entry(day_of(2, 4))]
    assert first_workout_date(rows) == START
    assert last_workout_date(rows, today=day_of(9)) == day_of(3, 1)
    assert first_workout_date([]) is None
    assert last_workout_date([], today=START) is None


def test_a_future_dated_row_cannot_reset_the_idle_counter():
    rows = [entry(day_of(2)), entry(day_of(40))]
    assert last_workout_date(rows, today=day_of(6)) == day_of(2)


def test_history_rows_may_be_dicts_or_dataclasses():
    @dataclass
    class Row:
        date: str

    rows = [Row(day_of(2).isoformat()), entry(day_of(3))]
    assert first_workout_date(rows) == day_of(2)


# ─────────────────────────────────────────────────────────────────────────
# store adapter
# ─────────────────────────────────────────────────────────────────────────


def test_set_then_load_round_trips_through_the_store():
    store = FakeStore()
    assert set_program_start(store, START, routine=routine(CTF)) == START
    assert store.prefs[PROGRAM_START_PREF_KEY] == f"{CTF}|2026-01-05"

    start = load_program_start(store, routine=routine(CTF))
    assert start.source is StartSource.PREF
    assert start.day == START


def test_set_program_start_accepts_an_iso_string_and_rejects_junk():
    store = FakeStore()
    assert set_program_start(store, "2026-01-05", routine=routine(CTF)) == START
    with pytest.raises(ValueError, match="not a date"):
        set_program_start(store, "next monday", routine=routine(CTF))


def test_load_falls_back_to_the_history_without_touching_the_pref():
    store = FakeStore(entries=[entry(day_of(2, 1)), entry(day_of(1, 3))])
    start = load_program_start(store, routine=routine(CTF))
    assert start.source is StartSource.FIRST_WORKOUT
    assert start.day == day_of(1, 3)


def test_load_does_not_scan_the_history_once_a_date_is_stored():
    """One row read on the common path. `build()` is a pure render and views
    will call this often."""

    class Exploding(FakeStore):
        def get_all(self):
            raise AssertionError("history scanned even though the start date is stored")

    store = Exploding(prefs={PROGRAM_START_PREF_KEY: encode_program_start(START, routine(CTF))})
    assert load_program_start(store, routine=routine(CTF)).day == START


def test_current_program_week_end_to_end():
    store = FakeStore(entries=[entry(day_of(1, 1)), entry(day_of(4, 2))])
    set_program_start(store, START, routine=routine(CTF))
    result = current_program_week(store, routine=routine(CTF), today=day_of(6, 2))
    assert result.status is WeekStatus.ACTIVE
    assert result.week == 6
    assert result.phase.id == 2
    assert result.rotation_index == 2
    assert result.weeks_idle == 2
    assert result.stale
    assert result.routine_id == CTF


def test_current_program_week_defaults_to_the_active_routine():
    data.set_active_routine(CTF)
    store = FakeStore()
    set_program_start(store, START)
    result = current_program_week(store, today=day_of(2))
    assert result.routine_id == CTF
    assert result.week == 2


def test_switching_routine_invalidates_the_stored_start_through_the_store():
    store = FakeStore(entries=[entry(day_of(1))])
    set_program_start(store, START, routine=routine(CTF))
    result = current_program_week(store, routine=routine("push-pull-legs"), today=day_of(3))
    assert result.status is WeekStatus.UNKNOWN
    assert result.start.source is StartSource.OTHER_ROUTINE
    assert result.start.stored_routine_id == CTF


def test_clear_program_start_forgets_without_deleting_the_row():
    store = FakeStore()
    set_program_start(store, START, routine=routine(CTF))
    clear_program_start(store)
    assert store.prefs[PROGRAM_START_PREF_KEY] == ""
    assert load_program_start(store, routine=routine(CTF)).source is StartSource.UNKNOWN


def test_entries_can_be_supplied_so_the_store_is_read_once():
    store = FakeStore()
    result = current_program_week(
        store, routine=routine(CTF), today=day_of(3), entries=[entry(day_of(1))]
    )
    assert result.week == 3
    assert result.start.source is StartSource.FIRST_WORKOUT


# ─────────────────────────────────────────────────────────────────────────
# view-facing API — the three names views/plan.py imports
# ─────────────────────────────────────────────────────────────────────────


def test_current_week_is_none_for_every_flavour_of_not_knowing():
    """One `None` so a screen cannot render week 0 by forgetting a branch."""
    empty = FakeStore()
    assert current_week(empty, routine=routine(CTF), today=day_of(3)) is None

    scheduled = FakeStore()
    set_program_start(scheduled, day_of(4), routine=routine(CTF))
    assert current_week(scheduled, routine=routine(CTF), today=START) is None

    other = FakeStore(entries=[entry(day_of(1))])
    set_program_start(other, START, routine=routine(CTF))
    assert current_week(other, routine=routine("upper-lower"), today=day_of(3)) is None


def test_current_week_still_answers_after_the_program_ends():
    """Finished is not unknown: `week` set, `phase` None is what views/plan.py
    reads as "the program ran off its own end"."""
    store = FakeStore()
    set_program_start(store, START, routine=routine(CTF))
    week = current_week(store, routine=routine(CTF), today=day_of(26))
    assert week is not None
    assert week.week == 26
    assert week.phase is None


def test_current_week_carries_what_the_plan_screen_reads():
    store = FakeStore()
    set_program_start(store, START, routine=routine(CTF))
    week = current_week(store, routine=routine(CTF), today=day_of(5, 3))
    assert week is not None
    assert week.week == 5
    assert week.phase.id == 2
    assert week.rotation_index == 1


def test_week_rotation_for_returns_this_weeks_row():
    store = FakeStore()
    set_program_start(store, START, routine=routine(CTF))
    labels = week_rotation_for(store, routine=routine(CTF), today=day_of(2, 3))
    assert labels == list(data.WEEK_ROTATION[1])
    assert isinstance(labels, list)  # views mutate/slice it; a tuple would bite


@pytest.mark.parametrize(
    ("rid", "today", "why"),
    [
        (CTF, 10, "phase 4 has full-body days the rotation never names"),
        (CTF, 26, "the program is over"),
        ("upper-lower", 2, "the routine has no rotation at all"),
    ],
)
def test_week_rotation_for_is_none_when_the_row_would_be_a_lie(rid, today, why):
    store = FakeStore()
    set_program_start(store, START, routine=routine(rid))
    assert week_rotation_for(store, routine=routine(rid), today=day_of(today)) is None, why


def test_week_rotation_for_is_none_without_a_start_date():
    assert week_rotation_for(FakeStore(), routine=routine(CTF), today=day_of(2)) is None


def test_set_start_date_is_the_same_write_as_set_program_start():
    a, b = FakeStore(), FakeStore()
    set_start_date(a, START, routine=routine(CTF))
    set_program_start(b, START, routine=routine(CTF))
    assert a.prefs == b.prefs


def test_the_view_facing_calls_do_not_scan_the_history_once_the_date_is_pinned():
    """`read_week()` in views/plan.py calls both on every render."""

    class Exploding(FakeStore):
        def get_all(self):
            raise AssertionError("history scanned on a render")

    store = Exploding()
    set_start_date(store, START, routine=routine(CTF))
    assert current_week(store, routine=routine(CTF), today=day_of(2)).week == 2
    assert week_rotation_for(store, routine=routine(CTF), today=day_of(2))


def test_program_start_is_not_ephemeral_and_survives_a_backup():
    """The draft is scratch state and `backup.py` drops it. This one is user
    data: forgetting it on a restore means forgetting where the program is."""
    from workout_draft import EPHEMERAL_PREF_KEYS

    assert PROGRAM_START_PREF_KEY not in EPHEMERAL_PREF_KEYS


def test_program_start_dataclass_is_immutable():
    """Frozen on purpose: a view holds one of these across a render and must
    not be able to edit the date it is displaying."""
    start = ProgramStart(START, StartSource.PREF)
    with pytest.raises(AttributeError):
        start.day = date(2020, 1, 1)
