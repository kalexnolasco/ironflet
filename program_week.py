"""Which week of the program today is — and therefore which phase and which
row of the weekly rotation apply.

The app knew the routine and it knew the phases, but it never knew *where in
the routine Alex was*. `views/plan.py` compensated with a manual "Distribution"
tab and three `WK 1 / WK 2 / WK 3` buttons that Alex had to press himself, and
`storage.weekly_session_minimum` says out loud what was missing: *"no routine
start date is stored, so a past calendar week cannot be mapped onto a phase"*.
This module stores that date and does the arithmetic. Nothing else changes.

Nothing here imports Flet. The arithmetic half is pure functions over plain
data — same contract as `analytics.py` and `set_types.py`, so it unit-tests
without a running app and the Telegram coach in `../agente/` can reuse it. The
last section is a thin adapter over `Storage.get_pref` / `set_pref`, marked as
such, so views never spell the preference key by hand.

The four decisions
------------------

**1. Where the start date comes from: both ways, in this order.**

*Explicit* wins. One row of `preferencias` under `PROGRAM_START_PREF_KEY`,
holding `"<routine_id>|<iso date>"`. It works from minute zero, which matters:
Alex's history is empty today, so an inference-only answer would be "I don't
know" on the very day he asked for this.

*Inferred* is the fallback: the earliest logged session is taken as week 1. It
costs him nothing and it will be right the moment he trains. It is reported as
`StartSource.FIRST_WORKOUT` and never silently promoted to fact, because it
carries two real errors — a session logged before the program properly began,
and the fact that `entrenos` has no routine column, so "first workout ever" is
the first workout under *any* routine.

*Unknown* is a first-class answer. `WeekStatus.UNKNOWN` with `week = None`.
Showing the wrong week is worse than showing none: it would send Alex to the
gym on the wrong day, training chest twice and never touching legs. Every
function here returns `None` rather than a plausible-looking number, and the
`status` field exists so a view cannot accidentally render a missing week as
week 0.

**Why the routine id is stored next to the date.** It is a guard, not a
lookup. Switching routines *is* starting a new program, so a start date saved
under `cambiatufisico` must not be reused to place Alex inside `upper-lower`.
On a mismatch the answer degrades to `StartSource.OTHER_ROUTINE` — unknown,
with the stale date carried along so a view can offer "use this date here too".
It also self-heals after a restore: `backup._write_prefs` remaps the `routine`
pref when it holds `user:<pk>` but knows nothing about this key, so an imported
start date pointing at a renumbered stored routine resolves to OTHER_ROUTINE —
an honest "I'm not sure any more" instead of a confident wrong week.

A value with no `|` (`"2026-08-03"`) is accepted and applies to whatever
routine is active. The app never writes that form; it exists so the date can be
set by hand with `psql`, or by the coach in `../agente/`, without knowing which
routine is selected.

**2. The week runs Monday to Sunday, anchored to the calendar, not to the
start date.** Program week 1 is the Mon-Sun week *containing* the start date,
and the counter ticks over every Monday. The rotation rows in `data.py` are
five weekday columns — `views/plan.py` labels them with `dates.day_name`,
Mon to Fri, with the Rest day sitting on Wednesday. A week anchored to the
start date would put column 0 on whatever weekday Alex began, so a Thursday
start would prescribe the Monday session on Thursday and the Rest day on
Saturday. The whole table stops meaning anything.

It also decides what a Sunday shows, which is the case that made the choice:
calendar-anchored, Sunday shows the week that is ending — the five sessions
just done — and the new distribution appears on Monday morning, when it is
needed. Start-anchored, a Thursday starter sees his week roll over on a
Wednesday evening, mid-rotation.

The cost, stated so nobody debugs it as a bug: **starting mid-week spends a
whole program week on the days that are left.** Begin on a Friday and phase 1
gets two weeks and one day. `restart_date()` returns the Monday of the current
week precisely so the "start / restart the program" button in a view cannot
create that situation by accident.

**3. Skipped weeks: the calendar advances, the program advances with it.**
Miss ten days and you are two weeks further into the program, not two weeks
behind. Three reasons:

* the rotation is a *calendar* device (see decision 2). Advancing it per
  completed session would slide the muscle-group columns off the weekdays;
* periodization is prescribed in time. Phase 2 is defined as "weeks 4-6", and
  the deload in week 10 is scheduled by the calendar, not earned by volume;
* a session-driven count is not stable. It would change retroactively whenever
  a row is added, deleted, or written by the Telegram coach, so the same day
  could be week 5 in the morning and week 4 in the evening.

But a calendar-only number lies in the other direction: after a three-month
break it says "week 15" and cheerfully prescribes drop sets that were never
worked up to. So the number never bends, and the honesty lives in a separate
signal — `weeks_idle` and `stale`, derived from the last logged session. A view
shows the week *and* "you've missed N weeks", and offers `restart_date()`.
Re-timing the program is Alex's decision, taken once, explicitly; it is not
something this module does behind his back on every render.

**4. Which phases the rotation applies to, without a magic tuple.**
`views/plan.py` used to gate the Distribution tab on `phase.id in (1, 2, 3)`
— correct for `cambiatufisico` and meaningless for anything else, including a
routine Alex builds in the editor. It calls `rotation_applies_to()` now, which
asks the structural
question instead: do the labels in the rotation rows name the day templates
this phase actually has? Phases 1-3 share `DAYS_PHASE_1_3`, whose days are
`Chest - Biceps` / `Back - Triceps` / `Shoulder - Leg`, and the rotation says
`Chest-Biceps` / `Back-Triceps + Abs` / ... — the same days modulo spacing and
the `+ Abs` add-on, which is what `normalize_day_label` strips. Phase 4's
`Day 1 Full Body` and phase 7's `W1-3: Chest-Biceps` match nothing, so those
phases get no rotation. Same answer as the hardcoded tuple, derived rather than
asserted, and it keeps working for a routine that does not exist yet.

Traps
-----

* **`Phase.weeks` is free text.** `"1-3"`, `"10"`, and whatever Alex types into
  the routine editor (`String(40)`, default `"1-4"`). `parse_week_range` reads
  the first and last integers it finds and nothing else is assumed. A phase it
  cannot parse contributes no weeks and can never be selected — the program
  then has `total_weeks == 0` and is never reported as finished, which is the
  safe direction.
* **`week` is a real number even when it exceeds the program.** Week 25 of a
  24-week routine reports `week=25`, `status=FINISHED`, `phase=None`. Do not
  clamp it: "week 25 of 24" is the sentence that tells Alex to pick a new
  block.
* **`preferencias.clave` is `String(60)`.** `program_start` plus nothing else;
  the routine id lives in the *value*, so a long stored-routine id cannot
  overflow the key.
* **`current_program_week()` runs one query.** Call it from `on_show()` and
  keep the result on `self.`; `build()` is a pure render and must not hit the
  database on every refresh.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from data import Phase, Routine, TrainingDay, active_routine

# ─────────────────────────────────────────────────────────────────────────
# knobs
# ─────────────────────────────────────────────────────────────────────────

#: The `preferencias` row holding the start date. The only key this module
#: touches. Durable user data, so it is *not* in `EPHEMERAL_PREF_KEYS`: a
#: backup must carry it, or a restored phone forgets where the program is.
PROGRAM_START_PREF_KEY = "program_start"

#: Separates the routine id from the ISO date inside that row. Neither half can
#: contain it — routine ids are `cambiatufisico`-style slugs or `user:<pk>`.
PREF_SEPARATOR = "|"

#: `weeks_idle` at or above this flips `ProgramWeek.stale`. Two means at least
#: one whole calendar week passed with nothing logged: one idle week is an
#: ordinary bad week (or a Monday, before this week's first session), two is a
#: break worth telling him about.
STALE_AFTER_WEEKS = 2

#: The rotation entry that prescribes no session. Compared normalised, so
#: casing and spacing do not matter.
REST_LABEL = "Rest"

_INTEGERS = re.compile(r"\d+")
_LABEL_NOISE = re.compile(r"[^a-z0-9]+")


# ─────────────────────────────────────────────────────────────────────────
# coercion
#
# Dates reach this module as `date`, as `datetime`, and as the ISO strings that
# `WorkoutEntry.date` and `export_all()` carry. None of them is assumed.
# ─────────────────────────────────────────────────────────────────────────


def _as_date(value: Any) -> date | None:
    """`date` / `datetime` / ISO string → `date`. None for anything else.

    `datetime` is checked first on purpose: it subclasses `date`, so the
    obvious `isinstance(value, date)` would return the datetime itself and leak
    a time component into arithmetic that is supposed to be day-granular.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _field(entry: Any, name: str, default: Any = None) -> Any:
    """Read `name` off a dataclass entry or a dict entry — same shapes as
    `analytics.py` accepts."""
    if isinstance(entry, dict):
        return entry.get(name, default)
    return getattr(entry, name, default)


# ─────────────────────────────────────────────────────────────────────────
# calendar
# ─────────────────────────────────────────────────────────────────────────


def monday_of(day: date) -> date:
    """Monday of the week `day` falls in. Weeks are ISO: Monday to Sunday.

    Same definition as `analytics._monday`, restated rather than imported: the
    two modules must agree, and a week that meant one thing in the streak and
    another in the program week would be a very quiet bug.
    """
    return day - timedelta(days=day.weekday())


def week_bounds(day: date) -> tuple[date, date]:
    """(Monday, Sunday) of the week `day` falls in."""
    start = monday_of(day)
    return start, start + timedelta(days=6)


def weeks_between(earlier: date, later: date) -> int:
    """Whole Mon-Sun weeks from one day's week to another's. Signed."""
    return (monday_of(later) - monday_of(earlier)).days // 7


def restart_date(today: date | None = None) -> date:
    """The date a "start / restart the program" button should store.

    The Monday of the current week, never today. See decision 2: a mid-week
    start burns a program week on the two or three days that are left, and the
    one place where that is avoidable for free is the button that creates it.
    """
    return monday_of(_as_date(today) or date.today())


# ─────────────────────────────────────────────────────────────────────────
# reading the routine
# ─────────────────────────────────────────────────────────────────────────


def parse_week_range(text: Any) -> tuple[int, int] | None:
    """`Phase.weeks` → (first week, last week), both 1-based and inclusive.

    The field is free text — `"1-3"`, `"10"`, `"19-24"` in `data.py`, and
    anything at all in a routine Alex writes in the editor. So: take the first
    and the last integer in the string and ignore the rest. `"10"` yields
    (10, 10); a reversed `"6-3"` is straightened rather than rejected, since
    the intent is unambiguous; a string with no digits yields None, and the
    caller must treat that phase as unplaceable rather than guess at it.
    """
    numbers = [int(n) for n in _INTEGERS.findall(str(text or ""))]
    if not numbers:
        return None
    first, last = numbers[0], numbers[-1]
    if last < first:
        first, last = last, first
    first = max(1, first)  # weeks are 1-based; a "0-3" typo starts at 1
    return first, max(first, last)


def phase_weeks(phase: Phase) -> tuple[int, int] | None:
    """(first, last) program week of a phase, or None if `weeks` is unreadable."""
    return parse_week_range(phase.weeks)


def total_program_weeks(routine: Routine | None = None) -> int:
    """Length of the routine in weeks — the last week any phase claims.

    0 when no phase declares a readable range. That is not "zero weeks long",
    it is "unknown length", and `program_week_for` treats it as such: a program
    of unknown length never finishes.
    """
    routine = routine or active_routine()
    ends = [r[1] for r in (parse_week_range(p.weeks) for p in routine.phases) if r]
    return max(ends, default=0)


def phase_for_week(week: int, routine: Routine | None = None) -> Phase | None:
    """The phase that owns program week `week`, or None.

    None covers three different situations and the caller usually cares which:
    the week is past the end of the program (`total_program_weeks`), it falls
    in a gap between two hand-written ranges, or no phase parses at all.
    """
    routine = routine or active_routine()
    for phase in routine.phases:
        span = parse_week_range(phase.weeks)
        if span and span[0] <= week <= span[1]:
            return phase
    return None


# ─────────────────────────────────────────────────────────────────────────
# the weekly rotation
# ─────────────────────────────────────────────────────────────────────────


def normalize_day_label(text: Any) -> str:
    """Comparison key for a rotation label or a `TrainingDay.name`.

    Drops everything after a `+` — the rotation writes `"Back-Triceps + Abs"`
    for the same session `data.py` calls `"Back - Triceps"`, the abs work being
    an add-on, not a different day — then lowercases and removes every
    non-alphanumeric character, so spacing around the hyphen stops mattering.

    Deliberately *not* fuzzy. Matching is by equality on this key, never by
    substring, or phase 7's `"W1-3: Chest-Biceps"` would answer to the
    rotation's `"Chest-Biceps"` and hand back the wrong exercises.
    """
    head = str(text or "").split("+")[0]
    return _LABEL_NOISE.sub("", head.lower())


def is_rest_label(label: Any) -> bool:
    """True for the rotation's own rest day (Wednesday in `cambiatufisico`).

    Prefix match, not equality: `"Rest"` is what `data.py` writes, but a
    routine written in the editor may say `"Rest / cardio"`, and that is still
    a day with no session on it.
    """
    return normalize_day_label(label).startswith(normalize_day_label(REST_LABEL))


def rotation_applies_to(phase: Phase, routine: Routine | None = None) -> bool:
    """Does this phase train the days the weekly rotation talks about?

    See decision 4. The rotation is a property of the *routine*, but it only
    describes some of its phases, and the test is structural: the sessions the
    rotation names must be exactly the day templates this phase has.

    Exactly, not "at least". A phase holding a fourth template the rotation
    never mentions is not described by the rotation — showing the row would
    quietly hide that fourth day, which is the same class of wrong answer as
    showing the wrong week.
    """
    routine = routine or active_routine()
    rotation = routine.week_rotation
    if not rotation:
        return False
    days = {normalize_day_label(d.name) for d in routine.days_for_phase(phase.id)}
    days.discard("")
    labels = {
        normalize_day_label(label) for row in rotation for label in row if not is_rest_label(label)
    }
    labels.discard("")
    return bool(labels) and labels == days


def rotation_index_for_week(week: int, routine: Routine | None = None) -> int | None:
    """Which row of `week_rotation` program week `week` uses. 0-based.

    Anchored to the *program*, not to the phase. For `cambiatufisico` the two
    agree — three rows, phases of three weeks, so every phase happens to open
    on row 0 — and the tie is broken towards the program because a phase-
    anchored cycle repeats a row across any boundary whose phase length is not
    a multiple of the rotation (a 4-week phase would end on row 0 and the next
    phase would open on row 0 again, giving Alex the same Monday twice).

    Only the row number: whether the row *applies* to the week's phase is
    `rotation_applies_to`, and `program_week_for` checks both.
    """
    routine = routine or active_routine()
    rotation = routine.week_rotation
    if not rotation or week < 1:
        return None
    return (week - 1) % len(rotation)


def training_day_for_label(
    label: Any, phase: Phase | None, routine: Routine | None = None
) -> TrainingDay | None:
    """Turn a rotation label into the `TrainingDay` it prescribes.

    This is what makes the distribution actionable instead of decorative: the
    view can go straight from "today is Back-Triceps + Abs" to the seven
    exercises. None for the rest day, and None when the label names nothing in
    this phase — which is the answer that keeps a mismatched rotation from
    silently opening a neighbouring day's workout.
    """
    routine = routine or active_routine()
    if phase is None or is_rest_label(label):
        return None
    key = normalize_day_label(label)
    if not key:
        return None
    for day in routine.days_for_phase(phase.id):
        if normalize_day_label(day.name) == key:
            return day
    return None


# ─────────────────────────────────────────────────────────────────────────
# the start date
# ─────────────────────────────────────────────────────────────────────────


class StartSource(str, Enum):
    """Where the start date came from — and therefore how much to trust it.

    `str` mixin so the value can be compared to a plain string and logged
    without ceremony, same as `set_types.SetType`.
    """

    #: Alex told us. The only source that is a fact.
    PREF = "pref"
    #: Guessed from the earliest logged session. Right often, not always.
    FIRST_WORKOUT = "first_workout"
    #: A date is stored, but under a different routine. Treated as unknown.
    OTHER_ROUTINE = "other_routine"
    #: Nothing stored and nothing logged.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProgramStart:
    """The answer to "when did this program begin?", provenance included."""

    day: date | None
    source: StartSource
    #: Routine the stored date was saved under, when there was one. Only
    #: interesting for OTHER_ROUTINE, where a view may offer to adopt it.
    stored_routine_id: str | None = None

    @property
    def known(self) -> bool:
        """Is there a date we are willing to compute a week from?

        False for OTHER_ROUTINE even though `day` is set: the date is real, it
        just does not describe the routine being asked about.
        """
        return self.day is not None and self.source in (
            StartSource.PREF,
            StartSource.FIRST_WORKOUT,
        )

    @property
    def certain(self) -> bool:
        """True only when Alex set the date himself. Views should qualify
        anything derived from an uncertain start ("assuming you started …")."""
        return self.source is StartSource.PREF


def encode_program_start(day: date, routine: Routine | None = None) -> str:
    """Build the preference value: `"<routine_id>|<iso date>"`."""
    routine = routine or active_routine()
    return f"{routine.id}{PREF_SEPARATOR}{day.isoformat()}"


def decode_program_start(raw: Any) -> tuple[str | None, date | None]:
    """Preference value → (routine id or None, date or None).

    Tolerates the bare-date form written by hand outside the app (see the
    module docstring), and returns `(None, None)` for anything unreadable —
    garbage is treated exactly like an empty row, because a stored value we
    cannot parse is not evidence of anything.
    """
    text = str(raw or "").strip()
    if not text:
        return None, None
    routine_id, _, tail = text.rpartition(PREF_SEPARATOR)
    return (routine_id.strip() or None), _as_date(tail.strip())


def first_workout_date(entries: Iterable[Any]) -> date | None:
    """Earliest date in a history. None for an empty one."""
    days = [d for d in (_as_date(_field(e, "date")) for e in entries) if d]
    return min(days, default=None)


def last_workout_date(entries: Iterable[Any], *, today: date | None = None) -> date | None:
    """Most recent date in a history, ignoring future-dated rows.

    Future rows are excluded for the same reason `analytics.training_streak`
    excludes them: a session dated next Tuesday has not happened, and letting
    it count would silently reset the idle counter.
    """
    limit = _as_date(today) or date.today()
    days = [d for d in (_as_date(_field(e, "date")) for e in entries) if d and d <= limit]
    return max(days, default=None)


def resolve_program_start(
    pref_value: Any,
    *,
    first_workout: Any = None,
    routine: Routine | None = None,
) -> ProgramStart:
    """Decide the start date from the stored preference and the history.

    Explicit beats inferred beats nothing, and a date stored under another
    routine beats both by refusing to answer — see decision 1. Pure: the
    caller supplies both inputs.
    """
    routine = routine or active_routine()
    stored_id, day = decode_program_start(pref_value)
    if day is not None:
        if stored_id is None or stored_id == routine.id:
            return ProgramStart(day, StartSource.PREF, stored_id)
        return ProgramStart(day, StartSource.OTHER_ROUTINE, stored_id)

    inferred = _as_date(first_workout)
    if inferred is not None:
        return ProgramStart(inferred, StartSource.FIRST_WORKOUT)
    return ProgramStart(None, StartSource.UNKNOWN)


def _coerce_start(value: Any) -> ProgramStart:
    """Accept a `ProgramStart`, a bare date, or nothing.

    A caller handing over a raw date is asserting it, so it is recorded as
    PREF. Convenient in tests and for a view that already knows the date.
    """
    if isinstance(value, ProgramStart):
        return value
    day = _as_date(value)
    if day is None:
        return ProgramStart(None, StartSource.UNKNOWN)
    return ProgramStart(day, StartSource.PREF)


# ─────────────────────────────────────────────────────────────────────────
# the answer
# ─────────────────────────────────────────────────────────────────────────


class WeekStatus(str, Enum):
    """Why `ProgramWeek.week` is or is not a number.

    Views must branch on this rather than on `week is None`: UNKNOWN and
    SCHEDULED both have no week, and they need opposite copy — "tell me when
    you started" versus "starts on Monday".
    """

    #: No usable start date. Ask for one; show no week.
    UNKNOWN = "unknown"
    #: The start date is in a future week. The program has not begun.
    SCHEDULED = "scheduled"
    #: Normal case.
    ACTIVE = "active"
    #: Past the last week any phase claims.
    FINISHED = "finished"


@dataclass(frozen=True)
class ProgramWeek:
    """Where today sits in the program. The whole point of this module.

    Everything is a snapshot for one `today`; nothing recomputes itself. Build
    it in `on_show()`, hold it on the view, render from it in `build()`.
    """

    status: WeekStatus
    start: ProgramStart
    routine_id: str
    total_weeks: int
    #: The day this snapshot was taken for.
    today: date | None = None
    #: 1-based program week. None unless status is ACTIVE or FINISHED. May
    #: exceed `total_weeks` — that is what FINISHED means.
    week: int | None = None
    #: Monday and Sunday of that week.
    week_start: date | None = None
    week_end: date | None = None
    #: The phase this week belongs to, or None (finished, gap, unparseable).
    phase: Phase | None = None
    #: 1-based position inside the phase — phase 7 of `cambiatufisico` splits
    #: its own days into "W1-3" and "W4-6", and this is how a view picks.
    week_in_phase: int | None = None
    #: Length of that phase in weeks.
    phase_length: int | None = None
    #: 0-based row of `routine.week_rotation`, when the rotation applies to
    #: this phase. None otherwise — including for the three routines that have
    #: no rotation at all.
    rotation_index: int | None = None
    #: That row, one label per weekday starting Monday.
    rotation: tuple[str, ...] | None = None
    #: Whole calendar weeks since the last logged session. None when the
    #: history is empty or was not supplied.
    weeks_idle: int | None = None

    @property
    def known(self) -> bool:
        """Is there a week number to show?"""
        return self.week is not None

    @property
    def has_rotation(self) -> bool:
        return self.rotation is not None

    @property
    def weeks_left_in_phase(self) -> int | None:
        """Weeks remaining after this one, 0 on the last week of the phase."""
        if self.week_in_phase is None or self.phase_length is None:
            return None
        return max(0, self.phase_length - self.week_in_phase)

    @property
    def stale(self) -> bool:
        """Has enough time passed with no training that the week number, while
        arithmetically right, is misleading? See decision 3."""
        return self.weeks_idle is not None and self.weeks_idle >= STALE_AFTER_WEEKS

    def focus_for(self, weekday: int) -> str | None:
        """The rotation label for a weekday, Monday = 0.

        `"Rest"` comes back as itself — the plan's own rest day is information.
        None means the rotation says nothing about that day: no rotation, or a
        weekend, since the rows only cover Monday to Friday.
        """
        if self.rotation is None or not 0 <= weekday < len(self.rotation):
            return None
        return self.rotation[weekday]

    @property
    def today_focus(self) -> str | None:
        """What the rotation prescribes for `self.today`."""
        if self.today is None:
            return None
        return self.focus_for(self.today.weekday())


def program_week_for(
    start: ProgramStart | date | str | None,
    *,
    routine: Routine | None = None,
    today: date | None = None,
    last_workout: Any = None,
) -> ProgramWeek:
    """Place a day inside a program. The pure core; everything else feeds it.

    `start` accepts a resolved `ProgramStart`, a bare date (taken as asserted)
    or None. `last_workout` is optional and only drives `weeks_idle` / `stale`
    — omit it and those stay silent rather than reading as "trained today".
    """
    routine = routine or active_routine()
    today = _as_date(today) or date.today()
    start = _coerce_start(start)
    total = total_program_weeks(routine)

    last = _as_date(last_workout)
    idle = weeks_between(last, today) if last else None

    common: dict[str, Any] = {
        "start": start,
        "routine_id": routine.id,
        "total_weeks": total,
        "today": today,
        "weeks_idle": idle,
    }

    if not start.known:
        return ProgramWeek(status=WeekStatus.UNKNOWN, **common)

    assert start.day is not None  # implied by .known; spelled out for type readers
    week = weeks_between(start.day, today) + 1
    if week < 1:
        # Start date sits in a later week: Alex has scheduled the program.
        return ProgramWeek(status=WeekStatus.SCHEDULED, **common)

    week_start, week_end = week_bounds(today)
    common |= {"week": week, "week_start": week_start, "week_end": week_end}

    # `total == 0` means no phase declared a readable range, so the routine has
    # no known length and cannot be over. Reporting FINISHED there would hide a
    # half-built custom routine behind a "program complete" screen.
    if total and week > total:
        return ProgramWeek(status=WeekStatus.FINISHED, **common)

    phase = phase_for_week(week, routine)
    if phase is None:
        return ProgramWeek(status=WeekStatus.ACTIVE, **common)

    span = parse_week_range(phase.weeks)
    assert span is not None  # phase_for_week only returns phases whose range parsed
    first, last_week = span
    common |= {
        "phase": phase,
        "week_in_phase": week - first + 1,
        "phase_length": last_week - first + 1,
    }

    if rotation_applies_to(phase, routine):
        index = rotation_index_for_week(week, routine)
        if index is not None:
            rotation = routine.week_rotation or []
            common |= {"rotation_index": index, "rotation": tuple(rotation[index])}

    return ProgramWeek(status=WeekStatus.ACTIVE, **common)


# ─────────────────────────────────────────────────────────────────────────
# store adapter
#
# The only impure part of the file: four functions that read and write the one
# preference row. They exist so no view spells `PROGRAM_START_PREF_KEY` or the
# `"<routine>|<date>"` encoding by hand — the same reason `workout_draft.py`
# ends in `DraftStore`. `store` is duck-typed on `Storage.get_pref` /
# `set_pref` / `get_all`, so a dict-backed fake is enough to test with.
# ─────────────────────────────────────────────────────────────────────────


def load_program_start(
    store: Any,
    *,
    routine: Routine | None = None,
    entries: Iterable[Any] | None = None,
) -> ProgramStart:
    """Read the stored start date, falling back to the history.

    The history is only scanned when there is nothing stored, so the common
    path is a single-row lookup. Pass `entries` if you already hold them.
    """
    routine = routine or active_routine()
    raw = store.get_pref(PROGRAM_START_PREF_KEY)
    _, stored_day = decode_program_start(raw)

    inferred = None
    if stored_day is None:
        rows = entries if entries is not None else store.get_all()
        inferred = first_workout_date(rows)

    return resolve_program_start(raw, first_workout=inferred, routine=routine)


def current_program_week(
    store: Any,
    *,
    routine: Routine | None = None,
    today: date | None = None,
    entries: Iterable[Any] | None = None,
) -> ProgramWeek:
    """Where the program is today. The one call most views need.

    Reads the history once — for the inferred start date and for `weeks_idle`
    — so hand it `entries` if you already have them, and call it from
    `on_show()` rather than from `build()`.
    """
    routine = routine or active_routine()
    today = _as_date(today) or date.today()
    rows = list(entries) if entries is not None else store.get_all()
    start = load_program_start(store, routine=routine, entries=rows)
    return program_week_for(
        start,
        routine=routine,
        today=today,
        last_workout=last_workout_date(rows, today=today),
    )


def set_program_start(store: Any, day: date | str, *, routine: Routine | None = None) -> date:
    """Pin the start date for a routine. Returns the date actually stored.

    The literal day is stored, not its Monday: if Alex says he began on a
    Wednesday, that is the truth, and the Monday anchoring belongs to the
    arithmetic (decision 2). A view offering "start the program now" should
    pass `restart_date()` instead of `date.today()`.
    """
    routine = routine or active_routine()
    parsed = _as_date(day)
    if parsed is None:
        raise ValueError(f"not a date: {day!r}")
    store.set_pref(PROGRAM_START_PREF_KEY, encode_program_start(parsed, routine))
    return parsed


def clear_program_start(store: Any) -> None:
    """Forget the stored start date.

    Writes an empty string rather than deleting the row: `Storage` has no
    `delete_pref`, and `decode_program_start("")` already reads as "nothing
    stored" — the same trick `workout_draft.DraftStore.clear` uses.
    """
    store.set_pref(PROGRAM_START_PREF_KEY, "")


# ─────────────────────────────────────────────────────────────────────────
# view-facing API
#
# The three names `views/plan.py` imports. They are thin, and they exist as
# names rather than as "call the other one and check two fields" because the
# checks are exactly where a screen would get it wrong:
#
# * `current_week` collapses "no start date" and "starts next week" into a
#   single `None`, so a view cannot render week 0 by forgetting a branch;
# * `week_rotation_for` returns a row only when that row genuinely describes
#   the current phase, so a view cannot put a real session name on the wrong
#   weekday.
#
# Neither reads the training history unless the start date has to be inferred
# from it, so they are cheap enough to survive a `refresh_current()` storm.
# They also do not fill in `weeks_idle`, because that *does* cost a scan — use
# `current_program_week()` for the staleness signal.
# ─────────────────────────────────────────────────────────────────────────


def current_week(
    store: Any,
    *,
    routine: Routine | None = None,
    today: date | None = None,
    entries: Iterable[Any] | None = None,
) -> ProgramWeek | None:
    """The week the program is on, or **None when the app cannot tell**.

    None covers every case where there is no honest week number: no start date
    stored and no session logged, a date saved under a different routine, and a
    start date that has not arrived yet. A finished program is *not* None — it
    comes back with `week` set and `phase` None, because "week 25 of 24" is a
    real answer and the screen has something to say about it.
    """
    result = program_week_for(
        load_program_start(store, routine=routine, entries=entries),
        routine=routine,
        today=today,
    )
    return result if result.known else None


def week_rotation_for(
    store: Any,
    *,
    routine: Routine | None = None,
    today: date | None = None,
    entries: Iterable[Any] | None = None,
) -> list[str] | None:
    """This week's row of the rotation, Monday first. None when there is none.

    Three different situations collapse into that None and none of them is an
    error: the week is unknown, the routine has no rotation at all (three of
    the four shipped ones), or the current phase is not one the rotation
    describes. A caller that wants to tell them apart should read
    `current_week(store).rotation` and the surrounding fields instead.
    """
    week = current_week(store, routine=routine, today=today, entries=entries)
    if week is None or week.rotation is None:
        return None
    return list(week.rotation)


def set_start_date(store: Any, day: date | str, *, routine: Routine | None = None) -> date:
    """Record when the current routine began. Alias of `set_program_start`.

    Named for the caller: `views/plan.py` asks Alex for "the routine start
    date", and the dialog should not have to know the value is stored as a
    program-start preference keyed by routine id.
    """
    return set_program_start(store, day, routine=routine)
