"""Guards for `substitutions.py` — swapping an exercise when the machine is taken.

Three groups, and the middle one is the reason the file exists:

1. **The derived catalogue.** It is computed from `exercise_details.py`, so it
   can shift under a slug edit without anybody touching this module. The tests
   pin the swaps the routine actually needs, and — just as hard — the wrong
   ones the raw data would otherwise produce.
2. **The key that reaches `entrenos.ejercicio`.** If Alex squats instead of leg
   pressing, the row says `Squat`. Nothing in the system raises when that goes
   wrong; the app and the Telegram coach simply stop agreeing about what was
   trained. Every path into `key_to_log` is checked here.
3. **Persistence and expiry**, through a real `Storage` against the test
   database, including a second `Storage` instance for "Alex closed the app and
   opened it again".

Nothing here imports the Telegram coach in ../agente/.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url

import substitutions as subs
from data import set_active_routine
from exercises import exercise_key
from storage import Entreno, Preferencia, Storage, WorkoutEntry
from substitutions import (
    PREF_KEY,
    STATE_VERSION,
    TIER_DIRECT,
    TIER_VARIATION,
    Scope,
    active_substitutions,
    alternatives,
    clear_substitution,
    equipment_for,
    is_alias,
    is_combination,
    is_valid_substitution,
    key_to_log,
    load_state,
    pattern_for,
    set_substitution,
    starting_point,
    substitution_for,
    swap_prescription,
)

DEFAULT_ROUTINE = "cambiatufisico"
TODAY = date(2026, 8, 19)


@pytest.fixture(autouse=True)
def use_routine():
    """Pin the active routine: `set_substitution` reads its id for phase scope."""
    set_active_routine(DEFAULT_ROUTINE)
    yield
    set_active_routine(DEFAULT_ROUTINE)


@pytest.fixture
def url():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        base = os.environ.get("DATABASE_URL")
        if not base:
            pytest.skip("no DATABASE_URL: there is no database to test against")
        # render_as_string, not str(): str() masks the password.
        value = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)
    if make_url(value).database == "entrenador":
        pytest.skip("points at the production database: leave it alone")
    return value


@pytest.fixture
def store(url):
    """A `Storage` with our preference row and the workout table emptied.

    Only the `substitutions` key is removed, not the whole table: `routine`
    lives there too and other suites depend on it.
    """
    almacen = Storage(url)
    with almacen._Session() as s:
        s.execute(delete(Preferencia).where(Preferencia.clave == PREF_KEY))
        s.execute(delete(Entreno))
        s.commit()
    return almacen


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


def keys(items) -> list[str]:
    return [a.key for a in items]


# ── the derived catalogue ────────────────────────────────────────────────


def test_the_five_blocked_machines_all_offer_something():
    """The exercises Alex actually waits for. An empty list is a failed feature."""
    for machine in (
        "Leg Press",
        "Leg Extensions",
        "Seated Cable Row",
        "Pec Deck",
        "Lying Leg Curl",
    ):
        assert alternatives(machine), f"{machine} offers no substitute at all"


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("Leg Press", "Squat"),
        ("Squat", "Leg Press"),
        ("Pec Deck", "Cable Crossover"),
        ("Cable Crossover", "Pec Deck"),
        ("Lying Leg Curl", "Seated Leg Curl"),
        ("Seated Cable Row", "Machine Row"),
        ("Seated Cable Row", "T-Bar Row"),
        ("Front Lat Pulldown", "Pull-ups"),
        ("Lateral Raises", "Machine Lateral Raises"),
        ("Treadmill", "Bike"),
    ],
)
def test_equivalent_movements_are_offered_both_ways(original, expected):
    assert expected in keys(alternatives(original, limit=0))
    assert is_valid_substitution(original, expected)


@pytest.mark.parametrize(
    ("original", "forbidden", "why"),
    [
        # One muscle called "shoulders" covers three heads in the source data.
        ("DB Rear Delts", "Lateral Raises", "a rear delt is not a side delt"),
        ("Lateral Raises", "DB Rear Delts", "a side delt is not a rear delt"),
        ("Plate Front Raises", "Lateral Raises", "a front raise is not a side raise"),
        # Different muscle entirely.
        ("Leg Press", "Seated Cable Row", "quads are not back"),
        ("Pec Deck", "Lying Leg Curl", "chest is not hamstrings"),
        # `Air_Bike` makes HIIT Intervals abdominal work in the raw data.
        ("Cable Crunch", "HIIT Intervals", "conditioning is not an ab exercise"),
        # Both are `quadriceps` in the source; only one is a lift.
        ("Squat", "Treadmill", "a treadmill does not replace a squat"),
        ("Leg Press", "Bike", "a bike does not replace a leg press"),
    ],
)
def test_wrong_swaps_the_raw_data_would_produce_are_refused(original, forbidden, why):
    assert forbidden not in keys(alternatives(original, limit=0)), why
    assert not is_valid_substitution(original, forbidden), why


def test_a_fly_is_never_a_direct_swap_for_a_press():
    """`Incline_Dumbbell_Flyes` ships `mechanic: compound` in the source data.

    Uncorrected, that puts a fly in the same pattern as a bench press and
    offers it as a like-for-like swap. It stays available as a *variation*,
    which is what it is.
    """
    offered = {a.key: a.tier for a in alternatives("Barbell Bench Press", limit=0)}
    assert offered.get("Incline DB Flyes") == TIER_VARIATION
    assert offered.get("Cable Crossover") == TIER_VARIATION
    assert offered.get("Incline DB Press") == TIER_DIRECT

    back = {a.key: a.tier for a in alternatives("Pec Deck", limit=0)}
    assert back.get("Incline DB Flyes") == TIER_DIRECT
    assert back.get("Barbell Bench Press") == TIER_VARIATION


def test_an_exercise_is_never_a_substitute_for_itself():
    assert not is_valid_substitution("Leg Press", "Leg Press")
    assert "Leg Press" not in keys(alternatives("Leg Press", limit=0))


def test_aliases_are_not_offered_as_substitutes():
    """Two names for the same bar in the same corner frees nothing."""
    assert is_alias("Straight Bar Curl", "Barbell Curl")
    assert is_alias("Skull Crushers", "EZ Bar Skull Crushers")
    assert is_alias("Dips", "Parallel Bar Dips")
    assert "Barbell Curl" not in keys(alternatives("Straight Bar Curl", limit=0))
    assert not is_valid_substitution("Dips", "Parallel Bar Dips")


def test_same_photo_but_different_hardware_is_still_a_substitution():
    """The image bundle has one side-raise photo for three stations.

    Slug equality alone would have collapsed them and lost the only swap that
    matters when the lateral raise machine is busy.
    """
    assert not is_alias("Lateral Raises", "Machine Lateral Raises")
    assert not is_alias("Lateral Raises", "Cable Lateral Raises")
    assert equipment_for("Machine Lateral Raises") == "machine"
    assert equipment_for("Cable Lateral Raises") == "cable"
    assert equipment_for("Lateral Raises") == "dumbbell"


def test_alternatives_never_repeat_the_same_movement_twice():
    offered = keys(alternatives("Pec Deck", limit=0))
    assert len(offered) == len(set(offered))
    for i, a in enumerate(offered):
        for b in offered[i + 1 :]:
            assert not is_alias(a, b), f"{a} and {b} are the same movement"


def test_unknown_names_are_refused():
    """The guard that keeps a foreign key out of `entrenos.ejercicio`.

    "Hack Squat" is the obvious quad substitute and the app does not know it:
    no image, no muscle data, nothing the coach could read back.
    """
    assert alternatives("Hack Squat") == ()
    assert not is_valid_substitution("Leg Press", "Hack Squat")
    assert not is_valid_substitution("Hack Squat", "Squat")
    assert not is_valid_substitution("", "Squat")
    assert not is_valid_substitution("Leg Press", "")


def test_combination_entries_neither_offer_nor_accept():
    for name in (
        "Bi-set: Leg Press + Extensions",
        "SS: Squat + Lying Leg Curl",
        "Triset: Front + Lateral + Rear Delts",
        "Abs Triset",
        "Calf Press + Seated",
    ):
        assert is_combination(name), name
        assert pattern_for(name) is None, name
        assert alternatives(name) == (), name
        assert not is_valid_substitution(name, "Squat"), name
    assert not is_combination("Cable Crossover")
    assert not is_combination("Leg Press")


def test_bulgarian_split_squat_is_classified_by_hand():
    """It has no entry in the details table at all — CLAUDE.md says why."""
    from exercise_details import details_for

    assert details_for("Bulgarian Split Squat") is None
    assert pattern_for("Bulgarian Split Squat") == subs.Pattern(("quadriceps",), "compound")
    assert is_valid_substitution("Leg Press", "Bulgarian Split Squat")


def test_direct_swaps_rank_above_variations():
    offered = alternatives("Pec Deck", limit=0)
    tiers = [a.tier for a in offered]
    assert tiers == sorted(tiers, key=lambda t: 0 if t == TIER_DIRECT else 1)
    assert offered[0].tier == TIER_DIRECT
    assert offered[0].is_direct


def test_leg_extensions_falls_back_to_the_compound_tier():
    """No other isolation quad movement exists anywhere in the catalogue.

    Without the variation tier one of the five blocked machines would offer
    nothing, so the fallback is load-bearing rather than a nicety.
    """
    offered = alternatives("Leg Extensions", limit=0)
    assert offered
    assert {a.tier for a in offered} == {TIER_VARIATION}
    assert "Squat" in keys(offered)
    assert all("different load" in a.reason for a in offered)


def test_every_offer_carries_an_english_reason():
    for name in ("Leg Press", "Pec Deck", "Seated Cable Row", "Lying Leg Curl"):
        for a in alternatives(name, limit=0):
            assert a.reason.endswith(".")
            assert a.equipment
            assert " a isolation " not in a.reason  # article agreement


def test_the_offered_list_is_stable_between_calls():
    assert keys(alternatives("Seated Cable Row")) == keys(alternatives("Seated Cable Row"))


def test_alternatives_accept_a_prescription_string():
    """The routine holds `"Leg Press [4×8-10]"`, not the bare key."""
    assert keys(alternatives("Leg Press [4×8-10]")) == keys(alternatives("Leg Press"))
    assert is_valid_substitution("Leg Press [4×8-10]", "Squat")


# ── the prescription follows the slot, not the machine ───────────────────


def test_swap_prescription_keeps_the_scheme():
    assert swap_prescription("Leg Press [4×8-10]", "Squat") == "Squat [4×8-10]"
    assert swap_prescription("Leg Press", "Squat") == "Squat"
    assert swap_prescription("Pec Deck [3×12] [comp]", "Cable Crossover") == (
        "Cable Crossover [3×12] [comp]"
    )
    assert swap_prescription("Squat*", "Leg Press") == "Leg Press*"


def test_swap_prescription_result_reads_back_as_the_substitute():
    assert exercise_key(swap_prescription("Leg Press [4×8-10]", "Squat")) == "Squat"


# ── the key that reaches the database ────────────────────────────────────


def test_key_to_log_without_a_store_is_the_plain_canonical_key():
    assert key_to_log("Leg Press [4×8-10]") == "Leg Press"
    assert key_to_log("Squat*") == "Squat"
    assert key_to_log("") == ""


def test_key_to_log_returns_the_exercise_actually_performed(store):
    """The whole point. Hack Squat day writes Hack Squat, not Leg Press."""
    set_substitution(store, "Leg Press", "Squat", Scope.TODAY, today=TODAY)
    assert key_to_log("Leg Press [4×8-10]", store=store, today=TODAY) == "Squat"


def test_the_substituted_row_lands_under_the_substitute_key(store):
    """End to end: what a view would do, then what the history actually holds."""
    set_substitution(store, "Pec Deck", "Cable Crossover", Scope.TODAY, today=TODAY)
    performed = key_to_log("Pec Deck [3×12]", store=store, today=TODAY)
    log(store, TODAY, performed, [{"weight": 25.0, "reps": 12}])

    assert [e.exercise for e in store.get_exercise_history("Cable Crossover")] == [
        "Cable Crossover"
    ]
    assert store.get_exercise_history("Pec Deck") == []


def test_an_untouched_exercise_still_logs_itself(store):
    set_substitution(store, "Leg Press", "Squat", Scope.TODAY, today=TODAY)
    assert key_to_log("Seated Cable Row", store=store, today=TODAY) == "Seated Cable Row"


def test_substitution_exposes_the_key_to_log():
    swap = subs.Substitution("Leg Press", "Squat", Scope.TODAY)
    assert swap.key_to_log == swap.performed == "Squat"


# ── scopes ───────────────────────────────────────────────────────────────


def test_today_scope_is_gone_tomorrow(store):
    set_substitution(store, "Leg Press", "Squat", Scope.TODAY, today=TODAY)
    assert substitution_for(store, "Leg Press", today=TODAY).performed == "Squat"

    tomorrow = TODAY + timedelta(days=1)
    assert substitution_for(store, "Leg Press", today=tomorrow) is None
    assert key_to_log("Leg Press", store=store, today=tomorrow) == "Leg Press"


def test_phase_scope_lasts_the_phase_and_ends_with_it(store):
    set_substitution(store, "Leg Press", "Squat", Scope.PHASE, phase_id=3, today=TODAY)

    later = TODAY + timedelta(days=20)
    assert substitution_for(store, "Leg Press", phase_id=3, today=later).performed == "Squat"
    assert substitution_for(store, "Leg Press", phase_id=4, today=later) is None
    # Without a phase there is nothing to compare against, so it does not apply.
    assert substitution_for(store, "Leg Press", today=later) is None


def test_phase_scope_does_not_cross_routines(store):
    set_substitution(
        store,
        "Leg Press",
        "Squat",
        Scope.PHASE,
        routine_id="cambiatufisico",
        phase_id=2,
        today=TODAY,
    )
    assert (
        substitution_for(store, "Leg Press", routine_id="upper-lower", phase_id=2, today=TODAY)
        is None
    )


def test_a_phase_scoped_swap_needs_a_phase(store):
    with pytest.raises(ValueError):
        set_substitution(store, "Leg Press", "Squat", Scope.PHASE, today=TODAY)


def test_today_wins_over_the_phase(store):
    set_substitution(store, "Leg Press", "Squat", Scope.PHASE, phase_id=3, today=TODAY)
    set_substitution(store, "Leg Press", "DB Lunges", Scope.TODAY, today=TODAY)

    swap = substitution_for(store, "Leg Press", phase_id=3, today=TODAY)
    assert swap.performed == "DB Lunges"
    assert swap.scope is Scope.TODAY

    # And tomorrow the phase-scoped one is back in charge.
    tomorrow = TODAY + timedelta(days=1)
    later = substitution_for(store, "Leg Press", phase_id=3, today=tomorrow)
    assert later.performed == "Squat"
    assert later.scope is Scope.PHASE


def test_both_scopes_can_hold_several_exercises_at_once(store):
    set_substitution(store, "Leg Press", "Squat", Scope.TODAY, today=TODAY)
    set_substitution(store, "Pec Deck", "Cable Crossover", Scope.TODAY, today=TODAY)
    set_substitution(
        store, "Lying Leg Curl", "Seated Leg Curl", Scope.PHASE, phase_id=1, today=TODAY
    )

    active = active_substitutions(store, phase_id=1, today=TODAY)
    assert {k: v.performed for k, v in active.items()} == {
        "Leg Press": "Squat",
        "Pec Deck": "Cable Crossover",
        "Lying Leg Curl": "Seated Leg Curl",
    }


def test_scope_accepts_its_string_form(store):
    set_substitution(store, "Leg Press", "Squat", "today", today=TODAY)
    assert substitution_for(store, "Leg Press", today=TODAY).scope is Scope.TODAY


def test_clearing_a_swap(store):
    set_substitution(store, "Leg Press", "Squat", Scope.TODAY, today=TODAY)
    set_substitution(store, "Pec Deck", "Cable Crossover", Scope.TODAY, today=TODAY)

    clear_substitution(store, "Leg Press", today=TODAY)
    active = active_substitutions(store, today=TODAY)
    assert "Leg Press" not in active
    assert "Pec Deck" in active


def test_clearing_without_a_scope_clears_both(store):
    set_substitution(store, "Leg Press", "Squat", Scope.PHASE, phase_id=3, today=TODAY)
    set_substitution(store, "Leg Press", "DB Lunges", Scope.TODAY, today=TODAY)

    clear_substitution(store, "Leg Press")
    assert active_substitutions(store, phase_id=3, today=TODAY) == {}


# ── persistence ──────────────────────────────────────────────────────────


def test_a_saved_swap_survives_reopening_the_app(url, store):
    """A second `Storage` over the same database — the APK restarted."""
    set_substitution(store, "Leg Press", "Squat", Scope.PHASE, phase_id=3, today=TODAY)

    reopened = Storage(url)
    swap = substitution_for(reopened, "Leg Press", phase_id=3, today=TODAY + timedelta(days=5))
    assert swap is not None
    assert swap.performed == "Squat"
    assert swap.scope is Scope.PHASE
    assert key_to_log("Leg Press [4×8-10]", store=reopened, phase_id=3, today=TODAY) == "Squat"


def test_a_today_swap_also_survives_a_restart_within_the_day(url, store):
    set_substitution(store, "Pec Deck", "Cable Crossover", Scope.TODAY, today=TODAY)
    reopened = Storage(url)
    assert substitution_for(reopened, "Pec Deck", today=TODAY).performed == "Cable Crossover"


def test_it_is_stored_as_json_under_one_preference_key(store):
    set_substitution(store, "Leg Press", "Squat", Scope.TODAY, today=TODAY)
    raw = store.get_pref(PREF_KEY)
    assert raw
    parsed = json.loads(raw)
    assert parsed["version"] == STATE_VERSION
    assert parsed["today"] == {"date": TODAY.isoformat(), "map": {"Leg Press": "Squat"}}
    assert len(PREF_KEY) <= 60  # `preferencias.clave` is String(60)


def test_an_invalid_swap_is_never_persisted(store):
    with pytest.raises(ValueError):
        set_substitution(store, "Leg Press", "Hack Squat", Scope.TODAY, today=TODAY)
    with pytest.raises(ValueError):
        set_substitution(store, "Leg Press", "Seated Cable Row", Scope.TODAY, today=TODAY)
    assert store.get_pref(PREF_KEY) is None


def test_prescription_strings_are_normalised_on_the_way_in(store):
    set_substitution(store, "Leg Press [4×8-10]", "Squat [5×5]", Scope.TODAY, today=TODAY)
    stored = json.loads(store.get_pref(PREF_KEY))
    assert stored["today"]["map"] == {"Leg Press": "Squat"}


def test_a_pair_that_stopped_being_valid_is_dropped_on_read(store):
    """The catalogue is derived, so a stored pair can go stale.

    Whatever else happens, a key the app cannot resolve must not reach a view
    that is about to write it into `entrenos.ejercicio`.
    """
    store.set_pref(
        PREF_KEY,
        json.dumps(
            {
                "version": STATE_VERSION,
                "today": {"date": TODAY.isoformat(), "map": {"Leg Press": "Nordic Curl"}},
                "phase": {},
            }
        ),
    )
    assert active_substitutions(store, today=TODAY) == {}
    assert key_to_log("Leg Press", store=store, today=TODAY) == "Leg Press"


@pytest.mark.parametrize(
    "raw",
    ["", "not json at all", "[]", '"a string"', "null", '{"version": 999, "today": {}}'],
)
def test_a_broken_state_reads_as_no_substitutions(store, raw):
    """Shared, hand-editable database. This must never be a stack trace."""
    store.set_pref(PREF_KEY, raw)
    assert load_state(store) == {"version": STATE_VERSION, "today": {}, "phase": {}}
    assert active_substitutions(store, phase_id=1, today=TODAY) == {}
    assert key_to_log("Leg Press", store=store, today=TODAY) == "Leg Press"


def test_reading_does_not_write(store):
    """The workout screen must not touch the database just by opening."""
    set_substitution(store, "Leg Press", "Squat", Scope.TODAY, today=TODAY)
    before = store.get_pref(PREF_KEY)
    active_substitutions(store, phase_id=3, today=TODAY + timedelta(days=400))
    assert store.get_pref(PREF_KEY) == before


def test_a_database_that_will_not_answer_reads_as_no_substitutions():
    class Down:
        def get_pref(self, key, default=None):
            raise RuntimeError("connection refused")

    assert load_state(Down())["today"] == {}
    assert key_to_log("Leg Press", store=Down()) == "Leg Press"


# ── the first session on the substitute ──────────────────────────────────


def test_no_history_anywhere_is_the_normal_case(store):
    """Alex has logged nothing yet. Both sides of the swap are empty."""
    point = starting_point(store, "Leg Press [4×8-10]", "Squat", today=TODAY)

    assert point.key == "Squat"
    assert point.has_history is False
    assert point.headline == ""
    assert "No history for Squat" in point.note
    assert "nothing to carry over" in point.reference
    assert point.lines()


def test_the_replaced_exercise_is_shown_as_context_not_as_a_target(store):
    log(store, TODAY - timedelta(days=7), "Leg Press", [{"weight": 120.0, "reps": 10}] * 4)

    from progression import recommend_from_store

    point = starting_point(store, "Leg Press [4×8-10]", "Squat", today=TODAY)
    assert point.has_history is False
    assert "Leg Press" in point.reference
    assert "not a target" in point.reference
    assert point.headline == ""

    # The number quoted is the leg press's own, straight out of progression.
    # No squat weight is invented from it — that is the whole discipline here.
    leg_press = recommend_from_store(store, "Leg Press [4×8-10]", today=TODAY)
    assert leg_press.headline() in point.reference
    assert "Squat" not in point.reference


def test_once_the_substitute_has_history_progression_takes_over(store):
    from progression import recommend_from_store

    log(store, TODAY - timedelta(days=7), "Squat", [{"weight": 80.0, "reps": 10}] * 4)

    point = starting_point(store, "Leg Press [4×8-10]", "Squat", today=TODAY)
    assert point.has_history is True
    # Delegated verbatim: analytics and progression own every number in the app.
    assert point.headline == recommend_from_store(store, "Squat [4×8-10]", today=TODAY).headline()
    assert point.reference == ""


def test_the_substitute_inherits_the_prescription_of_the_slot(store):
    """Its own history, the plan's sets and reps."""
    log(store, TODAY - timedelta(days=7), "Squat", [{"weight": 80.0, "reps": 10}] * 4)

    wide = starting_point(store, "Leg Press [4×8-10]", "Squat", today=TODAY)
    narrow = starting_point(store, "Leg Press [4×5]", "Squat", today=TODAY)
    assert wide.headline != narrow.headline


def test_starting_point_of_an_unsubstituted_exercise_is_just_progression(store):
    log(store, TODAY - timedelta(days=7), "Leg Press", [{"weight": 120.0, "reps": 10}] * 4)

    point = starting_point(store, "Leg Press [4×8-10]", "Leg Press", today=TODAY)
    assert point.has_history is True
    assert point.reference == ""


def test_lines_drops_the_empty_slots(store):
    point = starting_point(store, "Leg Press [4×8-10]", "Squat", today=TODAY)
    assert "" not in point.lines()
    assert point.note in point.lines()


# ── module hygiene ───────────────────────────────────────────────────────


def test_the_module_imports_no_flet_and_opens_no_database():
    """Same contract as the other analysis modules, so it unit-tests headless.

    Checked in a fresh interpreter: by the time this file runs, half the suite
    has already imported Flet, so `sys.modules` here proves nothing.
    """
    import subprocess
    import sys

    probe = (
        "import sys; import substitutions; "
        "assert 'flet' not in sys.modules, 'substitutions pulled in Flet'; "
        "assert 'sqlalchemy' not in sys.modules, 'substitutions pulled in the ORM'"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(subs.__file__).parent,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
