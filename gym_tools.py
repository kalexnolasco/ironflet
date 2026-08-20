"""Gym-floor maths — plate loading, warm-up ramps and percentage tables.

Pure functions over plain data. Nothing here imports Flet, opens a database or
touches the filesystem, exactly like `analytics.py` and `set_types.py`, so it
unit-tests without a running app and the Telegram coach in ../agente/ can reuse
it verbatim.

Why this module exists: Alex's routine is almost entirely barbell work (Bench,
Military Press, Squat, Barbell Row, Romanian Deadlift, Incline Barbell, EZ
Curl). Three questions come up on every single one of those sets and none of
them had an answer in the app:

1. *What do I hang on the bar for 82.5 kg?* — `loadable_options` /
   `plate_breakdown`.
2. *What do I warm up with?* — `warmup_plan`.
3. *What is 80% of my max, and how many reps should that give me?* —
   `percentage_table` / `predicted_reps`.

Two rules shape every answer:

* **Never fail silently.** A weight that cannot be assembled from the plates in
  the room is not an error, it is a fact about the room. `loadable_options`
  always reports the nearest loadable weight below *and* above, so the caller
  can show "82.5 not possible — 81.25 or 83.75" instead of nothing.
* **Every weight this module hands back is a weight that can actually be
  loaded.** A warm-up set of 43.7 kg is worse than useless: it makes the lifter
  do arithmetic mid-session. Warm-ups and percentage rows are rounded through
  the plate solver before they are returned.

One-rep-max estimation is **not** reimplemented here. `analytics.estimated_1rm`
is the single Epley implementation in this repo; it is imported below and
`predicted_reps` / `weight_for_reps` are written as its exact inverses,
including its `reps == 1` short-circuit (see the note there).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from analytics import estimated_1rm
from exercises import exercise_key

__all__ = [
    "Bar",
    "BARS",
    "DEFAULT_BAR",
    "EZ_BAR",
    "OLYMPIC_BAR",
    "TRAINING_BAR",
    "WOMENS_BAR",
    "bar_for_exercise",
    "PlateInventory",
    "DEFAULT_INVENTORY",
    "NO_MICRO_INVENTORY",
    "MINIMAL_INVENTORY",
    "PlateSolution",
    "LoadOptions",
    "loadable_options",
    "plate_breakdown",
    "round_to_loadable",
    "WarmupSet",
    "WARMUP_SCHEMES",
    "warmup_plan",
    "PercentageRow",
    "PLANNING_PERCENTAGES",
    "RELIABLE_MAX_REPS",
    "percentage_table",
    "predicted_reps",
    "weight_for_reps",
    "estimated_1rm",  # re-exported so callers have one import, not two
]


# ─────────────────────────────────────────────────────────────────────────
# coercion and fixed-point arithmetic
# ─────────────────────────────────────────────────────────────────────────

#: Half a centi-kilo. Everything user-visible is rounded to 0.01 kg, so two
#: weights closer together than this are the same weight.
_EPS = 0.005

#: Internal unit: centi-kilos. 1.25 kg → 125, 2.5 kg → 250.
#:
#: Plate maths in binary floats drifts — 2.5 + 1.25 + 1.25 is not reliably 5.0
#: once it has been through a few sums — and the solver compares totals for
#: equality. Integers make that exact. Kept private: every public value is a
#: plain float in kilograms.
_SCALE = 100


def _cents(value: float) -> int:
    return int(round(value * _SCALE))


def _kg(cents: int) -> float:
    return round(cents / _SCALE, 2)


def _num(value: Any) -> float | None:
    """Best-effort float. None for anything that is not a real number.

    Same rule as `analytics._num` and for the same reason (three writers reach
    this data: the app, the Telegram coach, restored backups), kept local
    rather than importing a private name across modules. `bool` is rejected
    explicitly because it subclasses `int` and a stray True would read as 1 kg.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────
# bars
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Bar:
    """A bar, by name and weight. Frozen so it can be a default argument."""

    name: str
    weight: float

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({_trim(self.weight)} kg)"


#: 20 kg men's Olympic bar — what "the bar" means unless stated otherwise.
OLYMPIC_BAR = Bar("Barra olímpica", 20.0)
#: 15 kg women's Olympic bar. Common as a second bar on a Spanish gym rack.
WOMENS_BAR = Bar("Barra de 15", 15.0)
#: 10 kg technique/training bar.
TRAINING_BAR = Bar("Barra de entreno", 10.0)
#: EZ curl bars are the vague ones: anywhere from 6.5 to 10 kg depending on
#: make, and almost never stamped. 7.5 kg is the middle of that range and the
#: figure most Spanish gym EZ bars weigh; override it once the real one is on a
#: scale, because a 2.5 kg error on a curl is a whole plate pair.
EZ_BAR = Bar("Barra EZ", 7.5)

BARS: tuple[Bar, ...] = (OLYMPIC_BAR, WOMENS_BAR, TRAINING_BAR, EZ_BAR)

DEFAULT_BAR = OLYMPIC_BAR


#: Exercise-key fragments that imply a bar other than the Olympic one. Matched
#: case-insensitively as substrings of `exercises.exercise_key(name)`, so
#: "EZ Curl [4×12]" and "EZ Bar Curl" both land on the EZ bar. This is a
#: *suggestion* for prefilling a picker, never a constraint.
_BAR_HINTS: tuple[tuple[str, Bar], ...] = (
    ("ez", EZ_BAR),
    ("preacher", EZ_BAR),
)


def bar_for_exercise(name: Any, default: Bar = DEFAULT_BAR) -> Bar:
    """The bar this exercise is most likely done with. Falls back to `default`.

    Only used to prefill; the user always gets to change it. Anything that is
    not a barbell movement quietly returns the default, because the plate
    calculator is meaningless there anyway and a wrong guess costs nothing.
    """
    if not isinstance(name, str):
        return default
    # Whole words only. Substring matching would make "ez" fire on any exercise
    # whose name happens to contain those two letters.
    words = set(exercise_key(name).lower().replace("-", " ").split())
    for fragment, bar in _BAR_HINTS:
        if fragment in words:
            return bar
    return default


def _bar_kg(bar: Bar | float | int | str | None) -> float | None:
    """Bar → kilograms. Accepts a `Bar`, a number, or None for the default."""
    if bar is None:
        return DEFAULT_BAR.weight
    if isinstance(bar, Bar):
        return bar.weight
    value = _num(bar)
    if value is None or value < 0:
        return None
    return value


# ─────────────────────────────────────────────────────────────────────────
# plate inventory
# ─────────────────────────────────────────────────────────────────────────

#: Guard rails on user-supplied inventories. The solver enumerates reachable
#: per-side sums, which is cheap for a real rack and unbounded for a typo.
MAX_PAIRS_PER_SIZE = 20
MAX_PLATE_SIZES = 12


@dataclass(frozen=True)
class PlateInventory:
    """What is on the rack, counted in **pairs**.

    Pairs, not plates, because a bar has to be symmetric: one spare 20 kg plate
    with no partner cannot be loaded, so counting it would let the solver
    propose a weight that cannot exist. A rack with five 20s therefore has two
    usable pairs, and `PlateInventory.of({20: 2})` is how you say that.

    Frozen and tuple-backed so it is hashable, which is what lets the reachable
    -sum table be cached (`_reachable`) instead of recomputed on every keystroke.
    """

    pairs: tuple[tuple[float, int], ...]  # (plate kg, pairs available), heaviest first

    @classmethod
    def of(cls, mapping: Mapping[Any, Any] | Iterable[tuple[Any, Any]]) -> PlateInventory:
        """Build from `{plate_kg: pairs}`. Junk entries are dropped, not raised.

        Dropping rather than raising is deliberate: this can be fed from a
        preference string the user typed, and a malformed row should cost that
        plate size, not the whole calculator.
        """
        items = mapping.items() if isinstance(mapping, Mapping) else mapping
        clean: dict[int, int] = {}
        for raw_size, raw_pairs in items:
            size = _num(raw_size)
            count = _num(raw_pairs)
            if size is None or count is None or size <= 0 or count < 1:
                continue
            cents = _cents(size)
            if cents <= 0:
                continue
            capped = min(int(count), MAX_PAIRS_PER_SIZE)
            # A size repeated in the input adds up rather than overwriting;
            # "20x2,20x1" plainly means three pairs of 20.
            clean[cents] = min(clean.get(cents, 0) + capped, MAX_PAIRS_PER_SIZE)
        ordered = sorted(clean.items(), key=lambda kv: -kv[0])[:MAX_PLATE_SIZES]
        return cls(tuple((_kg(c), n) for c, n in ordered))

    def as_dict(self) -> dict[float, int]:
        return dict(self.pairs)

    def sizes(self) -> tuple[float, ...]:
        return tuple(size for size, _ in self.pairs)

    @property
    def smallest(self) -> float | None:
        """Lightest plate available — the finest step is twice this."""
        return self.pairs[-1][0] if self.pairs else None

    def without(self, *sizes: float) -> PlateInventory:
        """Same rack minus these plate sizes. `DEFAULT_INVENTORY.without(1.25)`."""
        drop = {_cents(s) for s in sizes if _num(s) is not None}
        return PlateInventory(tuple((s, n) for s, n in self.pairs if _cents(s) not in drop))

    def to_text(self) -> str:
        """`"20x2,15x1,10x2"` — round-trips through `from_text`.

        There is a serialised form because the inventory belongs in
        `preferencias`, which is a string key-value store (`Storage.get_pref`).
        """
        return ",".join(f"{_trim(size)}x{count}" for size, count in self.pairs)

    @classmethod
    def from_text(cls, text: Any, default: PlateInventory | None = None) -> PlateInventory:
        """Parse `to_text()`. Anything unreadable falls back to `default`.

        Falls back rather than raising for the same reason `of` drops junk: a
        corrupted preference must not take the gym tools down mid-session.
        """
        fallback = DEFAULT_INVENTORY if default is None else default
        if not isinstance(text, str) or not text.strip():
            return fallback
        found: list[tuple[Any, Any]] = []
        for chunk in text.replace(";", ",").split(","):
            if not chunk.strip():
                continue
            size, _, count = chunk.lower().partition("x")
            found.append((size, count if count.strip() else 1))
        parsed = cls.of(found)
        return parsed if parsed.pairs else fallback


#: The plates a Spanish commercial gym actually has on the rack: 20/15/10/5 in
#: rubber bumpers or iron, 2.5 and 1.25 as the small iron discs. Pair counts are
#: deliberately modest — enough for a 240 kg bar, few enough that the "limited
#: inventory" path is exercised by real use and not just by tests.
DEFAULT_INVENTORY = PlateInventory.of({20: 5, 15: 2, 10: 2, 5: 2, 2.5: 2, 1.25: 2})

#: Plenty of gyms stop at 2.5 kg. Without 1.25s the finest jump is 5 kg, which
#: is why the calculator has to be honest about non-loadable weights.
NO_MICRO_INVENTORY = DEFAULT_INVENTORY.without(1.25)

#: A hotel/garage rack. Kept as a named constant because it is the shape that
#: breaks naive greedy plate maths.
MINIMAL_INVENTORY = PlateInventory.of({20: 1, 10: 1, 5: 1, 2.5: 1})


def _trim(value: float) -> str:
    """`20.0 → "20"`, `2.5 → "2.5"`. Kilos read badly with trailing zeros."""
    rounded = round(float(value), 2)
    text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return text or "0"


# ─────────────────────────────────────────────────────────────────────────
# the plate solver
# ─────────────────────────────────────────────────────────────────────────


def _plate_rank(plates: tuple[float, ...]) -> tuple[int, tuple[float, ...]]:
    """Sort key for two plate sets that weigh the same. Lower is better.

    Fewest plates wins (one 20 beats two 10s: fewer discs to fetch and fewer to
    strip). On a tie, the set whose plates run heavier first wins — negating
    turns "heaviest first" into "smallest tuple".
    """
    return (len(plates), tuple(-p for p in plates))


@lru_cache(maxsize=32)
def _reachable(inventory: PlateInventory) -> dict[int, tuple[float, ...]]:
    """Every per-side load this rack can build → the plates that build it.

    Bounded knapsack, not greedy. Greedy (take the heaviest that fits, repeat)
    is the obvious implementation and it is *wrong* once the rack is finite:
    with one 20 and two 15s, a 30 kg side is 15+15, but greedy takes the 20,
    finds nothing that makes the remaining 10, and reports the weight
    impossible. That is precisely the "nearest below/above" lie this module
    exists to avoid, so the whole reachable set is enumerated instead.

    Sizes are processed heaviest-first and appended in order, so every plate
    tuple comes out already sorted heaviest-first — which is also the order you
    load a bar. Candidates are ranked by `_plate_rank`: fewest plates first, and
    on a tie the one that starts heavier, so 31.25 per side is 20+10+1.25 rather
    than the equally-short 15+15+1.25. Both are three plates; only one puts the
    big disc against the collar, which is how a bar is actually loaded.

    Cost is bounded by the *range* of per-side sums divided by the plate
    granularity, not by the combinatorics — a few hundred states for any real
    rack — and the result is cached per inventory.
    """
    best: dict[int, tuple[float, ...]] = {0: ()}
    for size, count in inventory.pairs:  # already heaviest-first
        step = _cents(size)
        if step <= 0 or count <= 0:
            continue
        grown = dict(best)
        for base_sum, base_plates in best.items():
            total = base_sum
            plates = base_plates
            for _ in range(count):
                total += step
                plates = plates + (size,)
                current = grown.get(total)
                if current is None or _plate_rank(plates) < _plate_rank(current):
                    grown[total] = plates
        best = grown
    return best


@dataclass(frozen=True)
class PlateSolution:
    """One loadable weight, and the plates that make it.

    `per_side` is what goes on **one** sleeve, heaviest first — the order you
    actually slide them on, and the only list worth showing on a phone.
    """

    bar: float
    per_side: tuple[float, ...]
    target: float | None = None

    @property
    def plate_weight(self) -> float:
        """Total weight of the plates, both sides."""
        return round(2 * sum(self.per_side), 2)

    @property
    def total(self) -> float:
        """What the loaded bar weighs."""
        return round(self.bar + self.plate_weight, 2)

    @property
    def bar_only(self) -> bool:
        return not self.per_side

    @property
    def exact(self) -> bool:
        """True when this hits the requested weight. False when nothing was requested."""
        return self.target is not None and abs(self.total - self.target) < _EPS

    @property
    def delta(self) -> float:
        """Signed miss, in kg: positive means heavier than asked for."""
        return 0.0 if self.target is None else round(self.total - self.target, 2)

    def label(self) -> str:
        """`"20 + 10 + 2.5"` per side, or `"bar only"`. For a one-line hint."""
        if self.bar_only:
            return "solo barra"
        return " + ".join(_trim(p) for p in self.per_side)

    def describe(self) -> str:
        """`"82.5 kg — 20 bar + 20 + 10 + 1.25 per side"`. For a wider surface."""
        if self.bar_only:
            return f"{_trim(self.total)} kg — barra de {_trim(self.bar)} kg, sin discos"
        return f"{_trim(self.total)} kg — barra de {_trim(self.bar)} kg + {self.label()} por lado"


@dataclass(frozen=True)
class LoadOptions:
    """The complete, honest answer to "can I load X?".

    `exact` is the weight asked for when it can be built. When it cannot,
    `below` and `above` are the closest loadable weights on either side and at
    least one of them is always present — the bare bar is always loadable, so
    there is no such thing as "no answer".
    """

    target: float
    bar: float
    exact: PlateSolution | None
    below: PlateSolution | None
    above: PlateSolution | None

    @property
    def loadable(self) -> bool:
        return self.exact is not None

    @property
    def under_bar(self) -> bool:
        """Asked for less than the empty bar weighs — plates cannot help.

        Worth its own flag: the UI line for this is "the bar alone is 20 kg",
        not "nearest option 20 kg", and a 15 kg target on a 20 kg bar is a
        real thing to type when you mean a dumbbell or a machine.
        """
        return self.target < self.bar - _EPS

    @property
    def nearest(self) -> PlateSolution:
        """Exact if possible, else whichever side is closer; ties go **down**.

        Down on a tie because a rounded-up warm-up eats into the work set and a
        rounded-up work set is a weight that was not programmed. Erring light
        is the recoverable error.
        """
        if self.exact is not None:
            return self.exact
        if self.below is None:
            return self.above  # type: ignore[return-value]
        if self.above is None:
            return self.below
        return self.below if abs(self.below.delta) <= abs(self.above.delta) else self.above

    def summary(self) -> str:
        """One line for the gym: either the plates, or both neighbours."""
        if self.exact is not None:
            return self.exact.describe()
        if self.under_bar and self.above is not None:
            return f"por debajo de la barra — {_trim(self.above.total)} kg es lo más ligero posible"
        parts = []
        if self.below is not None:
            parts.append(f"{_trim(self.below.total)} kg ({self.below.label()})")
        if self.above is not None:
            parts.append(f"{_trim(self.above.total)} kg ({self.above.label()})")
        return f"{_trim(self.target)} kg not loadable — " + " or ".join(parts)


def loadable_options(
    target: Any,
    bar: Bar | float | None = DEFAULT_BAR,
    inventory: PlateInventory | None = None,
) -> LoadOptions | None:
    """Nearest loadable weights around `target`, with their plate breakdowns.

    Returns None only when the *inputs* are unusable (target not a number, a
    negative bar). A target that cannot be assembled is not a failure: it comes
    back as `exact=None` with `below`/`above` filled in.
    """
    want = _num(target)
    bar_kg = _bar_kg(bar)
    if want is None or bar_kg is None or want < 0:
        return None
    inv = inventory if inventory is not None else DEFAULT_INVENTORY

    # Per side, in centi-kilos. Odd half-kilos are handled by the ceil/floor
    # below: 45.1 kg on a 20 kg bar wants 12.55 per side, which no plate makes,
    # so the search simply finds neighbours on both sides.
    wanted_side = (_cents(want) - _cents(bar_kg)) / 2.0
    table = _reachable(inv)

    exact = below = above = None
    best_below = best_above = None
    for side_sum, plates in table.items():
        if abs(side_sum - wanted_side) < 0.5:  # within half a centi-kilo: same weight
            exact = PlateSolution(bar_kg, plates, want)
        elif side_sum < wanted_side:
            if best_below is None or side_sum > best_below:
                best_below, below = side_sum, PlateSolution(bar_kg, plates, want)
        else:
            if best_above is None or side_sum < best_above:
                best_above, above = side_sum, PlateSolution(bar_kg, plates, want)

    return LoadOptions(round(want, 2), bar_kg, exact, below, above)


def plate_breakdown(
    target: Any,
    bar: Bar | float | None = DEFAULT_BAR,
    inventory: PlateInventory | None = None,
) -> PlateSolution | None:
    """The single best answer: exact if loadable, otherwise the nearest.

    Use `loadable_options` when the caller can show both neighbours — which the
    workout screen should. This is the convenience for the places that need one
    number, such as rounding a warm-up.
    """
    options = loadable_options(target, bar, inventory)
    return None if options is None else options.nearest


def round_to_loadable(
    target: Any,
    bar: Bar | float | None = DEFAULT_BAR,
    inventory: PlateInventory | None = None,
) -> float | None:
    """`target` snapped to a weight this rack can build. None on bad input."""
    solution = plate_breakdown(target, bar, inventory)
    return None if solution is None else solution.total


# ─────────────────────────────────────────────────────────────────────────
# warm-up ramps
# ─────────────────────────────────────────────────────────────────────────

#: Percentages of the **working weight** (not of the 1RM) with their reps.
#:
#: Why these numbers. The three schemes in wide use agree far more than they
#: differ:
#:
#: * Wendler's 5/3/1 ramps 40% × 5, 50% × 5, 60% × 3 of the training max — which,
#:   since a training max is ~90% of the true max and the first work set is
#:   65-75%, lands within a few points of these ratios *relative to the work
#:   weight*.
#: * Rippetoe's Starting Strength prescribes the empty bar, then roughly even
#:   jumps to the work set with the reps coming down each time (5/5/3/2).
#: * The Stronger by Science / Nuckols warm-up is the terse version of the same
#:   idea: ~50% × 5, ~70% × 3, ~85% × 1-2.
#:
#: The shared shape, and the one implemented here: **start near half, finish
#: near 85%, drop the reps as the load climbs.** 85% is the ceiling because it
#: is close enough to groove the exact bar path and brace under near-work load,
#: while still being far enough away to cost nothing; going to 90-95% turns the
#: last warm-up into a work set. Reps fall so total warm-up tonnage stays small:
#: the point is to raise tissue temperature and rehearse the pattern, not to
#: spend the session's work capacity before the first real set.
WARMUP_SCHEMES: dict[int, tuple[tuple[float, int], ...]] = {
    1: ((0.55, 5),),
    2: ((0.50, 8), (0.75, 4)),
    3: ((0.45, 8), (0.65, 5), (0.85, 3)),
    4: ((0.40, 8), (0.55, 5), (0.70, 3), (0.85, 2)),
}

MAX_WARMUP_SETS = max(WARMUP_SCHEMES)


@dataclass(frozen=True)
class WarmupSet:
    """One warm-up: a loadable weight, its plates, and how many reps."""

    percent: float  # of the working weight, 0..1
    reps: int
    plates: PlateSolution

    @property
    def weight(self) -> float:
        """The weight to load. Always loadable — that is the whole point."""
        return self.plates.total

    def label(self) -> str:
        return f"{_trim(self.weight)} kg × {self.reps}"


def _warmup_set_count(work: float, bar: float) -> int:
    """How many ramp sets a given jump deserves.

    Measured on *headroom* — how much plate sits between the bar and the work
    weight — rather than on the work weight itself, because that is the actual
    distance to be covered. A 25 kg EZ curl on a 7.5 kg bar has 17.5 kg of
    headroom and does not want four warm-ups; a 100 kg squat has 80 kg and does.

    Thresholds: under 10 kg of plate there is barely a ramp to build, so two
    touches are enough; up to 40 kg three keeps the jumps under ~15 kg; beyond
    that four, which is where every published scheme also tops out.
    """
    headroom = work - bar
    if headroom < 10:
        return 2
    if headroom < 40:
        return 3
    return 4


def warmup_plan(
    work_weight: Any,
    bar: Bar | float | None = DEFAULT_BAR,
    inventory: PlateInventory | None = None,
    max_sets: int | None = None,
) -> list[WarmupSet]:
    """2-4 ramp sets up to `work_weight`, every one of them loadable.

    Empty list — not an error — when there is nothing to ramp: a work weight at
    or below the bare bar *is* the warm-up, and when the input is unusable.

    Three filters run after the percentages are applied, and all three exist
    because the naive version produced sets nobody would do:

    * the ramp aims at the *loadable* work weight, so a 43.7 kg entry warms up
      towards the 42.5 kg that will really be on the bar;
    * any set that rounds to the work weight or above is dropped — a warm-up
      heavier than the work set is not a warm-up;
    * duplicates are collapsed. On a rack with no micro plates several
      percentages can round to the same bar, and doing 40 kg twice is a waste;
      the earlier (higher-rep) set survives.
    """
    work_raw = _num(work_weight)
    bar_kg = _bar_kg(bar)
    if work_raw is None or bar_kg is None or work_raw <= 0:
        return []
    inv = inventory if inventory is not None else DEFAULT_INVENTORY

    top_solution = plate_breakdown(work_raw, bar_kg, inv)
    top = top_solution.total if top_solution is not None else work_raw
    if top <= bar_kg + _EPS:
        return []  # the bar alone is the work set; there is nothing below it

    count = _warmup_set_count(top, bar_kg)
    if max_sets is not None:
        limit = _num(max_sets)
        if limit is not None:
            count = max(1, min(count, min(int(limit), MAX_WARMUP_SETS)))

    plan: list[WarmupSet] = []
    seen: set[int] = set()
    for percent, reps in WARMUP_SCHEMES[count]:
        options = loadable_options(top * percent, bar_kg, inv)
        if options is None:
            continue
        # Prefer exact, then the lighter neighbour: a warm-up should never be
        # rounded up towards the work set. `above` only gets used when the
        # target sits under the bar, where the bare bar is the only option.
        choice = options.exact or options.below or options.above
        if choice is None or choice.total >= top - _EPS:
            continue
        key = _cents(choice.total)
        if key in seen:
            continue
        seen.add(key)
        plan.append(WarmupSet(percent, reps, choice))
    return plan


# ─────────────────────────────────────────────────────────────────────────
# percentages and rep predictions
# ─────────────────────────────────────────────────────────────────────────

#: The four percentages a training block is written in. 60/70/80/90 covers the
#: usable planning range: below 60% the load stops driving strength, above 90%
#: the reps are singles and the percentage stops being the useful handle.
PLANNING_PERCENTAGES: tuple[float, ...] = (0.60, 0.70, 0.80, 0.90)

#: Epley is fitted to low reps and drifts optimistic past roughly a dozen — the
#: same caveat `analytics.estimated_1rm` carries. Predictions above this are
#: still returned; the UI should mark them as approximate rather than hide them.
RELIABLE_MAX_REPS = 12


def predicted_reps(one_rm: Any, weight: Any) -> int | None:
    """How many reps `weight` should give, from a known 1RM. Inverse of Epley.

    Epley is `1rm = w × (1 + r/30)`, so `r = 30 × (1rm/w − 1)`. Two edges are
    special-cased to stay consistent with `analytics.estimated_1rm`:

    * **at the 1RM itself the answer is 1, not 0.** The formula gives 0 there,
      but `estimated_1rm` short-circuits `reps == 1` to the weight itself
      precisely so a genuine single is not inflated. Both halves have to agree
      or a single would round-trip to zero reps.
    * **above the 1RM the answer is 0** — that is a weight that does not move,
      and reporting 1 would claim a lift that is not there.

    Returns None for unusable input, never a negative.
    """
    rm, w = _num(one_rm), _num(weight)
    if rm is None or w is None or rm <= 0 or w <= 0:
        return None
    if w > rm + _EPS:
        return 0
    if abs(w - rm) < _EPS:
        return 1
    return max(1, int(round(30.0 * (rm / w - 1.0))))


def weight_for_reps(one_rm: Any, reps: Any) -> float | None:
    """The load that should allow exactly `reps`. Inverse of Epley, other way.

    `w = 1rm / (1 + r/30)`, with the same `reps == 1` short-circuit as
    `analytics.estimated_1rm`: one rep is the 1RM, not 96.8% of it. Without that
    the two functions would disagree by 3.3% on the one value they must share.

    Raw kilograms — round it through `plate_breakdown` before showing it as
    something to load.
    """
    rm, r = _num(one_rm), _num(reps)
    if rm is None or r is None or rm <= 0 or r < 1:
        return None
    if r == 1:
        return round(rm, 2)
    return round(rm / (1.0 + r / 30.0), 2)


@dataclass(frozen=True)
class PercentageRow:
    """One line of the percentage table: what to load and what to expect."""

    percent: float  # 0..1
    weight: float  # raw percentage of the 1RM, unrounded
    plates: PlateSolution | None  # None when no bar/rack was supplied
    reps: int | None  # predicted reps at the weight actually loaded

    @property
    def loadable(self) -> float:
        """The weight to put on the bar — rounded when a rack is known."""
        return self.weight if self.plates is None else self.plates.total

    @property
    def reliable(self) -> bool:
        """False once Epley is extrapolating (see `RELIABLE_MAX_REPS`)."""
        return self.reps is not None and 1 <= self.reps <= RELIABLE_MAX_REPS

    def label(self) -> str:
        reps = "—" if self.reps is None else f"~{self.reps}"
        return f"{round(self.percent * 100)}% · {_trim(self.loadable)} kg · {reps} reps"


def percentage_table(
    one_rm: Any,
    percentages: Sequence[float] = PLANNING_PERCENTAGES,
    bar: Bar | float | None = DEFAULT_BAR,
    inventory: PlateInventory | None = None,
    round_to_plates: bool = True,
) -> list[PercentageRow]:
    """The 60/70/80/90% table for a 1RM, as weights that can be loaded.

    Rep predictions are made against the **loaded** weight, not the arithmetic
    percentage: if 80% of 122 kg is 97.6 kg and the bar can only make 97.5, the
    prediction that matters is the one for 97.5.

    Pass `round_to_plates=False` for the pure arithmetic (planning a block on a
    PC, where the rack is not the question). Returns an empty list for a
    non-positive or unreadable 1RM.
    """
    rm = _num(one_rm)
    if rm is None or rm <= 0:
        return []
    rows: list[PercentageRow] = []
    for raw in percentages:
        percent = _num(raw)
        if percent is None or percent <= 0:
            continue
        # Tolerate 80 as well as 0.80: both spellings turn up in prescriptions
        # and silently computing 80× the 1RM would be an absurd answer.
        if percent > 1.0:
            percent = percent / 100.0
        weight = round(rm * percent, 2)
        solution = plate_breakdown(weight, bar, inventory) if round_to_plates else None
        loaded = weight if solution is None else solution.total
        rows.append(PercentageRow(round(percent, 4), weight, solution, predicted_reps(rm, loaded)))
    return rows
