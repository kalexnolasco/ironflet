"""User-created routines, stored in the database.

data.py ships eight routines as ~1400 lines of constants. The app could read
them and Alex could never write one. This module is the missing half: four
tables, CRUD on top of them, and — the part that actually matters — a way to
hand those rows to the views without the views learning anything new.

## How code routines and database routines end up interchangeable

The views call `data.active_routine()` and then read `.phases`, `.description`,
`.week_rotation` and `.days_for_phase(id)`; workout.py also reads `phase.color`
and `phase.scheme`, plan.py reads `phase.weeks`, `.subtitle`, `.rest`, `.notes`,
`.freq`. Wrapping the rows in a lookalike class would mean growing a new
attribute every time some view reads one more field, and finding out it is
missing at render time.

So `_materialize()` does not wrap: it *builds the real dataclasses*,
`data.Routine`, `data.Phase` and `data.TrainingDay`, straight from the rows. A
stored routine literally is a `Routine`, so "same interface" holds by
construction and nothing downstream can tell the two apart.

`sync_user_routines()` then splices them into `data.ROUTINES`, and that is why
`set_active_routine()` / `active_routine()` keep working untouched — the former
only accepts ids it can find in that list. The splice is a slice assignment on
purpose: views/plan.py does `from data import ROUTINES` and holds a reference to
that list object, so rebinding `data.ROUTINES` would leave it rendering the old
one. Built-ins keep their order and their ids; stored routines get `user:<pk>`,
a namespace no constant can collide with, and `is_user_routine()` reads it back.

## The exercise-name rule

An exercise row keeps the canonical `exercise_key()` name and its set scheme in
separate columns, and renders back as `"Squat [4×8-10]"` — the shape data.py
uses. Both halves matter: the Telegram coach in ../agente/ logs history under
the canonical key, so whatever the editor saves has to collapse to exactly the
same string as the equivalent line in data.py, or the same exercise ends up
split across two keys with no error to warn anyone.
"""

from __future__ import annotations

import re
import weakref
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, delete, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from data import ROUTINES, Phase, Routine, TrainingDay, active_routine
from exercises import exercise_key, phase_color
from storage import Base, Storage

# Stored routines live under this id namespace. Built-in ids are plain slugs
# ("cambiatufisico", "upper-lower"), so the colon can never collide.
USER_PREFIX = "user:"

MAX_SETS = 20
DEFAULT_SETS = 3
DEFAULT_REPS = "10"


# ── tables ───────────────────────────────────────────────────
# Declared on storage.Base so `Storage._init_db()` creates them with the rest.
# They are also mirrored in ../agente/entrenador/modelos.py: the bot owns no
# routine of its own, but the two files declare one schema between them and a
# table missing on one side is a migration bug waiting to happen.
#
# The four original tables are named in Spanish (entrenos, pesos…) because they
# predate the English-only refactor. New ones follow the code.


class UserRoutine(Base):
    __tablename__ = "user_routines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(240), default="")
    # Built-in id this was duplicated from, "" when started blank. Kept for the
    # "based on X" label and to make the provenance of a routine debuggable.
    source: Mapped[str] = mapped_column(String(60), default="")
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserRoutinePhase(Base):
    __tablename__ = "user_routine_phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    routine_id: Mapped[int] = mapped_column(
        ForeignKey("user_routines.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120), default="")
    subtitle: Mapped[str] = mapped_column(String(120), default="")
    weeks: Mapped[str] = mapped_column(String(40), default="")
    scheme: Mapped[str] = mapped_column(String(60), default="")
    rest: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    freq: Mapped[str] = mapped_column(String(10), default="low")


class UserRoutineDay(Base):
    __tablename__ = "user_routine_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("user_routine_phases.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120), default="")


class UserRoutineExercise(Base):
    __tablename__ = "user_routine_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_id: Mapped[int] = mapped_column(
        ForeignKey("user_routine_days.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Canonical key, already through exercise_key(). Never the display string:
    # the brackets are rebuilt from `sets`/`reps` when the routine is rendered.
    name: Mapped[str] = mapped_column(String(120))
    sets: Mapped[int] = mapped_column(Integer, default=DEFAULT_SETS)
    reps: Mapped[str] = mapped_column(String(40), default=DEFAULT_REPS)


_TABLES = (UserRoutine, UserRoutinePhase, UserRoutineDay, UserRoutineExercise)

# Engines already checked. `Storage.__init__` runs create_all once, at a moment
# when this module may not have been imported yet and its tables therefore are
# not in Base.metadata. Checking lazily here keeps the module usable whatever
# the import order — and create_all is a no-op after the first pass.
#
# A WeakSet, not a set of id()s: ids get recycled once an engine is collected,
# and a new engine landing on a freed id would silently skip its create_all.
_checked_engines: weakref.WeakSet = weakref.WeakSet()


def ensure_tables(store: Storage) -> None:
    engine = store._engine
    if engine in _checked_engines:
        return
    Base.metadata.create_all(engine)
    _checked_engines.add(engine)


def _sessions(store: Storage):
    ensure_tables(store)
    return sessionmaker(bind=store._engine, expire_on_commit=False)


# ── id helpers ───────────────────────────────────────────────


def user_routine_id(pk: int) -> str:
    return f"{USER_PREFIX}{pk}"


def is_user_routine(routine_id: str) -> bool:
    return str(routine_id).startswith(USER_PREFIX)


def routine_pk(routine_id: str) -> int | None:
    """Primary key behind a `user:<pk>` id, or None for a built-in."""
    if not is_user_routine(routine_id):
        return None
    try:
        return int(str(routine_id)[len(USER_PREFIX) :])
    except ValueError:
        return None


# ── the editable draft ───────────────────────────────────────
# The editor works on this tree and saves it whole. Editing rows live would mean
# a write per keystroke on a shared database, and no way to cancel.


@dataclass
class DraftExercise:
    name: str
    sets: int = DEFAULT_SETS
    reps: str = DEFAULT_REPS

    def display(self) -> str:
        return format_exercise(self.name, self.sets, self.reps)


@dataclass
class DraftDay:
    name: str = "Day"
    exercises: list[DraftExercise] = field(default_factory=list)


@dataclass
class DraftPhase:
    name: str = "Phase 1"
    subtitle: str = "Custom"
    weeks: str = "1-4"
    scheme: str = "3×10"
    rest: str = "90s"
    notes: str = ""
    freq: str = "low"
    days: list[DraftDay] = field(default_factory=list)


@dataclass
class DraftRoutine:
    name: str = "My Routine"
    description: str = ""
    source: str = ""
    pk: int | None = None  # None until first save
    phases: list[DraftPhase] = field(default_factory=list)

    def day_count(self) -> int:
        return sum(len(p.days) for p in self.phases)

    def exercise_count(self) -> int:
        return sum(len(d.exercises) for p in self.phases for d in p.days)


# ── scheme parsing / formatting ──────────────────────────────

# Everything accepts both the ASCII x and the × data.py writes.
# Numeric-only, for reading a Phase.scheme like "4×5-6 (*=3×8)" or "3-4×12".
_SCHEME_RE = re.compile(
    r"(\d{1,2})\s*[×x]\s*([0-9]{1,3}(?:\s*-\s*[0-9]{1,3})?(?:\s*,\s*[0-9]{1,3})*)"
)
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
# Inside a bracket the reps side is free text: "8-10", "max", "(20+20+20)".
_BRACKET_SCHEME_RE = re.compile(r"^\s*(\d{1,2})\s*[×x]\s*(\S.{0,39})\s*$")
# The alternate scheme a starred exercise follows, spelled "(*=3×8)" in Phase.scheme.
_STAR_SCHEME_RE = re.compile(r"\*\s*=\s*(\d{1,2})\s*[×x]\s*([0-9]{1,3}(?:\s*-\s*[0-9]{1,3})?)")


def format_exercise(name: str, sets: int, reps: str) -> str:
    """Render back into data.py's shape: `"Squat [4×8-10]"`.

    Kept symmetric with `exercise_key()` on purpose — feeding the result of this
    function back through it has to return `name` untouched, which is what makes
    a routine written here aggregate with the history the bot writes.
    """
    reps = (reps or "").strip()
    if not reps or sets <= 0:
        return name
    return f"{name} [{sets}×{reps}]"


def parse_exercise(raw: str, phase_scheme: str = "") -> DraftExercise:
    """Turn a data.py exercise string into an editable row.

    Three cases, in order:

    1. A bracket that reads `N×<anything>` wins — `[4×8-10]`, `[5×12,10,8,8,8]`,
       and also `[5×max]` or `[4×(20+20+20)]`, which is why the reps side is not
       restricted to digits. Brackets that are tags (`[comp]`, `[triple drop]`)
       have no `N×` and are skipped without special-casing.
    2. A starred exercise with no scheme takes the `(*=3×8)` alternate out of the
       phase scheme — that is precisely what the asterisk means in data.py.
    3. Anything else inherits the phase scheme.

    Reps are free text end to end (the editor's field is a plain TextField), so
    "max" and "failure" survive the round trip instead of being flattened.
    """
    name = canonical_name(raw)
    head = raw.split("[", 1)[0]  # the * marks the name, it is never inside a bracket
    starred = "*" in head

    for bracket in _BRACKET_RE.findall(raw):
        m = _BRACKET_SCHEME_RE.match(bracket)
        if m:
            return DraftExercise(name=name, sets=int(m.group(1)), reps=_clean_reps(m.group(2)))

    if starred:
        alt = _STAR_SCHEME_RE.search(phase_scheme or "")
        if alt:
            return DraftExercise(name=name, sets=int(alt.group(1)), reps=_clean_reps(alt.group(2)))

    m = _SCHEME_RE.search(phase_scheme or "")
    if m:
        return DraftExercise(name=name, sets=int(m.group(1)), reps=_clean_reps(m.group(2)))

    return DraftExercise(name=name)


def _clean_reps(reps: str) -> str:
    return re.sub(r"\s+", "", reps)[:40]


def canonical_name(raw: str) -> str:
    """`exercise_key()` applied until the name stops changing.

    One pass is enough for every string data.py contains, but not for everything
    a human can type into the editor: `exercise_key("Squat [5×5]*")` returns
    `"Squat [5×5]"`, because its regex only strips brackets that sit at the very
    end and the `*` is behind them. The bracket then falls off on the second
    pass. exercises.exercise_key is shared with the Telegram coach and frozen by
    tests/test_exercise_key.py, so the fixed point is taken here rather than
    there; on well-formed names the extra pass is a no-op.
    """
    name = (raw or "").strip()
    for _ in range(4):  # bounded: no input should need more than two
        nxt = exercise_key(name).strip()
        if nxt == name:
            return name
        name = nxt
    return name


def move(items: list, idx: int, delta: int) -> bool:
    """Swap an item with its neighbour. Returns False when it cannot move."""
    target = idx + delta
    if not (0 <= idx < len(items)) or not (0 <= target < len(items)):
        return False
    items[idx], items[target] = items[target], items[idx]
    return True


# ── drafts from the different sources ────────────────────────


def new_draft(name: str = "My Routine") -> DraftRoutine:
    return DraftRoutine(
        name=name,
        phases=[DraftPhase(days=[DraftDay(name="Day 1")])],
    )


def draft_from_builtin(routine_id: str) -> DraftRoutine:
    """Copy a code routine into an editable draft.

    `week_rotation` is dropped: it is a fixed 3-week wheel over day *names*, it
    only exists for CambiaTuFísico, and plan.py already hides the Distribution
    tab when a routine has none. Editing it would be a second screen for a
    feature one routine uses.
    """
    src = next((r for r in ROUTINES if r.id == routine_id), None)
    if src is None:
        raise KeyError(f"unknown routine: {routine_id}")

    phases: list[DraftPhase] = []
    for p in src.phases:
        days = [
            DraftDay(
                name=d.name,
                exercises=[parse_exercise(ex, p.scheme) for ex in d.exercises],
            )
            for d in src.days_for_phase(p.id)
        ]
        phases.append(
            DraftPhase(
                name=p.name,
                subtitle=p.subtitle,
                weeks=p.weeks,
                scheme=p.scheme,
                rest=p.rest,
                notes=p.notes,
                freq=p.freq,
                days=days,
            )
        )
    return DraftRoutine(
        name=f"{src.name} (copy)",
        description=src.description,
        source=src.id,
        phases=phases,
    )


def load_draft(store: Storage, pk: int) -> DraftRoutine | None:
    Session = _sessions(store)
    with Session() as s:
        row = s.get(UserRoutine, pk)
        if row is None:
            return None
        draft = DraftRoutine(
            name=row.name, description=row.description or "", source=row.source or "", pk=row.id
        )
        phase_rows = list(
            s.scalars(
                select(UserRoutinePhase)
                .where(UserRoutinePhase.routine_id == pk)
                .order_by(UserRoutinePhase.position, UserRoutinePhase.id)
            )
        )
        for pr in phase_rows:
            phase = DraftPhase(
                name=pr.name,
                subtitle=pr.subtitle or "",
                weeks=pr.weeks or "",
                scheme=pr.scheme or "",
                rest=pr.rest or "",
                notes=pr.notes or "",
                freq=pr.freq or "low",
                days=[],
            )
            day_rows = list(
                s.scalars(
                    select(UserRoutineDay)
                    .where(UserRoutineDay.phase_id == pr.id)
                    .order_by(UserRoutineDay.position, UserRoutineDay.id)
                )
            )
            for dr in day_rows:
                ex_rows = list(
                    s.scalars(
                        select(UserRoutineExercise)
                        .where(UserRoutineExercise.day_id == dr.id)
                        .order_by(UserRoutineExercise.position, UserRoutineExercise.id)
                    )
                )
                phase.days.append(
                    DraftDay(
                        name=dr.name,
                        exercises=[
                            DraftExercise(name=e.name, sets=e.sets, reps=e.reps) for e in ex_rows
                        ],
                    )
                )
            draft.phases.append(phase)
    return draft


# ── writes ───────────────────────────────────────────────────


def save_draft(store: Storage, draft: DraftRoutine) -> int:
    """Create or update. Returns the primary key, also set on the draft.

    Children are deleted and rewritten rather than diffed: a routine is a few
    dozen rows, position changes would otherwise need reconciling, and no other
    process writes these tables.
    """
    Session = _sessions(store)
    now = datetime.now().astimezone()
    name = (draft.name or "").strip() or "Untitled routine"
    phases = [p for p in draft.phases if p.days or (p.name or "").strip()]
    if not phases:
        phases = [DraftPhase(days=[DraftDay(name="Day 1")])]

    with Session() as s:
        if draft.pk is None:
            row = UserRoutine(
                name=name,
                description=(draft.description or "").strip()[:240],
                source=draft.source or "",
                created=now,
                updated=now,
            )
            s.add(row)
            s.flush()  # need the pk before writing the children
        else:
            row = s.get(UserRoutine, draft.pk)
            if row is None:
                raise KeyError(f"routine {draft.pk} no longer exists")
            row.name = name
            row.description = (draft.description or "").strip()[:240]
            row.updated = now
            _delete_children(s, row.id)

        for pos, p in enumerate(phases):
            phase_row = UserRoutinePhase(
                routine_id=row.id,
                # Position is the only phase numbering there is: `_materialize`
                # turns it into `Phase.id = position + 1`, which is what the
                # views index by (phase colour, `days_for_phase`).
                position=pos,
                name=(p.name or "").strip() or f"Phase {pos + 1}",
                subtitle=(p.subtitle or "").strip(),
                weeks=(p.weeks or "").strip(),
                scheme=(p.scheme or "").strip(),
                rest=(p.rest or "").strip(),
                notes=(p.notes or "").strip(),
                freq=p.freq if p.freq in ("high", "low") else "low",
            )
            s.add(phase_row)
            s.flush()
            for d_pos, d in enumerate(p.days):
                day_row = UserRoutineDay(
                    phase_id=phase_row.id,
                    position=d_pos,
                    name=(d.name or "").strip() or f"Day {d_pos + 1}",
                )
                s.add(day_row)
                s.flush()
                for e_pos, e in enumerate(d.exercises):
                    # THE rule of this repo: whatever the editor was handed, the
                    # stored name is the canonical key. A user who types
                    # "Squat [5×5]" into the name field must not create a second
                    # exercise that never matches the bot's history.
                    key = canonical_name(e.name)
                    if not key:
                        continue
                    s.add(
                        UserRoutineExercise(
                            day_id=day_row.id,
                            position=e_pos,
                            name=key[:120],
                            sets=max(1, min(int(e.sets or DEFAULT_SETS), MAX_SETS)),
                            reps=(e.reps or "").strip()[:40],
                        )
                    )
        s.commit()
        pk = row.id

    draft.pk = pk
    sync_user_routines(store)
    return pk


def _delete_children(s, routine_pk_: int) -> None:
    """Wipe phases/days/exercises of a routine, deepest level first.

    Explicit, not left to `ondelete="CASCADE"`: the constraint is only enforced
    if the tables were created after that clause existed, and this database has
    no migration tool to fix one that was not.
    """
    phase_ids = list(
        s.scalars(select(UserRoutinePhase.id).where(UserRoutinePhase.routine_id == routine_pk_))
    )
    if not phase_ids:
        return
    day_ids = list(
        s.scalars(select(UserRoutineDay.id).where(UserRoutineDay.phase_id.in_(phase_ids)))
    )
    if day_ids:
        s.execute(delete(UserRoutineExercise).where(UserRoutineExercise.day_id.in_(day_ids)))
    s.execute(delete(UserRoutineDay).where(UserRoutineDay.phase_id.in_(phase_ids)))
    s.execute(delete(UserRoutinePhase).where(UserRoutinePhase.id.in_(phase_ids)))


def delete_routine(store: Storage, pk: int) -> bool:
    """Delete a stored routine. Falls back to the first built-in if it was active."""
    Session = _sessions(store)
    with Session() as s:
        row = s.get(UserRoutine, pk)
        if row is None:
            return False
        _delete_children(s, pk)
        s.execute(delete(UserRoutine).where(UserRoutine.id == pk))
        s.commit()

    was_active = active_routine().id == user_routine_id(pk)
    sync_user_routines(store)
    if was_active:
        from data import set_active_routine

        fallback = ROUTINES[0].id
        set_active_routine(fallback)
        store.set_pref("routine", fallback)
    return True


def duplicate_builtin(store: Storage, routine_id: str, new_name: str | None = None) -> int:
    """Copy one of data.py's routines into the database, ready to edit.

    The realistic way to own a routine: start from the one you already follow and
    change the parts you disagree with.
    """
    draft = draft_from_builtin(routine_id)
    if new_name:
        draft.name = new_name
    return save_draft(store, draft)


def duplicate_user_routine(store: Storage, pk: int, new_name: str | None = None) -> int:
    draft = load_draft(store, pk)
    if draft is None:
        raise KeyError(f"routine {pk} does not exist")
    draft.pk = None  # forces an insert
    draft.name = new_name or f"{draft.name} (copy)"
    return save_draft(store, draft)


def duplicate_routine(store: Storage, routine_id: str, new_name: str | None = None) -> int:
    """Duplicate whatever the id points at, built-in or stored."""
    pk = routine_pk(routine_id)
    if pk is None:
        return duplicate_builtin(store, routine_id, new_name)
    return duplicate_user_routine(store, pk, new_name)


# ── the compatibility layer ──────────────────────────────────


def _materialize(draft: DraftRoutine) -> Routine:
    """Draft → the very dataclasses data.py exports. See the module docstring."""
    assert draft.pk is not None
    phases: list[Phase] = []
    days_by_phase: dict[int, list[TrainingDay]] = {}
    for idx, p in enumerate(draft.phases, start=1):
        phases.append(
            Phase(
                id=idx,
                weeks=p.weeks,
                name=p.name,
                subtitle=p.subtitle,
                # data.Phase.color holds a literal hex in data.py, chosen against
                # the old black background. Stored routines take theirs from the
                # active palette instead, so they follow the theme.
                color=phase_color(idx),
                scheme=p.scheme,
                rest=p.rest,
                notes=p.notes,
                freq=p.freq,
            )
        )
        days_by_phase[idx] = [
            TrainingDay(name=d.name, exercises=[e.display() for e in d.exercises]) for d in p.days
        ]
    return Routine(
        id=user_routine_id(draft.pk),
        name=draft.name,
        description=draft.description or _summary(draft),
        phases=phases,
        days_by_phase=days_by_phase,
        week_rotation=None,
    )


def _summary(draft: DraftRoutine) -> str:
    n_phases = len(draft.phases)
    n_days = draft.day_count()
    return f"Custom · {n_days} day{'s' if n_days != 1 else ''} · {n_phases} phase{'s' if n_phases != 1 else ''}"


def list_user_drafts(store: Storage) -> list[DraftRoutine]:
    Session = _sessions(store)
    with Session() as s:
        pks = list(s.scalars(select(UserRoutine.id).order_by(UserRoutine.id)))
    drafts = [load_draft(store, pk) for pk in pks]
    return [d for d in drafts if d is not None]


def list_user_routines(store: Storage) -> list[Routine]:
    """Stored routines as `data.Routine` objects."""
    return [_materialize(d) for d in list_user_drafts(store)]


def sync_user_routines(store: Storage) -> list[Routine]:
    """Refresh the stored half of `data.ROUTINES`. Idempotent.

    Slice assignment, not rebinding: views/plan.py imported the list object and
    would keep showing a stale copy otherwise.
    """
    mine = list_user_routines(store)
    ROUTINES[:] = [r for r in ROUTINES if not is_user_routine(r.id)] + mine
    return mine


def builtin_routines() -> list[Routine]:
    return [r for r in ROUTINES if not is_user_routine(r.id)]
