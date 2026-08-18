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
select day, app going to background) calls `save(force=True)` and lands
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

Format versioning
-----------------
The payload carries `"v"`. A draft written by another version is discarded
whole, never half-read, and the row is wiped so the garbage is not re-parsed on
every launch. Bump `DRAFT_VERSION` on any change to the payload shape.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
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
EPHEMERAL_PREF_KEYS: tuple[str, ...] = (DRAFT_PREF_KEY, "workout_log_date")

#: Payload format. Bump on any shape change; older drafts are then discarded.
DRAFT_VERSION = 1

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

#: A weight field holds "127.5", not an essay.
MAX_FIELD_CHARS = 12

#: The text fields of one draft row, in `views/workout.py` order.
ROW_FIELDS: tuple[str, ...] = ("weight", "reps", "rir")


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
        out.append({"exercise": name, "sets": clean})
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
    #: `[{"exercise": key, "sets": [...]}]` — already written to `entrenos`.
    completed: list[dict] = field(default_factory=list)
    #: Epoch seconds when the session chronometer started, so it survives a
    #: reload instead of restarting at 00:00 mid-workout.
    started_at: float | None = None
    saved_at: float = 0.0
    #: Exercises whose rows were dropped because they are no longer in the day.
    #: Set by `fit_to_routine`, never persisted — the caller may want to say so.
    dropped: tuple[str, ...] = field(default=(), compare=False)

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
        """
        if self.completed or self.ex_idx > 0:
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


def decode_draft(
    raw: Any,
    *,
    now: float | None = None,
    ttl_s: float = DRAFT_TTL_S,
) -> WorkoutDraft | None:
    """Stored string → draft, or `None` for anything that is not a live one.

    Returns `None` — never raises — for: an empty row, a blob too large to be
    ours, invalid or truncated JSON, a payload that is not an object, a version
    this build does not write, missing or wrongly typed fields, and a draft
    older than `ttl_s` (or stamped implausibly far in the future).

    Structural damage discards the whole draft; damage to an individual row only
    drops that row. The line is deliberate: a payload whose `phase` is a string
    cannot be trusted at all, whereas one bad row among twelve is worth losing
    on its own.
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
    # its other fields mean nothing until this matches.
    if _as_int(obj.get("v")) != DRAFT_VERSION:
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
        started_at=started_at,
        saved_at=saved_at,
    )


def fit_to_routine(draft: WorkoutDraft, routine: Routine | None = None) -> WorkoutDraft | None:
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
      `dropped`, so nobody's bench press weights show up under a squat.

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
    dropped = tuple(sorted(set(draft.pending) - known))
    return replace(
        draft,
        day_idx=day_idx,
        ex_idx=ex_idx,
        exercise=keys[ex_idx],
        pending=pending,
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
        an exercise changed, the app going to background); leave it off for
        keystrokes.
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

    # ── read ──────────────────────────────────────────────────
    def load(self, routine: Routine | None = None) -> WorkoutDraft | None:
        """The restorable draft, or `None`.

        Never raises. A draft that is expired, corrupt, of an unknown version,
        or that no longer fits the routine is not merely ignored — the row is
        wiped, so a bad blob is not re-parsed on every single launch.

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
        fitted = fit_to_routine(draft, routine)
        if fitted is None or fitted.is_empty():
            self.clear()
            return None
        return fitted
