"""Persistence, dual-engine: PostgreSQL on the PC, SQLite on the phone.

The same code has to serve two worlds, and they do not overlap:

* **PC (desktop and web)** — PostgreSQL, shared live with the Telegram coach in
  `../agente/`. What Alex logs here the bot sees instantly, and the other way
  round. Needs `docker compose up -d` in `../`.
* **Phone (APK)** — a SQLite file in the app's private storage. No network, no
  Docker, no bot. The APK must work standing in a gym basement with the PC off,
  so a remote database is not an option there.

Every model and every query in this repo is plain SQLAlchemy 2.x with nothing
Postgres-specific in it, so the engine really is swappable by URL alone. What is
*not* interchangeable is the tuning: see `create_db_engine`.

## Where the URL comes from

`resolve_db_url()` decides, in this order, and the order is the whole point:

1. **An explicit `db_url` argument**, then **`DATABASE_URL`**. An operator who
   named a database means it — tests point at `entrenador_test`, the systemd
   unit points at the shared server. Nothing may second-guess that, least of all
   a platform guess.
2. **SQLite, if we are running on Android** (or if `IRONFLET_SQLITE` forces it).
   There is no Postgres to reach from a phone; defaulting to one would give
   Alex a connection error instead of an app.
3. **PostgreSQL** otherwise — today's behaviour, unchanged, which is what keeps
   the desktop and the bot on one database.

### Why not `FLET_APP_STORAGE_DATA` as the Android signal

`asset_manager.py` reads that variable, and it is tempting to reuse it here. It
would be wrong: `flet_cli/commands/run.py` sets `FLET_APP_STORAGE_DATA` for a
plain `flet run` **on the desktop** too. It answers "do I have a private
directory to write in", not "am I a phone". Keying the engine off it would flip
Alex's desktop to a private SQLite file the first time he ran `flet run`,
silently disconnecting him from the database the bot writes to — with no error,
just an empty history. So it decides *where* the file lives (`sqlite_path()`),
never *whether* SQLite is used. See `running_on_android()` for the signals that
do answer that question.
"""

from __future__ import annotations

import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    event,
    func,
    select,
)
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import analytics
from data import active_routine

DEFAULT_URL = "postgresql+psycopg://entrenador@127.0.0.1:5432/entrenador"

# The database file on mobile. Deliberately at the root of the app's storage and
# NOT under `assets/`: Flet serves `assets/` over HTTP in web mode, so a database
# parked there would be downloadable by anything that can reach the port.
SQLITE_FILENAME = "ironflet.db"


# ── engine selection ─────────────────────────────────────────────


def running_on_android() -> bool:
    """True when this process is the Android build. Three signals, best first.

    1. **`sys.getandroidapilevel`** — CPython only defines it when compiled with
       `__ANDROID__`. It is a property of the interpreter binary, so no
       environment variable, shell or container can fake it either way. This is
       the one that answers for the APK: `flet build apk` embeds a CPython built
       for Android via serious-python.
    2. **`platform.system() == "Android"`** — true from CPython 3.13 on, which
       this project cannot use yet (`requires-python <3.13`). It is here so the
       check keeps working after the pin moves, not because it fires today.
    3. **`ANDROID_ROOT` + `ANDROID_DATA`** — exported into every process by the
       Android runtime itself. Both are required, because either alone shows up
       in unrelated SDK/tooling shells. This is the fallback if a future Flet
       runtime ships an interpreter without signal 1.

    Note what is *not* in the list: `FLET_APP_STORAGE_DATA` (set on the desktop
    too — see the module docstring) and `sys.platform`, which is plain `"linux"`
    on Android and would take Alex's Linux desktop with it.
    """
    if hasattr(sys, "getandroidapilevel"):
        return True
    if platform.system() == "Android":
        return True
    return bool(os.environ.get("ANDROID_ROOT") and os.environ.get("ANDROID_DATA"))


def sqlite_path() -> Path:
    """Absolute path of the mobile database file.

    `FLET_APP_STORAGE_DATA` is the app-private directory Flet guarantees is
    writable and survives app updates — the same variable `asset_manager.py`
    uses, resolved the same way, so the downloaded exercise frames and the
    database end up under one root. Falls back to the working directory when
    the variable is absent (running from source), which is where a developer
    would look for it anyway.
    """
    base = os.environ.get("FLET_APP_STORAGE_DATA") or os.getcwd()
    return Path(base) / SQLITE_FILENAME


def sqlite_url(path: str | os.PathLike) -> str:
    """SQLite URL for a file path.

    Built through `URL.create` rather than an f-string: an absolute POSIX path
    needs *four* slashes after the scheme (`sqlite:////data/...`) and hand-rolled
    concatenation gets that wrong in a way that silently opens a relative file
    next to the binary instead of the intended one.
    """
    return URL.create("sqlite+pysqlite", database=str(path)).render_as_string(hide_password=False)


def _forced_sqlite() -> str | None:
    """`IRONFLET_SQLITE`: run the mobile path on a desktop, for testing.

    `1`/`true`/`yes` uses `sqlite_path()`; any other non-empty value is taken as
    the file path to use. Ranked *below* `DATABASE_URL` on purpose — if both are
    set, the explicitly named database wins, because that one was typed with a
    target in mind.
    """
    raw = (os.environ.get("IRONFLET_SQLITE") or "").strip()
    if not raw or raw.lower() in ("0", "false", "no"):
        return None
    if raw.lower() in ("1", "true", "yes"):
        return sqlite_url(sqlite_path())
    return sqlite_url(raw)


def resolve_db_url(db_url: str | None = None) -> str:
    """Explicit URL > `DATABASE_URL` > SQLite on Android > PostgreSQL.

    See the module docstring for why the order is what it is.
    """
    if db_url:
        return db_url
    env = os.environ.get("DATABASE_URL")
    if env:
        return env
    forced = _forced_sqlite()
    if forced:
        return forced
    if running_on_android():
        return sqlite_url(sqlite_path())
    return DEFAULT_URL


def is_sqlite_url(db_url: str) -> bool:
    return make_url(db_url).get_backend_name() == "sqlite"


def _apply_sqlite_pragmas(engine: Engine) -> None:
    """Per-connection PRAGMAs. Without these SQLite is not Postgres-shaped.

    They go on the `connect` event, not on a one-off connection, because every
    one of them is **per connection**: the pool opens more than one, and a
    setting applied once would hold for whichever connection happened to be
    first and silently not for the others.

    * `foreign_keys=ON` — **the important one.** SQLite ships foreign keys
      *disabled*, for backwards compatibility. `create_all` does emit the
      `ON DELETE CASCADE` / `ON DELETE SET NULL` clauses from `nutrition.py` and
      `routine_builder.py`, and with the pragma off SQLite parses and ignores
      them. `Nutrition.delete_food()` has no ORM `relationship()` to cascade in
      Python — it deletes the row and lets the database do the rest — so on an
      untuned SQLite it would leave orphan `servings` and `food_log` rows
      pointing at a food that no longer exists. No error, ever. Just a diary
      that slowly rots. `tests/test_sqlite_backend.py` pins this.
    * `journal_mode=WAL` — readers no longer block the writer. The UI renders
      from the same database a background task is writing to; on the default
      rollback journal that is a frozen screen or an SQLITE_BUSY. WAL is a
      property of the *file*, so this only really matters the first time, but
      re-issuing it is a no-op and cheap. On a filesystem that cannot do WAL it
      returns the old mode instead of raising, so there is nothing to catch.
    * `synchronous=NORMAL` — the documented companion to WAL: durable across
      app crashes, and only at risk from an OS-level power loss. FULL costs an
      fsync per commit, which on phone flash is felt on every logged set.
    * `busy_timeout=5000` — SQLite's default is 0, i.e. a lock contention raises
      "database is locked" immediately. Five seconds of waiting turns a race
      between the UI thread and a background task into a pause nobody notices.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        try:
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
        finally:
            cur.close()


def create_db_engine(db_url: str, **kwargs) -> Engine:
    """`create_engine` with the arguments each backend actually wants.

    They have nothing in common, which is why this is a fork and not a dict of
    shared options:

    * **PostgreSQL** gets `pool_pre_ping=True`. Connections cross a socket and
      the server, a restart of the container or an idle timeout leaves dead ones
      in the pool; pre-ping spends one round trip to avoid handing one out.
    * **SQLite** gets neither — there is no connection to go stale, the "server"
      is a file handle, and a pre-ping would just be a wasted query per checkout.
      It gets `check_same_thread=False` instead: Flet dispatches UI callbacks and
      `page.run_task` work from more than one thread, and pysqlite's default
      refuses to use a connection from a thread other than the one that opened
      it. SQLAlchemy 2.0 already defaults this to False for file databases; it is
      pinned here so a dialect default flipping back cannot break the APK
      quietly. The pool still hands each thread its own connection.

    Also creates the parent directory: on a fresh install the app-storage path
    exists but nothing under it does, and pysqlite reports a missing directory as
    "unable to open database file", which reads like corruption.
    """
    url = make_url(db_url)
    if url.get_backend_name() != "sqlite":
        options = {"pool_pre_ping": True}
        options.update(kwargs)
        return create_engine(url, **options)

    database = url.database or ""
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    options: dict = {"connect_args": {"check_same_thread": False}}
    options.update(kwargs)
    engine = create_engine(url, **options)
    _apply_sqlite_pragmas(engine)
    return engine


# ── timestamps ───────────────────────────────────────────────────
# `DateTime(timezone=True)` does not mean the same thing on both engines, and
# the difference is silent.
#
# Postgres stores a `timestamptz`: the instant is preserved and comes back
# tz-aware, whatever offset went in. SQLite has no date type at all — the
# pysqlite dialect formats the datetime into a `YYYY-MM-DD HH:MM:SS.ffffff`
# string and **drops the offset**, then reads it back naive. So the wall clock
# survives and the offset does not.
#
# The consequence, measured: write `datetime.now(timezone.utc)` and read it back
# on SQLite and `.timestamp()` is off by the local UTC offset — two hours in
# Madrid in summer — because a naive datetime is interpreted as local time.
# Postgres would have returned the right instant. That is a workout landing on
# the wrong day at the edges, with nothing raised.
#
# The rule that makes both engines agree, and the reason these two helpers exist
# rather than inline `.astimezone()` / `.timestamp()` calls: **write local-aware,
# read as local**. Then the wall clock SQLite keeps is the local one, and
# interpreting it as local on the way out recovers the same instant Postgres
# would have given. `tests/test_sqlite_backend.py` pins the round trip.


def _as_local(value: datetime) -> datetime:
    """Normalise to local time before it reaches a timestamp column.

    Bare `.astimezone()` does both halves of the job: on a naive value it treats
    the wall clock as local and attaches the local offset; on an aware value it
    converts the instant into local time. Never call it on a value that is
    already going to a `DateTime(timezone=True)` column by another route.
    """
    return value.astimezone()


def _now() -> datetime:
    return datetime.now().astimezone()


def _epoch(value: datetime | None) -> float:
    """Unix timestamp of a value read back from a timestamp column.

    Naive (SQLite) is read as local time, which is exactly what `.timestamp()`
    already does — stated here so the assumption is one function and not
    scattered across six call sites.
    """
    return value.timestamp() if value is not None else 0.0


def weekly_session_minimum(routine=None) -> int:
    """Sessions a week must hold to extend the streak, read off the routine.

    A routine does not train the same number of days from start to finish.
    CambiaTuFísico — the default — prescribes 3 days a week in phases 1-4
    (weeks 1 to 10), 5 in phases 5-6 and 6 in phase 7, while `push-pull-legs`
    is a 3-day routine throughout. So any fixed number lies in some phase of
    some routine: the 4 that used to be hardcoded here is unreachable during
    the first ten weeks of the default routine, which is why a perfectly
    adherent user saw 🔥 0 and nothing else.

    Grading each week against the phase it belonged to is not possible: no
    routine start date is stored, so a past calendar week cannot be mapped
    onto a phase. The honest fallback is the lightest phase's prescription —
    the one number every phase of this routine can reach. Consequences,
    stated so nobody has to guess:

    * perfect adherence can never read 0, in any phase of any routine;
    * heavier phases keep slack, which is what the old "4 of 5" was after:
      one missed session does not erase months of consistency;
    * deload phases, the lightest by design, stay inside the streak.

    `days_by_phase` is the source, not `week_rotation`. For the three
    CambiaTuFísico phases that rotate, the rotation trains 4 days a week off
    3 day templates, so the template count is the lower — and therefore the
    safe — of the two.

    Falls back to 1 for a routine with no days at all (a half-built custom
    one), because a 0 minimum would make every week of doing nothing count.
    """
    routine = routine or active_routine()
    counts = [len(days) for days in routine.days_by_phase.values() if days]
    return max(1, min(counts, default=1))


@dataclass
class WorkoutEntry:
    date: str
    exercise: str
    muscle_group: str
    phase: int
    sets: list[dict]
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class Base(DeclarativeBase):
    pass


class Entreno(Base):
    """One exercise on one date. `series` is the JSON list of sets.

    What `JSON` compiles to differs by engine, and only one of the differences
    can bite:

    * On Postgres it is a real `json` column, validated by the server.
    * On SQLite it is `TEXT`, round-tripped through `json.dumps`/`json.loads` by
      SQLAlchemy's generic type. Verified byte-for-byte equal on the way back:
      floats keep their precision, key order is preserved, and the optional
      `"rir"` / `"type"` keys survive untouched — which is what matters, since
      the sets written by the Telegram coach have neither.
    * The real difference is that **SQLite cannot query inside the column**
      without the JSON1 extension, and the operators are not portable anyway.
      Nothing in this repo filters or indexes on `series` — it is always read
      whole into Python and handed to `analytics`. Keep it that way, or the
      mobile build gets a query the desktop has and it does not.

    One more asymmetry worth knowing before debugging something odd: SQLite does
    not enforce `String(120)` at all. An over-long exercise name that Postgres
    rejects loudly is stored in full on the phone, and only fails later when the
    row is pushed to the shared database via a backup.
    """

    __tablename__ = "entrenos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    ejercicio: Mapped[str] = mapped_column(String(120), index=True)
    grupo: Mapped[str] = mapped_column(String(120), default="")
    fase: Mapped[int] = mapped_column(Integer, default=0)
    series: Mapped[list] = mapped_column(JSON, default=list)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Peso(Base):
    __tablename__ = "pesos"

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    kg: Mapped[float] = mapped_column(Float)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Preferencia(Base):
    __tablename__ = "preferencias"

    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(Text)


class Perfil(Base):
    __tablename__ = "perfil"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    nombre: Mapped[str] = mapped_column(String(120), default="")
    nacimiento: Mapped[str] = mapped_column(String(20), default="")
    altura_cm: Mapped[float] = mapped_column(Float, default=0)
    sexo: Mapped[str] = mapped_column(String(20), default="")
    actividad: Mapped[str] = mapped_column(String(30), default="moderate")


def _hoy() -> date:
    return date.today()


def _fecha(valor: str | date) -> date:
    return date.fromisoformat(valor) if isinstance(valor, str) else valor


class Storage:
    """Training history, body weight, profile and preferences.

    `nutrition.py` and `routine_builder.py` share this engine (they declare
    their tables on the same `Base`), so whichever engine is chosen here is the
    engine the whole app runs on. Pass `db_url` to override everything; leave it
    out and `resolve_db_url()` decides.
    """

    def __init__(self, db_url: str | None = None):
        self.db_url = resolve_db_url(db_url)
        self._engine = create_db_engine(self.db_url)
        # Public: views and the backup screen need to say "this phone" vs "the
        # shared database", and re-parsing the URL at each call site invites one
        # of them to get it subtly wrong.
        self.is_sqlite = self._engine.dialect.name == "sqlite"
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._init_db()

    def _init_db(self):
        Base.metadata.create_all(self._engine)

    # ── prefs ────────────────────────────────────────────────
    def get_pref(self, key: str, default: str | None = None) -> str | None:
        with self._Session() as s:
            fila = s.get(Preferencia, key)
        return fila.valor if fila else default

    def set_pref(self, key: str, value: str):
        with self._Session() as s:
            fila = s.get(Preferencia, key)
            if fila:
                fila.valor = value
            else:
                s.add(Preferencia(clave=key, valor=value))
            s.commit()

    # ── profile ─────────────────────────────────────────────
    def get_profile(self) -> dict:
        with self._Session() as s:
            fila = s.get(Perfil, 1)
        if not fila:
            return {
                "name": "",
                "birthdate": "",
                "height_cm": 0.0,
                "sex": "",
                "activity_level": "moderate",
            }
        return {
            "name": fila.nombre or "",
            "birthdate": fila.nacimiento or "",
            "height_cm": float(fila.altura_cm or 0),
            "sex": fila.sexo or "",
            "activity_level": fila.actividad or "moderate",
        }

    def set_profile(
        self, name: str, birthdate: str, height_cm: float, sex: str, activity_level: str
    ):
        with self._Session() as s:
            fila = s.get(Perfil, 1)
            if fila is None:
                fila = Perfil(id=1)
                s.add(fila)
            fila.nombre, fila.nacimiento = name, birthdate
            fila.altura_cm, fila.sexo, fila.actividad = height_cm, sex, activity_level
            s.commit()

    # ── weight_log ──────────────────────────────────────────
    def save_weight(self, kg: float, date_iso: str | None = None):
        """Un pesaje por día: el segundo del mismo día corrige al primero."""
        dia = _fecha(date_iso) if date_iso else _hoy()
        with self._Session() as s:
            fila = s.get(Peso, dia)
            if fila:
                fila.kg = float(kg)
                fila.creado = _now()
            else:
                s.add(Peso(fecha=dia, kg=float(kg), creado=_now()))
            s.commit()

    def delete_weight(self, weight_id):
        """El id es la fecha: la tabla tiene una fila por día."""
        with self._Session() as s:
            s.execute(delete(Peso).where(Peso.fecha == _fecha(weight_id)))
            s.commit()

    def get_weights(self, limit: int = 60) -> list[dict]:
        with self._Session() as s:
            filas = list(s.scalars(select(Peso).order_by(Peso.fecha)))
        return [
            {
                "id": p.fecha.isoformat(),
                "date": p.fecha.isoformat(),
                "kg": float(p.kg),
                "timestamp": _epoch(p.creado),
            }
            for p in filas[-limit:]
        ]

    def get_latest_weight(self) -> float | None:
        with self._Session() as s:
            fila = s.scalar(select(Peso).order_by(Peso.fecha.desc()).limit(1))
        return float(fila.kg) if fila else None

    # ── backup / restore ────────────────────────────────────
    BACKUP_VERSION = 2

    def export_all(self) -> dict:
        with self._Session() as s:
            prefs = {p.clave: p.valor for p in s.scalars(select(Preferencia))}
            entrenos = list(s.scalars(select(Entreno).order_by(Entreno.id)))
            pesos = list(s.scalars(select(Peso).order_by(Peso.fecha)))
        return {
            "app": "ironflet",
            "version": self.BACKUP_VERSION,
            "exported_at": time.time(),
            "profile": self.get_profile(),
            "prefs": prefs,
            "workouts": [
                {
                    "date": e.fecha.isoformat(),
                    "exercise": e.ejercicio,
                    "muscle_group": e.grupo,
                    "phase": e.fase,
                    "sets": e.series,
                    "timestamp": _epoch(e.creado),
                }
                for e in entrenos
            ],
            "weights": [
                {"date": p.fecha.isoformat(), "kg": float(p.kg), "timestamp": _epoch(p.creado)}
                for p in pesos
            ],
        }

    def import_all(self, data: dict, *, wipe: bool = True) -> dict:
        if not isinstance(data, dict) or data.get("app") not in ("ironflet", "ironlog"):
            raise ValueError("Not an IronFlet backup")
        if int(data.get("version") or 0) > self.BACKUP_VERSION:
            raise ValueError(f"Backup version {data.get('version')} is newer than supported")

        counts = {"workouts": 0, "weights": 0, "prefs": 0, "profile": 0}
        with self._Session() as s:
            if wipe:
                s.execute(delete(Entreno))
                s.execute(delete(Peso))
                s.execute(delete(Preferencia))
                s.execute(delete(Perfil))
                s.commit()

            p = data.get("profile") or {}
            if p:
                s.add(
                    Perfil(
                        id=1,
                        nombre=p.get("name", ""),
                        nacimiento=p.get("birthdate", ""),
                        altura_cm=float(p.get("height_cm") or 0),
                        sexo=p.get("sex", ""),
                        actividad=p.get("activity_level", "moderate"),
                    )
                )
                counts["profile"] = 1

            for k, v in (data.get("prefs") or {}).items():
                s.merge(Preferencia(clave=str(k), valor=str(v)))
                counts["prefs"] += 1

            for w in data.get("weights") or []:
                s.merge(
                    Peso(
                        fecha=_fecha(w.get("date")),
                        kg=float(w.get("kg") or 0),
                        creado=_as_local(
                            datetime.fromtimestamp(float(w.get("timestamp") or time.time()))
                        ),
                    )
                )
                counts["weights"] += 1

            for wo in data.get("workouts") or []:
                s.add(
                    Entreno(
                        fecha=_fecha(wo.get("date")),
                        ejercicio=wo.get("exercise", ""),
                        grupo=wo.get("muscle_group", ""),
                        fase=int(wo.get("phase") or 0),
                        series=wo.get("sets") or [],
                        creado=_as_local(
                            datetime.fromtimestamp(float(wo.get("timestamp") or time.time()))
                        ),
                    )
                )
                counts["workouts"] += 1
            s.commit()
        return counts

    # ── destructive operations ──────────────────────────────
    def clear_workouts(self):
        with self._Session() as s:
            s.execute(delete(Entreno))
            s.commit()

    def clear_all(self):
        with self._Session() as s:
            for modelo in (Entreno, Peso, Perfil, Preferencia):
                s.execute(delete(modelo))
            s.commit()

    # ── writes ────────────────────────────────────────────────
    def save_workout(self, entry: WorkoutEntry):
        with self._Session() as s:
            s.add(
                Entreno(
                    fecha=_fecha(entry.date),
                    ejercicio=entry.exercise,
                    grupo=entry.muscle_group,
                    fase=entry.phase,
                    series=entry.sets,
                    creado=_as_local(datetime.fromtimestamp(entry.timestamp)),
                )
            )
            s.commit()

    # ── reads ─────────────────────────────────────────────────
    @staticmethod
    def _to_entries(filas) -> list[WorkoutEntry]:
        return [
            WorkoutEntry(
                date=f.fecha.isoformat(),
                exercise=f.ejercicio,
                muscle_group=f.grupo,
                phase=f.fase,
                sets=f.series or [],
                timestamp=_epoch(f.creado),
            )
            for f in filas
        ]

    def get_all(self) -> list[WorkoutEntry]:
        with self._Session() as s:
            filas = list(
                s.scalars(select(Entreno).order_by(Entreno.fecha.desc(), Entreno.id.desc()))
            )
        return self._to_entries(filas)

    def get_today(self) -> list[WorkoutEntry]:
        with self._Session() as s:
            filas = list(
                s.scalars(
                    select(Entreno).where(Entreno.fecha == _hoy()).order_by(Entreno.id.desc())
                )
            )
        return self._to_entries(filas)

    def get_week_stats(self) -> dict:
        """Sessions / sets / volume over the trailing 7 days.

        The keys are unchanged (`views/home.py` reads all three), but two of
        the values used to lie:

        * `sessions` counted table rows, and `entrenos` holds one row per
          exercise, so a normal six-exercise session was rendered as
          "6 Sessions". It now counts distinct training days, via
          `analytics.session_count`.
        * `sets` and `volume` counted warm-ups as work. Both now go through
          `analytics`, which drops sets flagged `type="warmup"` — warming up
          with the empty bar is not tonnage.

        Rows dated in the future are also excluded now, so a mistyped date
        cannot inflate the week.
        """
        today = _hoy()
        since = today - timedelta(days=7)
        with self._Session() as s:
            rows = list(
                s.scalars(select(Entreno).where(Entreno.fecha >= since, Entreno.fecha <= today))
            )
        entries = self._to_entries(rows)
        return {
            "sessions": analytics.session_count(entries),
            "sets": sum(len(analytics.working_sets(e.sets)) for e in entries),
            "volume": analytics.total_volume(entries),
        }

    def get_streak(self, *, min_sessions: int | None = None) -> int:
        """Consecutive **weeks** hitting a session minimum — weeks, not days.

        The unit changed. This used to count consecutive calendar days with
        any entry, walking back from today, which cannot describe a plan with
        rest days: the streak reset every weekend by design, and returned 0 on
        both rest days after a flawless Mon–Fri week.

        A week now counts when it holds at least `min_sessions` distinct
        training days, and the current, unfinished week is skipped rather than
        failed. See `analytics.training_streak` for the full reasoning.

        `min_sessions` defaults to the **active routine's** own minimum rather
        than a fixed number — see `weekly_session_minimum` for why a fixed one
        cannot be right. Pass it explicitly to grade against something else.
        """
        if min_sessions is None:
            min_sessions = weekly_session_minimum()
        with self._Session() as s:
            dates = list(s.scalars(select(func.distinct(Entreno.fecha))))
        return analytics.training_streak(dates, min_sessions=min_sessions)

    def get_last_sets(self, exercise: str) -> list[dict] | None:
        with self._Session() as s:
            fila = s.scalar(
                select(Entreno)
                .where(Entreno.ejercicio == exercise)
                .order_by(Entreno.fecha.desc(), Entreno.id.desc())
                .limit(1)
            )
        return (fila.series or []) if fila else None

    def get_exercise_history(self, exercise: str, limit: int = 20) -> list[WorkoutEntry]:
        with self._Session() as s:
            filas = list(
                s.scalars(
                    select(Entreno).where(Entreno.ejercicio == exercise).order_by(Entreno.fecha)
                )
            )
        return self._to_entries(filas)[-limit:]

    def get_exercise_summary(self) -> list[dict]:
        resumen: dict[str, dict] = {}
        for w in self.get_all():
            if w.exercise not in resumen:
                resumen[w.exercise] = {
                    "name": w.exercise,
                    "count": 0,
                    "last_date": w.date,
                    "max_weight": 0.0,
                }
            resumen[w.exercise]["count"] += 1
            for x in w.sets:
                peso = x.get("weight") or 0
                if peso > resumen[w.exercise]["max_weight"]:
                    resumen[w.exercise]["max_weight"] = peso
        return sorted(resumen.values(), key=lambda x: x["count"], reverse=True)
