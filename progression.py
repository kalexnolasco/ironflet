"""Double progression: what to load today, and why.

Alex's progression rule was already written down — in prose, inside `data.py`.
This module is that prose turned into code, and nothing more:

* RECOMP phase 2 — *"Double progression: hit the top of the rep range on every
  set, then add 2.5 kg upper / 5 kg lower."*
* RECOMP phase 1 — *"Find a load that leaves 2-3 reps in reserve. Week 1 sets
  the baseline, not PRs."*
* Upper/Lower phase 1 — *"Same loads. RIR 2-3. Add weight when top reps are
  easy."*
* PPL phase 1 — *"RIR 2-3 until last set."*

Those four sentences are the whole algorithm. The prescribed scheme lives in the
exercise string (`"Barbell Bench Press [4×5-8]"` is 4 sets of 5 to 8 reps), the
intensity target lives in `Phase.notes`, and the history lives in `entrenos`.
Put together they answer the only question that matters at the rack: *what do I
put on the bar, and how many reps do I chase?*

## Shape of this module

Pure functions. No Flet, no database, no import-time work. History arrives as a
list of entries (`storage.WorkoutEntry` or plain dicts — both are read
duck-typed, exactly as `analytics.py` does) so every rule here unit-tests
without PostgreSQL. `recommend_from_store()` is the only thing that touches a
`Storage`, and it is four lines.

## What it deliberately does NOT do

* It does not invent a starting weight. With no history the honest answer is
  "no recommendation, go find your baseline" — see `Action.BASELINE`. A made-up
  number on a bench press is how people get pinned.
* It does not compute plate maths. The split with `gym_tools.py` is: this
  module decides *what weight to aim for*, `gym_tools` decides *what can be
  built*. Barbell targets go out through `gym_tools.round_to_loadable` with the
  bar `gym_tools.bar_for_exercise` picks; dumbbells, stacks and cables round
  onto their own fixed step, because there are no plates to solve for there.
  The import is soft, so a missing `gym_tools` degrades to the step grid rather
  than breaking the workout screen. See `loadable_weight`.
* It does not decide *rest*. `set_types.rest_seconds` already does.
* It does not decide *warm-ups*. `gym_tools.warmup_plan` does, and it wants a
  work weight — which is what `Recommendation.weight` is.

## The staleness rule (the fourth honesty requirement)

Double progression assumes the last session is recent. It is not a statement
about your body, it is a statement about *the last time you tried*. So:

* under `STALE_AFTER_DAYS` (21) — normal rules;
* 21 to `RESET_AFTER_DAYS` (56) days — the jump is suppressed. You repeat the
  last load. Adding weight on top of three weeks off is how a rule that is
  right on paper gets you a failed first set;
* over 56 days — re-entry at `RE_ENTRY_FACTOR` (90 %) of the last load, with
  `Confidence.LOW`. Two months is enough to lose real strength, and the cheapest
  way back to it is one easy session, not one failed one.

Every one of those numbers is a judgement call, which is why the recommendation
carries a `reason` string and a `confidence` — the UI is expected to show them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

# These three coercion helpers are private in analytics.py but they encode the
# project's single policy for reading rows written by three different programs
# (this app, the Telegram coach, restored backups). Re-implementing them here
# would mean two float-coercion policies that must agree forever — precisely the
# duplication CLAUDE.md keeps warning about. Import, do not copy.
from analytics import _as_date, _field, _num
from analytics import working_sets as _working_sets
from exercises import exercise_key

# Same reason: `set_types._normalize` is the normalisation `is_compound` matches
# against, and equipment detection has to see names the same way it does.
from set_types import _normalize

# ─────────────────────────────────────────────────────────────────────────
# tunables — every one of these is a judgement call, stated once and here
# ─────────────────────────────────────────────────────────────────────────

#: Past this gap the "add weight" branch is suppressed. Three weeks is the
#: brief's own number and roughly where detraining starts to show on a heavy
#: compound. Below it, a missed week is just a missed week.
STALE_AFTER_DAYS = 21

#: Past this gap the last load is treated as aspirational, not current.
RESET_AFTER_DAYS = 56

#: Re-entry load after a long lay-off, and the back-off load after two failed
#: sessions at the same weight. 10 % is one working set's worth of fatigue, not
#: a reset to zero — the point is to finish the session, not to start over.
RE_ENTRY_FACTOR = 0.9
BACK_OFF_FACTOR = 0.9

#: How many sessions back `recommend` reads. Only the last two ever decide
#: anything (a failed session becomes a back-off when the one before it failed
#: at the same load); the rest is context for the caller.
DEFAULT_HISTORY_LIMIT = 12


# ─────────────────────────────────────────────────────────────────────────
# the prescribed scheme, read off the exercise string
# ─────────────────────────────────────────────────────────────────────────


class SchemeKind(str, Enum):
    """What kind of rep prescription this is.

    The five that actually occur in data.py, plus UNKNOWN. `str` base so a
    kind can be dropped straight into a format string or a JSON blob.
    """

    RANGE = "range"  # [4×5-8]      — the double-progression case
    FIXED = "fixed"  # [3×12]       — a range whose ends coincide
    PYRAMID = "pyramid"  # [5×12,10,8,8,8] — one target per set
    AMRAP = "amrap"  # [4×max]      — no ceiling, so no jump can be earned
    CLUSTER = "cluster"  # [2×10+10+10] — drop set / bi-set / triset
    UNKNOWN = "unknown"


#: Words that mean "as many as you can" in data.py.
_AMRAP_WORDS = frozenset({"max", "amrap", "failure"})

#: The drop-set arrow data.py appends to a segment: `6+12↓`.
_DROP_MARK = "↓"

# Bracket handling mirrors routine_builder.parse_exercise, which is the other
# reader of these strings. tests/test_progression.py::test_scheme_agrees_with_
# routine_builder walks every exercise in data.py and asserts the two parsers
# return the same sets/reps, so a drift here fails a test instead of quietly
# prescribing something else than the editor shows.
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_BRACKET_SCHEME_RE = re.compile(r"^\s*(\d{1,2})\s*[×x]\s*(\S.{0,39})\s*$")
_PHASE_SCHEME_RE = re.compile(
    r"(\d{1,2})\s*[×x]\s*([0-9]{1,3}(?:\s*-\s*[0-9]{1,3})?(?:\s*,\s*[0-9]{1,3})*)"
)
_STAR_SCHEME_RE = re.compile(r"\*\s*=\s*(\d{1,2})\s*[×x]\s*([0-9]{1,3}(?:\s*-\s*[0-9]{1,3})?)")


@dataclass(frozen=True)
class Scheme:
    """`"Barbell Bench Press [4×5-8]"` → 4 sets, 5 to 8 reps.

    `source` records where it came from: the exercise's own bracket, the
    phase's `scheme` string, the phase's `(*=3×8)` alternate for a starred
    exercise, or nothing at all.
    """

    sets: int | None = None
    kind: SchemeKind = SchemeKind.UNKNOWN
    reps_low: int | None = None
    reps_high: int | None = None
    per_set: tuple[int, ...] = ()  # explicit per-set targets (pyramids only)
    segments: tuple[str, ...] = ()  # cluster segments, as written
    has_drop: bool = False
    raw: str = ""  # the reps side exactly as data.py spells it
    source: str = "none"  # "bracket" | "phase" | "phase-star" | "none"

    def is_known(self) -> bool:
        return self.kind is not SchemeKind.UNKNOWN

    def reps_label(self) -> str:
        """The reps half of the on-row target: `"5-8 reps"`, `"max reps"`."""
        if self.kind is SchemeKind.RANGE:
            return f"{self.reps_low}-{self.reps_high} reps"
        if self.kind is SchemeKind.FIXED:
            return f"{self.reps_low} reps"
        if self.kind is SchemeKind.PYRAMID:
            return ",".join(str(v) for v in self.per_set) + " reps"
        if self.kind is SchemeKind.AMRAP:
            return "reps máx"
        if self.kind is SchemeKind.CLUSTER:
            return "+".join(self.segments) + " reps"
        return ""

    def label(self) -> str:
        """Full prescription including the set count: `"4×5-8 reps"`."""
        reps = self.reps_label()
        if not reps:
            return ""
        return f"{self.sets}×{reps}" if self.sets else reps


def _parse_reps_text(raw: str) -> dict:
    """Classify the reps side of a scheme. Order of the tests is load-bearing.

    Commas are checked before `+`, because `[4×10,10,8,6+12↓]` is a *pyramid*
    whose last set carries a drop, not a cluster. Read the other way round it
    would come out as an unreadable four-segment blob.
    """
    text = re.sub(r"\s+", "", raw or "")
    if not text:
        return {"kind": SchemeKind.UNKNOWN, "raw": raw or ""}

    # "(20+20+20)" and "20+20+20" are the same prescription; data.py writes both.
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1]

    has_drop = _DROP_MARK in text
    out: dict[str, Any] = {"raw": text, "has_drop": has_drop}

    if "," in text:
        targets: list[int] = []
        for item in (i for i in text.split(",") if i):
            # "6+12↓" — the prescribed working set is 6; the 12 is the drop
            # tail, done at a lighter load and not the target being progressed.
            head = item.split("+", 1)[0].replace(_DROP_MARK, "")
            if not head.isdigit():
                return {**out, "kind": SchemeKind.UNKNOWN}
            targets.append(int(head))
        if not targets:
            return {**out, "kind": SchemeKind.UNKNOWN}
        return {
            **out,
            "kind": SchemeKind.PYRAMID,
            "per_set": tuple(targets),
            "reps_low": min(targets),
            "reps_high": max(targets),
        }

    if "+" in text:
        return {**out, "kind": SchemeKind.CLUSTER, "segments": tuple(text.split("+"))}

    if text.lower() in _AMRAP_WORDS:
        return {**out, "kind": SchemeKind.AMRAP}

    m = re.fullmatch(r"(\d{1,3})-(\d{1,3})", text)
    if m:
        low, high = int(m.group(1)), int(m.group(2))
        if low > high:  # "10-8" written backwards; take it as written, sorted
            low, high = high, low
        return {**out, "kind": SchemeKind.RANGE, "reps_low": low, "reps_high": high}

    m = re.fullmatch(rf"(\d{{1,3}}){re.escape(_DROP_MARK)}?", text)
    if m:
        n = int(m.group(1))
        return {**out, "kind": SchemeKind.FIXED, "reps_low": n, "reps_high": n}

    return {**out, "kind": SchemeKind.UNKNOWN}


def parse_scheme(exercise: str, phase_scheme: str = "") -> Scheme:
    """Prescribed sets and reps for one exercise string.

    Three sources, in the order data.py means them:

    1. a bracket that reads `N×<anything>` — `[4×5-8]`, `[5×12,10,8,8,8]`,
       `[4×max]`. Tag brackets (`[comp]`, `[triple drop]`) carry no `N×` and
       are skipped without special-casing;
    2. for a starred exercise with no bracket, the phase's `(*=3×8)` alternate
       — that is exactly what the asterisk means;
    3. otherwise the phase's own scheme (`"3×12"`, `"4×6-10"`).

    Returns a Scheme with `kind == UNKNOWN` and `source == "none"` when nothing
    readable is found. That is a real answer: the caller must not pretend to
    know a rep target it was never given.
    """
    raw = exercise or ""
    head = raw.split("[", 1)[0]  # the `*` marks the name, never inside a bracket
    starred = "*" in head

    for bracket in _BRACKET_RE.findall(raw):
        m = _BRACKET_SCHEME_RE.match(bracket)
        if m:
            parsed = _parse_reps_text(m.group(2))
            return Scheme(sets=int(m.group(1)), source="bracket", **parsed)

    if starred:
        alt = _STAR_SCHEME_RE.search(phase_scheme or "")
        if alt:
            parsed = _parse_reps_text(alt.group(2))
            return Scheme(sets=int(alt.group(1)), source="phase-star", **parsed)

    # A phase scheme can name two prescriptions ("4×5-8 / 3×8-12" = compounds /
    # isolation). The first is taken. That is only reachable for routines whose
    # exercises carry no brackets, and none of those have a two-sided scheme.
    m = _PHASE_SCHEME_RE.search(phase_scheme or "")
    if m:
        parsed = _parse_reps_text(m.group(2))
        return Scheme(sets=int(m.group(1)), source="phase", **parsed)

    # Nothing readable anywhere. `raw` stays empty on purpose: there is no
    # prescription to quote back, and quoting the exercise name instead would
    # read like the name was the problem.
    return Scheme()


# ─────────────────────────────────────────────────────────────────────────
# the intensity target, read off the phase prose
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RirTarget:
    """Reps in reserve, as the phase states it.

    `low`/`high` are reps left in the tank; `0` is failure. `open_ended` marks
    "no failure" phrasing, which pins a floor and no ceiling ("RIR 1+").
    `last_set` holds a separate target for the final set, because half the
    phases in data.py prescribe exactly that ("Failure on last set").
    """

    low: int | None = None
    high: int | None = None
    open_ended: bool = False
    last_set: tuple[int, int] | None = None
    source: str = ""  # the phrase it was read from, for the "why"
    inherited_from: str = ""  # phase name, when carried over from an earlier phase

    def label(self) -> str:
        """`"RIR 2-3"`, `"RIR 1+"`, `"to failure"`, or `""` when unknown."""
        if self.low is None:
            if self.last_set is not None:
                return "última al fallo" if self.last_set == (0, 0) else ""
            return ""
        if self.low == 0 and (self.high in (0, None)):
            return "al fallo"
        if self.open_ended:
            return f"RIR {self.low}+"
        if self.high is None or self.high == self.low:
            return f"RIR {self.low}"
        return f"RIR {self.low}-{self.high}"

    def full_label(self) -> str:
        """`label()` plus the last-set clause when the phase adds one."""
        base = self.label()
        if self.last_set is not None and self.low is not None:
            tail = "última al fallo" if self.last_set == (0, 0) else f"RIR {self.last_set[0]}"
            return f"{base} · {tail}" if base else tail
        return base


# "RIR 2-3", "RIR 2"
# Bilingües a propósito, como `_DELOAD_MARKS`: las notas de las fases de serie
# están en español desde que la interfaz entera lo está, las de una rutina
# vieja del usuario pueden seguir en inglés, y este parser es la única pieza
# que las lee. Perder el idioma equivocado aquí no lanza nada — simplemente
# desaparece el objetivo de RIR de cada fila de la sesión.
_RIR_RE = re.compile(r"\brir\s*(\d)(?:\s*-\s*(\d))?", re.IGNORECASE)
# "leaves 2-3 reps in reserve" / "deja 2-3 repeticiones en reserva"
_RESERVE_RE = re.compile(
    r"(\d)(?:\s*-\s*(\d))?\s*(?:reps?\s+in\s+reserve|rep(?:eticione)?s?\s+en\s+reserva)",
    re.IGNORECASE,
)
# "No absolute failure", "not to failure" / "sin fallo", "sin llegar al fallo"
_NO_FAILURE_RE = re.compile(
    r"(\bno(?:t)?\s+(?:\w+\s+){0,2}failure|\bsin\s+(?:\w+\s+){0,2}fallo)", re.IGNORECASE
)
_LAST_SET_FAILURE_RE = re.compile(
    r"(last set[^.]{0,40}failure|failure[^.]{0,40}last set"
    r"|últim[oa]s? serie[^.]{0,40}fallo|fallo[^.]{0,40}últim[oa]s? serie)",
    re.IGNORECASE,
)
_ALL_SETS_FAILURE_RE = re.compile(
    r"(failure[^.]{0,40}(all|every) sets?|(all|every) sets?[^.]{0,40}failure"
    r"|fallo[^.]{0,40}todas? las series|todas? las series[^.]{0,40}fallo)",
    re.IGNORECASE,
)


def parse_rir(*texts: str | None) -> RirTarget | None:
    """Read an intensity target out of phase prose. None when it says nothing.

    The rules, applied in this order to the concatenated text:

    1. an explicit `RIR n[-m]` or `n[-m] reps in reserve` wins outright;
    2. "no failure" phrasing pins a floor of 1 and no ceiling ("RIR 1+");
    3. "failure" next to "last set" sets `last_set` only — the working sets
       keep no stated target, which is the truth;
    4. "failure" next to "all/every set" makes failure the general target;
    5. anything else → None.

    Rule 5 is why CambiaTuFísico phase 3 ("*= 3×8 to failure") returns None:
    the sentence is about the starred exercises, and reading it as a
    routine-wide instruction would print a wrong target on every other row.
    A caveat in the other direction: phase 5's "Failure on all sets except
    first" collapses to plain failure — the exception is lost.
    """
    blob = " ".join(t for t in texts if t)
    if not blob.strip():
        return None

    m = _RIR_RE.search(blob) or _RESERVE_RE.search(blob)
    last_set = (0, 0) if _LAST_SET_FAILURE_RE.search(blob) else None

    if m:
        low = int(m.group(1))
        high = int(m.group(2)) if m.group(2) else None
        return RirTarget(low=low, high=high, last_set=last_set, source=m.group(0).strip())

    if _NO_FAILURE_RE.search(blob):
        # "No absolute failure" is a floor, not a number: leave at least one.
        found = _NO_FAILURE_RE.search(blob)
        return RirTarget(low=1, open_ended=True, last_set=last_set, source=found.group(0).strip())

    if last_set is not None:
        found = _LAST_SET_FAILURE_RE.search(blob)
        return RirTarget(last_set=last_set, source=found.group(0).strip())

    found = _ALL_SETS_FAILURE_RE.search(blob)
    if found:
        return RirTarget(low=0, high=0, source=found.group(0).strip())

    return None


#: Words a phase uses to say "this is a recovery week". Matched against the
#: name and the notes, because the two routines say it in different places:
#: RECOMP names the phase "Deload", CambiaTuFísico names one "Deload" too but
#: also writes "Low intensity, no failure" in the notes.
_DELOAD_MARKS = ("deload", "de-load", "recovery week", "descarga")


def is_deload(phase: Any) -> bool:
    """True when the active phase is a recovery week, so loads must not rise.

    Duck-typed like everything else here, and deliberately text-based: neither
    routine carries a boolean for it. A phase that never says any of these
    words is treated as a normal training phase, which is the safe default —
    the cost of missing a deload is one unwanted 2.5 kg, while wrongly calling
    a training phase a deload would freeze progression for weeks.
    """
    if phase is None:
        return False
    texto = " ".join(
        str(getattr(phase, campo, "") or "") for campo in ("name", "notes", "subtitle", "focus")
    ).lower()
    return any(marca in texto for marca in _DELOAD_MARKS)


def rir_for_phase(phase: Any, routine: Any = None) -> RirTarget | None:
    """`parse_rir` over a `data.Phase`, with carry-over from earlier phases.

    Duck-typed, so data.py stays unimported here.

    The carry-over is not cleverness, it is how the plan is written: RECOMP
    phase 2 states the progression rule and says nothing about RIR, phase 3
    says "Same loads". The intensity target from the last phase that stated one
    is the one still in force, and the result records `inherited_from` so the UI
    can say so rather than implying the phase spelled it out.
    """
    if phase is None:
        return None

    direct = parse_rir(
        getattr(phase, "notes", None),
        getattr(phase, "subtitle", None),
    )
    if direct is not None:
        return direct

    phases = list(getattr(routine, "phases", None) or [])
    try:
        idx = phases.index(phase)
    except ValueError:
        idx = -1
    for earlier in reversed(phases[:idx]):
        found = parse_rir(getattr(earlier, "notes", None), getattr(earlier, "subtitle", None))
        if found is not None:
            return RirTarget(
                low=found.low,
                high=found.high,
                open_ended=found.open_ended,
                last_set=found.last_set,
                source=found.source,
                inherited_from=str(getattr(earlier, "name", "") or ""),
            )
    return None


def prescribed_target(exercise: str, phase: Any = None, routine: Any = None) -> str:
    """The on-row target string: `"5-8 reps @ RIR 2-3"`.

    This is requirement 3 of the brief: the set count is in the exercise title,
    the rep range is in the same title, and the RIR is buried in the phase
    description — so mid-set, the one moment it matters, none of it is on
    screen. Everything the row needs, in one short string.

    Degrades honestly. No readable RIR → `"5-8 reps"`. No readable scheme
    either → `""`, and the row should print nothing rather than a guess.
    """
    scheme = parse_scheme(exercise, getattr(phase, "scheme", "") or "")
    reps = scheme.reps_label()
    rir = rir_for_phase(phase, routine)
    rir_text = rir.full_label() if rir else ""
    if reps and rir_text:
        return f"{reps} @ {rir_text}"
    return reps or rir_text


# ─────────────────────────────────────────────────────────────────────────
# the increment: what "add weight" means for this exercise
# ─────────────────────────────────────────────────────────────────────────


class Equipment(str, Enum):
    BARBELL = "barbell"
    DUMBBELL = "dumbbell"
    MACHINE = "machine"
    CABLE = "cable"
    BODYWEIGHT = "bodyweight"
    UNKNOWN = "unknown"


# Substring groups, all tokens required, matched against `set_types._normalize`
# output (lower case, no brackets, hyphens flattened). The first family that
# matches wins, and the ORDER IS THE RULE:
#
# 1. bodyweight first — "Parallel Bar Dips" contains "bar" and is not a barbell
#    lift, and no other family should ever claim a dip or a pull-up;
# 2. then the families whose name is spelled out in the exercise (cable,
#    machine, dumbbell). Machine before dumbbell, or "Machine Lateral Raises"
#    is classified off the movement instead of off the equipment holding it;
# 3. barbell last, because its tokens are the loosest ("bar", "squat") and it
#    is also the sanest thing to fall into.
#
# Composite names (bi-sets, supersets) resolve to whichever half matches first.
# That is arbitrary and known: nothing progresses them anyway, `_repeat_only`
# refuses to move a cluster's weight on its own.
_EQUIPMENT_PATTERNS: tuple[tuple[Equipment, tuple[tuple[str, ...], ...]], ...] = (
    (
        Equipment.BODYWEIGHT,
        (
            ("pull up",),
            ("pullup",),
            ("chin up",),
            ("push up",),
            ("pushup",),
            ("dip",),
            ("hanging",),
            ("plank",),
            ("leg raise",),
            ("abs",),
        ),
    ),
    (
        Equipment.CABLE,
        (
            ("cable",),
            ("pushdown",),
            ("pulldown",),
            ("rope",),
            ("crossover",),
            ("face pull",),
        ),
    ),
    (
        Equipment.MACHINE,
        (
            ("machine",),
            ("leg press",),
            ("leg extension",),
            ("leg curl",),
            ("pec deck",),
            ("calf",),  # calf raises and calf presses are stack work here
            ("smith",),
            ("hack",),
        ),
    ),
    (
        Equipment.DUMBBELL,
        (
            ("db",),
            ("dumbbell",),
            ("arnold",),
            ("hammer curl",),
            ("lateral raise",),  # dumbbells unless a cable or machine said otherwise
            ("rear delt",),
            ("kickback",),
        ),
    ),
    (
        Equipment.BARBELL,
        (
            ("barbell",),
            ("ez",),
            ("bar",),  # "T-Bar Row", "Straight Bar Curl"
            ("squat",),
            ("deadlift",),
            ("romanian",),
            ("bench press",),
            ("military",),
            ("hip thrust",),
            ("lunge",),
            ("skull crusher",),
            ("upright row",),
            ("good morning",),
        ),
    ),
)

#: Lower-body movements, for the plan's own "2.5 kg upper / 5 kg lower" split.
#:
#: A keyword list rather than `analytics.resolve_muscles`, on purpose: the
#: details table has real holes (Bulgarian Split Squat maps to nothing at all,
#: by design — see CLAUDE.md), and a silent miss there would hand a squat the
#: upper-body increment. A wrong increment is a wrong bar; a keyword list is
#: at least visible and testable.
_LOWER_BODY_TOKENS: tuple[tuple[str, ...], ...] = (
    ("squat",),
    ("deadlift",),
    ("romanian",),
    ("leg press",),
    ("leg extension",),
    ("leg curl",),
    ("lunge",),
    ("hip thrust",),
    ("calf",),
    ("glute",),
    ("good morning",),
    ("split squat",),
    ("step up",),
)

#: Default step per equipment family, in kg. The two compound numbers are the
#: plan's own words; the rest are what the equipment physically allows.
_DEFAULT_STEP: dict[Equipment, float] = {
    Equipment.BARBELL: 2.5,  # a pair of 1.25 kg plates, the smallest real pair
    Equipment.DUMBBELL: 2.5,  # one step on the rack, per hand
    Equipment.MACHINE: 5.0,  # one plate on a stack
    Equipment.CABLE: 2.5,  # small stacks step in 2.5, and pushdowns are light
    Equipment.BODYWEIGHT: 2.5,  # a plate on a dipping belt
    Equipment.UNKNOWN: 2.5,  # the conservative end; never guess big
}

#: The plan's split, applied to barbell lower-body work: "add 2.5 kg upper /
#: 5 kg lower". A squat's working load is roughly twice a bench's, so the same
#: 2.5 kg is half the relative jump — 5 kg keeps the *percentage* comparable.
_BARBELL_LOWER_STEP = 5.0

#: Beyond this fraction of the current load, the note says so. A 2.5 kg jump on
#: a 15 kg lateral raise is 17 %, which no amount of rounding fixes; the wide
#: rep range (12-20) is what absorbs it, and the lifter deserves the warning.
_BIG_JUMP_FRACTION = 0.10

# "add 2.5 kg upper / 5 kg lower" / "suma 2,5 kg en superior / 5 kg en
# inferior" — el incremento que enuncia la fase 2 de RECOMP. Bilingüe como el
# resto de parsers de prosa de fases: la nota de serie está en español y la de
# una rutina vieja del usuario puede seguir en inglés.
_PRESCRIBED_STEP_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*kg\s*(?:en\s+)?(upper|lower|superior|inferior)",
    re.IGNORECASE,
)
_STEP_HALVES = {"upper": "upper", "superior": "upper", "lower": "lower", "inferior": "lower"}


def _matches(name: str, groups: Iterable[tuple[str, ...]]) -> bool:
    return any(all(token in name for token in group) for group in groups)


def classify_equipment(exercise: str) -> Equipment:
    """Best guess at what the load sits on. `UNKNOWN` when nothing matches."""
    name = _normalize(exercise)
    if not name:
        return Equipment.UNKNOWN
    for equipment, groups in _EQUIPMENT_PATTERNS:
        if _matches(name, groups):
            return equipment
    return Equipment.UNKNOWN


def is_lower_body(exercise: str) -> bool:
    name = _normalize(exercise)
    return bool(name) and _matches(name, _LOWER_BODY_TOKENS)


def parse_prescribed_step(text: str | None) -> dict[str, float]:
    """`"add 2.5 kg upper / 5 kg lower"` → `{"upper": 2.5, "lower": 5.0}`.

    The phase note is the authority when it states a number. Returns `{}` when
    it states none, which is every phase but RECOMP's accumulation block.
    """
    out: dict[str, float] = {}
    for value, half in _PRESCRIBED_STEP_RE.findall(text or ""):
        out[_STEP_HALVES[half.lower()]] = float(value.replace(",", "."))
    return out


@dataclass(frozen=True)
class Increment:
    kg: float
    equipment: Equipment
    reason: str


def weight_step(exercise: str, current_weight: float | None = None, phase: Any = None) -> Increment:
    """How much weight one successful double-progression cycle adds.

    Requirement 2 of the brief: 2.5 kg on a bench press and 2.5 kg on a curl
    are not the same event. The split, in order of authority:

    1. the phase's own prose, when it names kilos ("2.5 kg upper / 5 kg lower");
    2. barbell lower body → 5 kg, barbell upper body → 2.5 kg. That *is* the
       plan's rule, stated for the case it was written about;
    3. machine stacks → 5 kg, because that is one plate and the stack has no
       opinion about your preferences;
    4. dumbbells → 2.5 kg per hand, because that is the next dumbbell on the
       rack. Note this is a 5 kg jump in total system load, which is why the
       dumbbell work in this plan carries the wide rep ranges;
    5. cables and small stacks → 2.5 kg;
    6. bodyweight → 2.5 kg on a belt, and only once the top of the range is
       owned at bodyweight;
    7. anything unrecognised → 2.5 kg. Under-shooting costs one session;
       over-shooting costs a failed set and a bruised sternum.
    """
    equipment = classify_equipment(exercise)
    lower = is_lower_body(exercise)

    prescribed = parse_prescribed_step(getattr(phase, "notes", None))
    key = "lower" if lower else "upper"
    if key in prescribed and equipment in (Equipment.BARBELL, Equipment.MACHINE):
        kg = prescribed[key]
        why = f"la fase prescribe {_fmt(kg)} kg en {'inferior' if key == 'lower' else 'superior'}"
    elif equipment is Equipment.BARBELL and lower:
        kg = _BARBELL_LOWER_STEP
        why = "barra en inferior: 2×2,5 kg, el salto de 5 kg del plan"
    else:
        kg = _DEFAULT_STEP[equipment]
        why = {
            Equipment.BARBELL: "barra en superior: el par de discos real más pequeño (2×1,25 kg)",
            Equipment.DUMBBELL: "la siguiente mancuerna del rack, por mano",
            Equipment.MACHINE: "una placa más en la torre",
            Equipment.CABLE: "un paso más en la torre de polea",
            Equipment.BODYWEIGHT: "un disco más en el cinturón de lastre",
            Equipment.UNKNOWN: "equipo sin reconocer, así que el salto conservador",
        }[equipment]

    if current_weight and current_weight > 0 and kg / current_weight > _BIG_JUMP_FRACTION:
        pct = round(100 * kg / current_weight)
        why += f" — {pct}% de {_fmt(current_weight)} kg: cuenta con caer a la parte baja del rango"

    return Increment(kg=kg, equipment=equipment, reason=why)


# ─────────────────────────────────────────────────────────────────────────
# making the number loadable — gym_tools owns the plate maths
# ─────────────────────────────────────────────────────────────────────────

#: Step grid per equipment, for everything the plate calculator cannot help
#: with. A dumbbell rack, a cable stack and a machine's pin all move in fixed
#: increments and hold no plates, so "which plates" is not a question that
#: exists there — the grid *is* the right answer, not a degraded one.
_GRID: dict[Equipment, float] = {
    Equipment.BARBELL: 2.5,  # only reached if gym_tools is unavailable
    Equipment.DUMBBELL: 2.5,
    Equipment.MACHINE: 5.0,
    Equipment.CABLE: 2.5,
    Equipment.BODYWEIGHT: 2.5,
    Equipment.UNKNOWN: 2.5,
}


def _gym_tools():
    """The plate calculator module, or None.

    A soft import on purpose. `gym_tools.py` owns every question about bars,
    plates and what can physically be assembled; this module owns *what weight
    to aim for*. Importing it softly means progression keeps working — on the
    step grid — if the module is absent, and never grows a second plate
    calculator when it is present. Looked up per call rather than at import so
    the two files can land in either order.
    """
    try:
        import gym_tools  # type: ignore[import-not-found]
    except Exception:
        return None
    return gym_tools


def loadable_weight(
    weight: float,
    exercise: str = "",
    *,
    round_fn: Callable | None = None,
    equipment: Equipment | None = None,
) -> float:
    """Nearest weight that can actually be put on the bar (or the pin).

    Barbell work goes through `gym_tools.round_to_loadable`, with the bar it
    suggests for that exercise — an EZ curl bar is 7.5 kg, not 20, and getting
    that wrong moves every curl recommendation by 12.5 kg. Everything else
    rounds onto the equipment's own step, because a cable stack has no plates
    to solve for.

    `round_fn` overrides the whole lookup and is called as `round_fn(weight)`.
    One positional argument, nothing else: it exists as a test seam and as an
    escape hatch, so its contract is the narrowest thing that can work.
    """
    if weight is None or weight <= 0:
        return 0.0
    equipment = equipment or classify_equipment(exercise)

    if round_fn is not None:
        rounded = round_fn(weight)
        return float(rounded) if rounded is not None else float(weight)

    if equipment is Equipment.BARBELL:
        tools = _gym_tools()
        if tools is not None:
            rounded = tools.round_to_loadable(weight, tools.bar_for_exercise(exercise))
            # None means gym_tools could not read the inputs. Falling through to
            # the grid beats propagating a None into a weight field.
            if rounded is not None:
                return float(rounded)

    grid = _GRID[equipment]
    return round(round(weight / grid) * grid, 2)


# ─────────────────────────────────────────────────────────────────────────
# the recommendation
# ─────────────────────────────────────────────────────────────────────────


class Action(str, Enum):
    BASELINE = "baseline"  # no usable history: no weight is recommended
    ADD_WEIGHT = "add_weight"  # top of the range on every set → go up
    REPEAT = "repeat"  # same load, chase reps
    BACK_OFF = "back_off"  # failed twice, or back after a long lay-off
    HOLD_STALE = "hold_stale"  # would have gone up, but the gap is too long
    HOLD_DELOAD = "hold_deload"  # earned the jump, but this is a recovery week


class Confidence(str, Enum):
    NONE = "none"  # nothing to go on
    LOW = "low"  # a guess the user should overrule
    MEDIUM = "medium"  # readable history, unreadable or partial scheme
    HIGH = "high"  # recent history and a clean double-progression scheme


@dataclass(frozen=True)
class SetTarget:
    """Prefill for one row: what to load and what to chase."""

    index: int
    weight: float | None
    reps_low: int | None
    reps_high: int | None

    def label(self) -> str:
        reps = ""
        if self.reps_low is not None and self.reps_high is not None:
            reps = (
                f"{self.reps_low}"
                if self.reps_low == self.reps_high
                else f"{self.reps_low}-{self.reps_high}"
            )
        if self.weight is None:
            return reps
        return f"{_fmt(self.weight)} kg × {reps}" if reps else f"{_fmt(self.weight)} kg"


@dataclass(frozen=True)
class Recommendation:
    """What to do today, and — always — why.

    `reason` is not decoration. Every branch here is a judgement call about
    somebody's training, and a number with no argument behind it is worth less
    than no number at all.

    `weight is None` means "no bar to load", and `action` says which kind:
    `BASELINE` is *we do not know yet*, anything else is *this movement carries
    no external load* — a pull-up done at bodyweight. A UI renders both as an
    empty weight field, which is right in both cases, but only the first one
    should be asking the user to go find a number.
    """

    exercise: str  # canonical key, as stored in entrenos.ejercicio
    action: Action
    weight: float | None
    reps_low: int | None
    reps_high: int | None
    reason: str
    confidence: Confidence
    scheme: Scheme
    target_label: str = ""
    increment: Increment | None = None
    per_set: tuple[SetTarget, ...] = ()
    last_date: date | None = None
    days_since: int | None = None
    last_sets: tuple[dict, ...] = ()

    def has_weight(self) -> bool:
        return self.weight is not None

    def headline(self) -> str:
        """One line for the top of the exercise card."""
        if self.weight is None:
            return self.scheme.reps_label() or "Sin recomendación"
        reps = ""
        if self.reps_low is not None and self.reps_high is not None:
            reps = (
                f"{self.reps_low}"
                if self.reps_low == self.reps_high
                else f"{self.reps_low}-{self.reps_high}"
            )
        return f"{_fmt(self.weight)} kg × {reps}" if reps else f"{_fmt(self.weight)} kg"


def _fmt(value: float) -> str:
    """`80.0` → `"80"`, `72.5` → `"72.5"`. Nobody writes 80.0 on a whiteboard."""
    return f"{float(value):g}"


def _set_weight(one_set: dict) -> float:
    """A set's load. Missing or unparseable reads as 0 — i.e. bodyweight.

    Rows written by the Telegram coach are not guaranteed to carry every key
    (CLAUDE.md trap 4), and a pull-up logged with no weight is a real set.
    """
    value = _num(one_set.get("weight"))
    return float(value) if value is not None and value > 0 else 0.0


def _set_reps(one_set: dict) -> int | None:
    value = _num(one_set.get("reps"))
    if value is None or value <= 0:
        return None
    return int(value)


@dataclass(frozen=True)
class _Session:
    day: date | None
    sets: tuple[dict, ...]
    load: float
    reps: tuple[int, ...]  # reps of the sets performed at `load`, in order


def _sessions(exercise: str, history: Iterable[Any]) -> list[_Session]:
    """History → sessions, newest first, warm-ups and empty days dropped.

    Entries are read duck-typed (dataclass or dict) and filtered by exercise
    key when they carry one, so a caller can hand over either a pre-filtered
    list or the whole of `get_all()`.
    """
    key = exercise_key(exercise or "")
    out: list[_Session] = []
    for entry in history or []:
        name = _field(entry, "exercise", None)
        if name and key and exercise_key(str(name)) != key:
            continue
        sets = [s for s in _working_sets(_field(entry, "sets", []) or []) if _set_reps(s)]
        if not sets:
            continue
        # The load being progressed is the heaviest one worked that day. On a
        # straight-set scheme every set shares it; on a pyramid it is the top
        # of the pyramid, which is the set that has to move first.
        load = max(_set_weight(s) for s in sets)
        reps = tuple(
            r
            for r in (_set_reps(s) for s in sets if abs(_set_weight(s) - load) < 1e-6)
            if r is not None
        )
        out.append(
            _Session(
                day=_as_date(_field(entry, "date", None)), sets=tuple(sets), load=load, reps=reps
            )
        )

    # Undated rows sort last: they cannot participate in a staleness decision,
    # and putting them first would let one poison the whole recommendation.
    out.sort(key=lambda s: (s.day is not None, s.day or date.min), reverse=True)
    return out


def _failed(session: _Session, scheme: Scheme) -> bool:
    """True when a set fell under the bottom of the prescribed range."""
    if scheme.reps_low is None or not session.reps:
        return False
    return min(session.reps) < scheme.reps_low


def _hit_ceiling(session: _Session, scheme: Scheme) -> bool:
    """True when every prescribed set reached the top of the range."""
    if scheme.reps_high is None or not session.reps:
        return False
    target_sets = scheme.sets or len(session.reps)
    if len(session.reps) < target_sets:
        return False
    return all(r >= scheme.reps_high for r in session.reps)


def _pyramid_hit(session: _Session, scheme: Scheme) -> bool:
    """Pyramid version of `_hit_ceiling`: every set met its own target.

    Compared index by index against the sets actually logged that day (not just
    the ones at the top load — a pyramid's whole point is that the load moves).
    """
    logged = [_set_reps(s) for s in session.sets]
    if len(logged) < len(scheme.per_set):
        return False
    # strict=False deliberately: `logged` may be longer than the prescription
    # (an extra set is not a failure), and shorter was already rejected above.
    return all(
        done is not None and done >= target
        for done, target in zip(logged, scheme.per_set, strict=False)
    )


def _repeat_targets(session: _Session, scheme: Scheme, load: float) -> tuple[SetTarget, ...]:
    """Prefill for a repeat: same load, and at least what you did last time."""
    count = scheme.sets or len(session.reps) or 1
    high = scheme.reps_high
    out: list[SetTarget] = []
    for i in range(count):
        done = session.reps[i] if i < len(session.reps) else None
        low = (
            min(done, high)
            if (done is not None and high is not None)
            else (done or scheme.reps_low)
        )
        out.append(SetTarget(index=i, weight=load, reps_low=low, reps_high=high or low))
    return tuple(out)


def _flat_targets(scheme: Scheme, load: float | None) -> tuple[SetTarget, ...]:
    count = scheme.sets or 1
    return tuple(
        SetTarget(index=i, weight=load, reps_low=scheme.reps_low, reps_high=scheme.reps_high)
        for i in range(count)
    )


def _pyramid_targets(
    session: _Session,
    scheme: Scheme,
    step: float,
    exercise: str = "",
    round_fn: Callable | None = None,
) -> tuple[SetTarget, ...]:
    """Per-set prefill for a pyramid: last session's ladder, plus the step.

    Every rung is rounded, not just the top one: the lighter rungs of a
    pyramid are the ones most likely to land on something unloadable.
    """
    weights = [_set_weight(s) for s in session.sets]
    out: list[SetTarget] = []
    for i, target in enumerate(scheme.per_set):
        base = weights[i] if i < len(weights) else (weights[-1] if weights else 0.0)
        weight = loadable_weight(base + step, exercise, round_fn=round_fn) if base > 0 else base
        out.append(SetTarget(index=i, weight=weight or None, reps_low=target, reps_high=target))
    return tuple(out)


def _reps_text(reps: Iterable[int]) -> str:
    return ",".join(str(r) for r in reps)


def _load_text(load: float) -> str:
    return "peso corporal" if load <= 0 else f"{_fmt(load)} kg"


def recommend(
    exercise: str,
    history: Iterable[Any] | None = None,
    *,
    phase: Any = None,
    routine: Any = None,
    today: date | None = None,
    round_fn: Callable | None = None,
    scheme: Scheme | None = None,
) -> Recommendation:
    """Today's load and rep target for one exercise. Never guesses a weight.

    `history` is any iterable of entries with `date` and `sets` (a
    `storage.WorkoutEntry`, a dict, whatever the caller has). Order does not
    matter; entries for other exercises are filtered out when they name one.

    The branches, in the order they are tested:

    * no usable history → `Action.BASELINE`, `weight=None`. There is no honest
      number here and the module refuses to invent one;
    * gap over `RESET_AFTER_DAYS` → `BACK_OFF` at 90 % of the last load;
    * top of the range on every prescribed set → `ADD_WEIGHT`, unless the gap
      is over `STALE_AFTER_DAYS`, in which case `HOLD_STALE` repeats it;
    * a set under the bottom of the range, twice in a row at the same load →
      `BACK_OFF`. Once → `REPEAT`;
    * anything else → `REPEAT` at the same load, chasing the reps you missed.
    """
    today = today or date.today()
    key = exercise_key(exercise or "")
    scheme = scheme or parse_scheme(exercise, getattr(phase, "scheme", "") or "")
    target_label = prescribed_target(exercise, phase, routine)
    sessions = _sessions(exercise, history or [])

    if not sessions:
        return Recommendation(
            exercise=key,
            action=Action.BASELINE,
            weight=None,
            reps_low=scheme.reps_low,
            reps_high=scheme.reps_high,
            reason=_baseline_reason(key, scheme),
            confidence=Confidence.NONE,
            scheme=scheme,
            target_label=target_label,
            increment=None,
            per_set=_flat_targets(scheme, None),
        )

    last = sessions[0]
    load = last.load
    increment = weight_step(exercise, current_weight=load or None, phase=phase)
    days_since = (today - last.day).days if last.day else None
    # The fields every branch below fills in identically, splatted at each
    # return so the branches only have to spell out what they actually decide.
    base = {
        "exercise": key,
        "scheme": scheme,
        "target_label": target_label,
        "increment": increment,
        "last_date": last.day,
        "days_since": days_since,
        "last_sets": last.sets,
    }
    when = f" ({last.day.isoformat()})" if last.day else ""

    # ── long lay-off: the last load is history, not a starting point ──
    if days_since is not None and days_since >= RESET_AFTER_DAYS:
        target = loadable_weight(load * RE_ENTRY_FACTOR, exercise, round_fn=round_fn)
        return Recommendation(
            action=Action.BACK_OFF,
            weight=target or None,
            reps_low=scheme.reps_low,
            reps_high=scheme.reps_high,
            reason=(
                f"Último registro hace {days_since} días{when}, a {_load_text(load)}. "
                f"Es tiempo de sobra para perder parte, así que esto es una vuelta, "
                f"no una continuación: {_load_text(target)} "
                f"({int(RE_ENTRY_FACTOR * 100)}% de la carga vieja). "
                f"Si se mueve fácil, la próxima sesión vuelve directa arriba."
            ),
            confidence=Confidence.LOW,
            per_set=_flat_targets(scheme, target or None),
            **base,
        )

    stale = days_since is not None and days_since >= STALE_AFTER_DAYS

    # ── a deload week never adds weight ──
    #
    # Double progression says "top of the range on every set → go up", and in a
    # recovery week that rule is exactly wrong: RECOMP phase 3 prescribes "Same
    # loads, half the sets", CambiaTuFísico's says "Low intensity, no failure".
    # Hitting the ceiling on the reduced set count is the *expected* outcome of
    # a deload, so the ceiling test fires on every lift and the app would spend
    # the recovery week telling him to add 2.5 kg to all of them.
    #
    # Checked before every ADD_WEIGHT branch rather than inside each one, so a
    # future scheme kind cannot be added and quietly skip it.
    if is_deload(phase):
        return Recommendation(
            action=Action.HOLD_DELOAD,
            weight=load or None,
            reps_low=scheme.reps_low,
            reps_high=scheme.reps_high,
            reason=(
                f"Semana de descarga: misma carga, menos series. {_load_text(load)}, "
                f"como la última vez{when}. Llegar hoy al tope del rango es justo lo "
                f"que una descarga debe parecer, no una señal de subir — el salto "
                f"espera al siguiente bloque."
            ),
            confidence=Confidence.HIGH,
            per_set=_flat_targets(scheme, load or None),
            **base,
        )

    # ── schemes double progression cannot drive ──
    if scheme.kind in (SchemeKind.AMRAP, SchemeKind.CLUSTER, SchemeKind.UNKNOWN):
        return _repeat_only(last, scheme, load, base)

    # ── pyramids: per-set targets, evaluated index by index ──
    if scheme.kind is SchemeKind.PYRAMID:
        if _pyramid_hit(last, scheme) and not stale:
            targets = _pyramid_targets(last, scheme, increment.kg, exercise, round_fn)
            return Recommendation(
                action=Action.ADD_WEIGHT,
                weight=(targets[-1].weight if targets else None),
                reps_low=scheme.reps_low,
                reps_high=scheme.reps_high,
                reason=(
                    f"Todas las series cumplieron su objetivo la última vez{when} "
                    f"({_reps_text(scheme.per_set)}). Suma {_fmt(increment.kg)} kg a cada "
                    f"peldaño de la pirámide — {increment.reason}."
                ),
                confidence=Confidence.MEDIUM,
                per_set=targets,
                **base,
            )
        targets = _pyramid_targets(last, scheme, 0.0, exercise, round_fn)
        why = (
            f"Han pasado {days_since} días desde la última sesión{when}: hoy sin salto. "
            if stale
            else ""
        )
        return Recommendation(
            action=Action.HOLD_STALE if stale else Action.REPEAT,
            weight=(targets[-1].weight if targets else None),
            reps_low=scheme.reps_low,
            reps_high=scheme.reps_high,
            reason=(
                f"{why}Pirámide: la misma escalera que la última vez, buscando "
                f"{_reps_text(scheme.per_set)} en la subida. El peso solo se mueve cuando "
                f"cada peldaño cumple su número."
            ),
            confidence=Confidence.MEDIUM,
            per_set=targets,
            **base,
        )

    # ── the real case: RANGE and FIXED ──
    if _hit_ceiling(last, scheme):
        if stale:
            return Recommendation(
                action=Action.HOLD_STALE,
                weight=load or None,
                reps_low=scheme.reps_low,
                reps_high=scheme.reps_high,
                reason=(
                    f"Te ganaste el salto la última vez — {_reps_text(last.reps)} a "
                    f"{_load_text(load)}, tope de {scheme.reps_low}-{scheme.reps_high} en "
                    f"todas las series — pero eso fue hace {days_since} días{when}. Repite "
                    f"{_load_text(load)} y da el salto la próxima sesión; añadir peso encima "
                    f"de tres semanas de parón es como una regla correcta sobre el papel "
                    f"falla en la primera serie."
                ),
                confidence=Confidence.MEDIUM,
                per_set=_flat_targets(scheme, load or None),
                **base,
            )
        target = loadable_weight(load + increment.kg, exercise, round_fn=round_fn)
        bodyweight = load <= 0
        extra = (
            f"Añade {_fmt(increment.kg)} kg al cinturón — {increment.reason}."
            if bodyweight
            else f"Pasa a {_fmt(target)} kg — {increment.reason}."
        )
        return Recommendation(
            action=Action.ADD_WEIGHT,
            weight=(increment.kg if bodyweight else target),
            reps_low=scheme.reps_low,
            reps_high=scheme.reps_high,
            reason=(
                f"Última sesión{when}: {_reps_text(last.reps)} a {_load_text(load)} — "
                f"{scheme.reps_high} reps, el tope del rango, en las "
                f"{len(last.reps)} series. {extra} Reconstruye desde {scheme.reps_low} reps."
            ),
            confidence=Confidence.HIGH,
            per_set=_flat_targets(scheme, (increment.kg if bodyweight else target) or None),
            **base,
        )

    if _failed(last, scheme):
        previous = sessions[1] if len(sessions) > 1 else None
        twice = (
            previous is not None and abs(previous.load - load) < 1e-6 and _failed(previous, scheme)
        )
        if twice:
            target = loadable_weight(load * BACK_OFF_FACTOR, exercise, round_fn=round_fn)
            return Recommendation(
                action=Action.BACK_OFF,
                weight=target or None,
                reps_low=scheme.reps_low,
                reps_high=scheme.reps_high,
                reason=(
                    f"Dos sesiones seguidas por debajo de {scheme.reps_low} reps a "
                    f"{_load_text(load)} ({_reps_text(previous.reps)} y luego "
                    f"{_reps_text(last.reps)}). Eso no es un mal día, es demasiado "
                    f"peso: baja a {_load_text(target)} "
                    f"({int(BACK_OFF_FACTOR * 100)}%), domina el rango otra vez y vuelve a subir."
                ),
                confidence=Confidence.MEDIUM,
                per_set=_flat_targets(scheme, target or None),
                **base,
            )
        return Recommendation(
            action=Action.REPEAT,
            weight=load or None,
            reps_low=scheme.reps_low,
            reps_high=scheme.reps_high,
            reason=(
                f"Última sesión{when}: {_reps_text(last.reps)} a {_load_text(load)} — por "
                f"debajo de {scheme.reps_low}, el suelo del rango. Una sesión corta es un mal "
                f"día, no un veredicto: mismo peso, y devuelve cada serie a {scheme.reps_low}. "
                f"Si se repite, el peso baja."
            ),
            confidence=Confidence.HIGH,
            per_set=_flat_targets(scheme, load or None),
            **base,
        )

    worst = min(last.reps) if last.reps else scheme.reps_low
    chase = min(worst + 1, scheme.reps_high) if scheme.reps_high else worst
    short = (scheme.sets or len(last.reps)) - len(last.reps)
    missing = (
        f" Solo {len(last.reps)} de {scheme.sets} series quedaron registradas a esa carga, "
        f"así que el salto aún no está ganado."
        if short > 0
        else ""
    )
    stale_note = (
        f" (Han pasado {days_since} días de esa sesión — tómala como una vuelta.)" if stale else ""
    )
    return Recommendation(
        action=Action.REPEAT,
        weight=load or None,
        reps_low=chase,
        reps_high=scheme.reps_high,
        reason=(
            f"Última sesión{when}: {_reps_text(last.reps)} a {_load_text(load)}. Aún dentro "
            f"de {scheme.reps_low}-{scheme.reps_high}, así que el peso se queda: mismo "
            f"{_load_text(load)}, y supera {worst} en tu peor serie. La carga se mueve el día "
            f"que todas las series lleguen a {scheme.reps_high}.{missing}{stale_note}"
        ),
        confidence=Confidence.HIGH,
        per_set=_repeat_targets(last, scheme, load),
        **base,
    )


def _baseline_reason(key: str, scheme: Scheme) -> str:
    """The honest no-history answer. Requirement 4 of the brief.

    No weight is returned. An invented number on a first bench press is worse
    than a blank field: the field gets filled in thirty seconds, a load that is
    20 kg optimistic gets found out under the bar.
    """
    top = scheme.reps_high
    if top:
        return (
            f"Sin historial de {key}. No hay en qué basar un peso, así que no hay "
            f"recomendación: elige una carga que puedas llevar a {top} reps con 2-3 en la "
            f"recámara, apúntala, y esa es la línea base contra la que se mide todo lo demás."
        )
    return (
        f"Sin historial de {key} y sin prescripción de repeticiones legible. Apunta lo que "
        f"hagas hoy — con una sesión basta para empezar a recomendar."
    )


def _repeat_only(last: _Session, scheme: Scheme, load: float, base: dict) -> Recommendation:
    """Schemes where double progression has nothing to trigger on.

    Three of them, all real and all in data.py:

    * `[4×max]` / `[3×failure]` — no ceiling, so "hit the top of the range on
      every set" can never become true. The progression is total reps;
    * `[2×10+10+10]`, `[4×8+10]`, `[4×(20+20+20)]` — drop sets, bi-sets and
      trisets. `entrenos` stores one row per exercise with a flat list of sets,
      so nothing in the data says which segment a given set belongs to. Any
      rule applied to them would be applied to the wrong number;
    * unreadable brackets. Repeating the last load is the only claim that is
      certainly true.
    """
    total = sum(_set_reps(s) or 0 for s in last.sets)
    when = f" ({last.day.isoformat()})" if last.day else ""

    if scheme.kind is SchemeKind.AMRAP:
        reason = (
            f"AMRAP: la prescripción no tiene techo de repeticiones, así que no hay tope de "
            f"rango que alcanzar ni forma de ganarse el peso así. Última sesión{when}: "
            f"{_reps_text(r for r in (_set_reps(s) for s in last.sets) if r)} a "
            f"{_load_text(load)}, {total} reps en total. Misma carga, supera {total}."
        )
    elif scheme.kind is SchemeKind.CLUSTER:
        reason = (
            f"{scheme.reps_label()} es un clúster — drop set, bi-serie o triserie. El registro "
            f"guarda una lista plana de series por ejercicio, así que nada aquí sabe a qué "
            f"segmento pertenece cada serie, y una regla aplicada al segmento equivocado es "
            f"peor que ninguna. Mismo {_load_text(load)} que la última vez{when}; añade "
            f"repeticiones donde puedas."
        )
    else:
        reason = (
            f"Sin prescripción de repeticiones legible"
            f"{f' en “{scheme.raw}”' if scheme.raw else ''}, así que nada se puede inferir del "
            f"rango. Repetir el {_load_text(load)} de la última sesión{when} es la única "
            f"afirmación con certeza verdadera."
        )

    return Recommendation(
        action=Action.REPEAT,
        weight=load or None,
        reps_low=scheme.reps_low,
        reps_high=scheme.reps_high,
        reason=reason,
        confidence=Confidence.LOW,
        per_set=_flat_targets(scheme, load or None),
        **base,
    )


def recommend_from_store(
    store: Any,
    exercise: str,
    *,
    phase: Any = None,
    routine: Any = None,
    today: date | None = None,
    round_fn: Callable | None = None,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> Recommendation:
    """`recommend` fed from `Storage`. The only function here that does I/O.

    Reads through `get_exercise_history`, which is keyed on the canonical
    `exercise_key()` name — the same key the Telegram coach writes, so a
    session logged on Telegram counts towards the next recommendation here.
    """
    key = exercise_key(exercise or "")
    history = store.get_exercise_history(key, limit=limit) if key else []
    return recommend(
        exercise,
        history,
        phase=phase,
        routine=routine,
        today=today,
        round_fn=round_fn,
    )
