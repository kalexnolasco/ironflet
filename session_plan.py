"""Which set rows an exercise opens with — and what each of them is *for*.

The screen used to open every exercise with **one** empty row, whatever the
plan said. Across CambiaTuFísico's 178 prescribed exercises the plan asks for
635 sets, so that one row costs **457 taps of "+ Set"** over the 24 weeks, every
one of them a tap that tells the app something it already knew. On top of that
the plan prescribes **21 drop sets** (spread over 18 exercises — three of them
carry two, `[3×10,8+12↓,8+12↓]`), and the app neither opened those rows nor
labelled them, so a phase whose whole identity is "Drop Sets + Compound" was
logged as if drop sets did not exist.

`progression.parse_scheme` already knows all of this. Nobody was asking it.
This module asks, and turns the answer into rows.

Pure data in, pure data out: no Flet, no database, no `analytics` re-implemented
here. It is a *reader* of `progression.Scheme` and a *writer* of proposals.

──────────────────────────────────────────────────────────────────────────
THE ONE THING TO GET RIGHT WHEN INTEGRATING THIS
──────────────────────────────────────────────────────────────────────────

**Everything this module returns is a proposal, never a performed set.**

A `ProposedSet` deliberately carries **no weight and no performed reps**. It
carries how many rows to open, what each row is aiming at, and what kind of set
it is. The numbers Alex actually lifted are his to type; the weight to aim for
is `progression.recommend`'s answer, not this module's.

That is not fussiness, it is the draft invariant. `views/workout.py` persists
proposed rows as **empty holes on purpose** (`workout_draft.is_blank_row`), so
that restoring a draft can never turn something the app guessed into something
the history says he lifted — and it marks a row it seeded with `_SUGGESTED_KEY`
until he vouches for it. If an integrator ever fills a proposal's weight in and
saves it, `analytics` will mint a personal record for a set that never happened.

`to_draft_rows()` is the safe bridge and the reason it exists: it emits rows in
`workout_draft.blank_row()` shape whose weight/reps/rir are the empty string,
so every row it produces is *structurally* blank — `is_blank_row()` says True
for all of them, and the invariant holds without the caller having to know it.
There is no function here that can produce a filled row. Keep it that way.

──────────────────────────────────────────────────────────────────────────
THE HISTORY CONFLICT, DECIDED
──────────────────────────────────────────────────────────────────────────

When the exercise *does* have history, two answers are both defensible: open as
many rows as last session had, or as many as the plan prescribes.

**The plan wins by default** (`SetCountSource.PLAN`). Three reasons, in order of
how much they cost when ignored:

1. The routine is periodized over 24 weeks. Last session's Squat may well have
   been phase 5's `[5×12,10,10,8,8]` while today's is phase 6's
   `[4×10,10,10,6+12↓]`. Copying the count copies the *previous phase's*
   prescription into the new one, which is precisely the thing the periodization
   exists to change.
2. A session that got cut short — four sets done of five, gym closing — would
   become the new normal, and the session after that would inherit the shortfall
   again. Following history ratchets downwards and never back up.
3. The drop set exists only in the plan. History cannot ask for a row that was
   never logged, so a history-driven count in phase 6 silently deletes the one
   thing phase 6 is about.

The case for the other answer is real and worth stating: what Alex did last time
is the best single predictor of what he will do this time, the seeded prefill in
`views/workout.py::_seed_sets` comes from history so a plan-driven count leaves
the extra row conspicuously empty, and if he has settled on 4 sets where the plan
says 5 the app nags him with a blank row forever.

So the caller can ask for it: `count_source=SetCountSource.LAST_SESSION`. It
overrides **only the number of prescribed sets**. Rep targets, set types and the
drop rows still come from the plan — a drop set is structure, not a count.

Either way `SessionPlan` reports both numbers (`plan_set_count`,
`history_set_count`) and `disagrees_with_history()`, so the UI can show "the plan
asks for 5; last time you did 4" instead of picking a side in silence.

──────────────────────────────────────────────────────────────────────────
THE SCHEMES DOUBLE PROGRESSION CANNOT DRIVE
──────────────────────────────────────────────────────────────────────────

`progression.recommend` works by double progression: hit the top of the rep
range on every set, then add weight. Three scheme kinds give it nothing to hit,
and each gets a different, deliberate answer here.

**AMRAP — `[4×max]`, `[3×failure]`.** There is no ceiling, so no jump can ever be
earned. Rows are opened with *no rep target at all* rather than an invented one,
and typed `SetType.FAILURE`, because "max" is not a number, it is an
instruction. Phase 5 says "Failure on all sets except first" and phase 6 writes
`[3×failure]` in the bracket; the type is how that gets onto the row. Note this
is a *prescription* on a proposal, not a claim about what happened — it stays a
suggestion until the user confirms the row, exactly like a prefilled weight.

**Combination sets — `Bi-set: A + B [4×8+10]`, `Triset: … [4×10+10+10]`,
`A + B [comp] [4×8+8]`, `Abs Triset [4×(20+20+20)]`.** These get **one row per
round**, not one row per segment, and this one is not a matter of taste:
`analytics.resolve_muscles` splits the combined name and gives *each component
the entry's full set count*, because "in a paired set every round contains every
component". Emit 8 rows for a 4-round bi-set and every component is credited 8
sets instead of 4 — the muscle-volume chart doubles, silently, for the whole of
phase 7. So: one row per round, `reps_label` carrying the full `"8+10"` so the
row still says what to do. The honest cost, stated plainly: the second movement's
weight has nowhere to go. Fixing that needs a schema change (one `entrenos` row
per component), which is a two-repo commit under the shared-schema rule, and is
not this module's call to make.

**Single-movement clusters — `Cable Curl [triple drop] [2×10+10+10]`.** Here the
segments are the *same* movement at descending loads, so there is no
double-counting to fear and each segment is a set that really happened at its own
weight. These expand: segment 1 `NORMAL`, every later segment `DROPSET`. Two
rounds of a triple drop open six rows, which is what two triple drops are.

A cluster with no marker either way is treated as a combination — the
conservative direction, since a missing row costs one tap of "+ Set" while an
invented row is a row that can be filled in and saved.

**Nothing readable at all** (`SchemeKind.UNKNOWN`, `source == "none"`) opens
exactly one normal row with no target. That is today's behaviour and it is the
right answer: the module was given no prescription and must not invent one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from exercises import exercise_key

# `_DROP_MARK` and `_AMRAP_WORDS` are imported rather than re-typed on purpose.
# They describe how `data.py` spells a prescription, `progression.py` is the
# module that owns that reading, and a second copy of either one here would let
# the two drift with nothing raising — the same failure mode as every other
# duplicated constant in this repo. (`progression` itself imports `set_types.
# _normalize` for exactly this reason.)
from progression import _AMRAP_WORDS, _DROP_MARK, Scheme, SchemeKind, parse_scheme
from set_types import TYPE_KEY, SetType, set_type_of, working_sets

# ─────────────────────────────────────────────────────────────────────────
# limits
# ─────────────────────────────────────────────────────────────────────────

#: Hard ceiling on rows one exercise may propose. `progression`'s bracket regex
#: accepts two digits, so a typo like `[40×10+10+10]` would otherwise open 120
#: rows on a phone. Kept well under `workout_draft.MAX_ROWS_PER_EXERCISE` (50),
#: which is where the draft would start dropping rows silently on save.
MAX_PROPOSED_ROWS = 24

#: What a row with no readable prescription falls back to. One row, because that
#: is what an exercise had before this module existed: no regression, no guess.
FALLBACK_ROWS = 1

#: The draft row shape `to_draft_rows()` emits. Mirrors
#: `workout_draft.ROW_FIELDS` + `set_types.TYPE_KEY`; `tests/test_session_plan.py`
#: asserts the two agree, so a field added there fails a test here instead of
#: producing rows the draft silently normalises away.
DRAFT_ROW_FIELDS: tuple[str, ...] = ("weight", "reps", "rir")


class SetCountSource(str, Enum):
    """Who decides how many prescribed sets an exercise opens with.

    See the module docstring for the argument. `PLAN` is the default and the
    recommended one; `LAST_SESSION` exists so the integrator can offer the other
    answer without re-deriving any of this.
    """

    PLAN = "plan"
    LAST_SESSION = "last_session"


# ─────────────────────────────────────────────────────────────────────────
# reading the exercise string
# ─────────────────────────────────────────────────────────────────────────

#: Every `[..]` group. The scheme bracket (`[4×5-8]`) is one of these; the rest
#: are tags (`[comp]`, `[triple drop]`).
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")

#: A bracket that carries a prescription rather than a tag. Same shape
#: `progression._BRACKET_SCHEME_RE` matches, kept loose here because all this
#: needs to answer is "is this one a tag?".
_SCHEME_BRACKET_RE = re.compile(r"^\s*\d{1,2}\s*[×x]\s*\S")

#: How `data.py` writes "this is one exercise done twice over", either as a
#: named block (`Bi-set: A + B`, `Abs Triset`) or as a joined name
#: (`Lying + Seated Leg Curl [comp]`). Deliberately matches "triset" anywhere
#: and not only as a `Triset:` prefix — `analytics._COMBO_PREFIX_RE` anchors to
#: the front and therefore does not see `Abs Triset`, which is a combination all
#: the same. The two are answering different questions and are allowed to differ;
#: `tests/test_session_plan.py` pins the classification of all 33 real cluster
#: strings so neither can drift unnoticed.
_COMBO_WORD_RE = re.compile(
    r"\b(?:bi-?\s?set|super\s?set|tri-?\s?set|giant\s?set)\b", re.IGNORECASE
)

#: A tag bracket that says the segments are one movement losing weight.
_DROP_TAG_RE = re.compile(r"drop", re.IGNORECASE)


def _tag_brackets(exercise: str) -> tuple[str, ...]:
    """The `[..]` groups that are tags, not prescriptions: `("comp",)`."""
    return tuple(
        b.strip() for b in _BRACKET_RE.findall(exercise or "") if not _SCHEME_BRACKET_RE.match(b)
    )


def is_combination(exercise: str) -> bool:
    """True when the segments of a cluster are *different* movements.

    `"Bi-set: Dips + Triceps Pushdown [4×8+10]"` → True.
    `"Cable Curl [triple drop] [2×10+10+10]"`   → False.

    Checked before the drop tag, so a name that says both comes out a
    combination — the direction that cannot invent rows.
    """
    name = exercise_key(exercise or "")
    return bool(_COMBO_WORD_RE.search(name)) or "+" in name


def is_drop_cluster(exercise: str) -> bool:
    """True for a cluster that is one movement stripped down set by set."""
    if is_combination(exercise):
        return False
    return any(_DROP_TAG_RE.search(tag) for tag in _tag_brackets(exercise))


# ─────────────────────────────────────────────────────────────────────────
# one proposed row
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProposedSet:
    """One row the screen should open — **a proposal, not a logged set.**

    There is no `weight` field and no performed `reps` field, and that absence is
    the design. This says *open a row here, aiming at this, of this kind*. What
    was lifted is typed by the user; what should be lifted is
    `progression.recommend`'s answer.

    * `position`   — 1-based order on screen, drop rows included.
    * `set_number` — 1-based number among the *prescribed* sets; `None` on a drop
      row, because a drop is not set 5, it is the tail of set 4.
    * `drop_of`    — the `set_number` a drop row hangs off; `None` otherwise.
    * `reps_low` / `reps_high` — the target, equal for a fixed prescription, both
      `None` when the plan states no number (AMRAP, a combination round, an
      unreadable scheme). `None` means *unknown*, never zero.
    * `reps_label` — the bare target as data.py writes it: `"8-10"`, `"12"`,
      `"max"`, `"8+10"`. No unit; `progression.Scheme.reps_label()` is the one
      that appends the word "reps".
    * `note` — short English gloss for the row, or `""`.
    """

    position: int
    set_number: int | None
    set_type: SetType
    reps_low: int | None = None
    reps_high: int | None = None
    reps_label: str = ""
    drop_of: int | None = None
    note: str = ""

    def is_drop(self) -> bool:
        return self.set_type is SetType.DROPSET

    def has_target(self) -> bool:
        """False when the plan names no rep target for this row."""
        return self.reps_low is not None

    def label(self) -> str:
        """`"Set 2 · 10 reps"`, `"Drop · 12 reps"`, `"Set 1 · max reps"`."""
        head = "Drop" if self.is_drop() else f"Set {self.set_number}"
        return f"{head} · {self.reps_label} reps" if self.reps_label else head


# ─────────────────────────────────────────────────────────────────────────
# the plan for one exercise
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SessionPlan:
    """What one exercise opens with. Every row in `proposals` is a proposal.

    `plan_set_count` and `history_set_count` are both reported whether or not
    they were used, so the caller can say which one it followed and what the
    other one would have said.
    """

    exercise: str
    key: str
    scheme: Scheme
    proposals: tuple[ProposedSet, ...]
    count_source: SetCountSource = SetCountSource.PLAN
    plan_set_count: int | None = None
    history_set_count: int | None = None
    reason: str = ""
    warnings: tuple[str, ...] = ()

    def __len__(self) -> int:
        """Total rows to open, drop rows included."""
        return len(self.proposals)

    def working_count(self) -> int:
        """Prescribed sets, excluding the drop tails hanging off them."""
        return sum(1 for p in self.proposals if not p.is_drop())

    def drop_count(self) -> int:
        return sum(1 for p in self.proposals if p.is_drop())

    def has_drop(self) -> bool:
        return self.drop_count() > 0

    def is_known(self) -> bool:
        """False when no prescription was readable and the fallback row applies."""
        return self.scheme.is_known()

    def disagrees_with_history(self) -> bool:
        """True when plan and last session ask for different set counts.

        The point of surfacing it: whichever side the caller took, the other
        number is worth showing rather than quietly discarding.
        """
        if self.plan_set_count is None or self.history_set_count is None:
            return False
        return self.plan_set_count != self.history_set_count

    def label(self) -> str:
        """`"4 sets + 1 drop"`, `"3 sets"`, `"1 set"` — for a header line.

        Plurals are spelled here rather than through `views/shared_ui.plural`
        because that helper lives in the view layer and this module imports no
        views; the rule it encodes (never "1 sets") is what matters and is
        applied.
        """
        sets = self.working_count()
        text = f"{sets} set" if sets == 1 else f"{sets} sets"
        drops = self.drop_count()
        if drops:
            text += f" + {drops} drop" if drops == 1 else f" + {drops} drops"
        return text


# ─────────────────────────────────────────────────────────────────────────
# segment parsing — the detail `Scheme` flattens away
# ─────────────────────────────────────────────────────────────────────────


def _reps_of(segment: str) -> int | None:
    """`"12↓"` → 12, `"max"` → None. Never raises; unreadable is `None`."""
    text = (segment or "").replace(_DROP_MARK, "").strip()
    return int(text) if text.isdigit() else None


def _is_amrap(segment: str) -> bool:
    return (segment or "").replace(_DROP_MARK, "").strip().lower() in _AMRAP_WORDS


def _pyramid_segments(scheme: Scheme) -> tuple[str, ...]:
    """The comma-separated segments of a pyramid, *with* their drop tails.

    `Scheme.per_set` keeps only the head of each segment — `[4×10,10,8,6+12↓]`
    comes back as `(10, 10, 8, 6)` and the `12↓` is gone, surviving only as the
    `has_drop` flag. The tail is the whole prescription of a drop set, so it is
    re-read here from `Scheme.raw`, which `progression` documents as "the reps
    side exactly as data.py spells it" (already whitespace-stripped and with any
    wrapping parentheses removed).

    This is a *reader* of a public field, not a second parser: the heads are
    still `progression`'s, and `tests/test_session_plan.py` asserts segment heads
    equal `per_set` for every pyramid in the real routine, so a change to
    `_parse_reps_text` fails a test here rather than producing a different plan.
    """
    return tuple(s for s in (scheme.raw or "").split(",") if s)


# ─────────────────────────────────────────────────────────────────────────
# building the rows
# ─────────────────────────────────────────────────────────────────────────


class _Builder:
    """Accumulates rows while keeping `position` / `set_number` consistent."""

    def __init__(self) -> None:
        self.rows: list[ProposedSet] = []
        self.warnings: list[str] = []
        self._set_number = 0

    def working(
        self,
        set_type: SetType = SetType.NORMAL,
        low: int | None = None,
        high: int | None = None,
        label: str = "",
        note: str = "",
    ) -> int:
        self._set_number += 1
        self.rows.append(
            ProposedSet(
                position=len(self.rows) + 1,
                set_number=self._set_number,
                set_type=set_type,
                reps_low=low,
                reps_high=high,
                reps_label=label,
                note=note,
            )
        )
        return self._set_number

    def drop(self, of: int, reps: int | None, label: str, note: str = "") -> None:
        self.rows.append(
            ProposedSet(
                position=len(self.rows) + 1,
                set_number=None,
                set_type=SetType.DROPSET,
                reps_low=reps,
                reps_high=reps,
                reps_label=label,
                drop_of=of,
                note=note or f"Drop set off set {of}",
            )
        )

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)


def _build_range_or_fixed(b: _Builder, scheme: Scheme, count: int) -> None:
    low, high = scheme.reps_low, scheme.reps_high
    label = f"{low}-{high}" if low != high else f"{low}"
    last = 0
    for _ in range(count):
        last = b.working(low=low, high=high, label=label)
    if scheme.has_drop and last:
        # `[3×8↓]` — a drop marked on a scheme that names no tail. The row is
        # opened because the plan asked for a drop set; the target is left unset
        # because the plan never said how many reps it wants on it.
        b.drop(last, None, "", note="Drop set off the last set")
        b.warn("The scheme marks a drop set but names no reps for it.")


def _build_pyramid(b: _Builder, scheme: Scheme, count: int) -> None:
    segments = _pyramid_segments(scheme)
    if not segments:  # pragma: no cover - `per_set` non-empty implies segments
        b.warn("Pyramid scheme with no readable segments.")
        return

    if count > len(segments):
        # More sets than targets: repeat the last one. An ascending pyramid ends
        # at its working weight, so continuing at the final target is the only
        # reading that does not invent a number.
        b.warn(f"Scheme names {len(segments)} targets for {count} sets; repeating the last.")

    truncating = count < len(segments)
    for i in range(count):
        segment = segments[i] if i < len(segments) else segments[-1]
        parts = segment.split("+")
        head = parts[0]
        if _is_amrap(head):
            n = b.working(SetType.FAILURE, label=head.replace(_DROP_MARK, ""))
        else:
            reps = _reps_of(head)
            n = b.working(low=reps, high=reps, label=head.replace(_DROP_MARK, ""))
        _attach_drops(b, n, segment, parts[1:])

    if truncating:
        # The count was cut (LAST_SESSION with fewer sets than the pyramid
        # prescribes) and the drop the plan puts on the *final* set fell off the
        # end with it. Phase 6 is named "Drop Sets + Compound"; losing its only
        # drop set to an arithmetic truncation is the bug this module exists to
        # fix, so it is re-attached to whatever is now the last set.
        tail = segments[-1]
        emitted = segments[count - 1] if count else ""
        if _DROP_MARK in tail and _DROP_MARK not in emitted and b.rows:
            last_number = max((r.set_number for r in b.rows if r.set_number), default=0)
            _attach_drops(b, last_number, tail, tail.split("+")[1:])
            b.warn("Fewer sets than the plan prescribes; its drop set moved to the last one.")


def _attach_drops(b: _Builder, set_number: int, segment: str, extras: list[str]) -> None:
    """Emit the drop rows a pyramid segment carries after its working set."""
    for extra in extras:
        if _DROP_MARK not in segment:
            # `[4×10,8+8]` — a `+` inside a pyramid segment with no arrow. Not a
            # drop, not a documented notation, and not something to guess at: the
            # row is *not* opened, because an invented row can be filled in and
            # saved as history while a missing one costs one tap.
            b.warn(f"Ignored an unrecognised segment tail: {segment!r}.")
            continue
        b.drop(set_number, _reps_of(extra), extra.replace(_DROP_MARK, ""))


def _build_amrap(b: _Builder, scheme: Scheme, count: int) -> None:
    label = (scheme.raw or "max").replace(_DROP_MARK, "")
    last = 0
    for _ in range(count):
        # No target: there is no ceiling to hit, so double progression has
        # nothing to progress and a made-up number would be worse than none.
        last = b.working(SetType.FAILURE, label=label)
    if scheme.has_drop and last:
        b.drop(last, None, "", note="Drop set off the last set")


def _build_cluster(b: _Builder, scheme: Scheme, exercise: str, count: int) -> None:
    segments = scheme.segments or ()
    if not segments:  # pragma: no cover - CLUSTER implies at least two segments
        b.warn("Cluster scheme with no readable segments.")
        return

    if not is_drop_cluster(exercise):
        # A combination — or a cluster carrying no marker either way, which is
        # treated the same because that is the direction that cannot invent rows.
        label = "+".join(segments)
        note = f"{len(segments)} movements back to back"
        for _ in range(count):
            # One row per round. Expanding to one row per segment double-counts
            # muscle volume in `analytics.resolve_muscles` — see the module
            # docstring. The full label keeps the instruction on the row.
            b.working(label=label, note=note)
        return

    # Same movement, descending load: every segment is its own set, and every
    # segment after the first is a drop of the one before it.
    for _ in range(count):
        head = segments[0]
        if _is_amrap(head):
            n = b.working(SetType.FAILURE, label=head)
        else:
            reps = _reps_of(head)
            n = b.working(low=reps, high=reps, label=head)
        for extra in segments[1:]:
            b.drop(n, _reps_of(extra), extra)


# ─────────────────────────────────────────────────────────────────────────
# the entry point
# ─────────────────────────────────────────────────────────────────────────


def _phase_scheme(phase: Any) -> str:
    """`Phase.scheme` out of a phase, a bare scheme string, or nothing.

    Duck-typed like `set_types.rest_seconds_for_phase`, so `data.py` stays
    unimported and a test can pass a stub.
    """
    if phase is None:
        return ""
    if isinstance(phase, str):
        return phase
    return str(getattr(phase, "scheme", "") or "")


def history_set_count(last_session: Iterable[dict] | None) -> int | None:
    """Prescribed sets in a logged session: work, minus warm-ups, minus drops.

    Warm-ups go because they are not part of the prescription — the plan says
    `4×10`, the ramp up to it is `gym_tools.warmup_plan`'s business. Drops go
    because they are tails, not sets: counting them would make a `[4×…6+12↓]`
    session read as five prescribed sets and, under `LAST_SESSION`, quietly
    inflate the plan by one every time it ran.

    `None` when there is nothing to count, so the caller can tell "no history"
    from "a session with no work in it".
    """
    if last_session is None:
        return None
    rows = [s for s in working_sets(last_session) if set_type_of(s) is not SetType.DROPSET]
    return len(rows) or None


def plan_sets(
    exercise: str,
    phase: Any = None,
    *,
    last_session: Iterable[dict] | None = None,
    count_source: SetCountSource = SetCountSource.PLAN,
) -> SessionPlan:
    """The rows one exercise should open with. **Proposals, never logged sets.**

    `exercise` is the routine string exactly as `data.py` writes it, brackets and
    all — `"Barbell Bench Press [4×10,10,8,6+12↓]"`. `phase` is a `data.Phase`
    (duck-typed) or a bare scheme string; it supplies the prescription for phases
    1-4, where the exercises carry no bracket of their own and the set count
    lives only in `Phase.scheme` (`"3×8-10"`).

    `last_session` is the previous session's sets as `Storage.get_last_sets`
    returns them — plain dicts, warm-ups included, `"type"` optional. It is read
    for its *count* only. No weight from it, and none of its numbers, ever reach
    the result: filling a proposal in is how false history gets written.

    Never raises. An unreadable prescription comes back as one normal row with no
    target and `scheme.is_known()` False, which is exactly what the screen did
    before this module existed.
    """
    scheme = parse_scheme(exercise or "", _phase_scheme(phase))
    plan_count = scheme.sets if (scheme.is_known() and scheme.sets) else None
    hist_count = history_set_count(last_session)

    b = _Builder()

    if count_source is SetCountSource.LAST_SESSION and hist_count:
        count = hist_count
    else:
        count = plan_count or FALLBACK_ROWS
        if count_source is SetCountSource.LAST_SESSION:
            b.warn("No usable history; fell back to the plan's set count.")

    if not scheme.is_known():
        b.warn("No readable scheme; opening one set and assuming nothing.")
        b.working()
    elif scheme.kind in (SchemeKind.RANGE, SchemeKind.FIXED):
        _build_range_or_fixed(b, scheme, count)
    elif scheme.kind is SchemeKind.PYRAMID:
        _build_pyramid(b, scheme, count)
    elif scheme.kind is SchemeKind.AMRAP:
        _build_amrap(b, scheme, count)
    elif scheme.kind is SchemeKind.CLUSTER:
        _build_cluster(b, scheme, exercise or "", count)

    rows = b.rows
    if len(rows) > MAX_PROPOSED_ROWS:
        b.warn(f"Capped at {MAX_PROPOSED_ROWS} rows; the scheme asked for {len(rows)}.")
        rows = rows[:MAX_PROPOSED_ROWS]
    if not rows:  # pragma: no cover - every branch above emits at least one row
        rows = [ProposedSet(position=1, set_number=1, set_type=SetType.NORMAL)]

    return SessionPlan(
        exercise=exercise or "",
        key=exercise_key(exercise or ""),
        scheme=scheme,
        proposals=tuple(rows),
        count_source=count_source,
        plan_set_count=plan_count,
        history_set_count=hist_count,
        reason=_reason(scheme, count_source, plan_count, hist_count, rows),
        warnings=tuple(b.warnings),
    )


def _reason(
    scheme: Scheme,
    count_source: SetCountSource,
    plan_count: int | None,
    hist_count: int | None,
    rows: list[ProposedSet],
) -> str:
    """One English sentence quoting what the rows were read off.

    Same contract as `progression.Recommendation.reason`: it names the source in
    the words data.py uses, so a wrong plan can be spotted on the screen instead
    of being reverse-engineered from the row count.
    """
    if not scheme.is_known():
        return "No readable scheme — one set, nothing assumed."

    where = {
        "bracket": f"The exercise prescribes {scheme.label()}",
        "phase": f"The phase prescribes {scheme.label()}",
        "phase-star": f"The phase's starred scheme prescribes {scheme.label()}",
    }.get(scheme.source, f"Prescribed {scheme.label()}")

    working = sum(1 for r in rows if not r.is_drop())
    drops = len(rows) - working
    tail = f"{working} set" if working == 1 else f"{working} sets"
    if drops:
        tail += f" plus {drops} drop set" if drops == 1 else f" plus {drops} drop sets"

    if count_source is SetCountSource.LAST_SESSION and hist_count:
        return f"{where}; opening {tail} to match last session."
    if hist_count and plan_count and hist_count != plan_count:
        return f"{where} — opening {tail}. Last session had {hist_count}."
    return f"{where} — opening {tail}."


# ─────────────────────────────────────────────────────────────────────────
# the bridge to the draft
# ─────────────────────────────────────────────────────────────────────────


def to_draft_rows(plan: SessionPlan) -> list[dict[str, str]]:
    """`SessionPlan` → draft rows, in `workout_draft.blank_row()` shape.

    **Every row comes back structurally blank.** `weight`, `reps` and `rir` are
    the empty string; only `"type"` is set, and only because a drop row that is
    not labelled a drop row is just a row. `workout_draft.is_blank_row()` returns
    True for every one of them, which is what keeps a restored draft from turning
    a proposal into a number Alex is recorded as having lifted.

    That is the whole reason this function exists instead of the caller looping:
    there is no argument here that could fill a weight in, so the invariant holds
    by construction rather than by the caller remembering it.

    The rep target does **not** go in the `reps` box either. `reps` means "reps
    performed" everywhere in this app — in `entrenos.series`, in `analytics`, in
    what the coach writes — and a target sitting in that box is a lie the moment
    it is saved. Show the target next to the row (`ProposedSet.reps_label`) or as
    the field's `hint_text`; never as its value.
    """
    return [
        {**dict.fromkeys(DRAFT_ROW_FIELDS, ""), TYPE_KEY: one.set_type.value}
        for one in plan.proposals
    ]
