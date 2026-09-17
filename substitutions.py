"""Swapping an exercise for an equivalent one when the machine is taken.

The routine names specific stations — Leg Press, Leg Extensions, Seated Cable
Row, Pec Deck, Lying Leg Curl — and at peak hours they are all occupied. The
choice today is to wait or to drop the exercise. This module adds the third
option every training log has: do the equivalent movement on something else.

Three things live here and nothing else does:

1. **The equivalence catalogue** (`alternatives`, `is_valid_substitution`),
   *derived* from `exercise_details.py` rather than written out by hand. Two
   exercises are equivalent when they train the same muscles through the same
   kind of movement; the derivation and its exceptions are documented below.
2. **The scope** (`Scope.TODAY` / `Scope.PHASE`), persisted in `preferencias`
   as JSON under one key. No new column, no migration — see CLAUDE.md on why
   adding one is a two-repository operation.
3. **What to show when the substitute has no history**, which is the normal
   case and, right now, the only case: nothing has been logged yet.

THE RULE THIS MODULE EXISTS TO PROTECT
--------------------------------------
`entrenos.ejercicio` stores the exercise that was **actually performed**, under
its own canonical `exercises.exercise_key()`. If Alex does Squat instead of Leg
Press, the row says `Squat`. Recording it as `Leg Press` because that is what
the plan asked for would be a silent, unrecoverable corruption: the Telegram
coach in ../agente/ reads the same column, `progression.recommend_from_store`
keys its history on it, and nothing anywhere would raise — the numbers would
just quietly describe a session that never happened.

So the substitution lives in `preferencias`, never in `entrenos`, and
`key_to_log()` is the one function a view calls to find out what to write.

Nothing here imports Flet or opens a database at import time, like the other
analysis modules, so it unit-tests without a running app and the coach can
reuse it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from enum import Enum
from functools import lru_cache
from typing import Any

from exercises import exercise_key

# ─────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────

#: The `preferencias` key. `preferencias.clave` is `String(60)`; this fits.
PREF_KEY = "substitutions"

#: Bumped when the JSON shape changes. A state written by a *newer* version is
#: ignored rather than parsed optimistically or deleted: the database is shared
#: with the coach, and quietly discarding somebody else's data is the failure
#: mode this whole repo is organised around avoiding.
STATE_VERSION = 1


class Scope(str, Enum):
    """How long a swap lasts.

    `TODAY` is the busy-machine case: the Pec Deck is taken right now.
    `PHASE` is the durable one: the gym removed the machine, or Alex simply
    prefers the alternative for the rest of this block.

    A `TODAY` entry wins over a `PHASE` entry for the same exercise — it is the
    more specific and more recent statement of intent.
    """

    TODAY = "today"
    PHASE = "phase"


# ─────────────────────────────────────────────────────────────────────────
# The equivalence catalogue, derived
# ─────────────────────────────────────────────────────────────────────────
#
# Every exercise the app knows carries, through `exercise_details.details_for`
# (which looks up via `exercise_images.EXERCISE_IMAGE`), four usable fields:
# `primary`, `secondary`, `equipment` and `mechanic`. Two of them are enough to
# say what a movement *is*:
#
#     pattern = (primary muscles, mechanic)
#
# Leg Press and Squat are both `(quadriceps, compound)`. Pec Deck and Cable
# Crossover are both `(chest, isolation)`. Lying Leg Curl and Seated Leg Curl
# are both `(hamstrings, isolation)`. That is the whole catalogue: ~90 names
# fall into ~20 patterns without a single hand-written pair.
#
# `secondary` is deliberately *not* part of the pattern. It is noisy in the
# source data — Pec Deck lists none and Cable Crossover lists shoulders, which
# would split a pair the exercise selection screen must keep together.
#
# Where the derivation is wrong, the exceptions are below — four short tables,
# each documented with the wrong swap it prevents, and not one hand-written
# pair of exercises among them. That is the point: a pair table would go stale
# the moment somebody adds an exercise, and nothing would say so.

#: Patterns assigned by hand, because the derivation cannot reach them.
#:
#: * Bulgarian Split Squat has no entry at all. CLAUDE.md records why it has no
#:   image: the 500-exercise source catalogue has no such movement, and a
#:   confidently wrong photo is worse than none. Without this line it can
#:   neither be substituted nor offered, which would be a silent hole in a
#:   routine that prescribes it.
#: * HIIT Intervals borrows the `Air_Bike` slug — an *abdominal* exercise — so
#:   the derivation files it under abs and offers it as a swap for Cable
#:   Crunch. It is conditioning. Here it is given the cardio pattern (unknown
#:   mechanic, like Treadmill / Bike / Elliptical), which is what it actually
#:   interchanges with.
_MANUAL_PATTERN: dict[str, tuple[tuple[str, ...], str | None]] = {
    "Bulgarian Split Squat": (("quadriceps",), "compound"),
    "HIIT Intervals": (("quadriceps",), None),
}

#: `mechanic` corrections. The source labels some movements compound that are
#: single-joint, which puts them in the pattern of a heavy press.
#:
#: * flyes / crossover — `Incline_Dumbbell_Flyes` ships `mechanic: compound`,
#:   so "Incline DB Flyes" would be offered as a swap for Barbell Bench Press
#:   and vice versa. It is a fly; it belongs with Pec Deck and Cable Crossover.
#: * rear delts / face pull — `Face_Pull` ships `mechanic: compound`, which
#:   split "Cable Rear Delts" away from "DB Rear Delts" and put it in with the
#:   overhead presses.
_MECHANIC_OVERRIDE: tuple[tuple[str, str], ...] = (
    ("fly", "isolation"),
    ("crossover", "isolation"),
    ("rear delt", "isolation"),
    ("face pull", "isolation"),
)

#: The single biggest hole in the source data: it has one muscle called
#: `shoulders`, covering the front, side and rear head of the deltoid. Those
#: three are not interchangeable, and without this split the derivation offers
#: **Lateral Raises as a substitute for Rear Delts** — same primary muscle,
#: same mechanic, and completely the wrong exercise.
#:
#: The name is the only signal left, so the name is what is read. Anything
#: shoulder-primary that matches none of these is a press, and pressing is
#: anterior-deltoid work; that default is what keeps Military Press, Arnold
#: Press and Smith Military Press in one group.
_DELT_HEADS: tuple[tuple[str, str], ...] = (
    ("rear delt", "rear delts"),
    ("face pull", "rear delts"),
    ("lateral raise", "side delts"),
    ("upright row", "side delts"),
    ("front raise", "front delts"),
)
_DELT_DEFAULT = "front delts"

#: Combination entries — "Bi-set: Leg Press + Extensions", "SS: Squat + Lying
#: Leg Curl", "Calf Press + Seated". The routine logs them as one exercise
#: under one key, and `analytics.resolve_muscles` only gets muscles out of them
#: by splitting on `+` and retrying the halves, which works because it only
#: needs muscles. A substitution needs a *movement*, and half of these are
#: written too tersely to split back into keys the app knows ("EZ Preacher",
#: "Romanian DL", "V-Pulldown"). So they neither offer nor accept a swap.
#: Substituting one half of a bi-set is a different feature.
#:
#: Matched anywhere in the name, not just at the front: "Abs Triset" is one of
#: these and carries no prefix and no `+`.
_COMBINATION_TOKENS = ("bi-set", "ss:", "triset", "superset")

#: Tiers, best first. `DIRECT` is a like-for-like swap. `VARIATION` trains the
#: same muscle through the other mechanic — Leg Extensions has no isolation
#: partner anywhere in the catalogue, so without this tier one of the five
#: machines Alex actually gets blocked on would offer nothing at all.
TIER_DIRECT = "direct"
TIER_VARIATION = "variation"


@dataclass(frozen=True)
class Alternative:
    """One offered swap.

    `key` is canonical: it is what `entrenos.ejercicio` would hold, and it is
    a name the app already knows — it has an image, muscle data and a
    progression history of its own.
    """

    key: str
    equipment: str
    tier: str
    reason: str

    @property
    def is_direct(self) -> bool:
        return self.tier == TIER_DIRECT


@dataclass(frozen=True)
class Substitution:
    """An active swap, as read back out of `preferencias`."""

    prescribed: str  # canonical key of what the plan asked for
    performed: str  # canonical key of what Alex will actually do
    scope: Scope

    @property
    def key_to_log(self) -> str:
        """The value for `entrenos.ejercicio`. Always the performed exercise."""
        return self.performed


def is_combination(name: str) -> bool:
    """True for bi-sets, supersets and trisets, which cannot be substituted."""
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    return "+" in lowered or any(token in lowered for token in _COMBINATION_TOKENS)


def _details(key: str) -> dict | None:
    from exercise_details import details_for

    return details_for(key)


def _slug(key: str) -> str:
    """The details-table slug, or the key itself when it has none.

    Falling back to the key matters: two hand-classified exercises both
    carrying `None` would otherwise compare as the same movement.
    """
    from exercise_images import EXERCISE_IMAGE

    return EXERCISE_IMAGE.get(key) or f"\x00{key}"


#: The details table's own equipment vocabulary, translated into
#: `progression.Equipment`'s. Both end up in the same sentence on screen, and
#: "body only instead of bodyweight" is not a sentence.
_EQUIPMENT_ALIASES = {
    "body only": "bodyweight",
    "e-z curl bar": "barbell",
    "exercise ball": "bodyweight",
    "medicine ball": "bodyweight",
    "kettlebells": "dumbbell",
    "bands": "cable",
    "foam roll": "unknown",
    "other": "unknown",
    "": "unknown",
}

UNKNOWN_EQUIPMENT = "unknown"


def equipment_for(key: str) -> str:
    """What the load sits on: `barbell`, `machine`, `cable`, …

    Delegates to `progression.classify_equipment`, which reads the *name*, and
    that is the point: the details table's `equipment` field describes the
    slug, and slugs are shared. "Machine Lateral Raises" reuses the dumbbell
    side-raise photo and so claims `equipment: dumbbell`, which is exactly
    backwards for a feature whose entire job is to send Alex to a different
    piece of hardware. The details field is used only where the name says
    nothing ("Incline Flyes", "Pec Deck").
    """
    from progression import Equipment, classify_equipment

    guess = classify_equipment(key)
    if guess is not Equipment.UNKNOWN:
        return guess.value
    raw = ((_details(key) or {}).get("equipment") or "").strip().lower()
    return _EQUIPMENT_ALIASES.get(raw, raw or UNKNOWN_EQUIPMENT)


def _mechanic(key: str, detail: dict | None) -> str | None:
    lowered = key.lower()
    for token, mechanic in _MECHANIC_OVERRIDE:
        if token in lowered:
            return mechanic
    return (detail or {}).get("mechanic")


def _muscles(key: str, detail: dict | None) -> tuple[str, ...]:
    primary = tuple(sorted((detail or {}).get("primary") or ()))
    if primary != ("shoulders",):
        return primary
    lowered = key.lower()
    for token, head in _DELT_HEADS:
        if token in lowered:
            return (head,)
    return (_DELT_DEFAULT,)


@dataclass(frozen=True)
class Pattern:
    """What a movement *is*: the muscles it drives, and how.

    `mechanic` is `None` for the cardio machines, whose details carry none.
    That is load-bearing, not a gap: an unknown mechanic only ever matches
    another unknown one, which keeps Treadmill / Bike / Elliptical
    interchangeable with each other and stops Treadmill being offered as a
    variation on Squat — both are `quadriceps` in the source data.
    """

    muscles: tuple[str, ...]
    mechanic: str | None

    def label(self) -> str:
        muscles = " / ".join(self.muscles) if self.muscles else "unclassified"
        return f"{muscles} · {self.mechanic}" if self.mechanic else muscles


def pattern_for(name: str) -> Pattern | None:
    """The movement pattern of an exercise, or `None` if it has no place here.

    Accepts a prescription string — `"Leg Press [4×8-10]"` — as well as a bare
    key, because that is what the routine holds.
    """
    key = exercise_key(name or "")
    if not key or is_combination(key):
        return None
    manual = _MANUAL_PATTERN.get(key)
    if manual:
        return Pattern(tuple(sorted(manual[0])), manual[1])
    detail = _details(key)
    if not detail:
        return None
    muscles = _muscles(key, detail)
    if not muscles:
        return None
    return Pattern(muscles, _mechanic(key, detail))


@lru_cache(maxsize=1)
def _known_names() -> tuple[str, ...]:
    """Every non-combination exercise name the app knows, sorted.

    Deliberately built from the two *static* tables — `data.EXERCISE_CATALOG`
    and `exercise_images.EXERCISE_IMAGE` — plus the hand-classified names, and
    not from the routines. A user routine spliced in by
    `routine_builder.sync_user_routines()` can name an exercise that exists
    nowhere else; offering it as a substitute would write a key into
    `entrenos.ejercicio` that has no image, no muscle data and no meaning to
    the coach. Every name here already has all three.
    """
    from data import EXERCISE_CATALOG
    from exercise_images import EXERCISE_IMAGE

    names = {n for group in EXERCISE_CATALOG.values() for n in group}
    names |= set(EXERCISE_IMAGE)
    names |= set(_MANUAL_PATTERN)
    return tuple(sorted(n for n in names if not is_combination(n)))


@lru_cache(maxsize=1)
def _curated_names() -> frozenset[str]:
    """The names `data.EXERCISE_CATALOG` lists — the app's own vocabulary."""
    from data import EXERCISE_CATALOG

    return frozenset(n for group in EXERCISE_CATALOG.values() for n in group)


@lru_cache(maxsize=1)
def _by_pattern() -> dict[Pattern, tuple[str, ...]]:
    groups: dict[Pattern, list[str]] = {}
    for name in _known_names():
        pattern = pattern_for(name)
        if pattern is None:
            continue
        groups.setdefault(pattern, []).append(name)
    return {p: tuple(names) for p, names in groups.items()}


def reset_cache() -> None:
    """Drop the derived catalogue. For tests that patch the source tables."""
    _known_names.cache_clear()
    _curated_names.cache_clear()
    _by_pattern.cache_clear()


def is_alias(a: str, b: str) -> bool:
    """True when two names are the same movement written two ways.

    Same details slug *and* same equipment. The slug alone is not enough:
    "Lateral Raises", "Machine Lateral Raises" and "Cable Lateral Raises" all
    share `Side_Lateral_Raise` because the image bundle has one photo for the
    three, yet they are three different stations and swapping between them is
    the whole point. Adding equipment separates those from the genuine
    duplicates — "Straight Bar Curl" / "Barbell Curl", "Skull Crushers" /
    "EZ Bar Skull Crushers", "Dips" / "Parallel Bar Dips" — which are the same
    bar in the same corner and would be a useless thing to offer.

    Known cost: "Pec Deck" and "Machine Flyes" are one entry in the details
    table and both classify as `machine`, so they read as aliases and are not
    offered for each other. In a gym they are the same pec deck, so that is the
    behaviour we want; "Cable Crossover" and "Incline DB Flyes" are the swaps
    that actually free the station.
    """
    if a == b:
        return True
    return _slug(a) == _slug(b) and equipment_for(a) == equipment_for(b)


def _reason(original: str, candidate: str, pattern: Pattern, tier: str) -> str:
    from_eq = equipment_for(original)
    to_eq = equipment_for(candidate)
    muscles = " and ".join(pattern.muscles) if pattern.muscles else "the same muscles"
    if tier == TIER_VARIATION:
        kind = "compound" if pattern.mechanic == "compound" else "isolation"
        article = "a" if kind == "compound" else "an"
        return f"Trains {muscles} as {article} {kind} movement — expect a different load."
    known = UNKNOWN_EQUIPMENT not in (from_eq, to_eq)
    if known and to_eq != from_eq:
        return f"Same movement, {to_eq} instead of {from_eq}."
    return f"Same movement pattern for {muscles}."


def alternatives(name: str, *, limit: int = 8) -> tuple[Alternative, ...]:
    """Exercises that can stand in for this one, best first.

    Direct swaps (same muscles, same mechanic) come before variations (same
    muscles, other mechanic), and within a tier the ones on *different*
    equipment come first — the machine being busy is the reason we are here.
    Ties go to the name `data.EXERCISE_CATALOG` uses, then to alphabetical
    order, so the list a view renders is the same on every run.

    This is also the definition `is_valid_substitution` answers with: what can
    be offered and what can be stored are one list, deliberately, so a view can
    never present a swap the store would then refuse.

    Returns `()` for a combination entry, for an exercise the details table
    does not know, and for anything with no partner at all.
    """
    key = exercise_key(name or "")
    pattern = pattern_for(key)
    if pattern is None:
        return ()

    groups = _by_pattern()
    found: list[Alternative] = []

    for candidate in groups.get(pattern, ()):
        if is_alias(key, candidate):
            continue
        found.append(
            Alternative(
                candidate,
                equipment_for(candidate),
                TIER_DIRECT,
                _reason(key, candidate, pattern, TIER_DIRECT),
            )
        )

    # The other mechanic, but only between two *known* mechanics: `None` means
    # the source told us nothing, and guessing across a hole is how Treadmill
    # ends up offered for Squat.
    if pattern.mechanic is not None:
        other = "isolation" if pattern.mechanic == "compound" else "compound"
        sibling = Pattern(pattern.muscles, other)
        for candidate in groups.get(sibling, ()):
            if is_alias(key, candidate):
                continue
            found.append(
                Alternative(
                    candidate,
                    equipment_for(candidate),
                    TIER_VARIATION,
                    _reason(key, candidate, sibling, TIER_VARIATION),
                )
            )

    origin_equipment = equipment_for(key)
    curated = _curated_names()
    found.sort(
        key=lambda a: (
            0 if a.tier == TIER_DIRECT else 1,
            0 if a.equipment != origin_equipment else 1,
            # Prefer the name `data.EXERCISE_CATALOG` uses. It decides which of
            # two aliases survives the dedup below, and alphabetical order
            # would decide it arbitrarily — "Machine Flyes" is the same entry
            # as "Pec Deck", but Pec Deck is what the routine and the exercise
            # picker call it.
            0 if a.key in curated else 1,
            a.key,
        )
    )

    # Two names for one movement is noise on a list somebody reads standing up
    # between sets: "Incline DB Flyes" and "Incline Flyes" are the same photo
    # and the same dumbbells. Sorting first makes the survivor deterministic.
    kept: list[Alternative] = []
    for candidate in found:
        if any(is_alias(candidate.key, other.key) for other in kept):
            continue
        kept.append(candidate)
    return tuple(kept[:limit]) if limit else tuple(kept)


def is_valid_substitution(original: str, replacement: str) -> bool:
    """Whether `replacement` may stand in for `original`.

    False for an unknown name, for a combination entry, for the exercise
    itself, for an alias of it, and for anything training a different pattern.
    The unknown-name case is the one that matters: it is the guard that stops a
    name the app cannot resolve reaching `entrenos.ejercicio`.
    """
    key = exercise_key(original or "")
    target = exercise_key(replacement or "")
    if not key or not target:
        return False
    return any(a.key == target for a in alternatives(key, limit=0))


def swap_prescription(prescribed: str, performed: str) -> str:
    """Re-label a prescription onto the substitute, brackets intact.

    `("Leg Press [4×8-10]", "Squat")` → `"Squat [4×8-10]"`. The plan's sets,
    reps and tags belong to the *slot*, not to the machine, so the substitute
    inherits them. Feed the result to `progression` and it parses the right
    scheme while reading the right history: `recommend_from_store` keys history
    off `exercise_key()`, which is now `Squat`.

    `exercise_key()` only ever strips a suffix, so the key is a prefix of the
    string it came from and the remainder can be carried across verbatim.
    """
    key = exercise_key(prescribed or "")
    suffix = prescribed[len(key) :] if prescribed.startswith(key) else ""
    return f"{exercise_key(performed or '')}{suffix}"


# ─────────────────────────────────────────────────────────────────────────
# State in `preferencias`
# ─────────────────────────────────────────────────────────────────────────
#
# {
#   "version": 1,
#   "today": {"date": "2026-08-19", "map": {"Leg Press": "Squat"}},
#   "phase": {"routine": "cambiatufisico", "phase": 3, "map": {...}}
# }
#
# One row, one JSON blob, no migration. Each bucket carries the context that
# scopes it, so expiry is a comparison at read time rather than a cleanup job
# that has to run: a `today` map for another date and a `phase` map for another
# phase or routine are simply not returned.


def _empty_state() -> dict:
    return {"version": STATE_VERSION, "today": {}, "phase": {}}


def load_state(store: Any) -> dict:
    """Parse the stored blob, tolerating anything at all in the column.

    The database is shared and hand-editable, and this is a convenience
    feature: a malformed value means "no substitutions", never a stack trace on
    the way into the workout screen.
    """
    raw = None
    try:
        raw = store.get_pref(PREF_KEY, None)
    except Exception:
        return _empty_state()
    if not raw:
        return _empty_state()
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return _empty_state()
    if not isinstance(parsed, dict):
        return _empty_state()
    if parsed.get("version") != STATE_VERSION:
        # Written by a version that is not this one. Read nothing; write
        # nothing back until the user makes a new choice.
        return _empty_state()
    state = _empty_state()
    for bucket in ("today", "phase"):
        value = parsed.get(bucket)
        if isinstance(value, dict):
            state[bucket] = value
    return state


def save_state(store: Any, state: dict) -> None:
    store.set_pref(PREF_KEY, json.dumps(state, sort_keys=True))


def _valid_map(raw: Any) -> dict[str, str]:
    """The `map` sub-dict, keeping only pairs that are still a legal swap.

    Re-validated on every read on purpose. A stored pair can stop being valid
    — the catalogue is derived, so editing `EXERCISE_IMAGE` or the details
    table changes it — and the invariant that must survive that is the one
    about `entrenos.ejercicio`: never hand a view a key it cannot resolve.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for original, replacement in raw.items():
        if not isinstance(original, str) or not isinstance(replacement, str):
            continue
        if is_valid_substitution(original, replacement):
            out[exercise_key(original)] = exercise_key(replacement)
    return out


def _today_map(state: dict, today: date) -> dict[str, str]:
    bucket = state.get("today") or {}
    if bucket.get("date") != today.isoformat():
        return {}
    return _valid_map(bucket.get("map"))


def _phase_map(state: dict, routine_id: str | None, phase_id: int | None) -> dict[str, str]:
    bucket = state.get("phase") or {}
    if routine_id is None or phase_id is None:
        return {}
    if bucket.get("routine") != routine_id or bucket.get("phase") != phase_id:
        return {}
    return _valid_map(bucket.get("map"))


def _active_routine_id() -> str:
    from data import active_routine

    return active_routine().id


def set_substitution(
    store: Any,
    prescribed: str,
    performed: str,
    scope: Scope | str = Scope.TODAY,
    *,
    routine_id: str | None = None,
    phase_id: int | None = None,
    today: date | None = None,
) -> Substitution:
    """Record a swap. Raises `ValueError` if it is not a legal one.

    Refusing loudly is the right failure here. A caller that has not checked
    `is_valid_substitution` is about to persist a pairing that ends up in
    `entrenos.ejercicio`, and silence there is exactly the class of bug this
    repo keeps paying for.
    """
    scope = Scope(scope)
    key = exercise_key(prescribed or "")
    target = exercise_key(performed or "")
    if not is_valid_substitution(key, target):
        raise ValueError(f"{target or '(empty)'} is not a valid substitute for {key or '(empty)'}")

    today = today or date.today()
    routine_id = routine_id or _active_routine_id()
    if scope is Scope.PHASE and phase_id is None:
        raise ValueError("a phase-scoped substitution needs the phase it belongs to")

    state = load_state(store)
    if scope is Scope.TODAY:
        bucket = state.get("today") or {}
        stored = dict(bucket.get("map") or {}) if bucket.get("date") == today.isoformat() else {}
        stored[key] = target
        state["today"] = {"date": today.isoformat(), "map": stored}
    else:
        bucket = state.get("phase") or {}
        same_block = bucket.get("routine") == routine_id and bucket.get("phase") == phase_id
        stored = dict(bucket.get("map") or {}) if same_block else {}
        stored[key] = target
        state["phase"] = {"routine": routine_id, "phase": phase_id, "map": stored}

    save_state(store, state)
    return Substitution(key, target, scope)


def clear_substitution(
    store: Any,
    prescribed: str,
    scope: Scope | str | None = None,
    *,
    routine_id: str | None = None,
    phase_id: int | None = None,
    today: date | None = None,
) -> None:
    """Undo a swap. `scope=None` clears it from both buckets."""
    key = exercise_key(prescribed or "")
    if not key:
        return
    scopes = (Scope(scope),) if scope is not None else (Scope.TODAY, Scope.PHASE)
    state = load_state(store)
    changed = False
    for one in scopes:
        bucket = state.get(one.value) or {}
        stored = bucket.get("map")
        if isinstance(stored, dict) and key in stored:
            stored.pop(key)
            changed = True
    if changed:
        save_state(store, state)


def active_substitutions(
    store: Any,
    *,
    routine_id: str | None = None,
    phase_id: int | None = None,
    today: date | None = None,
) -> dict[str, Substitution]:
    """Every swap in force right now, keyed by the prescribed exercise.

    `today` entries override `phase` entries. Anything scoped to another day,
    phase or routine has expired and is not returned — and is not deleted
    either: rewriting the row on a read path would mean the workout screen
    writes to the database just by being opened.
    """
    today = today or date.today()
    routine_id = routine_id if routine_id is not None else _active_routine_id()
    state = load_state(store)

    out: dict[str, Substitution] = {}
    for original, replacement in _phase_map(state, routine_id, phase_id).items():
        out[original] = Substitution(original, replacement, Scope.PHASE)
    for original, replacement in _today_map(state, today).items():
        out[original] = Substitution(original, replacement, Scope.TODAY)
    return out


def substitution_for(
    store: Any,
    prescribed: str,
    *,
    routine_id: str | None = None,
    phase_id: int | None = None,
    today: date | None = None,
) -> Substitution | None:
    """The swap in force for one exercise, or `None`."""
    key = exercise_key(prescribed or "")
    if not key:
        return None
    return active_substitutions(store, routine_id=routine_id, phase_id=phase_id, today=today).get(
        key
    )


def key_to_log(
    prescribed: str,
    *,
    store: Any = None,
    routine_id: str | None = None,
    phase_id: int | None = None,
    today: date | None = None,
) -> str:
    """**The value to write into `entrenos.ejercicio`.** Call this, not `exercise_key`.

    With a substitution in force it returns the substitute's canonical key,
    because that is the exercise that was performed. Without one, and with no
    store, it degrades to `exercise_key(prescribed)` — the existing behaviour,
    unchanged.

    The whole module exists so that this function can be the only place a view
    has to think about it.
    """
    key = exercise_key(prescribed or "")
    if store is None or not key:
        return key
    swap = substitution_for(store, key, routine_id=routine_id, phase_id=phase_id, today=today)
    return swap.performed if swap else key


# ─────────────────────────────────────────────────────────────────────────
# The first session on a substitute
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StartingPoint:
    """What to put on the card when the substitute is new.

    Which it always will be at first, and — today — always is: nothing has been
    logged yet at all, so both sides of every swap are empty.

    Deliberately carries **no invented weight**. Translating 120 kg of leg
    press into a squat is a guess dressed as a number, and `progression` is
    built around refusing exactly that (`Action.BASELINE` is *we do not know
    yet*). The reference line names what the replaced exercise would have been
    today and says plainly that it is not a target.
    """

    key: str  # canonical key of the exercise actually being done
    has_history: bool
    headline: str  # progression's own line, or "" when there is nothing to say
    target_label: str  # the prescription: "8-10 reps @ RIR 2-3"
    note: str
    reference: str = ""

    def lines(self) -> tuple[str, ...]:
        """Non-empty display lines, in order. Saves every view a filter."""
        return tuple(x for x in (self.headline, self.target_label, self.note, self.reference) if x)


def starting_point(
    store: Any,
    prescribed: str,
    performed: str,
    *,
    phase: Any = None,
    routine: Any = None,
    today: date | None = None,
) -> StartingPoint:
    """What to show for a substituted exercise before it has any history.

    Both numbers come from `progression.recommend_from_store`, which is the
    only implementation of "what should I lift" in the repo — nothing is
    recomputed here. The substitute is asked with the *prescription of the
    slot* (`swap_prescription`), so it inherits the plan's sets and reps while
    reading its own history.
    """
    from progression import Action, recommend_from_store

    key = exercise_key(performed or "")
    original = exercise_key(prescribed or "")
    prescription = swap_prescription(prescribed or "", key)

    rec = recommend_from_store(store, prescription, phase=phase, routine=routine, today=today)
    has_history = rec.action is not Action.BASELINE

    if has_history:
        return StartingPoint(
            key=key,
            has_history=True,
            headline=rec.headline(),
            target_label=rec.target_label,
            note=rec.reason,
        )

    note = (
        f"No history for {key} yet. Pick a weight you can control for the whole "
        f"range, and log what you actually lift."
    )

    reference = ""
    if original and original != key:
        ref = recommend_from_store(store, prescribed, phase=phase, routine=routine, today=today)
        if ref.has_weight():
            reference = (
                f"{original} today would have been {ref.headline()}. "
                f"Different equipment moves different loads — that is context, not a target."
            )
        else:
            reference = f"No history for {original} either, so there is nothing to carry over."

    return StartingPoint(
        key=key,
        has_history=False,
        headline="",
        target_label=rec.target_label,
        note=note,
        reference=reference,
    )
