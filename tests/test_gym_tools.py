"""Tests for gym_tools.py.

No database and no Flet: every function under test is pure, so the cases are
literal data. The numbers are hand-computed from the bar weight and the plate
sizes rather than from the implementation — a plate calculator that agrees with
itself is worthless; it has to agree with the rack.

Two invariants get their own property-style sweeps because they are the whole
point of the module and a regression in either is silent:

* everything `warmup_plan` returns can actually be loaded;
* the RM helpers are exact inverses of `analytics.estimated_1rm`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analytics import estimated_1rm
from gym_tools import (
    BARS,
    DEFAULT_BAR,
    DEFAULT_INVENTORY,
    EZ_BAR,
    MINIMAL_INVENTORY,
    NO_MICRO_INVENTORY,
    PLANNING_PERCENTAGES,
    RELIABLE_MAX_REPS,
    TRAINING_BAR,
    WARMUP_SCHEMES,
    WOMENS_BAR,
    Bar,
    PlateInventory,
    bar_for_exercise,
    loadable_options,
    percentage_table,
    plate_breakdown,
    predicted_reps,
    round_to_loadable,
    warmup_plan,
    weight_for_reps,
)

# Racks used across the file, named so the assertions read as intentions.
FULL = DEFAULT_INVENTORY
NO_MICRO = NO_MICRO_INVENTORY
TINY = MINIMAL_INVENTORY
#: One 20 and two 15s. The shape that breaks greedy plate maths: 30 kg a side
#: exists (15+15) but greedy commits to the 20 and then cannot make 10.
GREEDY_TRAP = PlateInventory.of({20: 1, 15: 2})


# ── the module stays pure ────────────────────────────────────────────────


def test_module_imports_no_flet_and_no_storage():
    """Same contract as analytics.py: plain data in, plain data out.

    Asserted on the source because an accidental `import flet` inside a helper
    would still let every other test pass, and the Telegram coach — which has
    no Flet installed — imports this module.
    """
    source = (Path(__file__).resolve().parents[1] / "gym_tools.py").read_text()
    assert "import flet" not in source
    assert "from storage" not in source and "import storage" not in source


# ── plate calculator: weights that come out exact ────────────────────────


@pytest.mark.parametrize(
    ("target", "per_side"),
    [
        (20.0, ()),  # bar alone
        (30.0, (5.0,)),
        (40.0, (10.0,)),
        (60.0, (20.0,)),
        (100.0, (20.0, 20.0)),
        (82.5, (20.0, 10.0, 1.25)),  # the awkward one this module exists for
        (22.5, (1.25,)),
        (25.0, (2.5,)),
    ],
)
def test_exact_loads_on_a_full_rack(target, per_side):
    options = loadable_options(target, bar=DEFAULT_BAR, inventory=FULL)
    assert options.loadable
    assert options.exact.per_side == per_side
    assert options.exact.total == target
    assert options.exact.delta == 0.0
    # below/above are still populated: the UI may want the next jump either way.
    assert options.below is None or options.below.total < target
    assert options.above is None or options.above.total > target


def test_total_is_always_bar_plus_two_sides():
    """The symmetry that makes the whole thing valid. Checked, not assumed."""
    for target in range(20, 200):
        solution = plate_breakdown(target, bar=DEFAULT_BAR, inventory=FULL)
        assert solution.total == round(solution.bar + 2 * sum(solution.per_side), 2)


def test_plates_come_back_heaviest_first():
    solution = plate_breakdown(97.5, bar=DEFAULT_BAR, inventory=FULL)
    assert list(solution.per_side) == sorted(solution.per_side, reverse=True)


def test_fewest_plates_wins_then_the_heavier_start():
    # 20 kg a side: one 20, never two 10s.
    assert plate_breakdown(60, inventory=FULL).per_side == (20.0,)
    # 31.25 a side is three plates either way (20+10+1.25 or 15+15+1.25).
    # The big disc goes against the collar.
    assert plate_breakdown(82.5, inventory=FULL).per_side[0] == 20.0


# ── plate calculator: weights that cannot be built ───────────────────────


def test_unloadable_weight_reports_both_neighbours_and_never_fails_silently():
    options = loadable_options(43.7, bar=DEFAULT_BAR, inventory=FULL)
    assert options.exact is None and not options.loadable
    # 22.5 kg of plate is wanted per side; 11.25 and 12.5 are the neighbours.
    assert options.below.total == 42.5
    assert options.above.total == 45.0
    assert options.below.delta == -1.2
    assert options.above.delta == 1.3
    assert "not loadable" in options.summary()
    assert "42.5" in options.summary() and "45" in options.summary()


def test_nearest_breaks_a_tie_downwards():
    """Erring light is the recoverable error; a heavy warm-up eats the work set."""
    # 21.25 kg sits exactly between the bare 20 kg bar and 22.5 kg.
    options = loadable_options(21.25, bar=DEFAULT_BAR, inventory=FULL)
    assert options.exact is None
    assert options.below.total == 20.0 and options.above.total == 22.5
    assert options.nearest.total == 20.0


def test_no_micro_plates_makes_common_weights_unloadable():
    """The rack Alex may actually have: 2.5 kg is the smallest disc."""
    options = loadable_options(82.5, bar=DEFAULT_BAR, inventory=NO_MICRO)
    assert options.exact is None
    assert options.below.total == 80.0
    assert options.above.total == 85.0
    # Same weight on the full rack is fine — the difference is the rack, not the bar.
    assert loadable_options(82.5, bar=DEFAULT_BAR, inventory=FULL).loadable


def test_greedy_would_fail_here_and_the_solver_does_not():
    """A rack of one 20 and two 15s, where "take the heaviest that fits" loses."""
    # 50 kg on a 20 kg bar = 15 a side. Greedy would take the 20 and give up.
    exact = loadable_options(50, bar=DEFAULT_BAR, inventory=GREEDY_TRAP).exact
    assert exact is not None and exact.per_side == (15.0,)
    # 80 kg = 30 a side, which only exists as 15+15 — the 20 cannot start it.
    exact = loadable_options(80, bar=DEFAULT_BAR, inventory=GREEDY_TRAP).exact
    assert exact is not None and exact.per_side == (15.0, 15.0)


# ── plate calculator: edges ──────────────────────────────────────────────


def test_bar_alone_is_always_loadable_even_with_an_empty_rack():
    empty = PlateInventory.of({})
    options = loadable_options(20, bar=DEFAULT_BAR, inventory=empty)
    assert options.loadable
    assert options.exact.bar_only
    assert options.exact.label() == "solo barra"
    assert options.above is None  # nothing heavier exists


def test_target_below_the_bar_says_so_instead_of_pretending():
    options = loadable_options(15, bar=DEFAULT_BAR, inventory=FULL)
    assert options.under_bar
    assert options.exact is None
    assert options.below is None  # you cannot take weight off a bar
    assert options.above.total == 20.0 and options.above.bar_only
    assert options.nearest.total == 20.0
    assert "por debajo de la barra" in options.summary()


def test_zero_and_tiny_targets_are_under_the_bar_not_errors():
    for target in (0, 0.5, 5):
        options = loadable_options(target, bar=DEFAULT_BAR, inventory=FULL)
        assert options is not None and options.under_bar
        assert options.nearest.total == 20.0


def test_target_beyond_what_the_rack_holds_reports_the_ceiling():
    options = loadable_options(500, bar=DEFAULT_BAR, inventory=FULL)
    assert options.exact is None
    assert options.above is None  # nothing heavier can be built
    # 5×20 + 2×15 + 2×10 + 2×5 + 2×2.5 + 2×1.25 = 167.5 a side.
    assert options.below.total == 20 + 2 * 167.5
    assert options.nearest is options.below


def test_a_single_unpaired_plate_is_not_usable():
    """Inventory counts pairs. A lone plate cannot be loaded symmetrically."""
    one_pair = PlateInventory.of({10: 1})
    assert loadable_options(40, inventory=one_pair).loadable  # 10 a side
    assert not loadable_options(60, inventory=one_pair).loadable  # would need two pairs


def test_lighter_bars_shift_every_answer():
    assert plate_breakdown(55, bar=WOMENS_BAR, inventory=FULL).per_side == (20.0,)
    assert plate_breakdown(30, bar=TRAINING_BAR, inventory=FULL).per_side == (10.0,)
    # The EZ bar's own weight is odd, so the loadable grid shifts with it:
    # 7.5 + 2.5k, i.e. 10, 12.5, 15 … and never 21.
    assert not loadable_options(21, bar=EZ_BAR, inventory=FULL).loadable
    assert loadable_options(22.5, bar=EZ_BAR, inventory=FULL).loadable  # 7.5 + 2×7.5


def test_a_bar_can_be_given_as_a_plain_number():
    assert plate_breakdown(60, bar=20).total == 60.0
    assert plate_breakdown(60, bar=Bar("custom", 20)).total == 60.0


def test_bad_input_returns_none_rather_than_raising():
    assert loadable_options("not a weight") is None
    assert loadable_options(None) is None
    assert loadable_options(True) is None  # bool is not a weight
    assert loadable_options(-5) is None
    assert plate_breakdown("nope") is None
    assert round_to_loadable("nope") is None
    assert loadable_options(60, bar=-1) is None


def test_comma_decimals_are_accepted():
    """Spanish keyboards produce "82,5"; the field is free text."""
    assert round_to_loadable("82,5", inventory=FULL) == 82.5


# ── inventory handling ───────────────────────────────────────────────────


def test_inventory_round_trips_through_text():
    text = FULL.to_text()
    assert text == "20x5,15x2,10x2,5x2,2.5x2,1.25x2"
    assert PlateInventory.from_text(text) == FULL


def test_inventory_from_text_falls_back_instead_of_exploding():
    assert PlateInventory.from_text("") == FULL
    assert PlateInventory.from_text("garbage") == FULL
    assert PlateInventory.from_text(None) == FULL
    assert PlateInventory.from_text("garbage", default=TINY) == TINY


def test_inventory_of_drops_junk_rows_and_keeps_the_rest():
    inv = PlateInventory.of({20: 2, "bad": 3, 10: 0, -5: 2, 5: "2"})
    assert inv.sizes() == (20.0, 5.0)


def test_inventory_without_removes_a_size():
    assert 1.25 in FULL.sizes()
    assert 1.25 not in NO_MICRO.sizes()
    assert NO_MICRO.smallest == 2.5


def test_inventory_pair_count_is_capped():
    """A typo in a preference must not turn the solver into a hang."""
    inv = PlateInventory.of({20: 10_000})
    assert inv.as_dict()[20.0] <= 20


# ── warm-up ramps ────────────────────────────────────────────────────────


def test_warmup_weights_are_always_loadable():
    """The invariant the whole feature rests on: no 43.7 kg warm-ups.

    Swept across three racks and four bars, because rounding is exactly where
    a non-loadable weight would sneak back in.
    """
    for inventory in (FULL, NO_MICRO, TINY):
        for bar in BARS:
            for work in [x / 2 for x in range(2 * 5, 2 * 200)]:
                for warmup in warmup_plan(work, bar=bar, inventory=inventory):
                    # Note: `warmup.plates.exact` is about the *percentage*
                    # target (40% of 82.5 is 33, which no bar makes), so the
                    # invariant is checked by re-solving the weight handed back.
                    rebuilt = loadable_options(warmup.weight, bar=bar, inventory=inventory)
                    assert rebuilt.loadable, (bar, inventory, work, warmup.weight)
                    assert warmup.weight == round(bar.weight + 2 * sum(warmup.plates.per_side), 2)


def test_warmup_ramp_ascends_and_stays_under_the_work_weight():
    for work in (42.5, 60, 82.5, 100, 140):
        plan = warmup_plan(work, inventory=FULL)
        weights = [w.weight for w in plan]
        assert weights == sorted(weights)
        assert len(weights) == len(set(weights))  # no set repeated
        assert all(w < work for w in weights)
        assert [w.reps for w in plan] == sorted((w.reps for w in plan), reverse=True)


def test_warmup_for_a_heavy_lift_is_the_full_four_sets():
    plan = warmup_plan(100, bar=DEFAULT_BAR, inventory=FULL)
    assert [(w.weight, w.reps) for w in plan] == [
        (40.0, 8),  # 40%
        (55.0, 5),  # 55%
        (70.0, 3),  # 70%
        (85.0, 2),  # 85%
    ]


def test_warmup_count_follows_the_headroom_not_the_absolute_weight():
    # 80 kg of plate above the bar: the full ramp.
    assert len(warmup_plan(100, bar=DEFAULT_BAR, inventory=FULL)) == 4
    # 22.5 kg of plate: three touches.
    assert len(warmup_plan(42.5, bar=DEFAULT_BAR, inventory=FULL)) == 3
    # An EZ curl at 25 kg is 17.5 kg of headroom — three, not four, even though
    # 25 / 7.5 is a bigger ratio than 100 / 20.
    assert len(warmup_plan(25, bar=EZ_BAR, inventory=FULL)) == 3


def test_warmup_is_empty_when_there_is_nothing_to_ramp():
    assert warmup_plan(20, bar=DEFAULT_BAR, inventory=FULL) == []  # the bar is the work set
    assert warmup_plan(15, bar=DEFAULT_BAR, inventory=FULL) == []  # under the bar
    assert warmup_plan(0) == []
    assert warmup_plan(None) == []
    assert warmup_plan("heavy") == []


def test_warmup_ramps_towards_the_loadable_work_weight():
    """43.7 kg will really be 42.5 kg on the bar, so that is what we ramp to."""
    assert [w.weight for w in warmup_plan(43.7, inventory=FULL)] == [
        w.weight for w in warmup_plan(42.5, inventory=FULL)
    ]


def test_warmup_collapses_duplicates_on_a_coarse_rack():
    """Two percentages that round to the same bar must not become two sets."""
    plan = warmup_plan(30, bar=DEFAULT_BAR, inventory=NO_MICRO)
    weights = [w.weight for w in plan]
    assert weights == sorted(set(weights))
    assert all(w >= DEFAULT_BAR.weight for w in weights)


def test_warmup_on_a_bar_only_start_is_the_bare_bar():
    """25 kg bench: the only sane warm-up is the empty bar."""
    plan = warmup_plan(25, bar=DEFAULT_BAR, inventory=FULL)
    assert [w.weight for w in plan] == [20.0]
    assert plan[0].plates.bar_only


def test_warmup_respects_max_sets():
    assert len(warmup_plan(140, inventory=FULL, max_sets=2)) <= 2
    assert len(warmup_plan(140, inventory=FULL, max_sets=1)) == 1
    # Asking for more than the scheme offers does not invent sets.
    assert len(warmup_plan(140, inventory=FULL, max_sets=99)) <= max(WARMUP_SCHEMES)


def test_warmup_percentages_are_the_documented_scheme():
    """Locks the ramp shape: starts near half, tops out at 85%, reps descend."""
    for count, scheme in WARMUP_SCHEMES.items():
        percents = [p for p, _ in scheme]
        reps = [r for _, r in scheme]
        assert percents == sorted(percents)
        assert reps == sorted(reps, reverse=True)
        assert max(percents) <= 0.85, count  # never a work set in disguise
        assert min(percents) >= 0.40, count  # never so light it does nothing


def test_warmup_labels_read_like_a_gym_cue():
    plan = warmup_plan(100, inventory=FULL)
    assert plan[0].label() == "40 kg × 8"
    assert plan[0].plates.label() == "10"


# ── percentages and rep predictions ──────────────────────────────────────


def test_percentage_table_rounds_to_loadable_weights():
    rows = percentage_table(122, bar=DEFAULT_BAR, inventory=FULL)
    assert [row.percent for row in rows] == list(PLANNING_PERCENTAGES)
    for row in rows:
        assert row.weight == round(122 * row.percent, 2)  # the arithmetic is kept
        assert row.loadable == row.plates.total  # and the loadable version alongside it
        assert loadable_options(row.loadable, inventory=FULL).loadable
    # 60% of 122 is 73.2, which no rack builds; the row still carries both.
    assert rows[0].weight == 73.2 and rows[0].loadable == 72.5
    # A 1RM whose percentages land clean keeps them untouched.
    assert [r.loadable for r in percentage_table(100, inventory=FULL)] == [60.0, 70.0, 80.0, 90.0]


def test_percentage_table_predicts_reps_at_the_weight_actually_loaded():
    """80% of 122 is 97.6, but 97.5 is what goes on the bar — predict for 97.5."""
    row = next(r for r in percentage_table(122, inventory=FULL) if r.percent == 0.80)
    assert row.weight == 97.6
    assert row.loadable == 97.5
    assert row.reps == predicted_reps(122, 97.5)


def test_percentage_table_can_skip_the_rack():
    rows = percentage_table(100, round_to_plates=False)
    assert [row.loadable for row in rows] == [60.0, 70.0, 80.0, 90.0]
    assert all(row.plates is None for row in rows)


def test_percentage_table_accepts_both_spellings_of_a_percentage():
    whole = percentage_table(100, percentages=(80,), round_to_plates=False)
    fraction = percentage_table(100, percentages=(0.8,), round_to_plates=False)
    assert whole[0].weight == fraction[0].weight == 80.0


def test_percentage_table_flags_where_epley_stops_being_trustworthy():
    rows = percentage_table(100, round_to_plates=False)
    at_60 = rows[0]
    at_90 = rows[-1]
    assert at_60.reps > RELIABLE_MAX_REPS and not at_60.reliable
    assert at_90.reps <= RELIABLE_MAX_REPS and at_90.reliable


def test_percentage_table_is_empty_for_a_missing_max():
    assert percentage_table(0) == []
    assert percentage_table(None) == []
    assert percentage_table("strong") == []


def test_predicted_reps_edges_agree_with_estimated_1rm():
    # At the max itself Epley's own short-circuit says one rep, not zero.
    assert predicted_reps(100, 100) == 1
    # Above it, nothing moves.
    assert predicted_reps(100, 110) == 0
    assert predicted_reps(100, 80) == 8  # 30 × (100/80 − 1) = 7.5 → 8
    assert predicted_reps(100, 0) is None
    assert predicted_reps(0, 80) is None
    assert predicted_reps(None, 80) is None


def test_weight_for_reps_is_the_inverse_of_epley():
    assert weight_for_reps(100, 1) == 100.0  # not 96.8 — matches the short-circuit
    assert weight_for_reps(100, 5) == 85.71
    assert weight_for_reps(100, 0) is None
    assert weight_for_reps(0, 5) is None


@pytest.mark.parametrize("reps", list(range(1, 13)))
@pytest.mark.parametrize("one_rm", [60.0, 100.0, 137.5])
def test_rm_helpers_round_trip_through_analytics(one_rm, reps):
    """gym_tools must not become a second Epley. These are its inverses."""
    weight = weight_for_reps(one_rm, reps)
    assert estimated_1rm(weight, reps) == pytest.approx(one_rm, abs=0.05)
    assert predicted_reps(one_rm, weight) == reps


# ── bar suggestions ──────────────────────────────────────────────────────


def test_bar_for_exercise_prefills_the_ez_bar_for_curls():
    assert bar_for_exercise("EZ Curl [4×12]") is EZ_BAR
    assert bar_for_exercise("EZ Bar Curl") is EZ_BAR
    assert bar_for_exercise("Preacher Curl") is EZ_BAR


def test_bar_for_exercise_defaults_to_the_olympic_bar():
    for name in ("Bench Press", "Squat [5×12,10,8,8,8]", "Romanian Deadlift", "Barbell Row"):
        assert bar_for_exercise(name) is DEFAULT_BAR
    assert bar_for_exercise(None) is DEFAULT_BAR
    assert bar_for_exercise("Squat", default=WOMENS_BAR) is WOMENS_BAR
