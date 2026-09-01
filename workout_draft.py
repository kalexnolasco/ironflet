"""The workout in progress, kept alive across everything that used to kill it.

Until now a session lived only in `WorkoutView`'s attributes (`self.sets`,
`self.ex_idx`, `self.completed`). Six ordinary things wiped it, none of them
with a warning: swiping to the next exercise, the Android back gesture, Escape,
switching tabs, reloading the page, and a restart of the `ironflet-web` unit.
Alex's words: *"al querer cambiar de ejercicio o moverlo por casualidad, al
volver a la rutina se hizo reset"*.

This module is the durable half. It has no Flet import and opens no database of
its own: plain data in, plain data out, same contract as `analytics.py` and
`set_types.py`, so it unit-tests without a running app.

Where it lives
--------------
One row of `preferencias`, under `DRAFT_PREF_KEY`, written through the public
`Storage.get_pref` / `Storage.set_pref`. Deliberately **not** a new table:

* the schema is duplicated by hand in `../agente/entrenador/modelos.py` and
  guarded by `test_modelos_espejo.py` — a thirteenth table here would fail that
  test and break the backup mapping being written alongside this;
* a draft is rubbish within hours by design. It has no business in a backup or
  in the training history. `EPHEMERAL_PREF_KEYS` exists so `backup.py` can skip
  it by name without importing anything heavy.

Because it is a single row there is exactly one draft at a time. That is the
truth of the domain: one person cannot be in two workouts at once.

The three decisions
-------------------
**When it is written.** Not per keystroke — `ft.TextField.on_change` fires per
character and that would be one UPDATE per digit. Not on exercise change either:
by then the data is already gone, which is the bug. So both, at two speeds:
every *structural* event (add/remove set, change type, move exercise, save,
select day, **pick a logging date**, app going to background) calls
`save(force=True)` and lands
immediately, while typing calls plain `save()`, which coalesces to at most one
write every `MIN_WRITE_INTERVAL_S`. A write is also skipped when the content did
not actually change, which matters because `refresh_current()` re-renders often.
Worst case exposure is a few seconds of typing, and the next tap of any kind
closes even that.

**When it expires.** `DRAFT_TTL_S` is six hours, measured from the last write.
Longer than any real session including the interruptions that motivated this —
a phone call, a queue for the rack, going for water, a nap on the sofa mid
log-in — and shorter than a night's sleep, so a draft can never come back the
next morning pretending yesterday's workout is still running. Sub-day, not
same-calendar-day: a session that starts at 22:30 and ends at 00:10 is one
session and must not die at midnight.

**What if the routine changed.** Alex can switch routines in Plan or edit one in
the editor between saving a draft and restoring it, so a draft is a set of
*pointers* that may have gone stale. Nothing here trusts an index:

* the routine id must be the active one (switching routines is deliberate — the
  old session is not resumed silently);
* the phase must still exist;
* the day is found again **by name**, so reordering days does not resume the
  wrong workout, and a deleted day discards the draft instead of landing on its
  neighbour;
* half-written rows are keyed **by exercise name**, not by position, so
  inserting or deleting an exercise moves nobody's weights onto another lift.
  Rows belonging to an exercise that is no longer in the day are dropped and
  reported in `WorkoutDraft.dropped`.

Everything degrades to "there is no draft". Nothing in this module raises at the
caller: a lost draft is an annoyance, an exception on start-up is a dead app.

One logging date per exercise
-----------------------------
Alex: *"hoy es miercoles, pero quiero poner mi entreno del lunes y martes"*. So
the date stopped being a property of the session and became a property of each
exercise: the bench press is Monday's, the pull-ups are Tuesday's, both typed on
Wednesday.

He was told, in as many words, that per-exercise dates are the easiest possible
way to file a set under the wrong day without noticing, and chose them anyway.
**That makes the mitigation the feature**, and this module owes the screen above
it everything it needs to make the day impossible to miss:

* `resolve_date()` returns a date *and where it came from* (`DateSource`), so a
  row can always say "Monday — this exercise" rather than showing a bare date
  that the reader has to attribute;
* `dates_in_use()` / `is_multi_day()` let the screen state, before anything is
  written, how many different days this session is about to touch.

**Why a map and not a field inside each entry.** A date lives in
`WorkoutDraft.dates`, keyed by exercise name, next to `pending` rather than
inside it. `pending` deliberately holds *only* exercises with something typed —
`with_rows` deletes an all-blank list, and `views/workout.py` never puts a
suggestion-only exercise in it — so a date carried inside an entry would
evaporate the instant it mattered most: picking Monday for an exercise *before*
typing its first set is exactly the order the user works in. A parallel map also
inherits the invariant that already protects the rows (keyed by name, never by
position) and is pruned by the same pass in `fit_to_routine`.

**The default is a value, not a `None` each caller re-invents.** An exercise
without its own date uses `session_date`; a draft without a session date uses
today. That chain is resolved in exactly one place, `resolve_date()`, which
never returns `None` and always names the source. Nothing else in the app is
allowed to reimplement it.

**The calendar-day rule, applied N times.** A date is stored with the day it was
chosen on (`LogDate.chosen_on`), and a choice is refused on any later calendar
day — the same rule `views/workout.py::_load_log_date` applies to the session
date, for the same reason: picking Monday on Wednesday is intent, and that
intent does not survive to Thursday. The stamp is **per date, not one for the
whole draft**: a single shared stamp would let today's pick silently revive
yesterday's forgotten one. Refused dates fall back to the default, which is
never a surprise, and are reported in `WorkoutDraft.stale_dates` so the screen
can say so instead of quietly moving a lift.

**No future dates**, same as the session date and for the same arithmetic
reason: `analytics.training_streak`, `Storage.get_week_stats` and
`program_week.last_workout_date` all ignore rows dated after today, so a session
filed forward would be written, reported as saved, and counted by nothing.
`MAX_BACKDATE_DAYS` bounds the other end.

Format versioning
-----------------
The payload carries `"v"`. A draft written by a version this build does not
understand is discarded whole, never half-read, and the row is wiped so the
garbage is not re-parsed on every launch. Bump `DRAFT_VERSION` on any change to
the payload shape.

`DRAFT_VERSION` is 2 (per-exercise dates). Version 1 is still **read**, which is
a deliberate exception to "discard whole" and the only one: v2 is v1 plus two
new keys, so a v1 payload is a v2 payload with no date ever recorded — which is
precisely what v1 meant. Nothing is invented, no field changed meaning, and the
worst case is the pre-existing behaviour (everything logs to the session date).
Discarding instead would throw away a live session for the single deploy that
lands mid-workout, and buy nothing. Any *other* version is still refused: an
unknown format is unknown, and guessing is what this rule exists to prevent.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from enum import Enum
from typing import Any

from data import Routine, active_routine
from exercises import exercise_key
from set_types import TYPE_KEY, SetType, parse_set_type

# ─────────────────────────────────────────────────────────────────────────
# knobs
# ─────────────────────────────────────────────────────────────────────────

#: The `preferencias` key holding the draft. Only key this module touches.
DRAFT_PREF_KEY = "workout_draft"

#: Preference keys that are scratch state, not user data. `backup.py` may skip
#: these when dumping `preferencias`; restoring one would resurrect a workout
#: that ended months ago.
# The log-date pick belongs here too: it is a property of the session in
# progress, not of the history. Restoring a backup must not drop someone
# else's "I am logging Saturday" onto this device.
#
# And `workout_notes` (views/workout.py NOTES_PREF), for the same reason and
# with a sharper edge. It holds notes **still being typed** in the session in
# progress; a note only becomes user data when the exercise is saved, and then
# it lives in `entrenos.nota`, which the backup carries properly. Leaving it out
# of this tuple would put half a sentence about a bench Alex was standing at in
# August into a restore performed in November — filed against whatever exercise
# he happened to be on then.
#
# Spelled as literals rather than imported from views/workout.py on purpose:
# this module must not import a view, and `backup.py` reads this tuple by name
# precisely so it never has to import Flet.
#
# The **per-exercise** dates add nothing to this tuple, and that is a property
# of the design rather than an omission: they ride inside the draft payload,
# under `DRAFT_PREF_KEY`, which is already the first entry. A fourth preference
# row would have had to be pruned by hand every time the routine changed, in a
# module that cannot see the routine — `fit_to_routine` does it for free.
EPHEMERAL_PREF_KEYS: tuple[str, ...] = (
    DRAFT_PREF_KEY,
    "workout_log_date",
    "workout_notes",
)

#: Payload format. Bump on any shape change; unknown versions are discarded.
DRAFT_VERSION = 2

#: Older payloads this build can still read, and what they are missing. Version
#: 1 predates per-exercise dates and is upgraded by reading no dates at all —
#: see "Format versioning" in the module docstring for why that is not a
#: violation of "never half-read". Nothing else is ever accepted here.
READABLE_VERSIONS: frozenset[int] = frozenset({1, DRAFT_VERSION})

#: How far back a logging date may reach, in days. The same number lives in
#: `views/workout.py` as `MAX_BACKDATE_DAYS`, where the picker validates and
#: explains before ever calling in here; this copy is the backstop that keeps a
#: hand-edited or half-migrated preference row from filing a session a year ago
#: (which would drag the inferred program start with it). Change one, change the
#: other — better still, have the view import this one.
MAX_BACKDATE_DAYS = 30

#: See the module docstring: longer than a session, shorter than a night.
DRAFT_TTL_S = 6 * 60 * 60

#: Typing coalesces to at most one write per this many seconds.
MIN_WRITE_INTERVAL_S = 3.0

#: A draft stamped in the future is a clock that moved (or a corrupt row). A few
#: minutes is ordinary NTP drift between the phone and the server; more than
#: that and the timestamp cannot be trusted to expire, so the draft is dropped.
FUTURE_SKEW_S = 300.0

#: Caps. The row is read on every start-up, so a pathological blob would be paid
#: for forever. Nobody logs 50 sets of one exercise or 40 exercises in a day.
MAX_PAYLOAD_CHARS = 256_000
MAX_ROWS_PER_EXERCISE = 50
MAX_PENDING_EXERCISES = 40
MAX_COMPLETED = 60
#: One date per exercise of the day, so the same ceiling as `pending`.
MAX_DATED_EXERCISES = MAX_PENDING_EXERCISES

#: A weight field holds "127.5", not an essay.
MAX_FIELD_CHARS = 12

#: The text fields of one draft row, in `views/workout.py` order.
ROW_FIELDS: tuple[str, ...] = ("weight", "reps", "rir")


# ─────────────────────────────────────────────────────────────────────────
# dates — which day each exercise is being filed under
# ─────────────────────────────────────────────────────────────────────────


class DateSource(str, Enum):
    """Where the date shown against an exercise actually came from.

    The whole risk of per-exercise dates is a date the user reads without
    attributing, so `resolve_date` never hands back a bare date: it says whether
    this exercise was dated on its own (`EXERCISE`), inherited the session's
    choice (`SESSION`), or is simply today because nobody chose anything
    (`TODAY`). A screen that renders the source cannot show "17 Aug" in a place
    where the reader assumes it means something else.

    A `str` enum so `.value` drops straight into a control key or a test
    parameter without a conversion nobody would remember to write.
    """

    EXERCISE = "exercise"
    SESSION = "session"
    TODAY = "today"


@dataclass(frozen=True)
class LogDate:
    """A chosen logging date, plus the calendar day the choice was made on.

    Both halves are load-bearing. `day` is what gets written to `entrenos`;
    `chosen_on` is what makes the choice expire by itself, because "I am logging
    Monday" is a statement about the day it was said on and cannot be adopted
    the following morning. Same two-part value the session date has carried in
    `views/workout.py::LOG_DATE_PREF` since back-dating shipped — one date, one
    stamp, no shared stamps (see the module docstring).
    """

    day: date
    chosen_on: date

    def is_current(self, today: date) -> bool:
        """Was this chosen on the calendar day that is still running?"""
        return self.chosen_on == today

    def in_window(self, today: date, max_back_days: int = MAX_BACKDATE_DAYS) -> bool:
        """Is `day` inside the range a session may legally be filed under?"""
        return today - timedelta(days=max_back_days) <= self.day <= today

    def to_payload(self) -> dict[str, str]:
        return {"date": self.day.isoformat(), "chosen_on": self.chosen_on.isoformat()}

    @classmethod
    def from_payload(cls, raw: Any) -> LogDate | None:
        """One stored date → a `LogDate`, or `None` for anything malformed.

        Validation of *meaning* (stale, future, too far back) is not done here:
        it needs to know what day it is, and it belongs where the answer can be
        reported to the user. See `decode_draft`.
        """
        if not isinstance(raw, dict):
            return None
        day = _as_date(raw.get("date"))
        chosen_on = _as_date(raw.get("chosen_on"))
        if day is None or chosen_on is None:
            return None
        return cls(day, chosen_on)


@dataclass(frozen=True)
class ResolvedDate:
    """The answer to "which day does this exercise go to, and why".

    Deliberately not a bare `date`: see `DateSource`.
    """

    day: date
    source: DateSource

    @property
    def is_explicit(self) -> bool:
        """Did somebody actually choose this, or is it just today?"""
        return self.source is not DateSource.TODAY

    def is_backdated(self, today: date | None = None) -> bool:
        """Is this exercise being written under a day that is not today?

        The one question the warning strip is built on, and the reason it is a
        method here rather than a `!=` retyped at each call site.
        """
        return self.day != (date.today() if today is None else today)


def _as_date(value: Any) -> date | None:
    """An ISO `YYYY-MM-DD` string → a `date`, or `None`. Never raises.

    Strings only. A JSON number is not a date, and interpreting one as an
    ordinal or an epoch would be a guess about a field whose whole point is not
    to be guessed at.
    """
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def clamp_log_date(
    day: date,
    chosen_on: date,
    *,
    max_back_days: int = MAX_BACKDATE_DAYS,
) -> date:
    """The date actually adoptable for `day`, clamped into the legal window.

    Mirrors `views/workout.py::_set_log_date`: the picker validates and explains
    first, so this is the backstop for programmatic callers and for the
    day-rollover corner where "today" moved under a value already held. Clamping
    rather than raising, because the caller is a tap during a workout and the
    honest fallback (the nearest legal day) is always visible on screen.
    """
    return min(max(day, chosen_on - timedelta(days=max_back_days)), chosen_on)


def _today_from(now: float | None) -> date:
    """The calendar day of an epoch timestamp, in local time.

    One clock for the whole module: `DraftStore` injects it, so a test can cross
    midnight without touching the system date. Anything unusable falls back to
    the real today — a broken clock must not make every date look stale.
    """
    if now is None:
        return date.today()
    try:
        return date.fromtimestamp(now)
    except (OverflowError, OSError, ValueError):
        return date.today()


# ─────────────────────────────────────────────────────────────────────────
# rows — the half-written set the user is looking at
# ─────────────────────────────────────────────────────────────────────────


def blank_row() -> dict[str, str]:
    """A fresh draft row.

    Shape contract with `views/workout.py::_blank_set`: every value is a `str`
    (it comes straight out of a `TextField`) and the type is the plain string
    that lands in the database, so `set_types.set_type_of` reads a draft row
    unchanged and `_parse_set` needs no special case.
    """
    return {"weight": "", "reps": "", "rir": "", TYPE_KEY: SetType.NORMAL.value}


def is_blank_row(row: Any) -> bool:
    """True when nothing was typed. The set type alone does not count as input.

    Used to decide what deserves persisting: an untouched row carries no
    information a fresh `blank_row()` would not give back.
    """
    if not isinstance(row, dict):
        return True
    return not any(str(row.get(f) or "").strip() for f in ROW_FIELDS)


def _text(value: Any) -> str:
    """Any JSON scalar → the string a `TextField` would have held.

    Numbers are accepted because a future writer (or a hand-fixed row) may store
    `60` instead of `"60"`; containers are not — there is no sane string for a
    list, and silently stringifying one would put `"['a']"` in the weight box.
    """
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        text = f"{value:g}"
    elif isinstance(value, str):
        text = value
    else:
        return ""
    return text[:MAX_FIELD_CHARS]


def normalize_row(raw: Any) -> dict[str, str] | None:
    """One stored row → a draft row, or `None` if it is not a row at all.

    Unknown keys are dropped rather than carried: unlike `entrenos.series`,
    which three programs write and where extra keys must survive, this payload
    has exactly one writer. `parse_set_type` never raises, so an unknown type
    degrades to normal — the same reading the rest of the app gives it.
    """
    if not isinstance(raw, dict):
        return None
    row = {f: _text(raw.get(f)) for f in ROW_FIELDS}
    row[TYPE_KEY] = parse_set_type(raw.get(TYPE_KEY)).value
    return row


def normalize_rows(raw: Any) -> list[dict[str, str]]:
    """A stored list of rows → clean rows, junk entries dropped."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw[:MAX_ROWS_PER_EXERCISE]:
        row = normalize_row(item)
        if row is not None:
            out.append(row)
    return out


def rows_from_last_sets(last_sets: Iterable[dict] | None) -> list[dict[str, str]] | None:
    """Last session's sets → draft rows, ready to be shown pre-filled.

    Optional convenience for the second half of the complaint ("siempre tienen
    que volver a poner los pesos"): the numbers were already on screen as grey
    `hint_text`, which is a placeholder — Alex could read them but still had to
    type them. Handing them back as real values makes repeating a session zero
    taps and beating it one edit.

    Warm-ups are kept: they are part of how the session was performed. RIR is
    only carried over when it was recorded. Returns `None` when there is no
    history, so the caller can tell "nothing to copy" from "an empty set".
    """
    rows: list[dict[str, str]] = []
    for one_set in list(last_sets or [])[:MAX_ROWS_PER_EXERCISE]:
        if not isinstance(one_set, dict):
            continue
        row = blank_row()
        row["weight"] = _text(one_set.get("weight"))
        row["reps"] = _text(one_set.get("reps"))
        if one_set.get("rir") is not None:
            row["rir"] = _text(one_set.get("rir"))
        row[TYPE_KEY] = parse_set_type(one_set.get(TYPE_KEY)).value
        rows.append(row)
    return rows or None


def _clean_completed(raw: Any) -> list[dict]:
    """The already-saved exercises of this session, sanitised.

    These rows are *already in `entrenos`* — losing them costs the summary
    screen, not the training log — so this is lenient: keep what is shaped
    right, drop the rest. Set values stay exactly as the database holds them
    (floats and ints, not strings): the finished screen renders them with
    `set_types`/`analytics`, which expect the stored shape.

    An optional `"date"` is carried through when it parses, and only then. Once
    an exercise is written its day is a fact in the database, not a choice that
    can still expire, so none of the freshness rules apply to it — but the
    summary has to be able to say "Bench Press → Monday, Pull-up → Tuesday",
    and with per-exercise dates a summary that cannot is a summary that hides
    the one thing worth checking before walking out of the gym.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw[:MAX_COMPLETED]:
        if not isinstance(item, dict):
            continue
        name = item.get("exercise")
        if not isinstance(name, str) or not name.strip():
            continue
        sets = item.get("sets")
        if not isinstance(sets, list):
            continue
        clean = [s for s in sets[:MAX_ROWS_PER_EXERCISE] if isinstance(s, dict)]
        entry: dict = {"exercise": name, "sets": clean}
        when = _as_date(item.get("date"))
        if when is not None:
            entry["date"] = when.isoformat()
        out.append(entry)
    return out


# ─────────────────────────────────────────────────────────────────────────
# the draft
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class WorkoutDraft:
    """A workout in progress, as much of it as is worth restoring.

    `day_name` and `exercise` are not decoration: they are how the draft is
    re-located after the routine was edited (see `fit_to_routine`). The indices
    are only a fallback for when the names no longer resolve.
    """

    routine_id: str
    phase_id: int
    day_idx: int
    day_name: str
    ex_idx: int
    exercise: str
    #: exercise key → its half-written rows. Keyed by name, never by position,
    #: so deleting exercise 2 does not shift exercise 3's weights onto it.
    pending: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    #: `[{"exercise": key, "sets": [...], "date": "<iso>"?}]` — already in
    #: `entrenos`. `"date"` is optional and only ever informational here.
    completed: list[dict] = field(default_factory=list)
    #: The day the session as a whole is filed under, when one was chosen.
    #: `None` means today — the default state, which leaves nothing behind to go
    #: stale, exactly as `views/workout.py::_log_date_chosen_on` records it.
    session_date: LogDate | None = None
    #: exercise key → the day *that exercise* is filed under. Only exercises the
    #: user dated on their own are in here; everything else inherits, and the
    #: inheritance is resolved once, in `resolve_date`.
    dates: dict[str, LogDate] = field(default_factory=dict)
    #: Epoch seconds when the session chronometer started, so it survives a
    #: reload instead of restarting at 00:00 mid-workout.
    started_at: float | None = None
    saved_at: float = 0.0
    #: Exercises whose rows were dropped because they are no longer in the day.
    #: Set by `fit_to_routine`, never persisted — the caller may want to say so.
    dropped: tuple[str, ...] = field(default=(), compare=False)
    #: Exercises whose stored date was **not** adopted: chosen on an earlier
    #: calendar day, outside the legal window, or unreadable. They fall back to
    #: the session date (or today), which is safe but is a change the user did
    #: not make, so it is reported rather than performed in silence. Set by
    #: `decode_draft`, never persisted.
    stale_dates: tuple[str, ...] = field(default=(), compare=False)
    #: Same, for the session date itself.
    session_date_stale: bool = field(default=False, compare=False)

    # ── dates ─────────────────────────────────────────────────
    def resolve_date(self, exercise: str, today: date | None = None) -> ResolvedDate:
        """Which day `exercise` is filed under, and where that came from.

        The only implementation of the default chain — exercise, then session,
        then today — and it never returns `None`. Every caller asking "what date
        is this set going to be written with" asks here, so there is exactly one
        answer and one place to be wrong.
        """
        own = self.dates.get(exercise)
        if own is not None:
            return ResolvedDate(own.day, DateSource.EXERCISE)
        if self.session_date is not None:
            return ResolvedDate(self.session_date.day, DateSource.SESSION)
        return ResolvedDate(date.today() if today is None else today, DateSource.TODAY)

    def date_for(self, exercise: str, today: date | None = None) -> date:
        """`resolve_date(...).day`, for the call sites that only write the row."""
        return self.resolve_date(exercise, today).day

    def is_backdated(self, exercise: str, today: date | None = None) -> bool:
        """Is `exercise` going to a day that is not today?"""
        return self.resolve_date(exercise, today).is_backdated(today)

    def with_date(self, exercise: str, day: date, *, chosen_on: date) -> WorkoutDraft:
        """Copy of this draft filing `exercise` under `day`.

        `chosen_on` is the calendar day the user is making the choice on — i.e.
        today at the moment of the tap. It is stored so the choice can expire on
        its own, and it doubles as the ceiling: `day` is clamped into
        `[chosen_on - MAX_BACKDATE_DAYS, chosen_on]`, so no future date can be
        recorded through this path any more than through the picker.

        A date equal to what the exercise would inherit anyway is *removed*
        rather than stored — but the comparison is against the **effective
        default** (the session date, or today), never against today alone.
        Storing "today" for one exercise of a session filed under Monday is a
        real, and dangerous, override: dropping it because it happens to equal
        today would silently move that lift back to Monday.
        """
        if not exercise:
            return self
        adopted = clamp_log_date(day, chosen_on)
        default = self.session_date.day if self.session_date is not None else chosen_on
        dates = dict(self.dates)
        if adopted == default:
            dates.pop(exercise, None)
        elif exercise in dates or len(dates) < MAX_DATED_EXERCISES:
            dates[exercise] = LogDate(adopted, chosen_on)
        else:
            # Beyond any real day's exercise count; keeping the payload bounded
            # matters more than the 41st date. The exercise still resolves to
            # the session default, which is on screen.
            return self
        return replace(self, dates=dates)

    def without_date(self, exercise: str) -> WorkoutDraft:
        """Copy with `exercise` back on the session default."""
        if exercise not in self.dates:
            return self
        dates = dict(self.dates)
        dates.pop(exercise, None)
        return replace(self, dates=dates)

    def with_session_date(self, day: date, *, chosen_on: date) -> WorkoutDraft:
        """Copy of this draft with the session default set to `day`.

        Same clamping and the same "choosing today is not a choice" rule as
        `with_date`. Per-exercise dates are deliberately left alone: they were
        each chosen against the exercise, not against the session, and wiping
        them here would undo work the user can no longer see.
        """
        adopted = clamp_log_date(day, chosen_on)
        session = None if adopted == chosen_on else LogDate(adopted, chosen_on)
        return replace(self, session_date=session)

    def without_dates(self) -> WorkoutDraft:
        """Copy with every date forgotten — everything logs to today again.

        What "the session ended" means for dates. `views/workout.py::_reset`
        already clears the draft outright; this is for the softer paths (the
        picker's "reset to today") that keep the session alive.
        """
        if self.session_date is None and not self.dates:
            return self
        return replace(self, session_date=None, dates={})

    def dated_exercises(self) -> tuple[str, ...]:
        """Exercises carrying a date of their own, sorted. Never `pending`'s."""
        return tuple(sorted(self.dates))

    def dates_in_use(
        self,
        exercises: Iterable[str] | None = None,
        today: date | None = None,
    ) -> tuple[date, ...]:
        """Every distinct day this session would write to, oldest first.

        Pass the day's exercise keys to get the honest answer for the whole
        workout — including the ones still on the default, which is the half a
        per-exercise picker makes easy to forget. With no argument it answers
        for what the draft actually holds.

        This is what lets the screen say "writing to 2 days" *before* the save,
        which is the cheapest place to catch a set filed under the wrong day.
        """
        if exercises is None:
            keys = set(self.dates) | set(self.pending)
        else:
            keys = {k for k in exercises if k}
        if not keys:
            # No exercises at all still writes somewhere: the session default.
            return (self.resolve_date("", today).day,)
        return tuple(sorted({self.resolve_date(k, today).day for k in keys}))

    def is_multi_day(
        self,
        exercises: Iterable[str] | None = None,
        today: date | None = None,
    ) -> bool:
        """Is this one session about to be written across more than one day?"""
        return len(self.dates_in_use(exercises, today)) > 1

    # ── content ───────────────────────────────────────────────
    def rows_for(self, exercise: str) -> list[dict[str, str]]:
        """The saved rows for `exercise`, or one fresh blank row.

        Always a copy: the caller assigns this to `self.sets` and then mutates
        it on every keystroke, and aliasing the draft's own list would make
        `save()` see no change and skip the write.
        """
        rows = [dict(r) for r in self.pending.get(exercise, [])]
        return rows or [blank_row()]

    def with_rows(self, exercise: str, rows: Iterable[dict[str, str]]) -> WorkoutDraft:
        """Copy of this draft remembering `rows` for `exercise`.

        An all-blank list removes the entry instead of storing it: that keeps
        the payload small, and it is also how a cleared field is persisted —
        on restore the exercise simply gets a fresh blank row back.
        """
        pending = dict(self.pending)
        rows = [dict(r) for r in rows or []]
        if exercise and any(not is_blank_row(r) for r in rows):
            pending[exercise] = rows[:MAX_ROWS_PER_EXERCISE]
        else:
            pending.pop(exercise, None)
        return replace(self, pending=pending)

    def is_empty(self) -> bool:
        """True when there is nothing a restore would give back.

        Being parked on exercise 4 *is* something, even with no rows typed —
        that is the "moverlo por casualidad" case. But a day just opened, with
        no input and nothing logged, must not resurface hours later as a
        "workout in progress" that never happened.

        A chosen date counts, for the same reason and more sharply. Picking
        Monday and *then* typing is the order the feature is used in, so a draft
        that holds only a date is a draft holding the one piece of state that,
        if lost, is lost silently: the sets would come back and be filed under
        today. Dates only ever exist here when they were explicitly chosen —
        picking today stores nothing — so this cannot resurrect an untouched
        day either.
        """
        if self.completed or self.ex_idx > 0:
            return False
        if self.session_date is not None or self.dates:
            return False
        return not any(any(not is_blank_row(r) for r in rows) for rows in self.pending.values())

    def age_s(self, now: float | None = None) -> float:
        return (time.time() if now is None else now) - self.saved_at

    # ── serialisation ─────────────────────────────────────────
    def to_payload(self) -> dict[str, Any]:
        """The dict that gets JSON-encoded into the preference row."""
        return {
            "v": DRAFT_VERSION,
            "saved_at": float(self.saved_at),
            "routine": self.routine_id,
            "phase": int(self.phase_id),
            "day_idx": int(self.day_idx),
            "day": self.day_name,
            "ex_idx": int(self.ex_idx),
            "exercise": self.exercise,
            "pending": {k: [dict(r) for r in v] for k, v in self.pending.items()},
            "completed": self.completed,
            "started_at": None if self.started_at is None else float(self.started_at),
            "session_date": None if self.session_date is None else self.session_date.to_payload(),
            "dates": {k: v.to_payload() for k, v in self.dates.items()},
        }


def _as_int(value: Any) -> int | None:
    """A JSON integer, or `None`. `True` is not 1 here.

    `json` decodes `true` to `bool`, and `bool` is an `int` subclass, so without
    this guard a payload saying `"phase": true` would train phase 1.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def encode_draft(draft: WorkoutDraft) -> str:
    """Draft → the string stored in the preference row."""
    return json.dumps(draft.to_payload(), ensure_ascii=True, separators=(",", ":"))


def _decode_dates(
    raw: Any,
    *,
    today: date,
    limit: int = MAX_DATED_EXERCISES,
) -> tuple[dict[str, LogDate], tuple[str, ...]]:
    """Stored date map → adopted dates, plus the exercises that lost theirs.

    Three ways a recorded date is refused, all of them ending in the same safe
    place (the exercise inherits the session default) and all of them reported:

    * chosen on an earlier calendar day — the rule this whole feature turns on;
    * outside `[today - MAX_BACKDATE_DAYS, today]`, which includes any future
      date, because a row that no metric counts is worse than a visible error;
    * unreadable, which only a hand-edited or truncated row can produce.

    Reported, not silent, because "your Monday pick expired" is a sentence the
    user can act on and a lift that quietly moved to today is not.
    """
    if not isinstance(raw, dict):
        return {}, ()
    out: dict[str, LogDate] = {}
    stale: list[str] = []
    for key, value in list(raw.items())[:limit]:
        if not isinstance(key, str) or not key:
            continue
        stamped = LogDate.from_payload(value)
        if stamped is None or not stamped.is_current(today) or not stamped.in_window(today):
            stale.append(key)
            continue
        out[key] = stamped
    return out, tuple(sorted(set(stale)))


def decode_draft(
    raw: Any,
    *,
    now: float | None = None,
    ttl_s: float = DRAFT_TTL_S,
    today: date | None = None,
) -> WorkoutDraft | None:
    """Stored string → draft, or `None` for anything that is not a live one.

    Returns `None` — never raises — for: an empty row, a blob too large to be
    ours, invalid or truncated JSON, a payload that is not an object, a version
    this build cannot read, missing or wrongly typed fields, and a draft older
    than `ttl_s` (or stamped implausibly far in the future).

    Structural damage discards the whole draft; damage to an individual row only
    drops that row. The line is deliberate: a payload whose `phase` is a string
    cannot be trusted at all, whereas one bad row among twelve is worth losing
    on its own. **Dates sit on the row side of that line by choice**: a date
    that cannot be adopted falls back to a default the screen is already
    showing, so discarding a whole session over one of them would cost far more
    than it protects.

    `today` defaults to the calendar day of `now`, so one injected clock decides
    both expiry and the day-rollover rule and a test can cross midnight without
    touching the system date.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    if len(raw) > MAX_PAYLOAD_CHARS:
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    # Version first: a draft from another format must never be half-read, and
    # its other fields mean nothing until this matches. Version 1 is the single
    # documented exception (see the module docstring) — it is read as a v2 with
    # no dates recorded, and its date keys, if a foreign writer put any there,
    # are not looked at.
    version = _as_int(obj.get("v"))
    if version not in READABLE_VERSIONS:
        return None

    routine_id = obj.get("routine")
    if not isinstance(routine_id, str) or not routine_id:
        return None
    phase_id = _as_int(obj.get("phase"))
    day_idx = _as_int(obj.get("day_idx"))
    ex_idx = _as_int(obj.get("ex_idx"))
    if phase_id is None or day_idx is None or ex_idx is None:
        return None
    if phase_id <= 0 or day_idx < 0 or ex_idx < 0:
        return None
    day_name = obj.get("day")
    exercise = obj.get("exercise")
    if not isinstance(day_name, str) or not isinstance(exercise, str):
        return None
    saved_at = _as_float(obj.get("saved_at"))
    if saved_at is None:
        return None
    started_at = None if obj.get("started_at") is None else _as_float(obj.get("started_at"))
    raw_pending = obj.get("pending")
    if not isinstance(raw_pending, dict):
        return None

    age = (time.time() if now is None else now) - saved_at
    if age > ttl_s or age < -FUTURE_SKEW_S:
        return None

    day_now = _today_from(now) if today is None else today
    if version == DRAFT_VERSION:
        session_date = LogDate.from_payload(obj.get("session_date"))
        session_stale = obj.get("session_date") is not None and (
            session_date is None
            or not session_date.is_current(day_now)
            or not session_date.in_window(day_now)
        )
        if session_stale:
            session_date = None
        dates, stale_dates = _decode_dates(obj.get("dates"), today=day_now)
    else:
        # Version 1: no dates were ever recorded, so nothing was lost and there
        # is nothing to report. Everything falls back to today, which is what
        # that build did.
        session_date, session_stale, dates, stale_dates = None, False, {}, ()

    pending: dict[str, list[dict[str, str]]] = {}
    for key, rows in list(raw_pending.items())[:MAX_PENDING_EXERCISES]:
        if not isinstance(key, str) or not key:
            continue
        clean = normalize_rows(rows)
        if any(not is_blank_row(r) for r in clean):
            pending[key] = clean

    return WorkoutDraft(
        routine_id=routine_id,
        phase_id=phase_id,
        day_idx=day_idx,
        day_name=day_name,
        ex_idx=ex_idx,
        exercise=exercise,
        pending=pending,
        completed=_clean_completed(obj.get("completed")),
        session_date=session_date,
        dates=dates,
        started_at=started_at,
        saved_at=saved_at,
        stale_dates=stale_dates,
        session_date_stale=session_stale,
    )


def fit_to_routine(
    draft: WorkoutDraft,
    routine: Routine | None = None,
    extra_keys: tuple[str, ...] = (),
) -> WorkoutDraft | None:
    """Re-point a draft at the routine as it is *now*, or reject it.

    A draft is a bundle of pointers into `data.ROUTINES`, and Alex can change
    routine in Plan or edit one in the editor between saving and restoring. This
    is the only place allowed to resolve them, and it resolves by **name** where
    a name exists:

    * a different active routine → no restore. Switching is deliberate; quietly
      resuming the previous routine's session would be the app arguing back.
    * a phase that no longer exists → no restore.
    * the day is looked up by name, so reordering days lands on the right one
      and a deleted day discards the draft instead of silently taking over its
      neighbour's slot.
    * the current exercise likewise; if it is gone, the stored index is clamped
      into range so the user lands somewhere valid rather than nowhere.
    * rows for exercises no longer in the day are dropped and listed in
      `dropped`, so nobody's bench press weights show up under a squat. Their
      dates go with them, in the same pass and by the same key: a date left
      behind would be a Monday attached to nothing, waiting to be inherited by
      whatever exercise is next given that name.

    `extra_keys` are the movements Alex added mid-session (`extras.py`). They
    are not in the routine and never will be — that is the whole point of an
    extra — so without them this function would do exactly what it promises
    above and **silently drop the rows he had just typed into one**. They count
    as part of the day for this pass only; the caller supplies them because
    this module reads no storage.

    Returns a new draft; the input is not mutated.
    """
    routine = active_routine() if routine is None else routine
    if draft.routine_id != routine.id:
        return None
    if not any(p.id == draft.phase_id for p in routine.phases):
        return None

    days = routine.days_for_phase(draft.phase_id)
    if not days:
        return None
    names = [d.name for d in days]
    if draft.day_name:
        if draft.day_name not in names:
            return None
        day_idx = names.index(draft.day_name)
    elif draft.day_idx < len(days):
        day_idx = draft.day_idx
    else:
        return None

    keys = [exercise_key(x) for x in days[day_idx].exercises]
    keys += [k for k in extra_keys if k and k not in keys]
    if not keys:
        return None
    if draft.exercise and draft.exercise in keys:
        ex_idx = keys.index(draft.exercise)
    else:
        # The exercise was removed or renamed. Keep the position — the rows for
        # whatever now sits there are that exercise's own, keyed by its name.
        ex_idx = min(draft.ex_idx, len(keys) - 1)

    known = set(keys)
    pending = {k: v for k, v in draft.pending.items() if k in known}
    dates = {k: v for k, v in draft.dates.items() if k in known}
    dropped = tuple(sorted((set(draft.pending) | set(draft.dates)) - known))
    return replace(
        draft,
        day_idx=day_idx,
        ex_idx=ex_idx,
        exercise=keys[ex_idx],
        pending=pending,
        dates=dates,
        dropped=dropped,
    )


# ─────────────────────────────────────────────────────────────────────────
# the store
# ─────────────────────────────────────────────────────────────────────────


class DraftStore:
    """Reads and writes the draft. One instance per `WorkoutView`.

    Owns the write policy (see the module docstring): coalesced writes while
    typing, immediate ones on `force=True`, and no write at all when nothing
    changed. Every method swallows storage errors — the database is on the other
    side of a network in web mode, and a workout must not stop because a write
    failed.

    `clock` is injected so the expiry rules are testable without sleeping.
    """

    def __init__(
        self,
        store: Any,
        *,
        key: str = DRAFT_PREF_KEY,
        ttl_s: float = DRAFT_TTL_S,
        min_interval_s: float = MIN_WRITE_INTERVAL_S,
        clock: Callable[[], float] = time.time,
    ):
        self._store = store
        self._key = key
        self.ttl_s = ttl_s
        self.min_interval_s = min_interval_s
        self._clock = clock
        #: Content of the last successful write, minus its timestamp.
        self._last_written: str | None = None
        self._last_write_at: float = float("-inf")

    # ── write ─────────────────────────────────────────────────
    def save(self, draft: WorkoutDraft, *, force: bool = False) -> bool:
        """Persist `draft`. Returns True only when a row was actually written.

        Call it on every change — it is cheap to call and decides for itself.
        `force=True` for anything the user perceives as an action (a set added,
        an exercise changed, **a logging date picked**, the app going to
        background); leave it off for keystrokes. A date is never a keystroke:
        coalescing one means a window in which the screen says Monday and the
        stored draft says today.
        """
        now = self._clock()
        if draft.is_empty():
            # Nothing to restore. Clearing rather than storing an empty draft is
            # what stops a "resume workout?" prompt for a workout that never
            # started — and it also handles the last row being deleted.
            self.clear()
            return False

        try:
            payload = draft.to_payload()
            payload["saved_at"] = now
            body = {k: v for k, v in payload.items() if k != "saved_at"}
            fingerprint = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        except (TypeError, ValueError):
            # Something non-serialisable, or a field that is not the type the
            # dataclass promises, reached the draft. Losing one write is bad;
            # taking the workout screen down with it is worse.
            return False

        # Unchanged content is skipped even when forced: the only thing a
        # rewrite would refresh is `saved_at`, and no real session sits idle for
        # six hours. `refresh_current()` re-renders constantly, so this check is
        # what keeps a rest between sets from costing a dozen UPDATEs.
        if fingerprint == self._last_written:
            return False
        if not force and (now - self._last_write_at) < self.min_interval_s:
            # Dropped, not queued: the next keystroke (or the next tap, which
            # forces) retries with fresher content anyway.
            return False
        if len(text) > MAX_PAYLOAD_CHARS:
            return False

        try:
            self._store.set_pref(self._key, text)
        except Exception:
            return False
        self._last_written = fingerprint
        self._last_write_at = now
        return True

    def flush(self, draft: WorkoutDraft) -> bool:
        """`save(force=True)`, named for the call sites that mean "now"."""
        return self.save(draft, force=True)

    def clear(self) -> None:
        """Forget the draft. Called when the session finishes or is abandoned.

        Stores an empty string instead of deleting the row: `Storage` exposes no
        `delete_pref`, and `get_pref` returning `""` reads as "no draft" anyway.
        """
        self._last_written = None
        self._last_write_at = float("-inf")
        with contextlib.suppress(Exception):
            self._store.set_pref(self._key, "")

    def _extra_keys(self) -> tuple[str, ...]:
        """Los ejercicios de hoy que la rutina no prescribe, como claves.

        Los que añadió a mano (`extras.py`) y los de la rutina de abdomen
        (`abdomen.py`), que son los dos casos de algo que está en la sesión y
        no en el día. Sin ellos, `fit_to_routine` tira sus series al restaurar
        — trampa 32.

        Vive aquí y no en `fit_to_routine` porque ese módulo no lee
        almacenamiento — es lo que le deja probarse con datos a mano. Falla a
        vacío: sin nada de esto el ajuste se comporta como siempre.
        """
        try:
            import abdomen
            import extras
            from exercises import exercise_key

            nombres = list(extras.de_hoy(self._store))
            if abdomen.activo(self._store):
                nombres += abdomen.de_hoy(self._store)
            return tuple(exercise_key(x) for x in nombres)
        except Exception:
            return ()

    # ── read ──────────────────────────────────────────────────
    def load(self, routine: Routine | None = None) -> WorkoutDraft | None:
        """The restorable draft, or `None`.

        Never raises. A draft that is expired, corrupt, of an unknown version,
        or that no longer fits the routine is not merely ignored — the row is
        wiped, so a bad blob is not re-parsed on every single launch.

        A draft that *is* restored may still have lost individual dates to the
        day-rollover rule: check `stale_dates` and `session_date_stale` and tell
        the user, because those exercises are now going to today.

        Call it from `on_show()` rather than from `__init__`: user routines are
        spliced into `data.ROUTINES` by `sync_user_routines()` at start-up, and
        a draft for one of them would not resolve before that has run.
        """
        try:
            raw = self._store.get_pref(self._key)
        except Exception:
            # Database unreachable. No draft is a correct answer here; the
            # session in memory carries on untouched.
            return None
        if not raw:
            return None

        draft = decode_draft(raw, now=self._clock(), ttl_s=self.ttl_s)
        if draft is None:
            self.clear()
            return None
        fitted = fit_to_routine(draft, routine, extra_keys=self._extra_keys())
        if fitted is None or fitted.is_empty():
            self.clear()
            return None
        return fitted
