"""Whole-database backup: fourteen tables out, fourteen tables back in.

`Storage.export_all()` (BACKUP_VERSION = 2) covers four tables — workouts,
weights, profile and prefs. The database has **fourteen**: `nutrition.py` adds
`foods`, `servings`, `food_log` and `nutrition_targets`, `routine_builder.py`
adds `user_routines`, `user_routine_phases`, `user_routine_days` and
`user_routine_exercises`, and `storage.py` also holds `notas_sesion` and
`duraciones_sesion`. A backup taken on the desktop and restored on the phone
therefore arrived with the whole food diary and every hand-written routine
missing, and nothing said so — the restore reported success. On mobile the
backup file *is* the only bridge between two devices, so that silent hole is
the difference between moving your data and losing it.

This module is the complete one. It is a separate file rather than a
rewrite of `Storage.export_all()` because the four-table version has to stay
exactly as it is: it defines what a version-2 document looks like, and this
module still has to read those.

## Shape of the document

Version 3 is a **superset** of version 2 — `app`, `version`, `exported_at`,
`profile`, `prefs`, `workouts` and `weights` keep their v2 spelling — plus two
new sections, `nutrition` and `routines`, and some provenance metadata
(`app_version`, `engine`, `exported_at_iso`) so a file found in six months can
be traced back to the device that wrote it.

Version 4 is a superset of that, and only adds notes: an optional `note` on
every entry of `workouts`, and a `session_notes` section of
`{date, note, timestamp}`. Both are absent from a v2 or v3 file, which parses to
"no notes" — the same story as the sections above.

Version 5 adds one more section, `session_durations`, of
`{date, seconds, timestamp}` — how long each training day lasted. Absent from a
v2, v3 or v4 file, which parses to "nothing was timed", which is the truth about
every session logged before the chronometer was written down at all.

## No primary keys travel

Autoincrement ids are a property of *one* database. Copying them into another
either collides with rows already there or leaves children pointing at nothing.
Two rules avoid the whole class of bug:

* **Parent/child trees are nested, not flattened.** A routine carries its
  phases, a phase its days, a day its exercises. The document contains no
  `phase_id` at all, so there is nothing to dangle: the importer inserts a
  parent, flushes to learn its brand-new id, and hands that id to the children
  it is about to insert. Ids are therefore *remapped by construction*.
* **`food_log` references a food by `slug`, never by id.** The slug is the
  natural key of the catalogue (`foods.slug` is UNIQUE), it is stable across
  databases, and it is what seeding already matches on. The importer resolves
  slug → local id after inserting the foods.

The one id that does travel is `user_routines.id`, and only because the
`routine` preference stores the active routine as `user:<pk>`. That pref is
rewritten through the same old-pk → new-pk map, so restoring a backup does not
leave the app pointing at a routine id that no longer exists.

## Failure is all-or-nothing

An import happens in two phases:

1. **Parse** — the whole document is validated and normalised into plain Python
   with no database open at all. A truncated file, a number that is not a
   number, a meal slug the app does not know: all of it raises `BackupError`
   here, before a single row is touched.
2. **Write** — one session, one transaction, one commit at the end. The wipe is
   *inside* that transaction, which is the point: if the write fails halfway —
   the phone dies, a constraint trips — the rollback takes the wipe with it and
   the user still has the data they started with. (`Storage.import_all()`
   commits its wipe separately, so an exception after it leaves an empty
   database.)

## Merging, when `wipe=False`

One rule, applied everywhere: **the backup fills gaps, it never overwrites a
row that is already there.** An existing food slug, weight date, session-note
date, session-duration date, target start date, pref key or profile is kept
as-is; an exercise note rides inside its workout row and is appended or skipped
with it; log rows (workouts, food entries) are appended unless an identical row
already exists, so importing the same file twice does not double the history.
Stored routines have no natural key — two routines called "PPL" are two
routines — so they are always inserted fresh.

`wipe=True`, the default and what the restore button does, gives an exact copy
of the source database instead.

## The exercise-key contract

Every exercise name — in `entrenos` and in `user_routine_exercises` — goes
through `canonical_name()` (the fixed point of `exercises.exercise_key()`) on
the way in. That key is shared with the Telegram coach in ../agente/, and an
import is exactly the kind of thing that could inject `"Squat [5×5]"` as a
literal name and split a history in two with no error to warn anyone.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from data import set_active_routine
from nutrition import MEALS, Food, FoodLogEntry, NutritionTarget, Serving
from routine_builder import (
    DEFAULT_SETS,
    MAX_SETS,
    UserRoutine,
    UserRoutineDay,
    UserRoutineExercise,
    UserRoutinePhase,
    canonical_name,
    is_user_routine,
    routine_pk,
    sync_user_routines,
    user_routine_id,
)
from storage import (
    SECRET_PREF_KEYS,
    Base,
    DuracionSesion,
    Entreno,
    Foto,
    NotaSesion,
    Perfil,
    Peso,
    Preferencia,
    Storage,
    clean_duration,
    clean_note,
)
from workout_draft import EPHEMERAL_PREF_KEYS

# Bumped from Storage.BACKUP_VERSION = 2, which only knew four tables. Anything
# that changes the *meaning* of a field must bump this again; adding an
# optional field does not, since the reader tolerates missing keys.
#
# v4 adds notes: `workouts[].note` and the `session_notes` section. That is
# strictly an addition, so by the rule above it need not have bumped — and it
# bumped anyway, deliberately. "The reader tolerates missing keys" cuts the
# wrong way here: a v3 build handed a file with notes would import it happily
# and drop every note on the floor without a word, which is the same silent loss
# that made v2 lose the food diary. Refusing the file outright ("update IronFlet
# and try again") is the loud version of the same event. Old files keep
# importing — `_parse` accepts anything up to BACKUP_VERSION.
#
# v5 adds `session_durations` and bumps for exactly the same reason as v4: it is
# a hand-entered fact nothing can recompute, and a v4 build reading a v5 file
# would import the workouts, drop every duration and report success. There is no
# clock to re-run afterwards — the session is over.
BACKUP_VERSION = 5

APP_NAME = "ironflet"
# "ironlog" is what the pre-rename builds wrote. Storage.import_all accepts it,
# so a document this module produces has to be readable under the same rule.
ACCEPTED_APPS = ("ironflet", "ironlog")

# The fourteen tables, in the order the counts dict reports them.
TABLES = (
    "workouts",
    "weights",
    "session_notes",
    "session_durations",
    "photos",
    "profile",
    "prefs",
    "foods",
    "servings",
    "food_log",
    "nutrition_targets",
    "routines",
    "routine_phases",
    "routine_days",
    "routine_exercises",
)


class BackupError(ValueError):
    """A document that cannot be imported.

    Subclasses `ValueError` on purpose: `Storage.import_all()` raises plain
    `ValueError`, and any view already catching that keeps working when it is
    pointed at this module instead.
    """


# ── metadata ─────────────────────────────────────────────────


def _app_version() -> str:
    """Version of the app that wrote the file, for after-the-fact forensics.

    Read from the VERSION file rather than imported from anywhere: there is no
    module holding it, and on Android the file may simply not be packaged, so a
    missing file is normal and must not break an export.
    """
    try:
        return Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _ensure_schema(store: Storage) -> None:
    """`create_all` over all fourteen tables, whatever the import order was.

    `Storage.__init__` only creates the tables registered on `Base` *at that
    moment*, and `nutrition` / `routine_builder` may well be imported later —
    which is exactly why `routine_builder.ensure_tables()` exists. This module
    imports both at the top, so by the time any function here runs every table
    is on the metadata. `checkfirst` makes it a no-op once they exist, and one
    reflection round trip is nothing for an operation that runs by hand.
    """
    Base.metadata.create_all(store._engine)


def _sessions(store: Storage):
    return sessionmaker(bind=store._engine, expire_on_commit=False)


# ── export ───────────────────────────────────────────────────


def export_all(store: Storage) -> dict:
    """Every row of all fourteen tables as one JSON-serialisable dict.

    Read in a single session so the fourteen tables are a consistent snapshot
    rather than fourteen reads racing the Telegram coach writing between them.
    """
    _ensure_schema(store)
    Session = _sessions(store)
    now = time.time()

    with Session() as s:
        # An in-progress workout is not part of anyone's history. Restoring a
        # backup taken mid-session used to resurrect that session on the target
        # device — verified: export with a live draft, discard the workout,
        # restore, and the app reopened it at the same exercise.
        prefs = {
            p.clave: p.valor
            for p in s.scalars(select(Preferencia))
            # Two different exclusions with two different reasons, and they are
            # kept separate on purpose: EPHEMERAL is about staleness (an
            # in-progress session is nobody else's business), SECRET is about a
            # credential that must never be written into a file Alex might send
            # himself over a chat app. See `storage.SECRET_PREF_KEYS`.
            if p.clave not in EPHEMERAL_PREF_KEYS and p.clave not in SECRET_PREF_KEYS
        }
        workouts = list(s.scalars(select(Entreno).order_by(Entreno.id)))
        weights = list(s.scalars(select(Peso).order_by(Peso.fecha)))
        session_notes = list(s.scalars(select(NotaSesion).order_by(NotaSesion.fecha)))
        session_durations = list(s.scalars(select(DuracionSesion).order_by(DuracionSesion.fecha)))
        photos = list(s.scalars(select(Foto).order_by(Foto.fecha)))
        perfil = s.get(Perfil, 1)
        nutrition = _export_nutrition(s)
        routines = _export_routines(s)

    return {
        "app": APP_NAME,
        "version": BACKUP_VERSION,
        # Epoch float, same as v2, plus a human-readable twin: the float is for
        # code, the ISO string is for whoever opens the file in a text editor.
        "exported_at": now,
        "exported_at_iso": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
        "app_version": _app_version(),
        # "postgresql" on the desktop, "sqlite" on the phone. Purely
        # informational — the document is engine-neutral by construction — but
        # it answers "where did this file come from?" without guessing.
        "engine": store._engine.dialect.name,
        "profile": _export_profile(perfil),
        "prefs": prefs,
        "workouts": [
            {
                "date": e.fecha.isoformat(),
                "exercise": e.ejercicio,
                "muscle_group": e.grupo,
                "phase": e.fase,
                # Set dicts are copied verbatim. "rir" and "type" are optional
                # and rows written by the bot carry neither; re-encoding them
                # here would be this module inventing history it did not write.
                "sets": e.series or [],
                "timestamp": e.creado.timestamp(),
                # Absent on every row logged before notes existed and on
                # everything the bot writes. Exported as the null it is rather
                # than as "", so the far side stores the same absence.
                "note": e.nota,
            }
            for e in workouts
        ],
        "weights": [
            {"date": p.fecha.isoformat(), "kg": float(p.kg), "timestamp": p.creado.timestamp()}
            for p in weights
        ],
        # The one table that is nothing but notes. Its own section rather than a
        # field on `workouts`, because a session note belongs to the day and can
        # exist for a day with no exercise rows at all.
        "session_notes": [
            {"date": n.fecha.isoformat(), "note": n.nota, "timestamp": n.creado.timestamp()}
            for n in session_notes
        ],
        # Keyed by day, like `session_notes` and for the same reason: the
        # duration belongs to the training day, not to any one `entrenos` row,
        # so it cannot ride along inside `workouts` without being duplicated
        # once per exercise. Most days have no entry at all — nothing logged
        # before the chronometer was stored has one, and neither does anything
        # the bot writes.
        # Metadata only, on purpose: the JPEG bytes live on disk and travel in
        # the separate photos zip (see fotos.exportar_zip). Months of photos in
        # base64 would make this document too big to send over a chat app —
        # which is exactly how these backups move between devices.
        "photos": [
            {
                "date": f.fecha.isoformat(),
                "file": f.archivo,
                "note": f.nota,
                "timestamp": f.creado.timestamp(),
            }
            for f in photos
        ],
        "session_durations": [
            {
                "date": d.fecha.isoformat(),
                "seconds": int(d.segundos),
                "timestamp": d.creado.timestamp(),
            }
            for d in session_durations
        ],
        "nutrition": nutrition,
        "routines": routines,
    }


def _export_profile(perfil: Perfil | None) -> dict:
    """v2's profile shape, straight off the row (or empty, like `get_profile`)."""
    if perfil is None:
        return {"name": "", "birthdate": "", "height_cm": 0.0, "sex": "", "activity_level": ""}
    return {
        "name": perfil.nombre or "",
        "birthdate": perfil.nacimiento or "",
        "height_cm": float(perfil.altura_cm or 0),
        "sex": perfil.sexo or "",
        "activity_level": perfil.actividad or "moderate",
    }


def _export_nutrition(s) -> dict:
    """foods (with their servings nested), the diary, and the target history."""
    foods = list(s.scalars(select(Food).order_by(Food.id)))
    servings = list(s.scalars(select(Serving).order_by(Serving.id)))
    entries = list(s.scalars(select(FoodLogEntry).order_by(FoodLogEntry.id)))
    targets = list(s.scalars(select(NutritionTarget).order_by(NutritionTarget.starts_on)))

    by_food: dict[int, list[dict]] = {}
    for sv in servings:
        by_food.setdefault(sv.food_id, []).append(
            {"name": sv.name, "grams": float(sv.grams), "is_default": bool(sv.is_default)}
        )

    # Numeric ids never leave the database; the slug is the natural key and the
    # only thing the log rows below refer to.
    slug_of = {f.id: f.slug for f in foods}

    return {
        "foods": [
            {
                "slug": f.slug,
                "name": f.name,
                "kcal": float(f.kcal or 0),
                "protein": float(f.protein or 0),
                "fat": float(f.fat or 0),
                "carbs": float(f.carbs or 0),
                # None and 0.0 mean different things here ("not printed on the
                # label" vs "none"), so the null is preserved rather than
                # flattened into a zero.
                "fiber": None if f.fiber is None else float(f.fiber),
                "is_favourite": bool(f.is_favourite),
                "source": f.source,
                "created": f.created.timestamp(),
                "servings": by_food.get(f.id, []),
            }
            for f in foods
        ],
        "food_log": [
            {
                "date": e.log_date.isoformat(),
                "meal": e.meal,
                # NULL once the food is deleted from the catalogue; the entry
                # outlives it thanks to the copied name and frozen macros.
                "food_slug": slug_of.get(e.food_id) if e.food_id else None,
                "food_name": e.food_name,
                "grams": float(e.grams or 0),
                # Frozen totals for the grams eaten, not per 100 g. Exported as
                # stored: recomputing them from the catalogue would rewrite last
                # Tuesday's lunch with this month's numbers.
                "kcal": float(e.kcal or 0),
                "protein": float(e.protein or 0),
                "fat": float(e.fat or 0),
                "carbs": float(e.carbs or 0),
                "fiber": float(e.fiber or 0),
                "created": e.created.timestamp(),
            }
            for e in entries
        ],
        "targets": [
            {
                "starts_on": t.starts_on.isoformat(),
                "kcal": float(t.kcal or 0),
                "protein": float(t.protein or 0),
                "fat": float(t.fat or 0),
                "carbs": float(t.carbs or 0),
                "note": t.note,
                "created": t.created.timestamp(),
            }
            for t in targets
        ],
    }


def _export_routines(s) -> list[dict]:
    """User routines as nested trees — routine → phases → days → exercises.

    Nesting is what makes the four tables portable: the child rows carry no
    foreign key, so there is no id to collide or dangle on the far side.
    """
    routines = list(s.scalars(select(UserRoutine).order_by(UserRoutine.id)))
    if not routines:
        return []

    phases = list(
        s.scalars(select(UserRoutinePhase).order_by(UserRoutinePhase.position, UserRoutinePhase.id))
    )
    days = list(
        s.scalars(select(UserRoutineDay).order_by(UserRoutineDay.position, UserRoutineDay.id))
    )
    exercises = list(
        s.scalars(
            select(UserRoutineExercise).order_by(
                UserRoutineExercise.position, UserRoutineExercise.id
            )
        )
    )

    ex_by_day: dict[int, list[dict]] = {}
    for e in exercises:
        ex_by_day.setdefault(e.day_id, []).append(
            {"position": e.position, "name": e.name, "sets": e.sets, "reps": e.reps}
        )

    days_by_phase: dict[int, list[dict]] = {}
    for d in days:
        days_by_phase.setdefault(d.phase_id, []).append(
            {"position": d.position, "name": d.name, "exercises": ex_by_day.get(d.id, [])}
        )

    phases_by_routine: dict[int, list[dict]] = {}
    for p in phases:
        phases_by_routine.setdefault(p.routine_id, []).append(
            {
                "position": p.position,
                "name": p.name,
                "subtitle": p.subtitle or "",
                "weeks": p.weeks or "",
                "scheme": p.scheme or "",
                "rest": p.rest or "",
                "notes": p.notes or "",
                "freq": p.freq or "low",
                "days": days_by_phase.get(p.id, []),
            }
        )

    return [
        {
            # The only surviving primary key, and only so the `routine` pref —
            # which stores "user:<pk>" — can be remapped on import.
            "id": r.id,
            "name": r.name,
            "description": r.description or "",
            "source": r.source or "",
            "created": r.created.timestamp(),
            "updated": r.updated.timestamp(),
            "phases": phases_by_routine.get(r.id, []),
        }
        for r in routines
    ]


# ── parsing (phase 1: no database is open) ───────────────────


def _fail(where: str, detail: str) -> BackupError:
    return BackupError(f"{where}: {detail}")


def _rows(data: Mapping, key: str, where: str) -> list[dict]:
    value = data.get(key) or []
    if not isinstance(value, list):
        raise _fail(where, f"expected a list, found {type(value).__name__}")
    for row in value:
        if not isinstance(row, dict):
            raise _fail(where, f"expected objects, found {type(row).__name__}")
    return value


def _float(value, where: str, *, default: float | None = 0.0) -> float:
    if value is None or value == "":
        if default is None:
            raise _fail(where, "missing number")
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise _fail(where, f"{value!r} is not a number") from exc


def _int(value, where: str, *, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _fail(where, f"{value!r} is not a whole number") from exc


def _text(value, limit: int) -> str:
    """Coerce and truncate to the column width.

    Postgres enforces `String(n)`, SQLite does not. Truncating here means a
    hand-edited document fails the same way on both engines — which is to say,
    it does not fail at all.
    """
    return "" if value is None else str(value)[:limit]


def _opt_text(value, limit: int) -> str | None:
    return None if value is None else str(value)[:limit]


def _note(value) -> str | None:
    """A note as the database would have stored it.

    `storage.clean_note` and nothing else: trimming and the length cap are one
    decision, and a second copy here would let a hand-edited document put a
    20 000-character note into a column the app itself would have cut at
    `NOTE_MAX_LEN`. Blank and missing both come out `None`, which is what the
    column holds for "no note".
    """
    return clean_note(value if value is None else str(value))


def _day(value, where: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise _fail(where, f"{value!r} is not an ISO date (YYYY-MM-DD)") from exc


def _moment(value, where: str) -> datetime:
    """Epoch float → local aware datetime, defaulting to now.

    A missing timestamp is tolerated (it is metadata, not data), a nonsensical
    one is not: `fromtimestamp` raises on values outside the platform range and
    that is a corrupt file, not a shrug.
    """
    if value in (None, ""):
        return datetime.now().astimezone()
    try:
        return datetime.fromtimestamp(float(value)).astimezone()
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise _fail(where, f"{value!r} is not a usable timestamp") from exc


def _parse(data) -> dict:
    """Validate and normalise the whole document. Raises before any write.

    Everything a malformed file can do wrong is caught here, with the section
    name in the message, so `import_all` never has to unwind a half-finished
    transaction to report a typo.
    """
    if not isinstance(data, Mapping):
        raise BackupError(
            f"No es una copia de IronFlet: se esperaba un objeto y hay {type(data).__name__}"
        )
    if data.get("app") not in ACCEPTED_APPS:
        raise BackupError(f"No es una copia de IronFlet (app={data.get('app')!r})")

    version = _int(data.get("version"), "version", default=0)
    if version < 1:
        raise BackupError("No es una copia de IronFlet: sin número de versión")
    if version > BACKUP_VERSION:
        # The mirror image of the check in Storage.import_all: a file from a
        # newer app is refused whole rather than imported in part.
        raise BackupError(
            f"La versión {version} de la copia es más nueva de lo que esta app admite "
            f"(up to {BACKUP_VERSION}) — update IronFlet and try again"
        )

    parsed = {
        "version": version,
        "profile": _parse_profile(data.get("profile")),
        "prefs": _parse_prefs(data.get("prefs")),
        "workouts": _parse_workouts(data),
        "weights": _parse_weights(data),
        # v2 and v3 documents have no `session_notes` key; absent parses to an
        # empty list, exactly like `nutrition` and `routines` below.
        "session_notes": _parse_session_notes(data),
        # Same again for v2, v3 and v4 and `session_durations`.
        "session_durations": _parse_session_durations(data),
        # v≤5 documents have no `photos` key; absent parses to empty, like
        # every section added after v2.
        "photos": _parse_photos(data),
    }
    # v2 documents simply have no "nutrition" / "routines" keys. That is the
    # entire backwards-compatibility story: absent sections parse to empty.
    nutrition = data.get("nutrition") or {}
    if not isinstance(nutrition, Mapping):
        raise _fail("nutrition", f"expected an object, found {type(nutrition).__name__}")
    parsed["foods"] = _parse_foods(nutrition)
    parsed["food_log"] = _parse_food_log(nutrition)
    parsed["targets"] = _parse_targets(nutrition)
    parsed["routines"] = _parse_routines(data)
    return parsed


def _parse_profile(raw) -> dict | None:
    if not raw:
        return None
    if not isinstance(raw, Mapping):
        raise _fail("profile", f"expected an object, found {type(raw).__name__}")
    return {
        "name": _text(raw.get("name"), 120),
        "birthdate": _text(raw.get("birthdate"), 20),
        "height_cm": _float(raw.get("height_cm"), "profile.height_cm"),
        "sex": _text(raw.get("sex"), 20),
        "activity_level": _text(raw.get("activity_level"), 30) or "moderate",
    }


def _parse_prefs(raw) -> dict[str, str]:
    if not raw:
        return {}
    if not isinstance(raw, Mapping):
        raise _fail("prefs", f"expected an object, found {type(raw).__name__}")
    return {_text(k, 60): _text(v, 10_000) for k, v in raw.items()}


def _parse_workouts(data: Mapping) -> list[dict]:
    out = []
    for i, w in enumerate(_rows(data, "workouts", "workouts")):
        where = f"workouts[{i}]"
        sets = w.get("sets") or []
        if not isinstance(sets, list):
            raise _fail(f"{where}.sets", f"expected a list, found {type(sets).__name__}")
        out.append(
            {
                "date": _day(w.get("date"), f"{where}.date"),
                # THE contract: the stored name is the canonical key, never the
                # prescription string. An import must not be able to create
                # "Squat [5×5]" as a second exercise the bot will never match.
                "exercise": canonical_name(_text(w.get("exercise"), 120)),
                "muscle_group": _text(w.get("muscle_group"), 120),
                "phase": _int(w.get("phase"), f"{where}.phase"),
                "sets": sets,
                "created": _moment(w.get("timestamp"), f"{where}.timestamp"),
                # Absent in every v2 and v3 file, and on any row the bot wrote.
                "note": _note(w.get("note")),
            }
        )
    return out


def _parse_weights(data: Mapping) -> list[dict]:
    out = []
    for i, p in enumerate(_rows(data, "weights", "weights")):
        where = f"weights[{i}]"
        out.append(
            {
                "date": _day(p.get("date"), f"{where}.date"),
                "kg": _float(p.get("kg"), f"{where}.kg", default=None),
                "created": _moment(p.get("timestamp"), f"{where}.timestamp"),
            }
        )
    return out


def _parse_session_notes(data: Mapping) -> list[dict]:
    """The `session_notes` section, one entry per day.

    A note that is blank after cleaning is dropped rather than stored: the table
    is NOT NULL and a row saying nothing is a row nobody can act on. Two entries
    for one date would violate the primary key, so the last one wins here instead
    of aborting the transaction with a database error nobody can read.
    """
    by_day: dict[date, dict] = {}
    for i, n in enumerate(_rows(data, "session_notes", "session_notes")):
        where = f"session_notes[{i}]"
        nota = _note(n.get("note"))
        if nota is None:
            continue
        day = _day(n.get("date"), f"{where}.date")
        by_day[day] = {
            "date": day,
            "note": nota,
            "created": _moment(n.get("timestamp"), f"{where}.timestamp"),
        }
    return [by_day[k] for k in sorted(by_day)]


def _parse_photos(data: Mapping) -> list[dict]:
    """The `photos` section: one row per day, metadata only.

    `file` must be a bare name — a path would let a crafted document plant
    rows pointing outside the photos directory, and the gallery resolves
    these names against that directory on every render. Last one wins per
    date, like `session_durations`, and a row that cleans to nothing is
    dropped rather than aborting the import.
    """
    by_day: dict[date, dict] = {}
    for i, f in enumerate(_rows(data, "photos", "photos")):
        where = f"photos[{i}]"
        nombre = str(f.get("file") or "").strip()
        if not nombre or "/" in nombre or "\\" in nombre or nombre.startswith("."):
            continue
        day = _day(f.get("date"), f"{where}.date")
        nota = f.get("note")
        by_day[day] = {
            "date": day,
            "file": nombre[:120],
            "note": (str(nota)[:500] or None) if nota else None,
            "created": _moment(f.get("timestamp"), f"{where}.timestamp"),
        }
    return sorted(by_day.values(), key=lambda x: x["date"])


def _parse_session_durations(data: Mapping) -> list[dict]:
    """The `session_durations` section, one entry per timed day.

    Same three rules as `_parse_session_notes`, for the same reasons: a value
    that cleans to nothing is dropped rather than stored (the column is NOT NULL
    and a zero-second session is not a session), and two entries for one date
    would violate the primary key, so the last one wins here instead of aborting
    the transaction with a database error nobody can read.

    The one difference is the cap. `clean_duration` raises `ValueError` past
    `MAX_SESSION_SECONDS`, and here that becomes a `BackupError` naming the
    entry — a hand-edited file saying a session lasted three days is a corrupt
    file, and importing it silently clamped would put a number nobody measured
    into the history under the name of a measurement.
    """
    by_day: dict[date, dict] = {}
    for i, d in enumerate(_rows(data, "session_durations", "session_durations")):
        where = f"session_durations[{i}]"
        try:
            seconds = clean_duration(d.get("seconds"))
        except ValueError as exc:
            raise _fail(f"{where}.seconds", str(exc)) from exc
        if seconds is None:
            continue
        day = _day(d.get("date"), f"{where}.date")
        by_day[day] = {
            "date": day,
            "seconds": seconds,
            "created": _moment(d.get("timestamp"), f"{where}.timestamp"),
        }
    return [by_day[k] for k in sorted(by_day)]


def _parse_foods(nutrition: Mapping) -> list[dict]:
    out = []
    seen: set[str] = set()
    for i, f in enumerate(_rows(nutrition, "foods", "nutrition.foods")):
        where = f"nutrition.foods[{i}]"
        slug = _text(f.get("slug"), 60).strip()
        if not slug:
            raise _fail(where, "a food with no slug cannot be matched or referenced")
        if slug in seen:
            # foods.slug is UNIQUE; letting the duplicate through would abort
            # the transaction at flush time with a database error instead of a
            # sentence anyone can act on.
            raise _fail(where, f"slug {slug!r} appears twice")
        seen.add(slug)

        servings = f.get("servings") or []
        if not isinstance(servings, list):
            raise _fail(f"{where}.servings", f"expected a list, found {type(servings).__name__}")
        parsed_servings = []
        names: set[str] = set()
        for j, sv in enumerate(servings):
            sw = f"{where}.servings[{j}]"
            if not isinstance(sv, Mapping):
                raise _fail(sw, f"expected an object, found {type(sv).__name__}")
            name = _text(sv.get("name"), 80).strip()
            if not name or name in names:
                # uq_serving_food_name: same reason as the slug above.
                continue
            names.add(name)
            parsed_servings.append(
                {
                    "name": name,
                    "grams": _float(sv.get("grams"), f"{sw}.grams", default=None),
                    "is_default": bool(sv.get("is_default")),
                }
            )

        fiber = f.get("fiber")
        out.append(
            {
                "slug": slug,
                "name": _text(f.get("name"), 120) or slug,
                "kcal": _float(f.get("kcal"), f"{where}.kcal"),
                "protein": _float(f.get("protein"), f"{where}.protein"),
                "fat": _float(f.get("fat"), f"{where}.fat"),
                "carbs": _float(f.get("carbs"), f"{where}.carbs"),
                "fiber": None if fiber is None else _float(fiber, f"{where}.fiber"),
                "is_favourite": bool(f.get("is_favourite")),
                "source": _opt_text(f.get("source"), 160),
                "created": _moment(f.get("created"), f"{where}.created"),
                "servings": parsed_servings,
            }
        )
    return out


def _parse_food_log(nutrition: Mapping) -> list[dict]:
    out = []
    for i, e in enumerate(_rows(nutrition, "food_log", "nutrition.food_log")):
        where = f"nutrition.food_log[{i}]"
        meal = _text(e.get("meal"), 20)
        if meal not in MEALS:
            # The five slots are fixed and every screen indexes by them, so an
            # unknown slug is food that would be stored and never shown again.
            # Refusing the document beats importing invisible rows.
            raise _fail(f"{where}.meal", f"{meal!r} is not one of {', '.join(MEALS)}")
        slug = _text(e.get("food_slug"), 60).strip()
        out.append(
            {
                "date": _day(e.get("date"), f"{where}.date"),
                "meal": meal,
                "food_slug": slug or None,
                "food_name": _text(e.get("food_name"), 120),
                "grams": _float(e.get("grams"), f"{where}.grams"),
                "kcal": _float(e.get("kcal"), f"{where}.kcal"),
                "protein": _float(e.get("protein"), f"{where}.protein"),
                "fat": _float(e.get("fat"), f"{where}.fat"),
                "carbs": _float(e.get("carbs"), f"{where}.carbs"),
                "fiber": _float(e.get("fiber"), f"{where}.fiber"),
                "created": _moment(e.get("created"), f"{where}.created"),
            }
        )
    return out


def _parse_targets(nutrition: Mapping) -> list[dict]:
    out = []
    for i, t in enumerate(_rows(nutrition, "targets", "nutrition.targets")):
        where = f"nutrition.targets[{i}]"
        out.append(
            {
                "starts_on": _day(t.get("starts_on"), f"{where}.starts_on"),
                "kcal": _float(t.get("kcal"), f"{where}.kcal"),
                "protein": _float(t.get("protein"), f"{where}.protein"),
                "fat": _float(t.get("fat"), f"{where}.fat"),
                "carbs": _float(t.get("carbs"), f"{where}.carbs"),
                "note": _opt_text(t.get("note"), 10_000),
                "created": _moment(t.get("created"), f"{where}.created"),
            }
        )
    return out


def _parse_routines(data: Mapping) -> list[dict]:
    out = []
    for i, r in enumerate(_rows(data, "routines", "routines")):
        where = f"routines[{i}]"
        phases_raw = r.get("phases") or []
        if not isinstance(phases_raw, list):
            raise _fail(f"{where}.phases", f"expected a list, found {type(phases_raw).__name__}")

        phases = []
        for j, p in enumerate(phases_raw):
            pw = f"{where}.phases[{j}]"
            if not isinstance(p, Mapping):
                raise _fail(pw, f"expected an object, found {type(p).__name__}")
            days_raw = p.get("days") or []
            if not isinstance(days_raw, list):
                raise _fail(f"{pw}.days", f"expected a list, found {type(days_raw).__name__}")

            days = []
            for k, d in enumerate(days_raw):
                dw = f"{pw}.days[{k}]"
                if not isinstance(d, Mapping):
                    raise _fail(dw, f"expected an object, found {type(d).__name__}")
                ex_raw = d.get("exercises") or []
                if not isinstance(ex_raw, list):
                    raise _fail(
                        f"{dw}.exercises", f"expected a list, found {type(ex_raw).__name__}"
                    )

                exercises = []
                for n, e in enumerate(ex_raw):
                    ew = f"{dw}.exercises[{n}]"
                    if not isinstance(e, Mapping):
                        raise _fail(ew, f"expected an object, found {type(e).__name__}")
                    # Same canonicalisation save_draft applies, for the same
                    # reason: the editor and an import must land on one key.
                    name = canonical_name(_text(e.get("name"), 120))
                    if not name:
                        continue
                    sets = _int(e.get("sets"), f"{ew}.sets", default=DEFAULT_SETS) or DEFAULT_SETS
                    exercises.append(
                        {
                            "position": _int(e.get("position"), f"{ew}.position", default=n),
                            "name": name,
                            # The same clamp save_draft applies, so a hand-edited
                            # 0 or 999 lands in the range the editor can show.
                            "sets": max(1, min(sets, MAX_SETS)),
                            "reps": _text(e.get("reps"), 40),
                        }
                    )
                days.append(
                    {
                        "position": _int(d.get("position"), f"{dw}.position", default=k),
                        "name": _text(d.get("name"), 120) or f"Día {k + 1}",
                        "exercises": exercises,
                    }
                )
            phases.append(
                {
                    "position": _int(p.get("position"), f"{pw}.position", default=j),
                    "name": _text(p.get("name"), 120) or f"Fase {j + 1}",
                    "subtitle": _text(p.get("subtitle"), 120),
                    "weeks": _text(p.get("weeks"), 40),
                    "scheme": _text(p.get("scheme"), 60),
                    "rest": _text(p.get("rest"), 60),
                    "notes": _text(p.get("notes"), 10_000),
                    # The column is String(10) and _materialize/plan.py only
                    # understand these two; anything else becomes "low".
                    "freq": p.get("freq") if p.get("freq") in ("high", "low") else "low",
                    "days": days,
                }
            )

        out.append(
            {
                "old_pk": _int(r.get("id"), f"{where}.id", default=0),
                "name": _text(r.get("name"), 120) or "Rutina sin título",
                "description": _text(r.get("description"), 240),
                "source": _text(r.get("source"), 60),
                "created": _moment(r.get("created"), f"{where}.created"),
                "updated": _moment(r.get("updated"), f"{where}.updated"),
                "phases": phases,
            }
        )
    return out


# ── import (phase 2: one transaction) ────────────────────────


def import_all(store: Storage, data, *, wipe: bool = True) -> dict:
    """Restore any document up to `BACKUP_VERSION`. Returns a row count per table.

    The counts are keyed by `TABLES` and are meant to be shown to the user —
    `summary_line()` turns them into "47 workouts, 120 food entries, 2 routines".
    They report what was actually written, so a merge that skipped duplicates
    reports the smaller, true number.

    `wipe=True` (the default) replaces the database with the document. The
    delete and the insert share one transaction: an import that dies halfway
    rolls back to the data the user had, never to an empty app.

    `wipe=False` merges — see the module docstring for the one rule.

    Raises `BackupError` (a `ValueError`) for anything unimportable, always
    before the first write.
    """
    parsed = _parse(data)

    _ensure_schema(store)
    Session = _sessions(store)
    counts = dict.fromkeys(TABLES, 0)

    with Session() as s:
        try:
            if wipe:
                _wipe(s)
            routine_map = _write_routines(s, parsed["routines"], counts)
            _write_nutrition(s, parsed, counts, wipe=wipe)
            _write_training(s, parsed, counts, wipe=wipe)
            _write_photos(s, parsed, counts, wipe=wipe)
            _write_prefs(s, parsed, counts, routine_map, wipe=wipe)
            s.commit()
        except Exception:
            # Explicit, even though the context manager rolls back on the way
            # out: the wipe lives in this transaction and losing it silently is
            # the failure mode this whole module exists to prevent.
            s.rollback()
            raise

    # The stored half of data.ROUTINES is now stale — different rows, different
    # pks. Splice the new ones in before any view renders.
    sync_user_routines(store)
    _restore_active_routine(store)
    return counts


def _wipe(s) -> None:
    """Empty all fourteen tables, children before parents.

    Explicit ordering rather than trusting `ondelete="CASCADE"`: SQLite does not
    enforce foreign keys unless `PRAGMA foreign_keys` is on (it is off by
    default, and on Android this database is SQLite), and `routine_builder`
    already documents that the constraints may predate the clause on the
    Postgres side. Deleting deepest-first is correct on every engine.
    """
    for model in (
        UserRoutineExercise,
        UserRoutineDay,
        UserRoutinePhase,
        UserRoutine,
        FoodLogEntry,
        Serving,
        NutritionTarget,
        Food,
        Entreno,
        NotaSesion,
        DuracionSesion,
        Foto,
        Peso,
        Perfil,
    ):
        s.execute(delete(model))
    # Preferences last and filtered: `SECRET_PREF_KEYS` survives a restore.
    # The API key belongs to this device and this person, not to the document —
    # and a restore is exactly what someone does on a new phone, when going to
    # find the key again is hardest.
    s.execute(delete(Preferencia).where(Preferencia.clave.notin_(SECRET_PREF_KEYS)))


def _write_routines(s, routines: list[dict], counts: dict) -> dict[int, int]:
    """Insert the routine trees. Returns old pk → new pk.

    Every row is an INSERT with a fresh autoincrement id; the children are
    written only after `flush()` has produced the parent's real id. That is the
    id remapping: nothing carries an id in from the document, so nothing can
    collide with the routines already in this database.
    """
    mapping: dict[int, int] = {}
    for r in routines:
        row = UserRoutine(
            name=r["name"],
            description=r["description"],
            source=r["source"],
            created=r["created"],
            updated=r["updated"],
        )
        s.add(row)
        s.flush()
        counts["routines"] += 1
        if r["old_pk"]:
            mapping[r["old_pk"]] = row.id

        for p in r["phases"]:
            phase = UserRoutinePhase(
                routine_id=row.id,
                position=p["position"],
                name=p["name"],
                subtitle=p["subtitle"],
                weeks=p["weeks"],
                scheme=p["scheme"],
                rest=p["rest"],
                notes=p["notes"],
                freq=p["freq"],
            )
            s.add(phase)
            s.flush()
            counts["routine_phases"] += 1

            for d in p["days"]:
                day = UserRoutineDay(phase_id=phase.id, position=d["position"], name=d["name"])
                s.add(day)
                s.flush()
                counts["routine_days"] += 1

                for e in d["exercises"]:
                    s.add(
                        UserRoutineExercise(
                            day_id=day.id,
                            position=e["position"],
                            name=e["name"],
                            sets=e["sets"],
                            reps=e["reps"],
                        )
                    )
                    counts["routine_exercises"] += 1
    return mapping


def _write_nutrition(s, parsed: dict, counts: dict, *, wipe: bool) -> None:
    """Catalogue, servings, diary and targets, resolving slugs to local ids."""
    # slug → id in *this* database. On a merge it starts out holding the rows
    # already here, which is what makes an existing food win over the imported
    # one and keeps its id stable for anything pointing at it.
    food_ids: dict[str, int] = {}
    if not wipe:
        food_ids = {slug: fid for fid, slug in s.execute(select(Food.id, Food.slug))}

    for f in parsed["foods"]:
        existing = food_ids.get(f["slug"])
        if existing is None:
            row = Food(
                slug=f["slug"],
                name=f["name"],
                kcal=f["kcal"],
                protein=f["protein"],
                fat=f["fat"],
                carbs=f["carbs"],
                fiber=f["fiber"],
                is_favourite=f["is_favourite"],
                source=f["source"],
                created=f["created"],
            )
            s.add(row)
            s.flush()  # the servings below need the id
            food_ids[f["slug"]] = row.id
            counts["foods"] += 1
            have: set[str] = set()
        else:
            # Merge: the local row is left exactly as it is. The user may have
            # corrected it against the packet in their hand, same reasoning as
            # `Nutrition.seed(overwrite=False)`.
            have = set(s.scalars(select(Serving.name).where(Serving.food_id == existing)).all())

        food_id = food_ids[f["slug"]]
        for sv in f["servings"]:
            if sv["name"] in have:
                continue
            s.add(
                Serving(
                    food_id=food_id,
                    name=sv["name"],
                    grams=sv["grams"],
                    is_default=sv["is_default"],
                )
            )
            have.add(sv["name"])
            counts["servings"] += 1

    seen_entries: set[tuple] = set()
    if not wipe:
        seen_entries = {
            _entry_key(e.log_date, e.meal, e.food_name, e.grams, e.created)
            for e in s.scalars(select(FoodLogEntry))
        }
    for e in parsed["food_log"]:
        key = _entry_key(e["date"], e["meal"], e["food_name"], e["grams"], e["created"])
        if key in seen_entries:
            continue
        seen_entries.add(key)
        s.add(
            FoodLogEntry(
                log_date=e["date"],
                meal=e["meal"],
                # A slug the document did not ship a food for degrades to NULL
                # rather than aborting: the entry still carries its own name and
                # its own frozen macros, which is the whole point of that design.
                food_id=food_ids.get(e["food_slug"]) if e["food_slug"] else None,
                food_name=e["food_name"],
                grams=e["grams"],
                kcal=e["kcal"],
                protein=e["protein"],
                fat=e["fat"],
                carbs=e["carbs"],
                fiber=e["fiber"],
                created=e["created"],
            )
        )
        counts["food_log"] += 1

    have_targets: set[date] = set()
    if not wipe:
        have_targets = set(s.scalars(select(NutritionTarget.starts_on)))
    for t in parsed["targets"]:
        if t["starts_on"] in have_targets:
            continue
        have_targets.add(t["starts_on"])
        s.add(
            NutritionTarget(
                starts_on=t["starts_on"],
                kcal=t["kcal"],
                protein=t["protein"],
                fat=t["fat"],
                carbs=t["carbs"],
                note=t["note"],
                created=t["created"],
            )
        )
        counts["nutrition_targets"] += 1


def _entry_key(day, meal, name, grams, created) -> tuple:
    """Identity of a diary row, for the merge.

    `food_log` has no natural key, so "the same entry" is the same food, of the
    same size, in the same meal, logged at the same second. Seconds rather than
    microseconds because the two engines do not round-trip fractions
    identically, and grams rounded for the same reason.
    """
    return (day, meal, name, round(float(grams or 0), 3), int(created.timestamp()))


def _write_training(s, parsed: dict, counts: dict, *, wipe: bool) -> None:
    """Profile, workouts, body weight, session notes and session durations.

    Exercise notes need no pass of their own: each one rides in the `entrenos`
    row it belongs to, and is inserted with it. Durations do need one — they are
    keyed by day, not by exercise, and a timed day can have no `entrenos` rows
    at all.
    """
    profile = parsed["profile"]
    if profile is not None and (wipe or s.get(Perfil, 1) is None):
        s.merge(
            Perfil(
                id=1,
                nombre=profile["name"],
                nacimiento=profile["birthdate"],
                altura_cm=profile["height_cm"],
                sexo=profile["sex"],
                actividad=profile["activity_level"],
            )
        )
        counts["profile"] = 1

    have_weights: set[date] = set()
    if not wipe:
        have_weights = set(s.scalars(select(Peso.fecha)))
    for p in parsed["weights"]:
        if p["date"] in have_weights:
            continue
        have_weights.add(p["date"])
        s.add(Peso(fecha=p["date"], kg=p["kg"], creado=p["created"]))
        counts["weights"] += 1

    seen_workouts: set[tuple] = set()
    if not wipe:
        seen_workouts = {
            (e.fecha, e.ejercicio, int(e.creado.timestamp())) for e in s.scalars(select(Entreno))
        }
    for w in parsed["workouts"]:
        key = (w["date"], w["exercise"], int(w["created"].timestamp()))
        if key in seen_workouts:
            continue
        seen_workouts.add(key)
        s.add(
            Entreno(
                fecha=w["date"],
                ejercicio=w["exercise"],
                grupo=w["muscle_group"],
                fase=w["phase"],
                series=w["sets"],
                creado=w["created"],
                nota=w["note"],
            )
        )
        counts["workouts"] += 1

    # Same gap-filling rule as weights: on a merge the note already on this
    # device wins. It was written here, about a session trained here; a note
    # from another device cannot know better than the one in front of you.
    have_notes: set[date] = set()
    if not wipe:
        have_notes = set(s.scalars(select(NotaSesion.fecha)))
    for n in parsed["session_notes"]:
        if n["date"] in have_notes:
            continue
        have_notes.add(n["date"])
        s.add(NotaSesion(fecha=n["date"], nota=n["note"], creado=n["created"]))
        counts["session_notes"] += 1

    # And once more for durations. Same gap-filling rule, same argument: a
    # session timed on this device was timed *here*, and a number from another
    # device is not a better answer about how long it took.
    have_durations: set[date] = set()
    if not wipe:
        have_durations = set(s.scalars(select(DuracionSesion.fecha)))
    for d in parsed["session_durations"]:
        if d["date"] in have_durations:
            continue
        have_durations.add(d["date"])
        s.add(DuracionSesion(fecha=d["date"], segundos=d["seconds"], creado=d["created"]))
        counts["session_durations"] += 1


def _write_photos(s, parsed: dict, counts: dict, *, wipe: bool) -> None:
    """Photo metadata rows. The JPEGs come back via the photos zip, not here."""
    have: set[date] = set()
    if not wipe:
        have = set(s.scalars(select(Foto.fecha)))
    for f in parsed["photos"]:
        if f["date"] in have:
            continue
        have.add(f["date"])
        s.add(Foto(fecha=f["date"], archivo=f["file"], nota=f["note"], creado=f["created"]))
        counts["photos"] += 1


def _write_prefs(s, parsed: dict, counts: dict, routine_map: dict[int, int], *, wipe: bool) -> None:
    """Preferences, with the active-routine pointer remapped.

    Written last because the `routine` pref may hold `user:<pk>` and the new pk
    only exists once the routines have been inserted and flushed.
    """
    have: set[str] = set()
    if not wipe:
        have = set(s.scalars(select(Preferencia.clave)))

    for key, value in parsed["prefs"].items():
        # Belt and braces with the export side: a v3 file written before this
        # exclusion existed still carries the draft, and importing one must not
        # drop someone else's half-finished session onto this device.
        if key in EPHEMERAL_PREF_KEYS or key in SECRET_PREF_KEYS:
            continue
        if key in have:
            continue
        if key == "routine" and is_user_routine(value):
            old = routine_pk(value)
            new = routine_map.get(old) if old is not None else None
            if new is None:
                # Points at a stored routine this document does not carry (a v2
                # backup, or a routine deleted before the export). Dropping the
                # pref is honest: `active_routine()` then falls back to the
                # first built-in instead of silently resolving to whatever
                # routine happens to own that pk here.
                continue
            value = user_routine_id(new)
        s.merge(Preferencia(clave=key, valor=value))
        counts["prefs"] += 1


def _restore_active_routine(store: Storage) -> None:
    """Re-select the routine the backup was taken under.

    Without this the app keeps the routine chosen before the import, which after
    a wipe may not exist any more — and the routine decides the plan on screen
    and the streak minimum. `set_active_routine` ignores ids it cannot find, so
    a stale value is harmless.
    """
    rid = store.get_pref("routine")
    if rid:
        set_active_routine(rid)


# ── files ────────────────────────────────────────────────────


def dumps(data: dict) -> str:
    """Serialise a backup. Indented: these files get opened in text editors."""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)


def loads(text: str | bytes) -> dict:
    """Parse a backup file's text, turning a truncated file into a `BackupError`.

    Callers should never see a raw `JSONDecodeError`: to the user a half-copied
    file and a file full of nonsense are the same event, and both must be
    reported without having touched the database.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError(f"El archivo no es JSON válido — truncado o corrupto ({exc})") from exc
    if not isinstance(data, dict):
        raise BackupError(f"No es una copia de IronFlet: hay {type(data).__name__}, no un objeto")
    return data


def export_to_file(store: Storage, path: str | Path) -> Path:
    """Write a full backup to `path`, creating parent directories."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps(export_all(store)), encoding="utf-8")
    return target


def import_from_file(store: Storage, path: str | Path, *, wipe: bool = True) -> dict:
    """Read and restore a backup file. See `import_all` for the semantics."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise BackupError(f"No se puede leer el archivo de copia: {exc}") from exc
    return import_all(store, loads(text), wipe=wipe)


def default_filename(when: float | None = None) -> str:
    """`ironflet-backup-YYYYMMDD-HHMM.json` — sorts chronologically by name."""
    moment = datetime.fromtimestamp(when if when is not None else time.time())
    return f"ironflet-backup-{moment:%Y%m%d-%H%M}.json"


# ── reporting ────────────────────────────────────────────────

# The seven counts worth showing. The other seven (servings, phases, days…) are
# in the dict, but nobody restores a backup wondering how many servings moved.
_HEADLINE = (
    ("workouts", "entreno", "entrenos"),
    ("weights", "pesaje", "pesajes"),
    # Worth a line of its own even though it is a small table: it is one of the
    # two things in the file Alex entered by hand and nothing can regenerate.
    ("session_notes", "nota de sesión", "notas de sesión"),
    # The other one. Listed for the same reason and with more at stake: a note
    # that failed to arrive is at least missed when the day is read back, while
    # a missing duration looks exactly like a session that was never timed.
    ("session_durations", "tiempo de sesión", "tiempos de sesión"),
    ("food_log", "apunte de comida", "apuntes de comida"),
    ("foods", "alimento", "alimentos"),
    ("routines", "rutina", "rutinas"),
)


def summary_line(counts: Mapping[str, int]) -> str:
    """ "47 workouts, 120 food entries, 2 routines" — for the restore dialog."""
    parts = [
        f"{n} {singular if n == 1 else plural}"
        for key, singular, plural in _HEADLINE
        if (n := int(counts.get(key) or 0))
    ]
    return ", ".join(parts) if parts else "nada"
