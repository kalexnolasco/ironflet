"""Guards for the workout draft — the layer that makes a session survive.

The bug it fixes is silent by nature: nothing raised when `self.sets` was reset,
the numbers were simply gone. So every test here asserts the *degradation*, not
just the happy path. The rule the whole module lives by is that a draft which
cannot be restored produces `None` — never an exception, never a half-restored
session pointing at an exercise that no longer exists.

Almost nothing here needs PostgreSQL: `DraftStore` only ever calls `get_pref`
and `set_pref`, so a dict-backed fake covers the logic exactly. One test does go
through a real `Storage` — twice, through two separate instances — because
"survives a restart of the service" is the claim and only the database can back
it up.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pytest

from data import Phase, Routine, TrainingDay, set_active_routine
from set_types import TYPE_KEY, SetType
from workout_draft import (
    DRAFT_PREF_KEY,
    DRAFT_TTL_S,
    DRAFT_VERSION,
    MAX_BACKDATE_DAYS,
    MAX_DATED_EXERCISES,
    MIN_WRITE_INTERVAL_S,
    DateSource,
    DraftStore,
    LogDate,
    WorkoutDraft,
    blank_row,
    clamp_log_date,
    decode_draft,
    encode_draft,
    fit_to_routine,
    is_blank_row,
    normalize_row,
    rows_from_last_sets,
)

# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    """Just the two `Storage` methods this module is allowed to use.

    `fail_get` / `fail_set` reproduce the database being unreachable, which in
    web mode is a normal Tuesday: the app talks to PostgreSQL over the network.
    """

    def __init__(self, fail_get: bool = False, fail_set: bool = False):
        self.prefs: dict[str, str] = {}
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.writes = 0

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        if self.fail_get:
            raise RuntimeError("database unreachable")
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        if self.fail_set:
            raise RuntimeError("database unreachable")
        self.writes += 1
        self.prefs[key] = value


class Clock:
    """A clock that only moves when a test says so."""

    def __init__(self, t: float = 1_700_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def a_phase(pid: int, name: str) -> Phase:
    return Phase(pid, "1-3", name, "sub", "#00D4AA", "3×12", "1'", "notes", "high")


PUSH = TrainingDay("Push", ["Bench Press [4×8-10]", "Overhead Press", "Triceps Pushdown*"])
PULL = TrainingDay("Pull", ["Barbell Row [4×8]", "Lat Pulldown", "Barbell Curl"])


def a_routine(days: list[TrainingDay] | None = None, phases: list[Phase] | None = None) -> Routine:
    """A routine under the test's control, so edits can be simulated."""
    return Routine(
        id="test-routine",
        name="Test Routine",
        description="fixture",
        phases=phases if phases is not None else [a_phase(1, "Base"), a_phase(2, "Peak")],
        days_by_phase={1: list(days if days is not None else [PUSH, PULL]), 2: [PUSH]},
    )


def a_draft(**overrides) -> WorkoutDraft:
    """A believable mid-session draft: two exercises typed, one already logged."""
    base = {
        "routine_id": "test-routine",
        "phase_id": 1,
        "day_idx": 0,
        "day_name": "Push",
        "ex_idx": 1,
        "exercise": "Overhead Press",
        "pending": {
            "Bench Press": [
                {"weight": "60", "reps": "10", "rir": "2", TYPE_KEY: SetType.NORMAL.value},
                {"weight": "65", "reps": "8", "rir": "", TYPE_KEY: SetType.FAILURE.value},
            ],
            "Overhead Press": [
                {"weight": "32.5", "reps": "", "rir": "", TYPE_KEY: SetType.WARMUP.value},
            ],
        },
        "completed": [{"exercise": "Bench Press", "sets": [{"weight": 60.0, "reps": 10}]}],
        "started_at": 1_699_999_000.0,
        "saved_at": 1_700_000_000.0,
    }
    base.update(overrides)
    return WorkoutDraft(**base)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def drafts(store: FakeStore, clock: Clock) -> DraftStore:
    return DraftStore(store, clock=clock)


def stored(store: FakeStore) -> dict:
    return json.loads(store.prefs[DRAFT_PREF_KEY])


def rewrite(store: FakeStore, **fields) -> None:
    """Tamper with the stored payload — how a foreign/older writer looks."""
    payload = stored(store)
    payload.update(fields)
    store.prefs[DRAFT_PREF_KEY] = json.dumps(payload)


# ── round trip ───────────────────────────────────────────────────────────


def test_round_trip_restores_the_whole_session(drafts, store, clock):
    """The point of the module: nothing typed is lost across a save/load."""
    routine = a_routine()
    original = a_draft(saved_at=clock.t)
    assert drafts.save(original, force=True) is True

    back = drafts.load(routine)
    assert back is not None
    assert back.routine_id == "test-routine"
    assert back.phase_id == 1
    assert back.day_idx == 0
    assert back.day_name == "Push"
    assert back.ex_idx == 1
    assert back.exercise == "Overhead Press"
    assert back.completed == original.completed
    assert back.started_at == original.started_at
    # The half-written rows are the thing that used to vanish on exercise change.
    assert back.pending["Bench Press"][0] == {
        "weight": "60",
        "reps": "10",
        "rir": "2",
        TYPE_KEY: "normal",
    }
    assert back.pending["Bench Press"][1][TYPE_KEY] == "failure"
    assert back.pending["Overhead Press"][0] == {
        "weight": "32.5",
        "reps": "",
        "rir": "",
        TYPE_KEY: "warmup",
    }
    assert back.dropped == ()


def test_rows_for_returns_a_detached_copy(drafts, store, clock):
    """`self.sets` is mutated per keystroke; aliasing would hide every change."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    back = drafts.load(a_routine())
    rows = back.rows_for("Bench Press")
    rows[0]["weight"] = "999"
    assert back.pending["Bench Press"][0]["weight"] == "60"


def test_rows_for_unknown_exercise_is_one_blank_row(drafts, store, clock):
    drafts.save(a_draft(saved_at=clock.t), force=True)
    back = drafts.load(a_routine())
    assert back.rows_for("Lateral Raise") == [blank_row()]


def test_clear_forgets_everything(drafts, store, clock):
    drafts.save(a_draft(saved_at=clock.t), force=True)
    drafts.clear()
    assert drafts.load(a_routine()) is None


# ── expiry ───────────────────────────────────────────────────────────────


def test_draft_from_twenty_minutes_ago_is_restored(drafts, store, clock):
    """ "Me fui a por agua" — the case the whole TTL exists to protect."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    clock.advance(20 * 60)
    assert drafts.load(a_routine()) is not None


def test_draft_just_inside_the_ttl_is_restored(drafts, store, clock):
    drafts.save(a_draft(saved_at=clock.t), force=True)
    clock.advance(DRAFT_TTL_S - 1)
    assert drafts.load(a_routine()) is not None


def test_expired_draft_is_dropped_and_the_row_wiped(drafts, store, clock):
    """A three-day-old draft must not come back as "workout in progress"."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    clock.advance(3 * 24 * 3600)
    assert drafts.load(a_routine()) is None
    # Wiped, not merely ignored: otherwise it is re-parsed on every launch.
    assert not store.prefs[DRAFT_PREF_KEY]


def test_draft_stamped_in_the_future_is_dropped(drafts, store, clock):
    """A clock that jumped cannot be trusted to ever expire the draft."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(store, saved_at=clock.t + 10 * 3600)
    assert drafts.load(a_routine()) is None


def test_small_clock_skew_is_tolerated(drafts, store, clock):
    """Phone and server drift by seconds; that is not a corrupt draft."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(store, saved_at=clock.t + 30)
    assert drafts.load(a_routine()) is not None


# ── the routine changed underneath ───────────────────────────────────────


def test_unknown_routine_id_yields_nothing(drafts, store, clock):
    drafts.save(a_draft(routine_id="deleted-routine", saved_at=clock.t), force=True)
    assert drafts.load(a_routine()) is None


def test_switching_routine_does_not_resume_the_old_session(drafts, store, clock):
    """Choosing another routine in Plan is deliberate; the app must not argue."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    other = a_routine()
    other.id = "another-routine"
    assert drafts.load(other) is None


def test_phase_that_no_longer_exists_yields_nothing(drafts, store, clock):
    drafts.save(a_draft(phase_id=2, day_name="Push", saved_at=clock.t), force=True)
    assert drafts.load(a_routine(phases=[a_phase(1, "Base")])) is None


def test_day_removed_from_the_routine_yields_nothing(drafts, store, clock):
    """Not "fall back to day 0": that would start a workout Alex never chose."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    assert drafts.load(a_routine(days=[PULL])) is None


def test_day_index_out_of_range_yields_nothing(drafts, store, clock):
    drafts.save(a_draft(day_idx=7, day_name="", saved_at=clock.t), force=True)
    assert drafts.load(a_routine()) is None


def test_reordered_days_are_found_by_name(drafts, store, clock):
    """Index 0 is now Pull; the draft has to follow Push to index 1."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    back = drafts.load(a_routine(days=[PULL, PUSH]))
    assert back is not None
    assert back.day_idx == 1
    assert back.day_name == "Push"


def test_reordered_exercises_relocate_the_current_one(drafts, store, clock):
    """Overhead Press moved to the front: the draft points at it, not at 1."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    shuffled = TrainingDay("Push", ["Overhead Press", "Bench Press [4×8-10]", "Triceps Pushdown*"])
    back = drafts.load(a_routine(days=[shuffled, PULL]))
    assert back is not None
    assert back.ex_idx == 0
    assert back.exercise == "Overhead Press"
    assert back.pending["Bench Press"][0]["weight"] == "60"


def test_rows_of_a_deleted_exercise_are_dropped_not_shifted(drafts, store, clock):
    """The weights must never reappear under a different lift."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    trimmed = TrainingDay("Push", ["Overhead Press", "Triceps Pushdown*"])
    back = drafts.load(a_routine(days=[trimmed, PULL]))
    assert back is not None
    assert "Bench Press" not in back.pending
    assert back.dropped == ("Bench Press",)
    # What still exists is untouched.
    assert back.pending["Overhead Press"][0]["weight"] == "32.5"
    assert back.ex_idx == 0


def test_current_exercise_gone_clamps_into_range(drafts, store, clock):
    """Landing somewhere valid beats landing on index 5 of a 2-exercise day."""
    drafts.save(a_draft(ex_idx=2, exercise="Triceps Pushdown", saved_at=clock.t), force=True)
    shrunk = TrainingDay("Push", ["Bench Press [4×8-10]"])
    back = drafts.load(a_routine(days=[shrunk, PULL]))
    assert back is not None
    assert back.ex_idx == 0
    assert back.exercise == "Bench Press"


def test_day_emptied_of_exercises_yields_nothing(drafts, store, clock):
    drafts.save(a_draft(saved_at=clock.t), force=True)
    assert drafts.load(a_routine(days=[TrainingDay("Push", []), PULL])) is None


def test_exercise_key_brackets_do_not_break_the_match(drafts, store, clock):
    """Drafts store the DB key, routines store `Squat [5×5]`. Same exercise."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rescheme = TrainingDay(
        "Push", ["Bench Press [5×5]", "Overhead Press [3×12] [comp]", "Triceps Pushdown"]
    )
    back = drafts.load(a_routine(days=[rescheme, PULL]))
    assert back is not None
    assert back.ex_idx == 1
    assert set(back.pending) == {"Bench Press", "Overhead Press"}


def test_fit_defaults_to_the_active_routine():
    """No explicit routine → `data.active_routine()`, as the view will call it."""
    set_active_routine("cambiatufisico")
    draft = a_draft(routine_id="cambiatufisico")
    assert fit_to_routine(draft) is None  # its day/exercises are not in there
    assert fit_to_routine(a_draft()) is None


# ── corrupt, truncated, foreign ──────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not json at all",
        '{"v":1,"routine":"test-routine","pha',  # truncated mid-write
        "[]",
        '"a string"',
        "42",
        "null",
        "{}",
    ],
)
def test_garbage_never_raises_and_never_restores(drafts, store, raw):
    store.prefs[DRAFT_PREF_KEY] = raw
    assert drafts.load(a_routine()) is None
    assert not store.prefs[DRAFT_PREF_KEY]


@pytest.mark.parametrize(
    "field, value",
    [
        ("routine", None),
        ("routine", ""),
        ("routine", 7),
        ("phase", "1"),
        ("phase", None),
        ("phase", 0),
        ("phase", True),  # bool is an int subclass — must not read as phase 1
        ("day_idx", -1),
        ("day_idx", "0"),
        ("ex_idx", None),
        ("day", None),
        ("day", 3),
        ("exercise", None),
        ("saved_at", "yesterday"),
        ("saved_at", None),
        ("pending", []),
        ("pending", "rows"),
        ("pending", None),
    ],
)
def test_structurally_wrong_fields_discard_the_whole_draft(drafts, store, clock, field, value):
    """Half a draft is worse than none: it would point somewhere wrong."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(store, **{field: value})
    assert drafts.load(a_routine()) is None


@pytest.mark.parametrize("version", [0, 3, 99, "1", None, True])
def test_unknown_version_is_discarded_whole(drafts, store, clock, version):
    """A draft from another build is never read field by field.

    Version 1 is the one documented exception and has its own tests below; a
    format from the future is still refused, because guessing at a shape nobody
    here has seen is exactly what this rule exists to prevent.
    """
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(store, v=version)
    assert drafts.load(a_routine()) is None
    assert not store.prefs[DRAFT_PREF_KEY]


def test_current_version_is_written(drafts, store, clock):
    drafts.save(a_draft(saved_at=clock.t), force=True)
    assert stored(store)["v"] == DRAFT_VERSION


def test_oversized_payload_is_refused(drafts, store):
    store.prefs[DRAFT_PREF_KEY] = "x" * 300_000
    assert drafts.load(a_routine()) is None


# ── damaged rows degrade one row at a time ───────────────────────────────


def test_junk_rows_are_dropped_but_good_ones_survive(drafts, store, clock):
    """One bad row among twelve is worth losing on its own, not all twelve."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(
        store,
        pending={
            "Bench Press": [
                {"weight": "60", "reps": "10"},
                "not a row",
                None,
                42,
                {"weight": ["nested"], "reps": {"x": 1}},
                {"weight": 65, "reps": 8, "rir": 1.5, TYPE_KEY: "wat"},
            ],
            "": [{"weight": "10", "reps": "10"}],  # unusable key
            "Overhead Press": "not a list",
        },
    )
    back = drafts.load(a_routine())
    assert back is not None
    rows = back.pending["Bench Press"]
    assert len(rows) == 3  # the string, the None and the bare int are gone
    assert rows[0] == {"weight": "60", "reps": "10", "rir": "", TYPE_KEY: "normal"}
    assert rows[1] == blank_row()  # containers become empty fields, not "['x']"
    # Numbers written by some other writer still read as the text a field held,
    # and an unknown set type degrades to normal exactly like everywhere else.
    assert rows[2] == {"weight": "65", "reps": "8", "rir": "1.5", TYPE_KEY: "normal"}
    assert "" not in back.pending
    assert "Overhead Press" not in back.pending


def test_junk_completed_entries_are_dropped(drafts, store, clock):
    """These are already in `entrenos`; losing one costs the summary, not data."""
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(
        store,
        completed=[
            {"exercise": "Bench Press", "sets": [{"weight": 60.0, "reps": 10}, "junk"]},
            {"exercise": "", "sets": []},
            {"sets": []},
            {"exercise": "Row", "sets": "nope"},
            "not an entry",
        ],
    )
    back = drafts.load(a_routine())
    assert back is not None
    assert back.completed == [{"exercise": "Bench Press", "sets": [{"weight": 60.0, "reps": 10}]}]
    # Stored numbers stay numbers: the finished screen formats them with `:g`.
    assert isinstance(back.completed[0]["sets"][0]["weight"], float)


def test_completed_survives_even_when_every_row_is_dropped(drafts, store, clock):
    """The exercises already logged do not depend on the routine still listing them."""
    draft = a_draft(pending={}, ex_idx=0, exercise="Bench Press")
    draft.saved_at = clock.t
    drafts.save(draft, force=True)
    back = drafts.load(a_routine())
    assert back is not None
    assert back.completed


# ── storage failures ─────────────────────────────────────────────────────


def test_unreachable_database_on_read_is_not_an_exception(clock):
    """Web mode talks to PostgreSQL over the network. A blip is not a crash."""
    d = DraftStore(FakeStore(fail_get=True), clock=clock)
    assert d.load(a_routine()) is None


def test_unreachable_database_on_write_is_not_an_exception(clock):
    d = DraftStore(FakeStore(fail_set=True), clock=clock)
    assert d.save(a_draft(saved_at=clock.t), force=True) is False
    d.clear()  # must not raise either


def test_a_draft_the_json_encoder_chokes_on_is_refused_quietly(drafts, store, clock):
    """Nothing reaching this layer may take the workout screen down with it."""
    broken = a_draft(saved_at=clock.t)
    broken.completed = [{"exercise": "Bench Press", "sets": [{"weight": {1, 2}}]}]
    assert drafts.save(broken, force=True) is False
    assert DRAFT_PREF_KEY not in store.prefs


def test_a_draft_with_a_wrongly_typed_field_is_refused_quietly(drafts, store, clock):
    broken = a_draft(saved_at=clock.t)
    broken.phase_id = None
    assert drafts.save(broken, force=True) is False


def test_failed_write_is_retried_next_time(clock):
    """A dropped write must not be remembered as written."""
    store = FakeStore(fail_set=True)
    d = DraftStore(store, clock=clock)
    draft = a_draft(saved_at=clock.t)
    assert d.save(draft, force=True) is False
    store.fail_set = False
    assert d.save(draft, force=True) is True


# ── write policy ─────────────────────────────────────────────────────────


def test_typing_coalesces_into_one_write(drafts, store, clock):
    """`on_change` fires per character; one UPDATE per digit is not acceptable."""
    draft = a_draft(saved_at=clock.t)
    for i, keystroke in enumerate("6075"):
        draft = draft.with_rows("Bench Press", [{**blank_row(), "weight": keystroke * (i + 1)}])
        drafts.save(draft)
        clock.advance(0.2)
    assert store.writes == 1


def test_the_next_keystroke_after_the_interval_lands(drafts, store, clock):
    draft = a_draft(saved_at=clock.t)
    drafts.save(draft)
    clock.advance(MIN_WRITE_INTERVAL_S + 0.1)
    draft = draft.with_rows("Bench Press", [{**blank_row(), "weight": "80"}])
    assert drafts.save(draft) is True


def test_force_bypasses_the_interval(drafts, store, clock):
    """Adding a set, changing exercise, backgrounding: those land immediately."""
    draft = a_draft(saved_at=clock.t)
    assert drafts.save(draft, force=True) is True
    draft = draft.with_rows("Overhead Press", [{**blank_row(), "weight": "40", "reps": "8"}])
    assert drafts.save(draft, force=True) is True
    assert store.writes == 2


def test_unchanged_content_is_never_rewritten(drafts, store, clock):
    """`refresh_current()` re-renders constantly; each rebuild must be free."""
    draft = a_draft(saved_at=clock.t)
    drafts.save(draft, force=True)
    for _ in range(5):
        clock.advance(60)
        assert drafts.save(draft, force=True) is False
    assert store.writes == 1


def test_an_empty_draft_is_cleared_rather_than_stored(drafts, store, clock):
    """No phantom "resume workout?" for a day that was opened and abandoned."""
    empty = a_draft(pending={}, completed=[], ex_idx=0, exercise="Bench Press")
    assert drafts.save(empty, force=True) is False
    assert drafts.load(a_routine()) is None


def test_a_draft_with_only_blank_rows_is_empty(drafts, store, clock):
    empty = a_draft(
        pending={"Bench Press": [blank_row(), blank_row()]},
        completed=[],
        ex_idx=0,
        exercise="Bench Press",
    )
    assert empty.is_empty() is True
    assert drafts.save(empty, force=True) is False


def test_being_parked_on_a_later_exercise_is_worth_saving(drafts, store, clock):
    """ "Moverlo por casualidad" — position alone is progress worth restoring."""
    parked = a_draft(pending={}, completed=[], ex_idx=2, exercise="Triceps Pushdown")
    parked.saved_at = clock.t
    assert parked.is_empty() is False
    assert drafts.save(parked, force=True) is True
    back = drafts.load(a_routine())
    assert back is not None and back.ex_idx == 2


def test_deleting_the_last_typed_row_erases_the_draft(drafts, store, clock):
    """Clearing the fields must persist as "nothing", not as stale numbers."""
    draft = a_draft(pending={}, completed=[], ex_idx=0, exercise="Bench Press")
    draft = draft.with_rows("Bench Press", [{**blank_row(), "weight": "60"}])
    draft.saved_at = clock.t
    assert drafts.save(draft, force=True) is True
    cleared = draft.with_rows("Bench Press", [blank_row()])
    assert drafts.save(cleared, force=True) is False
    assert drafts.load(a_routine()) is None


def test_with_rows_keeps_partially_filled_lists_intact(clock):
    """Five rows added, three filled in: the two empty ones are still there."""
    rows = [
        {**blank_row(), "weight": "60", "reps": "10"},
        blank_row(),
        {**blank_row(), "weight": "65"},
    ]
    draft = a_draft().with_rows("Bench Press", rows)
    assert len(draft.pending["Bench Press"]) == 3
    assert draft.pending["Bench Press"][1] == blank_row()


def test_with_rows_does_not_alias_the_caller_list(clock):
    rows = [{**blank_row(), "weight": "60"}]
    draft = a_draft().with_rows("Bench Press", rows)
    rows[0]["weight"] = "999"
    assert draft.pending["Bench Press"][0]["weight"] == "60"


# ── row helpers ──────────────────────────────────────────────────────────


def test_blank_row_shape_matches_what_the_view_stores():
    """Contract with `views/workout.py::_blank_set` — all strings, type present."""
    row = blank_row()
    assert set(row) == {"weight", "reps", "rir", TYPE_KEY}
    assert all(isinstance(v, str) for v in row.values())
    assert row[TYPE_KEY] == SetType.NORMAL.value
    assert is_blank_row(row)


def test_a_row_with_only_a_type_is_still_blank():
    assert is_blank_row({**blank_row(), TYPE_KEY: SetType.WARMUP.value})
    assert not is_blank_row({**blank_row(), "reps": "8"})
    assert is_blank_row(None)
    assert is_blank_row("nope")


def test_normalize_row_rejects_non_dicts():
    assert normalize_row([1, 2]) is None
    assert normalize_row(None) is None
    assert normalize_row({"weight": "60"}) == {
        "weight": "60",
        "reps": "",
        "rir": "",
        TYPE_KEY: "normal",
    }


def test_normalize_row_drops_unknown_keys():
    """One writer, one shape — unlike `entrenos.series`, which three programs write."""
    row = normalize_row({"weight": "60", "tempo": "3-1-1", "notes": "felt heavy"})
    assert set(row) == {"weight", "reps", "rir", TYPE_KEY}


def test_rows_from_last_sets_prefills_instead_of_hinting():
    """The second half of the complaint: the number was visible but not usable."""
    rows = rows_from_last_sets(
        [
            {"weight": 20.0, "reps": 12, TYPE_KEY: "warmup"},
            {"weight": 60.0, "reps": 10, "rir": 2},
            {"weight": 62.5, "reps": 8},
        ]
    )
    assert rows == [
        {"weight": "20", "reps": "12", "rir": "", TYPE_KEY: "warmup"},
        {"weight": "60", "reps": "10", "rir": "2", TYPE_KEY: "normal"},
        {"weight": "62.5", "reps": "8", "rir": "", TYPE_KEY: "normal"},
    ]


def test_rows_from_last_sets_says_nothing_when_there_is_no_history():
    """`None`, not `[]`: "first time" is a different screen from "no sets"."""
    assert rows_from_last_sets(None) is None
    assert rows_from_last_sets([]) is None
    assert rows_from_last_sets(["junk", 3]) is None


# ── encode/decode edges reachable without the store ──────────────────────


def test_decode_of_a_freshly_encoded_draft_is_identity(clock):
    draft = a_draft(saved_at=clock.t)
    back = decode_draft(encode_draft(draft), now=clock.t)
    assert back == draft


def test_decode_never_raises_on_anything(clock):
    for raw in (None, 3, [], {}, b"bytes", "\x00\x01", '{"v":1}'):
        assert decode_draft(raw, now=clock.t) is None


# ── one logging date per exercise ────────────────────────────────────────
#
# Alex asked for a date per exercise after being told, plainly, that it is the
# easiest way there is to file a set under the wrong day without noticing. So
# these tests are not about dates being stored: they are about a date never
# being *silently* different from what he last saw. Every one of them asserts
# either that a choice is kept, or that losing it is reported and falls back to
# something the screen is already showing.


def today_of(clock: Clock) -> date:
    """The calendar day the module will read from that clock."""
    return date.fromtimestamp(clock.t)


def dated_draft(clock: Clock, **overrides) -> WorkoutDraft:
    """A draft with nothing in it but the dates a test cares about."""
    base = {
        "pending": {},
        "completed": [],
        "ex_idx": 0,
        "exercise": "Bench Press",
        "saved_at": clock.t,
    }
    base.update(overrides)
    return a_draft(**base)


# ── the default chain, and the fact that it is a value ───────────────────


def test_an_exercise_with_no_date_of_its_own_uses_the_session_date(clock):
    """The default is resolved here, once, not re-invented per caller."""
    today = today_of(clock)
    monday = today - timedelta(days=2)
    draft = dated_draft(clock, session_date=LogDate(monday, today))

    resolved = draft.resolve_date("Overhead Press", today)
    assert resolved.day == monday
    assert resolved.source is DateSource.SESSION
    assert draft.date_for("Overhead Press", today) == monday


def test_with_nothing_chosen_at_all_everything_logs_to_today(clock):
    today = today_of(clock)
    draft = dated_draft(clock)
    resolved = draft.resolve_date("Bench Press", today)
    assert resolved.day == today
    assert resolved.source is DateSource.TODAY
    assert resolved.is_explicit is False
    assert resolved.is_backdated(today) is False


def test_an_exercise_date_beats_the_session_date(clock):
    today = today_of(clock)
    monday, tuesday = today - timedelta(days=2), today - timedelta(days=1)
    draft = dated_draft(
        clock,
        session_date=LogDate(monday, today),
        dates={"Overhead Press": LogDate(tuesday, today)},
    )
    assert draft.date_for("Bench Press", today) == monday
    assert draft.date_for("Overhead Press", today) == tuesday
    assert draft.resolve_date("Overhead Press", today).source is DateSource.EXERCISE
    assert draft.is_backdated("Overhead Press", today) is True


def test_choosing_today_for_one_lift_of_a_backdated_session_is_recorded(clock):
    """The trap this API is shaped around.

    Session filed under Monday, and today's warm-up mobility work belongs to
    today. Dropping that pick because it "equals today" — the obvious
    optimisation — would move the lift back to Monday behind his back. The
    comparison is against the *effective default*, never against today.
    """
    today = today_of(clock)
    monday = today - timedelta(days=2)
    draft = dated_draft(clock, session_date=LogDate(monday, today))

    draft = draft.with_date("Overhead Press", today, chosen_on=today)
    assert draft.dates["Overhead Press"].day == today
    assert draft.date_for("Overhead Press", today) == today
    assert draft.resolve_date("Overhead Press", today).source is DateSource.EXERCISE
    # And the rest of the session is untouched by that override.
    assert draft.date_for("Bench Press", today) == monday


def test_choosing_the_default_again_stores_nothing(clock):
    """Picking today on a session that is already today is not a choice.

    Same rule `views/workout.py::_set_log_date` applies: the default state
    leaves nothing behind, so there is nothing to go stale tomorrow.
    """
    today = today_of(clock)
    draft = dated_draft(clock).with_date("Bench Press", today, chosen_on=today)
    assert draft.dates == {}
    assert draft.is_empty() is True

    monday = today - timedelta(days=2)
    backdated = dated_draft(clock, session_date=LogDate(monday, today))
    assert backdated.with_date("Bench Press", monday, chosen_on=today).dates == {}


# ── no future dates, and no ancient ones ─────────────────────────────────


def test_a_future_date_is_clamped_to_today(clock):
    """Not taste: `analytics` and `program_week` ignore rows dated forward."""
    today = today_of(clock)
    draft = dated_draft(clock).with_date("Bench Press", today + timedelta(days=3), chosen_on=today)
    # Clamped to today, which is the default, so nothing is recorded at all.
    assert draft.dates == {}
    assert draft.date_for("Bench Press", today) == today

    session = dated_draft(clock).with_session_date(today + timedelta(days=9), chosen_on=today)
    assert session.session_date is None


def test_a_date_older_than_the_window_is_clamped_to_the_window(clock):
    today = today_of(clock)
    floor = today - timedelta(days=MAX_BACKDATE_DAYS)
    draft = dated_draft(clock).with_date(
        "Bench Press", today - timedelta(days=400), chosen_on=today
    )
    assert draft.dates["Bench Press"].day == floor


@pytest.mark.parametrize("offset, expected_offset", [(-400, -MAX_BACKDATE_DAYS), (5, 0), (-3, -3)])
def test_clamp_log_date_is_the_one_rule(offset, expected_offset):
    today = date(2026, 8, 19)
    assert clamp_log_date(today + timedelta(days=offset), today) == today + timedelta(
        days=expected_offset
    )


# ── the calendar-day rule, N times over ──────────────────────────────────


def test_a_date_chosen_today_comes_back_on_a_restore(drafts, store, clock):
    today = today_of(clock)
    monday = today - timedelta(days=2)
    drafts.save(dated_draft(clock, dates={"Bench Press": LogDate(monday, today)}), force=True)

    back = drafts.load(a_routine())
    assert back is not None
    assert back.dates["Bench Press"] == LogDate(monday, today)
    assert back.stale_dates == ()


def test_a_date_chosen_yesterday_is_not_adopted_today(drafts, store, clock):
    """The rule the whole feature turns on.

    "I am logging Monday" is a statement about the day it was made on. Carried
    into the next morning it would file a fresh session two days back, with
    nothing on screen having changed to say so.
    """
    today = today_of(clock)
    yesterday = today - timedelta(days=1)
    monday = today - timedelta(days=2)
    drafts.save(
        dated_draft(
            clock,
            dates={"Bench Press": LogDate(monday, yesterday)},
            pending=a_draft().pending,
        ),
        force=True,
    )

    back = drafts.load(a_routine())
    assert back is not None
    assert back.dates == {}
    # Falls back to something the screen already shows — never to a third date.
    assert back.date_for("Bench Press", today) == today
    # The session it belonged to is not thrown away over it.
    assert back.pending["Bench Press"][0]["weight"] == "60"
    # And it is reported, because a lift that moved on its own is worth a word.
    assert back.stale_dates == ("Bench Press",)


def test_the_session_date_expires_the_same_way(drafts, store, clock):
    today = today_of(clock)
    yesterday = today - timedelta(days=1)
    drafts.save(
        dated_draft(
            clock,
            session_date=LogDate(yesterday, yesterday),
            pending=a_draft().pending,
        ),
        force=True,
    )

    back = drafts.load(a_routine())
    assert back is not None
    assert back.session_date is None
    assert back.session_date_stale is True
    assert back.date_for("Bench Press", today) == today


def test_a_fresh_pick_never_revives_a_forgotten_one(drafts, store, clock):
    """Why the stamp is per date and not one for the whole draft.

    A single shared stamp would be refreshed by today's pick and would carry
    yesterday's abandoned Monday along with it — one tap silently re-dating a
    lift nobody looked at.
    """
    today = today_of(clock)
    yesterday = today - timedelta(days=1)
    monday, tuesday = today - timedelta(days=2), today - timedelta(days=1)
    drafts.save(
        dated_draft(
            clock,
            dates={
                "Bench Press": LogDate(monday, yesterday),
                "Overhead Press": LogDate(tuesday, today),
            },
        ),
        force=True,
    )

    back = drafts.load(a_routine())
    assert back is not None
    assert back.stale_dates == ("Bench Press",)
    assert back.dates == {"Overhead Press": LogDate(tuesday, today)}
    assert back.date_for("Bench Press", today) == today


def test_a_hand_edited_future_date_is_refused_on_read(drafts, store, clock):
    today = today_of(clock)
    drafts.save(
        dated_draft(
            clock,
            dates={"Bench Press": LogDate(today, today)},
            pending=a_draft().pending,
        ),
        force=True,
    )
    rewrite(
        store,
        dates={
            "Bench Press": {
                "date": (today + timedelta(days=4)).isoformat(),
                "chosen_on": today.isoformat(),
            }
        },
    )
    back = drafts.load(a_routine())
    assert back is not None
    assert back.dates == {}
    assert back.stale_dates == ("Bench Press",)


def test_a_date_beyond_the_backdate_window_is_refused_on_read(drafts, store, clock):
    """`2025-08-16` for `2026-08-16` is one keystroke and a year of history."""
    today = today_of(clock)
    drafts.save(
        dated_draft(
            clock,
            dates={"Bench Press": LogDate(today, today)},
            pending=a_draft().pending,
        ),
        force=True,
    )
    rewrite(
        store,
        dates={
            "Bench Press": {
                "date": (today - timedelta(days=365)).isoformat(),
                "chosen_on": today.isoformat(),
            }
        },
    )
    back = drafts.load(a_routine())
    assert back is not None
    assert back.dates == {}
    assert back.stale_dates == ("Bench Press",)


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-17",
        {"date": "2026-08-17"},
        {"chosen_on": "2026-08-17"},
        {"date": "17/08/2026", "chosen_on": "17/08/2026"},
        {"date": 20260817, "chosen_on": 20260817},
        {"date": None, "chosen_on": None},
        [],
        None,
    ],
)
def test_a_malformed_date_costs_that_date_and_nothing_else(drafts, store, clock, value):
    """Dates degrade one entry at a time, like rows — not like `phase`.

    A date that cannot be read falls back to a default already on screen, so
    discarding the whole session over it would cost far more than it protects.
    """
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(store, dates={"Bench Press": value})
    back = drafts.load(a_routine())
    assert back is not None
    assert back.dates == {}
    assert back.stale_dates == ("Bench Press",)
    # The half-written rows — the thing this module exists for — are untouched.
    assert back.pending["Bench Press"][0]["weight"] == "60"


def test_a_wholly_junk_date_map_is_ignored_without_taking_the_draft(drafts, store, clock):
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(store, dates="not a map")
    back = drafts.load(a_routine())
    assert back is not None
    assert back.dates == {}
    assert back.stale_dates == ()


# ── keyed by name, pruned with the rows ──────────────────────────────────


def test_a_date_for_a_deleted_exercise_is_dropped_and_reported(clock):
    """A date left behind would wait to be inherited by the next lift renamed
    into that slot — a Monday attached to nothing."""
    today = today_of(clock)
    draft = dated_draft(
        clock,
        dates={"Lateral Raise": LogDate(today - timedelta(days=1), today)},
    )
    fitted = fit_to_routine(draft, a_routine())
    assert fitted is not None
    assert fitted.dates == {}
    assert "Lateral Raise" in fitted.dropped


def test_reordering_the_day_does_not_move_a_date_onto_another_lift(clock):
    today = today_of(clock)
    monday = today - timedelta(days=2)
    draft = dated_draft(clock, dates={"Overhead Press": LogDate(monday, today)})
    reordered = TrainingDay("Push", ["Triceps Pushdown*", "Overhead Press", "Bench Press [4×8-10]"])
    fitted = fit_to_routine(draft, a_routine(days=[reordered, PULL]))
    assert fitted is not None
    assert fitted.dates == {"Overhead Press": LogDate(monday, today)}
    assert fitted.date_for("Bench Press", today) == today


def test_the_date_map_is_capped(clock):
    today = today_of(clock)
    day = today - timedelta(days=1)
    draft = dated_draft(clock)
    for i in range(MAX_DATED_EXERCISES + 5):
        draft = draft.with_date(f"Exercise {i}", day, chosen_on=today)
    assert len(draft.dates) == MAX_DATED_EXERCISES


# ── a date is state worth saving on its own ──────────────────────────────


def test_a_draft_holding_only_a_date_is_still_worth_restoring(drafts, store, clock):
    """Picking the day before typing the first set is the normal order.

    If that draft were treated as empty, the pick would be dropped on the floor
    and the sets typed a minute later would land on today — the exact silent
    failure per-exercise dates were warned about.
    """
    today = today_of(clock)
    monday = today - timedelta(days=2)
    draft = dated_draft(clock, dates={"Bench Press": LogDate(monday, today)})
    assert draft.is_empty() is False
    assert drafts.save(draft, force=True) is True

    back = drafts.load(a_routine())
    assert back is not None
    assert back.date_for("Bench Press", today) == monday


def test_picking_a_date_is_a_change_the_store_writes(drafts, store, clock):
    """A coalesced date is a window where the screen and the row disagree."""
    today = today_of(clock)
    draft = dated_draft(clock, pending=a_draft().pending)
    assert drafts.save(draft, force=True) is True
    dated = draft.with_date("Bench Press", today - timedelta(days=1), chosen_on=today)
    assert drafts.save(dated, force=True) is True
    assert stored(store)["dates"]["Bench Press"]["chosen_on"] == today.isoformat()


def test_dates_survive_the_encode_decode_round_trip(clock):
    today = today_of(clock)
    draft = a_draft(
        saved_at=clock.t,
        session_date=LogDate(today - timedelta(days=2), today),
        dates={"Overhead Press": LogDate(today - timedelta(days=1), today)},
    )
    assert decode_draft(encode_draft(draft), now=clock.t) == draft


def test_clearing_the_dates_puts_everything_back_on_today(clock):
    today = today_of(clock)
    draft = dated_draft(
        clock,
        session_date=LogDate(today - timedelta(days=2), today),
        dates={"Overhead Press": LogDate(today - timedelta(days=1), today)},
    ).without_dates()
    assert draft.session_date is None and draft.dates == {}
    assert draft.date_for("Overhead Press", today) == today


def test_without_date_falls_back_to_the_session_not_to_today(clock):
    today = today_of(clock)
    monday = today - timedelta(days=2)
    draft = dated_draft(
        clock,
        session_date=LogDate(monday, today),
        dates={"Overhead Press": LogDate(today, today)},
    ).without_date("Overhead Press")
    assert draft.date_for("Overhead Press", today) == monday


# ── telling the user, before anything is written ─────────────────────────


def test_dates_in_use_counts_the_days_this_session_touches(clock):
    """Includes the exercises still on the default, which is the half a
    per-exercise picker makes easy to forget."""
    today = today_of(clock)
    monday, tuesday = today - timedelta(days=2), today - timedelta(days=1)
    draft = dated_draft(
        clock,
        session_date=LogDate(monday, today),
        dates={"Overhead Press": LogDate(tuesday, today)},
    )
    keys = ["Bench Press", "Overhead Press", "Triceps Pushdown"]
    assert draft.dates_in_use(keys, today) == (monday, tuesday)
    assert draft.is_multi_day(keys, today) is True

    same_day = dated_draft(clock, session_date=LogDate(monday, today))
    assert same_day.dates_in_use(keys, today) == (monday,)
    assert same_day.is_multi_day(keys, today) is False


def test_dates_in_use_answers_even_with_nothing_selected(clock):
    today = today_of(clock)
    assert dated_draft(clock).dates_in_use([], today) == (today,)
    assert dated_draft(clock).dates_in_use(None, today) == (today,)


def test_dated_exercises_lists_only_explicit_picks(clock):
    today = today_of(clock)
    draft = dated_draft(
        clock,
        session_date=LogDate(today - timedelta(days=2), today),
        dates={"Overhead Press": LogDate(today - timedelta(days=1), today)},
    )
    assert draft.dated_exercises() == ("Overhead Press",)


def test_a_completed_exercise_keeps_the_day_it_was_written_under(drafts, store, clock):
    """The summary has to be able to say which lift went to which day."""
    today = today_of(clock)
    monday = today - timedelta(days=2)
    draft = a_draft(
        saved_at=clock.t,
        completed=[
            {
                "exercise": "Bench Press",
                "sets": [{"weight": 60.0, "reps": 10}],
                "date": monday.isoformat(),
            },
        ],
    )
    drafts.save(draft, force=True)
    back = drafts.load(a_routine())
    assert back is not None
    assert back.completed[0]["date"] == monday.isoformat()


def test_an_unreadable_date_on_a_completed_exercise_is_simply_absent(drafts, store, clock):
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(
        store,
        completed=[{"exercise": "Bench Press", "sets": [], "date": "the day before"}],
    )
    back = drafts.load(a_routine())
    assert back is not None
    assert "date" not in back.completed[0]


# ── reading a draft written before dates existed ─────────────────────────


def test_a_version_one_draft_is_read_as_having_no_dates(drafts, store, clock):
    """v2 is v1 plus two keys, so a v1 payload means "nothing was ever dated".

    The single deploy that lands mid-workout keeps its session instead of
    losing it, and the worst it can do is the behaviour that build already had:
    everything logs to the session default.
    """
    today = today_of(clock)
    drafts.save(a_draft(saved_at=clock.t), force=True)
    payload = stored(store)
    payload.pop("dates", None)
    payload.pop("session_date", None)
    payload["v"] = 1
    store.prefs[DRAFT_PREF_KEY] = json.dumps(payload)

    back = drafts.load(a_routine())
    assert back is not None
    assert back.pending["Bench Press"][0]["weight"] == "60"
    assert back.dates == {} and back.session_date is None
    assert back.stale_dates == () and back.session_date_stale is False
    assert back.date_for("Bench Press", today) == today


def test_a_version_one_draft_carrying_date_keys_is_not_believed(drafts, store, clock):
    """v1 never wrote dates, so anything under those keys is not from v1.

    Read strictly by version rather than "read whatever is there": adopting a
    field a format never had is the half-read this rule exists to forbid.
    """
    today = today_of(clock)
    drafts.save(a_draft(saved_at=clock.t), force=True)
    rewrite(
        store,
        v=1,
        dates={
            "Bench Press": {
                "date": (today - timedelta(days=2)).isoformat(),
                "chosen_on": today.isoformat(),
            }
        },
    )
    back = drafts.load(a_routine())
    assert back is not None
    assert back.dates == {}
    assert back.date_for("Bench Press", today) == today


def test_the_version_written_today_is_two(drafts, store, clock):
    drafts.save(a_draft(saved_at=clock.t), force=True)
    assert DRAFT_VERSION == 2
    assert stored(store)["v"] == 2


# ── through a real Storage: the restart claim ────────────────────────────


@pytest.fixture
def real_store():
    """Same URL resolution as tests/test_smoke.py. Skips without a database."""
    from sqlalchemy.engine import make_url

    from storage import Storage

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ.get("DATABASE_URL")
        if not base:
            pytest.skip("no DATABASE_URL: there is no database to test against")
        # render_as_string, not str(): str() masks the password.
        url = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)
    if make_url(url).database == "entrenador":
        pytest.skip("points at the production database: leave it alone")
    return Storage(url)


def test_draft_survives_a_new_storage_instance(real_store, clock):
    """The claim is "survives a restart of ironflet-web", so prove it in the DB.

    A second `Storage` over the same URL is what the service comes back as: new
    engine, new session factory, nothing carried over in memory.
    """
    from storage import Storage

    writer = DraftStore(real_store, clock=clock)
    writer.save(a_draft(saved_at=clock.t), force=True)
    try:
        reader = DraftStore(Storage(real_store.db_url), clock=clock)
        back = reader.load(a_routine())
        assert back is not None
        assert back.pending["Bench Press"][0]["weight"] == "60"
        assert back.ex_idx == 1
    finally:
        writer.clear()


def test_clearing_leaves_no_draft_behind_in_the_database(real_store, clock):
    d = DraftStore(real_store, clock=clock)
    d.save(a_draft(saved_at=clock.t), force=True)
    d.clear()
    assert not real_store.get_pref(DRAFT_PREF_KEY)
    assert d.load(a_routine()) is None


def test_the_routine_preference_is_left_alone(real_store, clock):
    """`routine` was the only key in this table; the draft must not disturb it.

    Restores whatever it found: the test database is shared with every other
    suite here, and leaving a routine selected would decide their numbers.
    """
    before = real_store.get_pref("routine")
    real_store.set_pref("routine", "cambiatufisico")
    try:
        d = DraftStore(real_store, clock=clock)
        d.save(a_draft(saved_at=clock.t), force=True)
        d.clear()
        assert real_store.get_pref("routine") == "cambiatufisico"
    finally:
        real_store.set_pref("routine", before or "")
