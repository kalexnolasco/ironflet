"""Tests for session_plan.py.

No database and no Flet — everything under test is a pure function.

Three groups carry the weight:

* **The real routine.** Every one of CambiaTuFísico's 178 prescribed exercises
  across all 7 phases is planned and counted. The numbers are frozen: 635
  prescribed sets (457 more than the one row the screen used to open) and 25
  drop rows. Those constants are the measurement the module was written from, so
  a change to `data.py` or to `progression.parse_scheme` that moves them fails
  here rather than quietly changing what the gym screen opens with.
* **The draft invariant.** `to_draft_rows()` must emit rows that
  `workout_draft.is_blank_row()` calls blank, in exactly the shape
  `workout_draft.blank_row()` uses. This is the one that stops a proposal being
  saved as history, so it is tested against the real `workout_draft`, not a copy
  of its rules.
* **The assumptions this module makes about `progression`.** It re-reads
  `Scheme.raw` to recover the drop tails that `Scheme.per_set` flattens away.
  `test_segment_heads_match_per_set` walks the whole routine asserting the two
  readings agree, so a change to `_parse_reps_text` shows up as a failing test
  instead of a different plan.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import data
import session_plan as sp
import workout_draft
from progression import SchemeKind, parse_scheme
from session_plan import (
    MAX_PROPOSED_ROWS,
    ProposedSet,
    SessionPlan,
    SetCountSource,
    history_set_count,
    is_combination,
    is_drop_cluster,
    plan_sets,
    to_draft_rows,
)
from set_types import TYPE_KEY, SetType

# ─────────────────────────────────────────────────────────────────────────
# the real routine
# ─────────────────────────────────────────────────────────────────────────

#: What CambiaTuFísico actually prescribes, measured off `data.py`.
EXPECTED_EXERCISES = 178
EXPECTED_PRESCRIBED_SETS = 635
#: 635 prescribed sets minus one row per exercise: the "+ Set" taps this module
#: removes over the 24 weeks. The number in the bug report.
EXPECTED_SAVED_TAPS = 457
#: All of them in phase 6: 21 `↓` marks in the brackets (18 exercises, three of
#: which carry two) plus the 4 extra segments of the two rounds of
#: `Cable Curl [triple drop] [2×10+10+10]`.
EXPECTED_DROP_ROWS = 25

#: Sets prescribed per phase, and how many drop rows each opens.
EXPECTED_BY_PHASE = {
    1: (75, 0),
    2: (75, 0),
    3: (92, 0),
    4: (72, 0),
    5: (133, 0),
    6: (84, 25),
    7: (104, 0),
}


def routine():
    return next(r for r in data.ROUTINES if r.id == "cambiatufisico")


def all_prescriptions():
    """`(phase, exercise string)` for every exercise in the real routine."""
    rt = routine()
    for phase in rt.phases:
        for day in rt.days_by_phase[phase.id]:
            for exercise in day.exercises:
                yield phase, exercise


def test_the_routine_is_the_size_the_constants_claim():
    assert len(list(all_prescriptions())) == EXPECTED_EXERCISES


def test_every_phase_opens_the_rows_the_plan_prescribes():
    by_phase: dict[int, list[int]] = {p.id: [0, 0] for p in routine().phases}
    for phase, exercise in all_prescriptions():
        plan = plan_sets(exercise, phase)
        by_phase[phase.id][0] += plan.working_count()
        by_phase[phase.id][1] += plan.drop_count()
    assert {k: tuple(v) for k, v in by_phase.items()} == EXPECTED_BY_PHASE


def test_totals_match_the_measured_bug():
    sets = drops = 0
    for phase, exercise in all_prescriptions():
        plan = plan_sets(exercise, phase)
        sets += plan.working_count()
        drops += plan.drop_count()
    assert sets == EXPECTED_PRESCRIBED_SETS
    assert drops == EXPECTED_DROP_ROWS
    assert sets - EXPECTED_EXERCISES == EXPECTED_SAVED_TAPS


def test_working_count_always_equals_the_parsed_set_count():
    """The prescribed set count is `parse_scheme`'s answer, never a second one."""
    for phase, exercise in all_prescriptions():
        scheme = parse_scheme(exercise, phase.scheme)
        plan = plan_sets(exercise, phase)
        assert plan.working_count() == scheme.sets, exercise


def test_no_exercise_in_the_routine_is_unreadable():
    """Every real prescription parses. A warning here means a silent fallback."""
    for phase, exercise in all_prescriptions():
        plan = plan_sets(exercise, phase)
        assert plan.is_known(), exercise
        assert plan.warnings == (), (exercise, plan.warnings)


def test_phases_1_to_4_take_their_count_from_the_phase_scheme():
    """The exercises carry no bracket there; the number lives only in the phase."""
    for phase, exercise in all_prescriptions():
        if phase.id > 4:
            continue
        plan = plan_sets(exercise, phase)
        assert plan.scheme.source in ("phase", "phase-star"), exercise
        assert plan.working_count() >= 3, exercise


def test_a_phase_scheme_is_needed_for_phases_1_to_4():
    """Without the phase, the same exercise falls back to a single row.

    This is the integration trap: `plan_sets(name)` with no phase looks like it
    works — it returns a plan — and quietly gives back exactly the one empty row
    the module exists to replace.
    """
    plan = plan_sets("Smith Bench Press")
    assert len(plan) == 1
    assert not plan.is_known()
    assert plan_sets("Smith Bench Press", routine().phases[1]).working_count() == 3


def test_segment_heads_match_per_set():
    """The re-read of `Scheme.raw` agrees with `progression`'s own `per_set`."""
    checked = 0
    for phase, exercise in all_prescriptions():
        scheme = parse_scheme(exercise, phase.scheme)
        if scheme.kind is not SchemeKind.PYRAMID:
            continue
        segments = sp._pyramid_segments(scheme)
        heads = tuple(sp._reps_of(s.split("+")[0]) for s in segments)
        assert heads == scheme.per_set, exercise
        checked += 1
    assert checked > 0


# ─────────────────────────────────────────────────────────────────────────
# how many, and what each one aims at
# ─────────────────────────────────────────────────────────────────────────


def test_fixed_scheme_opens_one_row_per_set_with_the_same_target():
    plan = plan_sets("Smith Bench Press", "3×12")
    assert len(plan) == 3
    assert [p.reps_low for p in plan.proposals] == [12, 12, 12]
    assert [p.reps_high for p in plan.proposals] == [12, 12, 12]
    assert {p.reps_label for p in plan.proposals} == {"12"}
    assert {p.set_type for p in plan.proposals} == {SetType.NORMAL}


def test_range_scheme_carries_both_ends():
    plan = plan_sets("Smith Bench Press", "3×8-10")
    assert len(plan) == 3
    assert all(p.reps_low == 8 and p.reps_high == 10 for p in plan.proposals)
    assert plan.proposals[0].reps_label == "8-10"


def test_starred_exercise_takes_the_phases_alternate():
    plan = plan_sets("Pec Deck *", "4×5-6 (*=3×8)")
    assert plan.scheme.source == "phase-star"
    assert len(plan) == 3
    assert all(p.reps_low == 8 for p in plan.proposals)


def test_bracket_beats_the_phase_scheme():
    plan = plan_sets("Deadlift [3×12]", "5×5")
    assert plan.scheme.source == "bracket"
    assert plan.working_count() == 3


def test_pyramid_gives_a_different_target_per_set():
    plan = plan_sets("Barbell Bench Press [5×12,10,8,8,8]")
    assert len(plan) == 5
    assert [p.reps_low for p in plan.proposals] == [12, 10, 8, 8, 8]
    assert [p.set_number for p in plan.proposals] == [1, 2, 3, 4, 5]
    assert plan.drop_count() == 0


def test_positions_are_contiguous_and_one_based():
    for phase, exercise in all_prescriptions():
        plan = plan_sets(exercise, phase)
        assert [p.position for p in plan.proposals] == list(range(1, len(plan) + 1)), exercise


def test_set_numbers_skip_drop_rows():
    plan = plan_sets("Barbell Bench Press [4×10,10,8,6+12↓]")
    assert [p.set_number for p in plan.proposals] == [1, 2, 3, 4, None]


# ─────────────────────────────────────────────────────────────────────────
# the drop set
# ─────────────────────────────────────────────────────────────────────────


def test_drop_set_is_created_and_labelled():
    """`[4×10,10,8,6+12↓]` — four sets of 10,10,8,6 plus one descending 12."""
    plan = plan_sets("Barbell Bench Press [4×10,10,8,6+12↓]")
    assert len(plan) == 5
    assert plan.working_count() == 4
    assert plan.drop_count() == 1
    assert [p.reps_low for p in plan.proposals] == [10, 10, 8, 6, 12]

    drop = plan.proposals[-1]
    assert drop.set_type is SetType.DROPSET
    assert drop.is_drop()
    assert drop.set_number is None
    assert drop.drop_of == 4
    assert drop.reps_label == "12"
    assert "↓" not in drop.reps_label
    assert drop.label() == "Drop · 12 reps"


def test_a_drop_set_is_never_a_plain_working_set():
    """The bug being fixed: the descending set used to be an ordinary row."""
    plan = plan_sets("Barbell Bench Press [4×10,10,8,6+12↓]")
    assert plan.has_drop()
    assert all(p.set_type is SetType.NORMAL for p in plan.proposals[:4])
    assert to_draft_rows(plan)[-1][TYPE_KEY] == SetType.DROPSET.value


def test_two_drops_in_one_exercise_land_on_their_own_sets():
    """`[3×10,8+12↓,8+12↓]` — sets 2 and 3 each carry a drop, not just the last.

    Three of the routine's exercises are written this way. Treating "has_drop"
    as "one drop, on the final set" loses one of the two.
    """
    plan = plan_sets("Plate Front Raises [3×10,8+12↓,8+12↓]")
    assert plan.working_count() == 3
    assert plan.drop_count() == 2
    assert [p.set_type for p in plan.proposals] == [
        SetType.NORMAL,
        SetType.NORMAL,
        SetType.DROPSET,
        SetType.NORMAL,
        SetType.DROPSET,
    ]
    assert [p.drop_of for p in plan.proposals if p.is_drop()] == [2, 3]


def test_every_drop_row_follows_the_set_it_hangs_off():
    for phase, exercise in all_prescriptions():
        plan = plan_sets(exercise, phase)
        for i, row in enumerate(plan.proposals):
            if not row.is_drop():
                continue
            assert i > 0, exercise
            previous = plan.proposals[i - 1]
            owner = previous.set_number if previous.set_number else previous.drop_of
            assert row.drop_of == owner, exercise


def test_the_routine_prescribes_drops_only_in_phase_6():
    """Phase 6 is "High Intensity — Drop Sets + Compound". Nowhere else."""
    with_drops = {p.id for p, e in all_prescriptions() if plan_sets(e, p).has_drop()}
    assert with_drops == {6}


def test_a_drop_mark_with_no_tail_still_opens_a_row():
    """`[3×8↓]` does not occur today. It must not be silently ignored if it does."""
    plan = plan_sets("Something [3×8↓]")
    assert plan.working_count() == 3
    assert plan.drop_count() == 1
    drop = plan.proposals[-1]
    assert drop.set_type is SetType.DROPSET
    assert not drop.has_target()
    assert plan.warnings


# ─────────────────────────────────────────────────────────────────────────
# the schemes double progression cannot drive
# ─────────────────────────────────────────────────────────────────────────


def test_amrap_opens_the_sets_with_no_target_and_a_failure_type():
    plan = plan_sets("Hanging Abs [5×max]")
    assert len(plan) == 5
    assert all(p.set_type is SetType.FAILURE for p in plan.proposals)
    assert not any(p.has_target() for p in plan.proposals)
    assert {p.reps_label for p in plan.proposals} == {"max"}


def test_failure_spelled_out_is_the_same_answer():
    plan = plan_sets("Push-ups [3×failure]")
    assert len(plan) == 3
    assert all(p.set_type is SetType.FAILURE for p in plan.proposals)
    assert not any(p.has_target() for p in plan.proposals)


def test_triple_drop_expands_into_its_segments():
    """`[2×10+10+10]` on one movement: two rounds of set-plus-two-drops."""
    plan = plan_sets("Cable Curl [triple drop] [2×10+10+10]")
    assert is_drop_cluster("Cable Curl [triple drop] [2×10+10+10]")
    assert len(plan) == 6
    assert plan.working_count() == 2
    assert plan.drop_count() == 4
    assert [p.set_type for p in plan.proposals] == [
        SetType.NORMAL,
        SetType.DROPSET,
        SetType.DROPSET,
        SetType.NORMAL,
        SetType.DROPSET,
        SetType.DROPSET,
    ]
    assert [p.drop_of for p in plan.proposals if p.is_drop()] == [1, 1, 2, 2]
    assert all(p.reps_low == 10 for p in plan.proposals)


def test_a_biset_opens_one_row_per_round_not_per_movement():
    """Expanding it would double every component's set count in analytics.

    `analytics.resolve_muscles` splits the combined name and credits each
    component the entry's *full* set count. Eight rows for a four-round bi-set
    would report eight sets of chest instead of four, for the whole of phase 7.
    """
    exercise = "Bi-set: Incline DB Press + Flat Machine Press [4×8+10]"
    plan = plan_sets(exercise)
    assert is_combination(exercise)
    assert len(plan) == 4
    assert plan.drop_count() == 0
    assert {p.set_type for p in plan.proposals} == {SetType.NORMAL}
    # The row still says what to do, even though it holds one weight box.
    assert {p.reps_label for p in plan.proposals} == {"8+10"}
    assert not any(p.has_target() for p in plan.proposals)


def test_a_triset_is_a_combination_too():
    plan = plan_sets("Triset: Front + Lateral + Rear Delts [4×10+10+10]")
    assert len(plan) == 4
    assert plan.proposals[0].reps_label == "10+10+10"


def test_abs_triset_is_a_combination_despite_the_word_order():
    """ "Abs Triset" is not `Triset:`-prefixed, and is still three movements.

    `analytics._COMBO_PREFIX_RE` anchors to the front and does not see this one.
    Reading it as a single-movement cluster would open 12 rows, 8 of them
    labelled drop sets, for four rounds of three different ab exercises.
    """
    assert is_combination("Abs Triset [4×(20+20+20)]")
    plan = plan_sets("Abs Triset [4×(20+20+20)]")
    assert len(plan) == 4
    assert plan.drop_count() == 0


def test_joined_names_are_combinations():
    for name in (
        "V-Pulldown + V-Row [comp] [4×8+8]",
        "Lying + Seated Leg Curl [comp] [4×10+10]",
        "Calf Press + Seated [comp] [4×12+12]",
    ):
        assert is_combination(name), name
        assert not is_drop_cluster(name), name
        assert len(plan_sets(name)) == 4


def test_every_cluster_in_the_routine_is_classified_on_purpose():
    """Pins the combination/drop split for all 33 real cluster strings.

    Both classifiers are heuristics over prose written by a human. Freezing the
    real data is the only guard that means anything: a rule change that flips one
    of these silently changes how a whole phase is logged.
    """
    clusters = {
        e for p, e in all_prescriptions() if parse_scheme(e, p.scheme).kind is SchemeKind.CLUSTER
    }
    assert len(clusters) == 33
    drop_clusters = {e for e in clusters if is_drop_cluster(e)}
    assert drop_clusters == {"Cable Curl [triple drop] [2×10+10+10]"}
    assert all(is_combination(e) for e in clusters - drop_clusters)


def test_a_bare_cluster_defaults_to_one_row_per_round():
    """No marker either way: never invent rows that can be filled in and saved."""
    name = "Mystery Machine [3×10+10]"
    assert not is_combination(name)
    assert not is_drop_cluster(name)
    assert len(plan_sets(name)) == 3


def test_a_failure_segment_inside_a_biset_keeps_the_row_countable():
    plan = plan_sets("Bi-set: Decline Press + Push-ups [3×8+failure]")
    assert len(plan) == 3
    assert plan.proposals[0].reps_label == "8+failure"


# ─────────────────────────────────────────────────────────────────────────
# nothing readable
# ─────────────────────────────────────────────────────────────────────────


def test_no_scheme_opens_exactly_one_row_and_says_so():
    plan = plan_sets("Some Exercise Nobody Prescribed")
    assert len(plan) == 1
    assert not plan.is_known()
    assert plan.proposals[0].set_type is SetType.NORMAL
    assert not plan.proposals[0].has_target()
    assert plan.plan_set_count is None
    assert "nothing assumed" in plan.reason
    assert plan.warnings


@pytest.mark.parametrize("exercise", ["", "   ", "Only Tags [comp]", "Bad [x×y]", "Nope [0×]"])
def test_unreadable_input_never_raises(exercise):
    plan = plan_sets(exercise, "not a scheme either")
    assert isinstance(plan, SessionPlan)
    assert len(plan) >= 1
    assert all(isinstance(p, ProposedSet) for p in plan.proposals)


def test_a_pyramid_with_fewer_targets_than_sets_repeats_the_last():
    plan = plan_sets("Odd [4×10,8]")
    assert plan.working_count() == 4
    assert [p.reps_low for p in plan.proposals] == [10, 8, 8, 8]
    assert plan.warnings


def test_an_unrecognised_segment_tail_is_not_turned_into_a_row():
    """`[4×10,8+8]`: a `+` with no `↓`. Undocumented, so no row is invented."""
    plan = plan_sets("Odd [4×10,8+8]")
    assert plan.drop_count() == 0
    assert plan.working_count() == 4
    assert any("unrecognised" in w for w in plan.warnings)


def test_the_row_count_is_capped():
    plan = plan_sets("Silly [40×10+10+10]")
    assert len(plan) == MAX_PROPOSED_ROWS
    assert any("Capped" in w for w in plan.warnings)


# ─────────────────────────────────────────────────────────────────────────
# the history conflict
# ─────────────────────────────────────────────────────────────────────────

THREE_SETS = [
    {"weight": 60, "reps": 10},
    {"weight": 60, "reps": 10},
    {"weight": 65, "reps": 8},
]


def test_the_plan_wins_by_default():
    plan = plan_sets("Squat [5×12,10,10,8,8]", last_session=THREE_SETS)
    assert plan.working_count() == 5
    assert plan.count_source is SetCountSource.PLAN
    assert plan.plan_set_count == 5
    assert plan.history_set_count == 3
    assert plan.disagrees_with_history()
    assert "Last session had 3" in plan.reason


def test_the_caller_can_ask_for_the_other_answer():
    plan = plan_sets(
        "Squat [5×12,10,10,8,8]",
        last_session=THREE_SETS,
        count_source=SetCountSource.LAST_SESSION,
    )
    assert plan.working_count() == 3
    assert [p.reps_low for p in plan.proposals] == [12, 10, 10]
    assert plan.plan_set_count == 5
    assert plan.history_set_count == 3


def test_following_history_still_keeps_the_plans_drop_set():
    """A truncated count must not delete the one thing phase 6 is about."""
    plan = plan_sets(
        "Barbell Bench Press [4×10,10,8,6+12↓]",
        last_session=THREE_SETS,
        count_source=SetCountSource.LAST_SESSION,
    )
    assert plan.working_count() == 3
    assert plan.drop_count() == 1
    assert plan.proposals[-1].set_type is SetType.DROPSET
    assert plan.proposals[-1].drop_of == 3
    assert plan.warnings


def test_history_larger_than_the_plan_extends_the_pyramid():
    six = THREE_SETS * 2
    plan = plan_sets(
        "Calf Press [3×15,12,12]", last_session=six, count_source=SetCountSource.LAST_SESSION
    )
    assert plan.working_count() == 6
    assert [p.reps_low for p in plan.proposals] == [15, 12, 12, 12, 12, 12]


def test_no_history_falls_back_to_the_plan():
    for empty in (None, [], [{"weight": 20, "reps": 15, TYPE_KEY: "warmup"}]):
        plan = plan_sets(
            "Squat [5×12,10,10,8,8]", last_session=empty, count_source=SetCountSource.LAST_SESSION
        )
        assert plan.working_count() == 5
        assert not plan.disagrees_with_history()


def test_history_count_excludes_warmups_and_drops():
    """Warm-ups are not prescribed sets, and a drop is a tail, not a set."""
    session = [
        {"weight": 20, "reps": 15, TYPE_KEY: "warmup"},
        {"weight": 60, "reps": 10},
        {"weight": 60, "reps": 10},
        {"weight": 40, "reps": 12, TYPE_KEY: "dropset"},
    ]
    assert history_set_count(session) == 2
    assert history_set_count([]) is None
    assert history_set_count(None) is None


def test_untyped_history_rows_count_as_prescribed_sets():
    """Everything the Telegram coach writes has no `"type"` key."""
    assert history_set_count([{"weight": 60, "reps": 10}] * 4) == 4


def test_no_number_from_history_reaches_the_proposals():
    """The count is read. Nothing else is — a weight from here is false history.

    The session below is built so that a leak would be unmistakable: its weights
    (97.5, 102.5) and its performed reps (7, 9) appear nowhere in the plan's own
    targets, so finding either one in the output means history was copied.
    """
    session = [
        {"weight": 97.5, "reps": 7, "rir": 1},
        {"weight": 102.5, "reps": 9, "rir": 0},
    ]
    plan = plan_sets(
        "Squat [5×12,10,10,8,8]",
        last_session=session,
        count_source=SetCountSource.LAST_SESSION,
    )
    assert plan.working_count() == 2
    # Targets come from the plan's pyramid, not from what was performed.
    assert [p.reps_low for p in plan.proposals] == [12, 10]

    leaked = {97.5, 102.5, 7, 9}
    for row in plan.proposals:
        assert row.reps_low not in leaked
        assert row.reps_high not in leaked
    assert [row.reps_label for row in plan.proposals] == ["12", "10"]
    assert all(v == "" for row in to_draft_rows(plan) for v in row.values() if v != "normal")


# ─────────────────────────────────────────────────────────────────────────
# the draft invariant
# ─────────────────────────────────────────────────────────────────────────


def test_draft_rows_have_exactly_the_shape_workout_draft_expects():
    plan = plan_sets("Smith Bench Press", "3×12")
    reference = workout_draft.blank_row()
    for row in to_draft_rows(plan):
        assert set(row) == set(reference)
    assert set(sp.DRAFT_ROW_FIELDS) == set(workout_draft.ROW_FIELDS)


def test_every_proposed_row_is_blank_to_the_draft():
    """The invariant, checked against the real `is_blank_row`.

    Proposed rows are persisted as empty holes on purpose. If any of them ever
    carried a value, restoring a draft would turn something the app guessed into
    something Alex is recorded as having lifted.
    """
    for phase, exercise in all_prescriptions():
        for row in to_draft_rows(plan_sets(exercise, phase)):
            assert workout_draft.is_blank_row(row), exercise


def test_a_rep_target_never_lands_in_the_reps_box():
    """`reps` means reps *performed* in `entrenos.series`, everywhere."""
    plan = plan_sets("Barbell Bench Press [5×12,10,8,8,8]")
    assert plan.proposals[0].reps_low == 12
    assert all(row["reps"] == "" for row in to_draft_rows(plan))


def test_only_the_type_is_carried_into_the_draft():
    plan = plan_sets("Barbell Bench Press [4×10,10,8,6+12↓]")
    rows = to_draft_rows(plan)
    assert [r[TYPE_KEY] for r in rows] == ["normal"] * 4 + ["dropset"]
    assert all(r["weight"] == "" and r["reps"] == "" and r["rir"] == "" for r in rows)


def test_draft_rows_survive_a_round_trip_through_the_draft_normaliser():
    plan = plan_sets("Cable Curl [triple drop] [2×10+10+10]")
    rows = to_draft_rows(plan)
    assert workout_draft.normalize_rows(rows) == rows


def test_a_proposed_set_carries_no_weight_field():
    """Structural: there is no place to put a number that was never lifted."""
    assert "weight" not in ProposedSet.__dataclass_fields__
    assert "reps" not in ProposedSet.__dataclass_fields__


# ─────────────────────────────────────────────────────────────────────────
# labels, reasons and purity
# ─────────────────────────────────────────────────────────────────────────


def test_labels_never_say_one_sets():
    assert plan_sets("Something Unknown").label() == "1 set"
    assert plan_sets("X [3×10]").label() == "3 sets"
    assert plan_sets("Barbell Bench Press [4×10,10,8,6+12↓]").label() == "4 sets + 1 drop"
    assert plan_sets("Plate Front Raises [3×10,8+12↓,8+12↓]").label() == "3 sets + 2 drops"


def test_every_reason_is_a_sentence_quoting_the_prescription():
    for phase, exercise in all_prescriptions():
        plan = plan_sets(exercise, phase)
        assert plan.reason.endswith("."), exercise
        assert plan.scheme.label() in plan.reason, exercise


def test_module_is_pure():
    """No Flet, no database, no view imports — the same contract as analytics.

    Checked on the source rather than on `sys.modules`, because by the time this
    runs another test has almost certainly imported half the app already.
    """
    text = Path(sp.__file__).read_text(encoding="utf-8")
    body = text.split('"""', 2)[-1]  # skip the docstring, which names these on purpose
    for forbidden in ("import flet", "from flet", "sqlalchemy", "storage", "views."):
        assert forbidden not in body, forbidden
