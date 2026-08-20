"""progression.py — double progression against Alex's real routine.

Everything here is pure: history is handed in as plain dicts, so no test in
this file needs PostgreSQL and none of them skip. The one function that talks
to a `Storage` (`recommend_from_store`) is exercised against a fake with the
same two methods, which is the whole point of keeping the module I/O-free.

The cases are the ones the brief names, in the order it names them: first time
with no history, progress inside the range, ceiling reached, failed session,
and the odd schemes that really occur in data.py — `[5×12,10,8,8,8]`,
`[4×max]`, `[2×10+10+10]`.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import data
import gym_tools
import progression as prog
import routine_builder
from progression import (
    Action,
    Confidence,
    Equipment,
    SchemeKind,
)

TODAY = date(2026, 8, 18)


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def entry(exercise: str, when: str, sets: list[dict]) -> dict:
    """A history row shaped like `storage.WorkoutEntry`, as a dict.

    Dicts on purpose: `analytics._field` reads dataclasses and dicts the same
    way, and a dict makes the fixture readable at a glance.
    """
    return {"date": when, "exercise": exercise, "sets": sets}


def straight(weight: float, reps: list[int]) -> list[dict]:
    """One load, one rep count per set — how a `[4×5-8]` session is logged."""
    return [{"weight": weight, "reps": r} for r in reps]


# The routine Alex actually trains, and its accumulation phase.
RECOMP = next(r for r in data.ROUTINES if r.id == "recomp-ppl-ul")
BASE = RECOMP.phases[0]  # "Base" — RIR 2-3
ACCUMULATION = RECOMP.phases[1]  # "Accumulation" — states the 2.5/5 kg rule

BENCH = "Barbell Bench Press [4×5-8]"
SQUAT = "Squat [4×5-8]"


# ─────────────────────────────────────────────────────────────────────────
# 1. reading the prescription out of the exercise string
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, kind, sets, low, high",
    [
        ("Barbell Bench Press [4×5-8]", SchemeKind.RANGE, 4, 5, 8),
        ("Lateral Raises [4×12-20]", SchemeKind.RANGE, 4, 12, 20),
        ("Barbell Lunges [4×10]", SchemeKind.FIXED, 4, 10, 10),
        ("Barbell Bench Press [5×12,10,8,8,8]", SchemeKind.PYRAMID, 5, 8, 12),
        ("Hanging Abs [5×max]", SchemeKind.AMRAP, 5, None, None),
        ("Pull-ups [4×max]", SchemeKind.AMRAP, 4, None, None),
        ("Push-ups [3×failure]", SchemeKind.AMRAP, 3, None, None),
        ("Cable Curl [triple drop] [2×10+10+10]", SchemeKind.CLUSTER, 2, None, None),
        ("Abs Triset [4×(20+20+20)]", SchemeKind.CLUSTER, 4, None, None),
        (
            "Bi-set: Incline DB Press + Flat Machine Press [4×8+10]",
            SchemeKind.CLUSTER,
            4,
            None,
            None,
        ),
    ],
)
def test_parse_scheme_reads_every_shape_in_data_py(raw, kind, sets, low, high):
    scheme = prog.parse_scheme(raw)
    assert scheme.kind is kind
    assert scheme.sets == sets
    assert scheme.reps_low == low
    assert scheme.reps_high == high
    assert scheme.source == "bracket"


def test_pyramid_keeps_a_target_per_set():
    scheme = prog.parse_scheme("Barbell Bench Press [5×12,10,8,8,8]")
    assert scheme.per_set == (12, 10, 8, 8, 8)
    assert scheme.reps_label() == "12,10,8,8,8 reps"


def test_pyramid_with_a_drop_on_the_last_set_keeps_the_working_target():
    """`[4×10,10,8,6+12↓]` is four sets of 10/10/8/6, not four segments.

    The `12↓` is the drop tail: a lighter set tacked onto the sixth rep. It is
    real work but it is not the number being progressed, so the target for set
    four is 6.
    """
    scheme = prog.parse_scheme("Barbell Bench Press [4×10,10,8,6+12↓]")
    assert scheme.kind is SchemeKind.PYRAMID
    assert scheme.per_set == (10, 10, 8, 6)
    assert scheme.has_drop is True


def test_cluster_keeps_its_segments_and_refuses_to_average_them():
    scheme = prog.parse_scheme("Cable Curl [triple drop] [2×10+10+10]")
    assert scheme.segments == ("10", "10", "10")
    assert scheme.reps_low is None and scheme.reps_high is None
    assert scheme.reps_label() == "10+10+10 reps"


def test_tag_brackets_are_skipped_not_parsed():
    """`[comp]` carries no `N×`, so the scheme is read from the next bracket."""
    scheme = prog.parse_scheme("V-Pulldown + V-Row [comp] [4×8+8]")
    assert scheme.sets == 4
    assert scheme.kind is SchemeKind.CLUSTER


def test_scheme_falls_back_to_the_phase_and_then_to_its_star_alternate():
    """CambiaTuFísico phases 1-3 put the scheme on the phase, not the exercise."""
    phase = next(p for p in data.PHASES if p.id == 3)  # "4×5-6 (*=3×8)"
    plain = prog.parse_scheme("Smith Bench Press", phase.scheme)
    assert (plain.sets, plain.reps_low, plain.reps_high) == (4, 5, 6)
    assert plain.source == "phase"

    starred = prog.parse_scheme("Pec Deck *", phase.scheme)
    assert (starred.sets, starred.reps_low, starred.reps_high) == (3, 8, 8)
    assert starred.source == "phase-star"


def test_no_scheme_anywhere_is_reported_as_unknown_not_guessed():
    scheme = prog.parse_scheme("Some Exercise Nobody Prescribed")
    assert scheme.kind is SchemeKind.UNKNOWN
    assert scheme.is_known() is False
    assert scheme.sets is None
    assert scheme.reps_label() == ""


def test_every_exercise_in_data_py_parses():
    """348 prescription strings, zero UNKNOWNs. A new one must not slip in.

    An unreadable scheme is not a crash, it is a silent downgrade to
    "repeat last weight" — which looks like the app working, forever.
    """
    unreadable = [
        ex
        for routine in data.ROUTINES
        for phase in routine.phases
        for day in routine.days_for_phase(phase.id)
        for ex in day.exercises
        if not prog.parse_scheme(ex, phase.scheme).is_known()
    ]
    assert unreadable == []


def test_scheme_agrees_with_routine_builder_on_every_string():
    """Two parsers read these brackets; they must not drift apart.

    `routine_builder.parse_exercise` feeds the routine editor, `parse_scheme`
    feeds the recommendation. If they disagree, the editor shows one
    prescription and the workout screen progresses against another, with
    nothing raising.
    """
    for routine in data.ROUTINES:
        for phase in routine.phases:
            for day in routine.days_for_phase(phase.id):
                for ex in day.exercises:
                    mine = prog.parse_scheme(ex, phase.scheme)
                    theirs = routine_builder.parse_exercise(ex, phase.scheme)
                    assert mine.sets == theirs.sets, ex


# ─────────────────────────────────────────────────────────────────────────
# 2. the RIR target, read out of the phase prose
# ─────────────────────────────────────────────────────────────────────────


def test_rir_comes_from_the_phase_prose_of_the_routine_alex_trains():
    """RECOMP phase 1: "Find a load that leaves 2-3 reps in reserve"."""
    target = prog.rir_for_phase(BASE, RECOMP)
    assert (target.low, target.high) == (2, 3)
    assert target.label() == "RIR 2-3"
    assert "reps in reserve" in target.source


def test_rir_is_inherited_when_a_phase_states_none():
    """Phase 2 states the progression rule and no RIR; phase 3 says "Same loads".

    The target in force is the last one the plan stated, and the result says so
    rather than pretending phase 2 spelled it out.
    """
    target = prog.rir_for_phase(ACCUMULATION, RECOMP)
    assert target.label() == "RIR 2-3"
    assert target.inherited_from == "Base"


def test_explicit_rir_wins_and_last_set_failure_is_kept_separately():
    assert prog.parse_rir("Same loads. RIR 2-3. Add weight when top reps are easy.").label() == (
        "RIR 2-3"
    )
    ppl2 = next(p for p in data.PPL_PHASES if p.id == 2)
    target = prog.rir_for_phase(ppl2, None)
    assert target.last_set == (0, 0)
    assert target.full_label() == "last set to failure"


def test_no_failure_phrasing_becomes_a_floor_not_a_number():
    """ "No absolute failure" says "leave at least one", and nothing more."""
    target = prog.parse_rir("No absolute failure. 20' continuous cardio post-weights.")
    assert (target.low, target.open_ended) == (1, True)
    assert target.label() == "RIR 1+"


def test_prose_that_says_nothing_about_intensity_returns_none():
    assert prog.parse_rir("Drop sets on last set. 5' treadmill pre-weights.") is None
    assert prog.parse_rir("") is None
    assert prog.parse_rir(None) is None


def test_starred_failure_note_is_not_read_as_a_routine_wide_target():
    """CTF phase 3's "*= 3×8 to failure" is about the starred exercises only.

    Reading it as the phase's target would print "to failure" on every other
    row of the session, which is a different workout.
    """
    phase3 = next(p for p in data.PHASES if p.id == 3)
    assert prog.parse_rir(phase3.notes, phase3.subtitle) is None


def test_prescribed_target_is_the_one_string_the_set_row_needs():
    """Requirement 3: sets, reps and RIR are three different places in data.py."""
    assert prog.prescribed_target(BENCH, BASE, RECOMP) == "5-8 reps @ RIR 2-3"
    assert prog.prescribed_target("Lateral Raises [4×12-20]", BASE, RECOMP) == (
        "12-20 reps @ RIR 2-3"
    )


def test_prescribed_target_degrades_instead_of_inventing():
    """No readable RIR → reps only. Nothing readable at all → empty string."""
    phase6 = next(p for p in data.PHASES if p.id == 6)
    assert prog.prescribed_target("Push-ups [3×failure]", phase6) == "max reps"
    assert prog.prescribed_target("Unprescribed Thing") == ""


# ─────────────────────────────────────────────────────────────────────────
# 3. the increment
# ─────────────────────────────────────────────────────────────────────────


def test_the_plan_states_the_increment_and_the_phase_note_is_read_for_it():
    """RECOMP phase 2: "then add 2.5 kg upper / 5 kg lower"."""
    assert prog.parse_prescribed_step(ACCUMULATION.notes) == {"upper": 2.5, "lower": 5.0}
    assert prog.weight_step(BENCH, 80, ACCUMULATION).kg == 2.5
    assert prog.weight_step(SQUAT, 100, ACCUMULATION).kg == 5.0


def test_the_default_split_matches_the_plan_when_the_phase_says_nothing():
    """Phase 1 states no kilos; the defaults must land on the same numbers."""
    assert prog.weight_step(BENCH, 80, BASE).kg == 2.5
    assert prog.weight_step(SQUAT, 100, BASE).kg == 5.0


@pytest.mark.parametrize(
    "exercise, equipment, kg",
    [
        ("Barbell Bench Press", Equipment.BARBELL, 2.5),
        ("Romanian Deadlift", Equipment.BARBELL, 5.0),
        ("Hip Thrust", Equipment.BARBELL, 5.0),
        ("Incline DB Press", Equipment.DUMBBELL, 2.5),
        ("Leg Press", Equipment.MACHINE, 5.0),
        ("Triceps Pushdown", Equipment.CABLE, 2.5),
        ("Pull-ups", Equipment.BODYWEIGHT, 2.5),
        ("Seated Calf Raise", Equipment.MACHINE, 5.0),
    ],
)
def test_the_increment_depends_on_what_the_load_sits_on(exercise, equipment, kg):
    step = prog.weight_step(exercise)
    assert step.equipment is equipment
    assert step.kg == kg
    assert step.reason  # never silent: the UI shows the why


def test_a_curl_and_a_bench_press_do_not_get_the_same_event():
    """Same 2.5 kg, very different jumps — and the reason says so out loud."""
    bench = prog.weight_step("Barbell Bench Press", 80)
    raises = prog.weight_step("Lateral Raises", 12)
    assert bench.kg == raises.kg == 2.5
    assert "%" not in bench.reason  # 3 % of 80 kg is unremarkable
    assert "21%" in raises.reason  # 2.5 kg on 12 kg is not


def test_dips_and_pull_ups_add_weight_to_a_belt_not_to_a_bar():
    assert prog.classify_equipment("Parallel Bar Dips") is Equipment.BODYWEIGHT
    assert "belt" in prog.weight_step("Pull-ups").reason


# ─────────────────────────────────────────────────────────────────────────
# 4. making the number loadable — gym_tools owns the plate maths
# ─────────────────────────────────────────────────────────────────────────


def test_barbell_rounding_goes_through_gym_tools():
    """progression decides the target; gym_tools decides what can be built.

    The plate maths is not duplicated here, so this asserts the delegation
    rather than the arithmetic: the answer must be a weight `gym_tools` itself
    calls loadable on the bar it picks for that exercise.
    """
    got = prog.loadable_weight(78.3, "Barbell Bench Press")
    bar = gym_tools.bar_for_exercise("Barbell Bench Press")
    assert got == gym_tools.round_to_loadable(78.3, bar)
    assert gym_tools.loadable_options(got, bar).loadable


def test_an_ez_bar_curl_is_rounded_on_the_ez_bar_not_the_olympic_one():
    """A 7.5 kg EZ bar reaches loads a 20 kg Olympic bar simply cannot.

    `gym_tools.bar_for_exercise` is the only thing that knows which bar an
    exercise uses, which is exactly why the bar is passed to it rather than
    assumed. Above 20 kg both bars land on the same 2.5 kg lattice, so the
    difference only shows where it matters: a light curl.
    """
    assert gym_tools.bar_for_exercise("EZ Bar Curl").weight == 7.5
    assert prog.loadable_weight(12.0, "EZ Bar Curl") == 12.5
    assert prog.loadable_weight(12.0, "Barbell Curl") == 20.0  # the bare bar is the floor


def test_non_barbell_equipment_rounds_onto_its_own_step_not_onto_plates():
    """A cable stack has no plates to solve for; the pin step is the answer."""
    assert prog.loadable_weight(78.3, "Leg Press") == 80.0  # 5 kg stack plate
    assert prog.loadable_weight(13.7, "Lateral Raises") == 12.5  # next dumbbell
    assert prog.loadable_weight(0, "Pull-ups") == 0.0


def test_round_fn_overrides_everything_with_a_one_argument_contract():
    seen = []

    def fake(weight):
        seen.append(weight)
        return 99.0

    assert prog.loadable_weight(78.3, "Barbell Bench Press", round_fn=fake) == 99.0
    assert seen == [78.3]


def test_a_rounder_that_cannot_answer_leaves_the_weight_alone():
    """None must never reach a weight field as a recommendation."""
    assert prog.loadable_weight(78.3, "Squat", round_fn=lambda w: None) == 78.3


# ─────────────────────────────────────────────────────────────────────────
# 5. first time: no history means no recommendation
# ─────────────────────────────────────────────────────────────────────────


def test_no_history_refuses_to_invent_a_weight():
    """Requirement 4. A made-up first bench press is how people get pinned."""
    rec = prog.recommend(BENCH, [], phase=BASE, routine=RECOMP, today=TODAY)
    assert rec.action is Action.BASELINE
    assert rec.weight is None
    assert rec.has_weight() is False
    assert rec.confidence is Confidence.NONE
    assert "No history" in rec.reason
    assert "8 reps" in rec.reason  # it still tells you what to aim for
    assert rec.target_label == "5-8 reps @ RIR 2-3"
    assert rec.reps_low == 5 and rec.reps_high == 8


def test_a_session_of_nothing_but_warm_ups_is_not_history():
    """Warm-ups are excluded from work everywhere else; here too.

    Progressing off the empty bar would recommend 22.5 kg for a bench press.
    """
    history = [
        entry(
            "Barbell Bench Press",
            days_ago(3),
            [{"weight": 20, "reps": 10, "type": "warmup"}],
        )
    ]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.BASELINE
    assert rec.weight is None


def test_history_for_another_exercise_is_not_borrowed():
    history = [entry("Squat", days_ago(2), straight(100, [8, 8, 8, 8]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.BASELINE


# ─────────────────────────────────────────────────────────────────────────
# 6. inside the range: same weight, chase reps
# ─────────────────────────────────────────────────────────────────────────


def test_inside_the_range_repeats_the_weight_and_names_the_rep_to_beat():
    history = [entry("Barbell Bench Press", days_ago(4), straight(80, [8, 7, 6, 6]))]
    rec = prog.recommend(BENCH, history, phase=BASE, routine=RECOMP, today=TODAY)
    assert rec.action is Action.REPEAT
    assert rec.weight == 80
    assert rec.reps_low == 7  # beat the worst set (6), still capped by the range
    assert rec.reps_high == 8
    assert rec.confidence is Confidence.HIGH
    assert "80 kg" in rec.reason and "beat 6" in rec.reason
    assert rec.headline() == "80 kg × 7-8"


def test_repeat_prefills_each_row_with_at_least_what_was_done_last_time():
    """Hevy's actual affordance: the row arrives filled, you confirm or beat it."""
    history = [entry("Barbell Bench Press", days_ago(4), straight(80, [8, 7, 6, 6]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert [t.weight for t in rec.per_set] == [80, 80, 80, 80]
    assert [t.reps_low for t in rec.per_set] == [8, 7, 6, 6]
    assert rec.per_set[0].label() == "80 kg × 8"


def test_fewer_sets_than_prescribed_does_not_earn_the_jump():
    """Three sets of 8 is not four sets of 8, and the reason says which."""
    history = [entry("Barbell Bench Press", days_ago(4), straight(80, [8, 8, 8]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.REPEAT
    assert rec.weight == 80
    assert "3 of 4 sets" in rec.reason


# ─────────────────────────────────────────────────────────────────────────
# 7. ceiling reached: add weight, rebuild from the bottom
# ─────────────────────────────────────────────────────────────────────────


def test_top_of_the_range_on_every_set_adds_the_upper_body_step():
    history = [entry("Barbell Bench Press", days_ago(4), straight(80, [8, 8, 8, 8]))]
    rec = prog.recommend(BENCH, history, phase=ACCUMULATION, routine=RECOMP, today=TODAY)
    assert rec.action is Action.ADD_WEIGHT
    assert rec.weight == 82.5
    assert rec.reps_low == 5 and rec.reps_high == 8  # back to the bottom
    assert rec.confidence is Confidence.HIGH
    assert "82.5 kg" in rec.reason
    assert "Rebuild from 5 reps" in rec.reason


def test_the_same_success_on_a_squat_adds_five_kilos():
    """The plan's own split, on the exercise it was written for."""
    history = [entry("Squat", days_ago(3), straight(100, [8, 8, 8, 8]))]
    rec = prog.recommend(SQUAT, history, phase=ACCUMULATION, routine=RECOMP, today=TODAY)
    assert rec.action is Action.ADD_WEIGHT
    assert rec.weight == 105
    assert rec.increment.kg == 5.0


def test_beating_the_top_of_the_range_also_counts_as_hitting_it():
    history = [entry("Barbell Bench Press", days_ago(3), straight(80, [10, 9, 8, 8]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.ADD_WEIGHT


def test_bodyweight_pull_ups_earn_weight_on_a_belt_not_a_new_bar_load():
    """`[4×6-10]` pull-ups logged at bodyweight: the load is 0, the jump is 2.5."""
    history = [entry("Pull-ups", days_ago(3), [{"weight": 0, "reps": 10} for _ in range(4)])]
    rec = prog.recommend("Pull-ups [4×6-10]", history, phase=BASE, today=TODAY)
    assert rec.action is Action.ADD_WEIGHT
    assert rec.weight == 2.5
    assert "belt" in rec.reason
    assert "bodyweight" in rec.reason


def test_a_fixed_scheme_progresses_when_every_set_hits_the_number():
    history = [entry("Barbell Lunges", days_ago(3), straight(40, [10, 10, 10, 10]))]
    rec = prog.recommend("Barbell Lunges [4×10]", history, phase=BASE, today=TODAY)
    assert rec.action is Action.ADD_WEIGHT
    assert rec.weight == 45  # lower-body barbell


# ─────────────────────────────────────────────────────────────────────────
# 8. failed session: repeat once, back off twice
# ─────────────────────────────────────────────────────────────────────────


def test_one_short_session_repeats_the_weight():
    """Under the bottom of the range once is a bad day, not a verdict."""
    history = [entry("Barbell Bench Press", days_ago(3), straight(85, [5, 4, 4, 3]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.REPEAT
    assert rec.weight == 85
    assert rec.reps_low == 5  # the bottom of the range, not "beat 3"
    assert "bad day" in rec.reason


def test_two_short_sessions_at_the_same_weight_drop_the_load():
    history = [
        entry("Barbell Bench Press", days_ago(10), straight(85, [5, 4, 4, 4])),
        entry("Barbell Bench Press", days_ago(3), straight(85, [4, 4, 3, 3])),
    ]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.BACK_OFF
    assert rec.weight == 77.5  # 85 × 0.9 = 76.5, rounded onto the 2.5 kg grid
    assert rec.reps_low == 5 and rec.reps_high == 8
    assert "Two sessions in a row" in rec.reason


def test_a_failure_at_a_different_weight_does_not_count_as_the_second_strike():
    """Failing at 90 then at 85 is not "the same weight twice"; it is a taper."""
    history = [
        entry("Barbell Bench Press", days_ago(10), straight(90, [4, 3, 3, 3])),
        entry("Barbell Bench Press", days_ago(3), straight(85, [4, 4, 4, 4])),
    ]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.REPEAT
    assert rec.weight == 85


# ─────────────────────────────────────────────────────────────────────────
# 9. staleness — the honesty requirement about old history
# ─────────────────────────────────────────────────────────────────────────


def test_a_three_week_gap_suppresses_the_jump_it_would_otherwise_earn():
    """The rule is right on paper and wrong after three weeks off."""
    history = [entry("Barbell Bench Press", days_ago(24), straight(80, [8, 8, 8, 8]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.HOLD_STALE
    assert rec.weight == 80  # repeat, do not add
    assert rec.days_since == 24
    assert rec.confidence is Confidence.MEDIUM
    assert "24 days ago" in rec.reason


def test_a_gap_just_under_the_threshold_still_progresses():
    history = [entry("Barbell Bench Press", days_ago(20), straight(80, [8, 8, 8, 8]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.ADD_WEIGHT
    assert rec.weight == 82.5


def test_two_months_off_is_a_re_entry_at_ninety_percent():
    history = [entry("Barbell Bench Press", days_ago(70), straight(80, [8, 8, 8, 8]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.action is Action.BACK_OFF
    assert rec.weight == 72.5  # 80 × 0.9 = 72, onto the 2.5 kg grid
    assert rec.confidence is Confidence.LOW
    assert "re-entry" in rec.reason


def test_history_with_no_usable_date_cannot_trigger_a_staleness_decision():
    """Undated rows exist in restored backups; they must not poison the answer."""
    history = [entry("Barbell Bench Press", "not-a-date", straight(80, [8, 8, 8, 8]))]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.days_since is None
    assert rec.action is Action.ADD_WEIGHT


# ─────────────────────────────────────────────────────────────────────────
# 10. the odd schemes from data.py
# ─────────────────────────────────────────────────────────────────────────


PYRAMID = "Barbell Bench Press [5×12,10,8,8,8]"


def test_pyramid_progresses_only_when_every_step_meets_its_own_number():
    sets = [
        {"weight": 60, "reps": 12},
        {"weight": 70, "reps": 10},
        {"weight": 80, "reps": 8},
        {"weight": 80, "reps": 8},
        {"weight": 80, "reps": 8},
    ]
    rec = prog.recommend(PYRAMID, [entry("Barbell Bench Press", days_ago(4), sets)], today=TODAY)
    assert rec.action is Action.ADD_WEIGHT
    assert [t.weight for t in rec.per_set] == [62.5, 72.5, 82.5, 82.5, 82.5]
    assert [t.reps_low for t in rec.per_set] == [12, 10, 8, 8, 8]


def test_pyramid_that_misses_one_step_repeats_the_whole_ladder():
    sets = [
        {"weight": 60, "reps": 12},
        {"weight": 70, "reps": 9},  # one short of the prescribed 10
        {"weight": 80, "reps": 8},
        {"weight": 80, "reps": 8},
        {"weight": 80, "reps": 8},
    ]
    rec = prog.recommend(PYRAMID, [entry("Barbell Bench Press", days_ago(4), sets)], today=TODAY)
    assert rec.action is Action.REPEAT
    assert [t.weight for t in rec.per_set] == [60, 70, 80, 80, 80]
    assert "every step meets its number" in rec.reason


def test_amrap_says_out_loud_that_it_cannot_earn_a_jump():
    """`[4×max]` has no ceiling, so "hit the top of the range" is never true."""
    sets = [{"weight": 0, "reps": r} for r in (12, 10, 9, 8)]
    rec = prog.recommend("Pull-ups [4×max]", [entry("Pull-ups", days_ago(3), sets)], today=TODAY)
    assert rec.action is Action.REPEAT
    assert rec.weight is None  # bodyweight: there is nothing to load
    assert rec.confidence is Confidence.LOW
    assert "no rep ceiling" in rec.reason
    assert "39" in rec.reason  # beat the total, since there is no ceiling


def test_a_cluster_is_never_progressed_on_a_guess():
    """`[2×10+10+10]` — the log cannot say which segment a set belongs to."""
    sets = [{"weight": 15, "reps": 10} for _ in range(6)]
    rec = prog.recommend(
        "Cable Curl [triple drop] [2×10+10+10]",
        [entry("Cable Curl", days_ago(3), sets)],
        today=TODAY,
    )
    assert rec.action is Action.REPEAT
    assert rec.weight == 15
    assert rec.confidence is Confidence.LOW
    assert "cluster" in rec.reason


def test_an_unreadable_scheme_repeats_and_admits_it():
    history = [entry("Mystery Lift", days_ago(3), straight(40, [10, 10]))]
    rec = prog.recommend("Mystery Lift", history, today=TODAY)
    assert rec.action is Action.REPEAT
    assert rec.weight == 40
    assert rec.confidence is Confidence.LOW
    assert "No readable rep prescription" in rec.reason


# ─────────────────────────────────────────────────────────────────────────
# 11. every recommendation carries its reasoning
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "history",
    [
        [],
        [entry("Barbell Bench Press", days_ago(3), straight(80, [8, 8, 8, 8]))],
        [entry("Barbell Bench Press", days_ago(3), straight(80, [6, 6, 5, 5]))],
        [entry("Barbell Bench Press", days_ago(3), straight(80, [4, 4, 4, 4]))],
        [entry("Barbell Bench Press", days_ago(40), straight(80, [8, 8, 8, 8]))],
        [entry("Barbell Bench Press", days_ago(90), straight(80, [8, 8, 8, 8]))],
    ],
    ids=["none", "ceiling", "inside", "failed", "stale", "very-stale"],
)
def test_no_branch_ever_returns_a_bare_number(history):
    """A weight with no argument behind it is worth less than no weight."""
    rec = prog.recommend(BENCH, history, phase=BASE, routine=RECOMP, today=TODAY)
    assert len(rec.reason) > 40
    assert rec.target_label == "5-8 reps @ RIR 2-3"
    assert rec.scheme.sets == 4
    # A weight always comes with an increment behind it, and never the reverse.
    assert (rec.weight is None) == (rec.action is Action.BASELINE)
    assert (rec.increment is None) == (rec.action is Action.BASELINE)
    assert len(rec.last_sets) == (0 if not history else 4)


def test_the_recommendation_reports_the_session_it_read():
    history = [
        entry("Barbell Bench Press", days_ago(11), straight(77.5, [8, 8, 8, 8])),
        entry("Barbell Bench Press", days_ago(4), straight(80, [7, 7, 6, 6])),
    ]
    rec = prog.recommend(BENCH, history, phase=BASE, today=TODAY)
    assert rec.last_date == date(2026, 8, 14)
    assert rec.days_since == 4
    assert len(rec.last_sets) == 4
    assert rec.exercise == "Barbell Bench Press"  # the canonical DB key, no bracket


def test_history_order_does_not_matter():
    """Callers hand over whatever `get_exercise_history` or `get_all` returned."""
    newest = entry("Barbell Bench Press", days_ago(2), straight(80, [8, 8, 8, 8]))
    oldest = entry("Barbell Bench Press", days_ago(30), straight(70, [5, 5, 5, 5]))
    forwards = prog.recommend(BENCH, [oldest, newest], phase=BASE, today=TODAY)
    backwards = prog.recommend(BENCH, [newest, oldest], phase=BASE, today=TODAY)
    assert forwards.weight == backwards.weight == 82.5


# ─────────────────────────────────────────────────────────────────────────
# 12. the store adapter
# ─────────────────────────────────────────────────────────────────────────


class FakeStore:
    """Just the two methods `recommend_from_store` is allowed to call."""

    def __init__(self, rows):
        self.rows = rows
        self.asked = None

    def get_exercise_history(self, exercise, limit=20):
        self.asked = (exercise, limit)
        return [r for r in self.rows if r["exercise"] == exercise]


def test_recommend_from_store_queries_the_canonical_key():
    """The bracket never reaches the database — the bot writes the bare name."""
    store = FakeStore([entry("Barbell Bench Press", days_ago(3), straight(80, [8, 8, 8, 8]))])
    rec = prog.recommend_from_store(store, BENCH, phase=BASE, routine=RECOMP, today=TODAY)
    assert store.asked == ("Barbell Bench Press", prog.DEFAULT_HISTORY_LIMIT)
    assert rec.action is Action.ADD_WEIGHT
    assert rec.weight == 82.5


def test_recommend_from_store_on_an_empty_database_still_answers():
    store = FakeStore([])
    rec = prog.recommend_from_store(store, SQUAT, phase=BASE, routine=RECOMP, today=TODAY)
    assert rec.action is Action.BASELINE
    assert rec.weight is None


# ─────────────────────────────────────────────────────────────────────────
# 13. a whole session of the routine Alex actually trains
# ─────────────────────────────────────────────────────────────────────────


def test_a_full_push_day_produces_one_answer_per_exercise():
    """Nothing in a real session may raise, and every row gets a target string."""
    push = RECOMP.days_for_phase(ACCUMULATION.id)[0]
    assert push.name == "Push"
    for ex in push.exercises:
        rec = prog.recommend(ex, [], phase=ACCUMULATION, routine=RECOMP, today=TODAY)
        assert rec.action is Action.BASELINE
        assert rec.target_label.endswith("RIR 2-3")
        assert rec.reason


def test_the_module_stays_pure():
    """No Flet, no import-time database, no view imports.

    This is the property that lets the Telegram coach reuse the same rules, and
    that keeps every test in this file free of PostgreSQL. It is one grep, and
    it is much cheaper than discovering the coupling from a failing import in
    another repo.
    """
    import pathlib

    source = pathlib.Path(prog.__file__).read_text()
    assert "import flet" not in source
    assert "from views" not in source and "import views" not in source
    # Storage is reached through a duck-typed argument, never constructed here.
    assert "Storage(" not in source


def test_every_exercise_of_every_routine_survives_a_realistic_history():
    """A blunt sweep: 348 prescriptions × one logged session, nothing raises."""
    for routine in data.ROUTINES:
        for phase in routine.phases:
            for day in routine.days_for_phase(phase.id):
                for ex in day.exercises:
                    history = [
                        entry(
                            prog.exercise_key(ex),
                            days_ago(4),
                            straight(40, [10, 10, 10, 10]),
                        )
                    ]
                    rec = prog.recommend(ex, history, phase=phase, routine=routine, today=TODAY)
                    assert rec.reason
                    assert rec.action in set(Action)


# ── deload weeks (added after the module shipped recommending +2.5 kg in one) ──


class FaseFalsa:
    def __init__(self, name="", notes="", scheme="", subtitle=""):
        self.id = 1
        self.name = name
        self.notes = notes
        self.scheme = scheme
        self.subtitle = subtitle


class SesionFalsa:
    def __init__(self, dia, sets):
        self.date = dia.isoformat()
        self.sets = sets


def _tope(peso=80.0, reps=8, n=4):
    return [{"weight": peso, "reps": reps, "rir": 2} for _ in range(n)]


def test_la_descarga_no_sube_el_peso():
    """RECOMP phase 3 says "Same loads, half the sets" in as many words.

    Hitting the top of the range on a halved set count is the *expected*
    outcome of a deload, so the plain double-progression rule fired on every
    lift and turned the recovery week into a week of PRs.
    """
    from datetime import date, timedelta

    import progression as pr

    fase = FaseFalsa(name="Deload", notes="Same loads, half the sets.", scheme="2×5-8")
    hoy = date.today()
    rec = pr.recommend(
        "Barbell Bench Press [4×5-8]",
        [SesionFalsa(hoy - timedelta(days=7), _tope())],
        phase=fase,
        today=hoy,
    )
    assert rec.action is pr.Action.HOLD_DELOAD
    assert rec.weight == 80.0, "the deload must repeat the load, not add to it"
    assert "deload" in rec.reason.lower()


def test_una_fase_normal_si_sube():
    """The guard must not freeze progression outside a recovery week."""
    from datetime import date, timedelta

    import progression as pr

    fase = FaseFalsa(name="Accumulation", notes="Double progression: add 2.5 kg upper.")
    hoy = date.today()
    rec = pr.recommend(
        "Barbell Bench Press [4×5-8]",
        [SesionFalsa(hoy - timedelta(days=7), _tope())],
        phase=fase,
        today=hoy,
    )
    assert rec.action is pr.Action.ADD_WEIGHT
    assert rec.weight == 82.5


def test_is_deload_reconoce_ambas_rutinas():
    """Both shipped routines name the phase differently around it."""
    import data
    import progression as pr

    for rid in ("recomp-ppl-ul", "cambiatufisico"):
        data.set_active_routine(rid)
        fases = data.active_routine().phases
        descargas = [f for f in fases if pr.is_deload(f)]
        assert len(descargas) == 1, f"{rid}: expected exactly one deload phase"
        assert "deload" in descargas[0].name.lower()
    data.set_active_routine("cambiatufisico")


def test_sin_fase_no_es_descarga():
    import progression as pr

    assert pr.is_deload(None) is False
    assert pr.is_deload(FaseFalsa(name="Base", notes="Find a load.")) is False
