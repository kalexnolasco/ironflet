"""Set types and automatic rest — the two things every logged set was missing.

A set used to be `{"weight", "reps"}` plus an optional `"rir"`, and all of them
counted the same. That makes a 20 kg warm-up on the bench worth as much as the
top set: it inflates tonnage and, worse, a heavy warm-up single can steal a PR.

Two rules hold this module together.

1. **`"type"` is optional and absent means normal.** Every row already sitting
   in `entrenos.series` was written without it, and the Telegram coach still
   writes without it — `../agente/entrenador/entrenos.py::guardar_series`
   builds `{"weight", "reps", "rir"?}` and nothing else. Those sets are real
   work and must keep counting; treating them as anything else would rewrite
   Alex's history on the next release.
2. **Only warm-ups are discounted.** A drop set and a set to failure are work.
   The label says *how* the set was done, not *whether* it happened.

Rest is here because it is decided from the same two inputs: which exercise
this is, and what kind of set just finished. The coach already answers the
first half in `../agente/entrenador/sesion_viva.py::descanso_de` — 180 s for
the plan's basics, 90 s for everything else — and both sides have to say the
same number, or Alex reads one rest on his phone and another in the app.
`tests/test_set_types.py` loads the coach's own constants and compares, so the
day someone edits that list the disagreement shows up as a failing test rather
than as two apps arguing.

Nothing here imports Flet or opens a database: it is plain data in, plain data
out, same contract as `analytics.py`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import Enum
from typing import Any

from exercises import exercise_key

# ─────────────────────────────────────────────────────────────────────────
# the types
# ─────────────────────────────────────────────────────────────────────────

#: The key inside a set dict. Named once so nothing spells it by hand.
TYPE_KEY = "type"


class SetType(str, Enum):
    """What kind of set this was.

    The values are what lands in the JSON column, so they are lowercase ASCII
    and never change. `str` mixin so `set["type"] == SetType.WARMUP` works and
    `json.dumps` writes the bare string — but always serialise `.value`
    explicitly anyway (see `tag_set`), because a plain `str` in the payload is
    what every other reader of this table expects.
    """

    WARMUP = "warmup"
    NORMAL = "normal"
    DROPSET = "dropset"
    FAILURE = "failure"


DEFAULT_SET_TYPE = SetType.NORMAL

#: Full labels for menus.
LABELS: dict[SetType, str] = {
    SetType.WARMUP: "Warm-up",
    SetType.NORMAL: "Working set",
    SetType.DROPSET: "Drop set",
    SetType.FAILURE: "To failure",
}

#: One-letter badges for the set row, where there is no space for a word.
SHORT_LABELS: dict[SetType, str] = {
    SetType.WARMUP: "W",
    SetType.NORMAL: "N",
    SetType.DROPSET: "D",
    SetType.FAILURE: "F",
}

#: Order a tap-to-cycle control walks through. Normal first: it is the default
#: and the one Alex picks 90 % of the time, so it costs zero taps.
CYCLE_ORDER: tuple[SetType, ...] = (
    SetType.NORMAL,
    SetType.WARMUP,
    SetType.DROPSET,
    SetType.FAILURE,
)

# Spellings accepted on the way in. Three writers touch this table (this app,
# the coach, restored backups) so reading is generous and writing is strict.
#
# The warm-up spellings must stay in step with `analytics.WARMUP_TYPES`, which
# hardcodes its own copy — until analytics delegates here, a spelling added on
# one side only would count a warm-up as work. tests/test_set_types.py asserts
# the two agree.
_ALIASES: dict[str, SetType] = {
    "warmup": SetType.WARMUP,
    "warm_up": SetType.WARMUP,
    "warm-up": SetType.WARMUP,
    "warm up": SetType.WARMUP,
    "normal": SetType.NORMAL,
    "work": SetType.NORMAL,
    "working": SetType.NORMAL,
    "straight": SetType.NORMAL,
    "dropset": SetType.DROPSET,
    "drop": SetType.DROPSET,
    "drop_set": SetType.DROPSET,
    "drop-set": SetType.DROPSET,
    "drop set": SetType.DROPSET,
    "failure": SetType.FAILURE,
    "to_failure": SetType.FAILURE,
    "to failure": SetType.FAILURE,
    "amrap": SetType.FAILURE,
}


def parse_set_type(value: Any) -> SetType:
    """Any stored value → a `SetType`. Unknown and missing both mean normal.

    Deliberately never raises. This runs over rows written months ago by two
    different programs; a set that says something unexpected is still a set
    that Alex performed, and the safe reading is "it counted".
    """
    if isinstance(value, SetType):
        return value
    if value is None:
        return DEFAULT_SET_TYPE
    return _ALIASES.get(str(value).strip().lower(), DEFAULT_SET_TYPE)


def set_type_of(one_set: Any) -> SetType:
    """The type of a set dict. Anything that is not a dict is normal."""
    if not isinstance(one_set, dict):
        return DEFAULT_SET_TYPE
    return parse_set_type(one_set.get(TYPE_KEY))


def is_warmup(one_set: Any) -> bool:
    return set_type_of(one_set) is SetType.WARMUP


def counts_as_work(one_set: Any) -> bool:
    """True for every set that belongs in volume, set counts and PRs.

    That is everything except a warm-up — including sets with no `"type"` key,
    which is every set written before this module existed.
    """
    return not is_warmup(one_set)


def working_sets(sets: Iterable[dict] | None) -> list[dict]:
    """The sets that count: warm-ups dropped, non-dict junk dropped."""
    return [s for s in sets or [] if isinstance(s, dict) and counts_as_work(s)]


def warmup_sets(sets: Iterable[dict] | None) -> list[dict]:
    """The other half of the split, for showing "3 + 2 warm-up" in the UI."""
    return [s for s in sets or [] if isinstance(s, dict) and is_warmup(s)]


def count_by_type(sets: Iterable[dict] | None) -> dict[SetType, int]:
    """How many sets of each type. Every type is present, zeros included."""
    counts = dict.fromkeys(SetType, 0)
    for s in sets or []:
        if isinstance(s, dict):
            counts[set_type_of(s)] += 1
    return counts


def tag_set(one_set: dict, set_type: Any) -> dict:
    """Copy of `one_set` labelled with `set_type`.

    Two decisions worth knowing:

    * It returns a new dict. The caller's set — often a row read straight out
      of storage — is never mutated.
    * A normal set is written **without** the key. Normal is the default, so
      the key would be noise, and leaving it out keeps our payload identical to
      the ones the coach writes and to the ~everything already in the table.
      One shape for one meaning; no reader has to learn that `"normal"` and
      absent are the same thing.
    """
    resolved = parse_set_type(set_type)
    copy = {k: v for k, v in one_set.items() if k != TYPE_KEY}
    if resolved is not DEFAULT_SET_TYPE:
        copy[TYPE_KEY] = resolved.value
    return copy


def label_for(set_type: Any) -> str:
    return LABELS[parse_set_type(set_type)]


def short_label_for(set_type: Any) -> str:
    return SHORT_LABELS[parse_set_type(set_type)]


def next_set_type(set_type: Any) -> SetType:
    """The next type in `CYCLE_ORDER`, for a tap-to-cycle badge."""
    current = parse_set_type(set_type)
    return CYCLE_ORDER[(CYCLE_ORDER.index(current) + 1) % len(CYCLE_ORDER)]


# ─────────────────────────────────────────────────────────────────────────
# automatic rest
# ─────────────────────────────────────────────────────────────────────────

#: Same two numbers as `sesion_viva.DESCANSO_BASICO` / `DESCANSO_AISLAMIENTO`.
REST_COMPOUND_S = 180
REST_ISOLATION_S = 90

#: A warm-up is not the set you need to recover from. Capped against the
#: working rest below, so a 45 s isolation prescription never ends up with a
#: *longer* warm-up rest than working rest.
REST_AFTER_WARMUP_S = 60

# The plan's basic lifts, as canonical English keys.
#
# This is `sesion_viva.BASICOS` translated, not a general "is it multi-joint?"
# test, and the difference is visible: seated cable row, one-arm DB row, lat
# pulldown and seated DB press are all multi-joint and all get 90 s, because
# that is what the coach tells Alex on Telegram. Coherence beats taxonomy —
# two different numbers for the same exercise is a bug the user can see, a
# debatable 90 s on a lat pulldown is not.
#
# Each entry is a group of substrings that must *all* appear in the normalised
# name, which is what separates "Incline DB Press" (compound) from "Incline DB
# Curl" (isolation) and "Leg Press" from "Leg Extensions".
_COMPOUND_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("bench", "press"),
    ("military", "press"),
    ("incline", "press"),
    ("leg", "press"),
    ("barbell", "row"),
    ("hip", "thrust"),
    ("squat",),  # also Bulgarian split squat, as in the coach
    ("deadlift",),
    ("romanian",),  # data.py abbreviates it to "Romanian DL" inside bi-sets
    ("dip",),
    ("pull up",),
    ("pullup",),
)


def _normalize(exercise: str) -> str:
    """Prescription string → matchable name: no brackets, no case, no hyphens.

    Hyphens go so that "Pull-ups" and "Pull ups" are the same thing.
    """
    name = exercise_key(exercise or "").lower().replace("-", " ")
    return " ".join(name.split())


def is_compound(exercise: str) -> bool:
    """True for the plan's basic lifts — the ones that earn the long rest."""
    name = _normalize(exercise)
    if not name:
        return False
    return any(all(token in name for token in group) for group in _COMPOUND_PATTERNS)


# A duration term: `3'`, `1'30"`, `90s`, or a bare number that borrows its unit
# from the other end of a range ("60-90s" is seconds, "2-2'30"" is minutes).
# The `s` has to touch the number and end a word, or "2 sets" would parse as
# two seconds.
_TERM_RE = re.compile(r"(\d+)(?:\s*'\s*(\d+)?\s*\"?|(s)\b)?", re.IGNORECASE)
_PARENS_RE = re.compile(r"\([^)]*\)")


def _segment_seconds(segment: str) -> int | None:
    """Seconds prescribed by one segment, or None if it names no duration.

    A range resolves to its **upper** bound: "60-90s" is 90. The prescription
    is a ceiling to rest under, and the coach's isolation number is 90, so the
    upper bound is also what keeps the two sides equal.
    """
    terms: list[tuple[int, str | None]] = []
    for match in _TERM_RE.finditer(segment):
        number, extra_seconds, seconds_unit = match.groups()
        if match.group(0).isdigit():
            terms.append((int(number), None))  # bare: unit resolved below
        elif seconds_unit:
            terms.append((int(number), "s"))
        else:
            terms.append((int(number) * 60 + int(extra_seconds or 0), "m"))

    if not terms:
        return None

    values: list[int] = []
    for i, (value, unit) in enumerate(terms):
        if unit is not None:
            values.append(value)
            continue
        # Bare number: take the unit of the next term that has one — the "60"
        # in "60-90s" is seconds, the "2" in "2-2'30"" is minutes. With no
        # such term, read small numbers as minutes and the rest as seconds.
        following = next((u for _, u in terms[i + 1 :] if u is not None), None)
        if following == "s" or (following is None and value > 10):
            values.append(value)
        else:
            values.append(value * 60)
    return max(values)


def parse_prescribed_rest(text: str | None) -> tuple[int, int] | None:
    """`Phase.rest` → `(compound_s, isolation_s)`, or None if unreadable.

    `Phase.rest` is prose written for a human — "3' compounds / 60-90s
    isolation", "1'30\" sets (max 2')", "2-2'30\" / 3' ex. / 1' on *" — and it
    is the only per-phase rest the app has. Reading it beats ignoring it, but
    it is a best-effort parse: when nothing matches, the caller falls back to
    the coach's two constants.

    Rules, in order: a segment naming compounds or isolation wins for that
    bucket; otherwise the segment about *sets* applies to both (the "2-3'
    exercises" half is the pause between exercises, not between sets, and the
    rest timer is a between-sets timer); otherwise the first segment that names
    any duration. Parenthesised asides ("(max 2')") are dropped — they are
    ceilings, not the prescription.
    """
    if not text:
        return None

    cleaned = _PARENS_RE.sub(" ", text)
    segments = [seg for seg in re.split(r"[/,]", cleaned) if seg.strip()]
    parsed = [(seg.lower(), _segment_seconds(seg)) for seg in segments]
    usable = [(low, secs) for low, secs in parsed if secs is not None]
    if not usable:
        return None

    def find(*keywords: str) -> int | None:
        return next((s for low, s in usable if any(k in low for k in keywords)), None)

    fallback = find("set") or usable[0][1]
    compound = find("compound", "basic") or fallback
    isolation = find("isolation", "accessor") or fallback
    return compound, isolation


def rest_seconds(
    exercise: str,
    *,
    set_type: Any = None,
    phase_rest: str | None = None,
) -> int:
    """How long to rest after finishing a set of `exercise`.

    With no `phase_rest` this is exactly `sesion_viva.descanso_de`: 180 s for
    the plan's basics, 90 s for everything else. Pass `phase_rest` (the active
    `Phase.rest` string) and the phase's own prescription takes over when it
    can be parsed — for the recomposition routine it parses to the very same
    180/90, which is the point.

    `set_type` only matters for warm-ups, which get a short rest. Drop sets and
    sets to failure return the normal rest: they are harder, not different.
    """
    compound_s, isolation_s = REST_COMPOUND_S, REST_ISOLATION_S
    prescribed = parse_prescribed_rest(phase_rest)
    if prescribed:
        compound_s, isolation_s = prescribed

    base = compound_s if is_compound(exercise) else isolation_s
    if parse_set_type(set_type) is SetType.WARMUP:
        return min(REST_AFTER_WARMUP_S, base)
    return base


def rest_seconds_for_phase(exercise: str, phase: Any, set_type: Any = None) -> int:
    """`rest_seconds` for a `data.Phase`. Duck-typed so data.py stays unimported."""
    return rest_seconds(
        exercise,
        set_type=set_type,
        phase_rest=getattr(phase, "rest", None),
    )


def format_rest(seconds: int) -> str:
    """`180` → `"3:00"`. Clock format, same as the rest timer's own readout."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"
