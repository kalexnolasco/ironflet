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

# NOT `from datetime import time`: this module does `import time` at the top for
# `time.time()`, and pulling in `datetime.time` under the same name shadows it —
# `WorkoutEntry.__post_init__` then dies with "type object 'datetime.time' has no
# attribute 'time'" on every single write. Midnight is spelled `datetime.min.time()`
# below instead.
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
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
    text,
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


# ── notes ────────────────────────────────────────────────────────
# Two different notes, and the difference is not cosmetic:
#
# * **An exercise note** belongs to one `entrenos` row — "hole 4 on the
#   backrest", "left wrist complains in supination". It is about that movement
#   on that day, so it lives in that row and dies with it.
# * **A session note** belongs to the day — "slept 5 h, dropped the weights on
#   purpose". It hangs off no exercise: it explains all of them at once, and it
#   must survive deleting or re-logging any single exercise. Hence its own
#   table, keyed by date exactly like `pesos`.
#
# Both are optional everywhere. Six months of history already exist with no
# note, and every row the Telegram coach writes has none either — same rule as
# `rir` and `type`: **absent is normal**, read it with `.get()` on a dict or
# expect `None` off these methods, never assume it is there.

# Longest note kept, in characters. Roughly 200 words — far past anything typed
# between sets, and short enough that a paragraph never becomes a page in the
# history list.
#
# Enforced in Python rather than as `String(1000)` on purpose. Postgres enforces
# a VARCHAR width and SQLite does not (the `Entreno` docstring documents the same
# asymmetry for exercise names), so a DDL limit would mean a long note is stored
# whole on the phone, rejected on the desktop, and blows up later when the row
# travels in a backup. `Text` on both engines plus one truncation point here
# makes the two behave identically: a wall of text is trimmed, never refused.
NOTE_MAX_LEN = 1000


def clean_note(value: str | None) -> str | None:
    """Normalise a note on its way to the database.

    Blank in, `None` out: an empty box and a cleared box are the same intent,
    and storing `""` would make "has a note" true for a note that says nothing.
    """
    if value is None:
        return None
    texto = str(value).strip()
    if not texto:
        return None
    return texto[:NOTE_MAX_LEN].rstrip()


# ── session duration ─────────────────────────────────────────────
# How long the session lasted. The chronometer on the training screen used to be
# pixels and nothing else — `WorkoutView.session_started_at` lives in memory,
# dies with the view, and was never written anywhere. That was tolerable while
# every session was logged as it happened. It stops being tolerable the moment a
# session can be logged for a past day: the clock then measures how long the
# typing took, which is not a fact about any workout.
#
# ## One duration per DAY, not per exercise
#
# The date is the session, exactly as it already is for `pesos` and
# `notas_sesion`. Alex can now date each exercise separately, so "the Monday
# session" is assembled from rows that were entered at different moments — but
# they all carry the same `fecha`, and that shared date is the only thing that
# makes them one session at all. Hanging the duration off the same key is
# therefore not a simplification, it is the same definition of "a session" the
# rest of this schema already uses.
#
# Per-exercise was considered and is wrong in four separate ways:
#
# * **It is not what was measured.** One start, one stop, one span. Nobody times
#   bench press apart from the rest before it; the chronometer starts once.
# * **Six rows would hold six copies of one number.** `get_last_sets` already
#   documents that two rows can exist for one exercise on one day, so re-logging
#   one exercise updates one copy and leaves the day with two answers and
#   nothing to arbitrate between them.
# * **Deleting an exercise would delete the duration** of a session that is
#   still there.
# * **No aggregation is honest.** The sum double-counts nothing and misses the
#   rest *between* exercises, so it is shorter than the session; the max is one
#   exercise's share presented as the whole. Both are guesses, and a guess in
#   this table is indistinguishable from a measurement.
#
# Two sessions in one calendar day collapse into one row, like a second weigh-in
# corrects the first. That is the same trade `pesos` and `notas_sesion` already
# made; when it happens the number reads as "time trained that day", and the UI
# should say so rather than pretend it is one continuous session.
#
# ## Why a table and not a column on `entrenos`
#
# `add_missing_columns()` cannot add a NOT NULL column, and a nullable
# `entrenos.duracion_s` would still be all four problems above. A **table**
# sidesteps the migration question entirely: `create_all()` does create missing
# tables — it is only missing *columns* it ignores — so this appears on an
# existing database, on the phone included, with no hand-written ALTER on either
# side.
#
# ## Absence is normal
#
# Same rule as `rir`, `type` and `nota`: everything already logged and
# everything the Telegram coach writes has no duration, and never will. No row
# means no duration. `get_session_duration()` returns `None` and callers render
# nothing — never `0:00`, which would claim a session took no time.

#: Shortest span that counts as a duration. Anything at or below zero is
#: "no duration" and clears the row, the same way a blank note does.
MIN_SESSION_SECONDS = 1

#: Longest span accepted, in seconds (8 h). Not a limit on ambition — a filter
#: for the two ways a wrong number actually gets here:
#:
#: * a chronometer left running (the app reopened the next morning: 10-14 h);
#: * a slipped finger in a minutes field ("1000" for "100" is 16 h 40).
#:
#: The longest defensible real session — a very long one, heavy singles, long
#: rests, or a meet day — is under six hours, so eight leaves room to be wrong
#: about that and still catch both failures.
MAX_SESSION_SECONDS = 8 * 3600


def clean_duration(value: int | float | None) -> int | None:
    """Normalise a session duration on its way to the database.

    Whole seconds, because that is what a chronometer counts: minutes would
    round every value on the way in, and a float would store sub-second
    precision that means nothing about a workout.

    `None`, `""`, `0` and anything negative all come out `None` — an emptied
    field means "no duration", not "a session that took no time". A caller can
    therefore clear a duration by passing 0, exactly as it clears a note by
    passing "".

    **Over `MAX_SESSION_SECONDS` this raises `ValueError` rather than clamping.**
    Clamping would store a number nobody measured, in the shape of one that was:
    14 h capped to 8 h is not closer to the truth, it is a wrong answer that
    now looks plausible and will be averaged with the real ones forever. This is
    the same call the date picker makes when it refuses a future date instead of
    quietly accepting one nothing would count — a value that will be read as
    data but is not data has to stop and say so.
    """
    if value is None or value == "":
        return None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{value!r} is not a number of seconds") from exc
    if seconds < MIN_SESSION_SECONDS:
        return None
    if seconds > MAX_SESSION_SECONDS:
        raise ValueError(
            f"A session cannot last {format_duration(seconds)} — "
            f"the longest accepted is {format_duration(MAX_SESSION_SECONDS)}"
        )
    return seconds


def format_duration(seconds: int | float | None) -> str:
    """`4320` → `"1h 12m"`. The one rendering of a stored duration.

    Here rather than in a view for the reason `plural()` sits in `shared_ui`:
    three screens will show this number and three hand-rolled formatters would
    disagree about the hour boundary within a month.

    Deliberately **not** the chronometer's `h:mm:ss`. A clock that is still
    running has to show seconds; a session that finished two days ago does not,
    and "1:12:04" invites reading a recorded fact with a precision it does not
    have. Under a minute is reported as `"<1m"` rather than `"0m"`, which would
    read as nothing at all.

    `None` and anything at or below zero give `""` — nothing to show, so the
    caller renders nothing. Never `"0m"`.
    """
    if seconds is None:
        return ""
    total = int(seconds)
    if total < 1:
        return ""
    if total < 60:
        return "<1m"
    hours, minutes = divmod(total // 60, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


@dataclass
class WorkoutEntry:
    date: str
    exercise: str
    muscle_group: str
    phase: int
    sets: list[dict]
    timestamp: float = 0.0
    # Last, and defaulted: every existing construction site — views, tests, the
    # backup importer — keeps working untouched, and `None` is what an entry
    # written by the bot or by an older build genuinely is.
    note: str | None = None

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
    # What happened with *this* exercise on this day. Nullable, and NULL on
    # every row written before this column existed and on everything the
    # Telegram coach writes — see the notes section above.
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotaSesion(Base):
    """One free-text note per training day, about the session as a whole.

    Shaped like `Peso`: the date is the primary key, so writing twice for the
    same day corrects the note instead of stacking two of them.

    `nota` is NOT NULL, which is the whole design — a row exists *because* there
    is something written. Clearing the note deletes the row, so "is there a note
    for this day?" is one existence check and can never be answered by a row
    holding NULL.
    """

    __tablename__ = "notas_sesion"

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    nota: Mapped[str] = mapped_column(Text)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DuracionSesion(Base):
    """How long the training day lasted, in whole seconds.

    Shaped like `NotaSesion` and `Peso`, and for the same reason: the date is
    the primary key, so writing twice for one day corrects the number instead of
    stacking two of them, and the row belongs to the *day* rather than to any
    one `entrenos` row — it survives deleting or re-logging any single exercise.
    See the "session duration" block above for why this is not a column on
    `entrenos`.

    `segundos` is NOT NULL, which is the same design as `notas_sesion.nota`: the
    row exists *because* there is a duration, clearing it deletes the row, and
    "is this session timed?" is one existence check that no row holding NULL can
    muddy. Being a new **table** rather than a new column, that NOT NULL costs
    nothing on an existing database — `create_all()` creates missing tables.

    Nothing here enforces `MAX_SESSION_SECONDS`: the cap is a Python decision
    (`clean_duration`) so both engines behave identically, the same asymmetry
    `NOTE_MAX_LEN` documents. A row written by hand outside the app is read back
    as it is stored, not silently corrected.
    """

    __tablename__ = "duraciones_sesion"

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    segundos: Mapped[int] = mapped_column(Integer)
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


#: Preference keys that must never leave the device.
#:
#: `preferencias` is a general key-value bag and both exporters — the v2
#: `Storage.export_all()` below and the v3 `backup.export_all()` — copy every
#: row into the document verbatim. That was harmless while the only key was
#: `routine`. It stopped being harmless the moment the in-app coach put an
#: Anthropic API key in there: a backup is a plain JSON file Alex sends himself
#: to move devices, and the key would have ridden along in the clear, in a file
#: that ends up in a chat thread or a cloud drive.
#:
#: Excluded on **both** sides. On export because the key must not be written
#: out; on import because a key is bound to the person who created it, not to
#: the training history in the file — restoring someone else's backup, or an
#: old one of his own, must not silently re-point the coach at a different
#: account and bill it.
#:
#: A secret is not the same thing as `workout_draft.EPHEMERAL_PREF_KEYS`, which
#: is about *staleness*, so it gets its own tuple rather than being smuggled
#: into that one under a name that would stop describing it.
#: `agent_api_key` held an Anthropic key before the coach moved to OpenRouter.
#: Nothing reads it any more, and it stays on this list precisely because of
#: that: an install that still carries the row must not quietly start putting it
#: in backup files just because the code stopped caring about it. Removing a name
#: from here is a decision about a credential, never tidying.
SECRET_PREF_KEYS: tuple[str, ...] = ("agent_openrouter_key", "agent_api_key")

#: Which palette to paint in. Read before the first frame in `main.py`; an
#: unknown or missing value falls back to the default rather than raising, so a
#: backup from a build with a palette this one has never heard of still opens.
THEME_PREF = "theme"


class Perfil(Base):
    __tablename__ = "perfil"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    nombre: Mapped[str] = mapped_column(String(120), default="")
    nacimiento: Mapped[str] = mapped_column(String(20), default="")
    altura_cm: Mapped[float] = mapped_column(Float, default=0)
    sexo: Mapped[str] = mapped_column(String(20), default="")
    actividad: Mapped[str] = mapped_column(String(30), default="moderate")


# ── two tables that used to belong only to the Telegram coach ─────────────
#
# `medidas` and `recordatorios` were declared in `../agente/entrenador/modelos.py`
# and nowhere else. The Home screen now shows both — the waist number the plan
# adjusts calories by, and what the coach is going to nag about today — so the
# app has to be able to read them, and reading them means declaring them.
#
# DECLARING THEM PUTS THEM UNDER THE MIRROR RULE. `agente/tests/test_modelos_espejo.py`
# compares metadata for every table present on BOTH sides, so from now on these two
# are compared too: columns, types, nullability, defaults, primary keys, unique
# constraints and indexes all have to match, and a change to either copy without
# the other is a silent schema divergence. They are transcribed from the bot
# character for character, including the things that look incidental:
#
#   * `clave` is UNIQUE — that is what stops the coach creating two copies of a
#     fixed reminder when it restarts.
#   * `proxima` and `activo` are INDEXED — the bot's due-query filters on both.
#   * the `default=`s are Python-side, not DDL. They still have to match, because
#     the mirror test compares them.
#
# On the phone these two tables will normally be EMPTY, and that is not a bug:
# the coach runs on the PC against PostgreSQL and is what writes them. The app
# can write `medidas` itself (see `save_measurement`) precisely so the waist
# panel is not dead weight on a device the bot cannot reach; `recordatorios`
# stays read-only here, because deciding when something fires is the bot's job
# and two schedulers writing one table is how a reminder fires twice.
class Recordatorio(Base):
    __tablename__ = "recordatorios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    texto: Mapped[str] = mapped_column(Text)
    proxima: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    clave: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    origen: Mapped[str] = mapped_column(String(20), default="usuario")
    plantilla: Mapped[str | None] = mapped_column(String(40), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Medida(Base):
    __tablename__ = "medidas"

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    cintura: Mapped[float | None] = mapped_column(Float, nullable=True)
    cadera: Mapped[float | None] = mapped_column(Float, nullable=True)
    pecho: Mapped[float | None] = mapped_column(Float, nullable=True)
    brazo: Mapped[float | None] = mapped_column(Float, nullable=True)
    muslo: Mapped[float | None] = mapped_column(Float, nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True))


#: The coach's clock. `agente/entrenador/config.py` sets `TZ =
#: ZoneInfo("Europe/Madrid")` and evaluates every cron expression in it, so any
#: question about *its* schedule has to be asked in that zone. Resolved lazily
#: and with a fallback because the IANA database is not guaranteed to be
#: readable on Android — the phone never reaches this path (reminders need
#: PostgreSQL), but an import-time explosion there would take the whole app down
#: for a feature it does not even show.
_MADRID_CACHE: list = []


def _madrid():
    if not _MADRID_CACHE:
        try:
            from zoneinfo import ZoneInfo

            _MADRID_CACHE.append(ZoneInfo("Europe/Madrid"))
        except Exception:  # pragma: no cover - no tzdata on this platform
            _MADRID_CACHE.append(datetime.now().astimezone().tzinfo or timezone.utc)
    return _MADRID_CACHE[0]


def _hoy() -> date:
    return date.today()


def _fecha(valor: str | date) -> date:
    return date.fromisoformat(valor) if isinstance(valor, str) else valor


def add_missing_columns(engine: Engine) -> list[str]:
    """Add declared columns that an existing table does not have yet.

    **This is the migration step this project does not otherwise have**, and it
    exists because `create_all()` creates missing *tables* and silently ignores
    missing *columns*. Adding one column to a model therefore works perfectly on
    every fresh database — every test, every new install — and breaks every
    database that already exists, with `no such column` on the first read.

    That is not hypothetical. `entrenos.nota` was added and, on the next start,
    every query against `entrenos` failed: History, Home and the training screen
    all read it. On the PC that is fixable with one `ALTER TABLE` typed by hand.
    **On the phone it is not** — the APK carries its own SQLite file, it survives
    app updates, and there is no console. The alternative was asking Alex to
    export a backup, uninstall, reinstall and restore on every schema change,
    which works right up to the first time he forgets.

    Deliberately narrow, because a migration that guesses is worse than none:

    * **Only ever ADDs.** Never drops, never renames, never changes a type. The
      failure mode of a wrong guess here is deleted training history.
    * **Only nullable columns without a server default.** A `NOT NULL` column
      cannot be added to a table with rows in it, so those are reported and
      skipped rather than half-applied — a schema change that needs thought
      should stop and get it.
    * **Idempotent**, so it is safe on every start, and cheap: one metadata read
      per table, no writes when there is nothing to add.

    Returns the `table.column` names it added, so a caller can log them. Never
    raises: a database that will not describe itself must not stop the app from
    opening, and the query that needs the column will say so far more clearly
    than a crash at import time.
    """
    added: list[str] = []
    try:
        from sqlalchemy import inspect as sa_inspect

        inspector = sa_inspect(engine)
        existing_tables = set(inspector.get_table_names())
    except Exception:  # pragma: no cover - a database that cannot be inspected
        return added

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all made it, so it is already complete
        try:
            present = {c["name"] for c in inspector.get_columns(table.name)}
        except Exception:  # pragma: no cover
            continue
        for column in table.columns:
            if column.name in present:
                continue
            if not column.nullable or column.server_default is not None:
                # Needs a considered migration, not a guess. Left alone on
                # purpose: the query that wants it will fail loudly and name it.
                continue
            tipo = column.type.compile(engine.dialect)
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {tipo}')
                    )
            except Exception:  # pragma: no cover - raced with another process
                continue
            added.append(f"{table.name}.{column.name}")
    return added


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
        add_missing_columns(self._engine)

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

    # ── body measurements ───────────────────────────────────
    #: The five columns of `medidas`, app-facing name → column name. Waist is
    #: the one the plan acts on; the rest are here because the row already has
    #: them and dropping them on save would delete what the coach recorded.
    MEASUREMENTS = {
        "waist": "cintura",
        "hip": "cadera",
        "chest": "pecho",
        "arm": "brazo",
        "thigh": "muslo",
    }

    def save_measurement(self, on_date: str | date | None = None, **values) -> dict:
        """Record one or more tape measurements. **Omitted fields are left alone.**

        That is the whole subtlety. `medidas` has one row per date and five
        columns, the Telegram coach fills all five at a check-in, and this app
        realistically only ever asks for the waist — the number the plan adjusts
        calories by. Writing a fresh row with the other four unset would silently
        delete a fortnight's measurements to record one of them.

        So: `None` means "not measured now", not "measured as nothing". Pass a
        number to set a field; pass nothing to keep whatever is there.

        Raises `ValueError` on an unknown field or an implausible number, because
        a typo'd 8.5 cm waist that quietly becomes the new baseline is worse than
        a rejected save.
        """
        dia = _fecha(on_date) if on_date else _hoy()

        limpio: dict[str, float] = {}
        for nombre, valor in values.items():
            if nombre not in self.MEASUREMENTS:
                raise ValueError(f"Unknown measurement {nombre!r}.")
            if valor is None or valor == "":
                continue
            try:
                numero = float(valor)
            except (TypeError, ValueError):
                raise ValueError(f"{nombre}: {valor!r} is not a number.") from None
            # Centimetres. A human waist is not 8 cm and not 400.
            if not 20 <= numero <= 250:
                raise ValueError(f"{nombre}: {numero:g} cm is outside 20–250.")
            limpio[nombre] = round(numero, 1)

        if not limpio:
            raise ValueError("Nothing to save.")

        with self._Session() as s:
            fila = s.get(Medida, dia)
            if fila is None:
                fila = Medida(fecha=dia, creado=_now())
                s.add(fila)
            for nombre, numero in limpio.items():
                setattr(fila, self.MEASUREMENTS[nombre], numero)
            fila.creado = _now()
            s.commit()
        return {"date": dia.isoformat(), **limpio}

    def get_measurements(self, limit: int = 60) -> list[dict]:
        """Oldest first, same shape and ordering convention as `get_weights`."""
        with self._Session() as s:
            filas = list(s.scalars(select(Medida).order_by(Medida.fecha)))
        return [
            {
                "date": m.fecha.isoformat(),
                **{
                    nombre: (None if getattr(m, col) is None else float(getattr(m, col)))
                    for nombre, col in self.MEASUREMENTS.items()
                },
                "timestamp": _epoch(m.creado),
            }
            for m in filas[-limit:]
        ]

    def get_latest_measurement(self, field: str = "waist") -> dict | None:
        """The newest row that actually carries `field`.

        Not simply the newest row: a check-in that recorded only the chest would
        otherwise answer "no waist on record" while a perfectly good waist sat
        two rows down. The date comes back with it, because a waist from March
        is a different fact from a waist from Sunday.
        """
        if field not in self.MEASUREMENTS:
            raise ValueError(f"Unknown measurement {field!r}.")
        columna = getattr(Medida, self.MEASUREMENTS[field])
        with self._Session() as s:
            fila = s.scalar(
                select(Medida).where(columna.is_not(None)).order_by(Medida.fecha.desc()).limit(1)
            )
        if fila is None:
            return None
        return {
            "date": fila.fecha.isoformat(),
            field: float(getattr(fila, self.MEASUREMENTS[field])),
        }

    # ── reminders ────────────────────────────────────────────
    def bot_delivers_reminders(self) -> bool:
        """¿Quién entrega los avisos de esta base — el bot o el móvil?

        PostgreSQL compartido: el bot de Telegram sondea `vencidos()` cada 30 s
        y entrega él; esta app no debe tocar `proxima` ahí (dos planificadores
        sobre una tabla es como un aviso suena dos veces). SQLite en el móvil:
        no hay bot; los entrega Android vía `notificaciones.py`, y `proxima` la
        refresca la propia app.

        Esto ERA la puerta que apagaba la tarjeta de avisos en el móvil, cuando
        el móvil no tenía forma de entregar ninguno. Ya la tiene, así que la
        tarjeta se enseña en los dos sitios y esta pregunta solo decide quién
        reparte y qué se puede editar.
        """
        try:
            return not is_sqlite_url(str(self._engine.url))
        except Exception:  # pragma: no cover - defensive
            return False

    def get_reminders_today(self, now: datetime | None = None) -> list[dict]:
        """What the coach is still going to send today, soonest first.

        **Not "today's reminders".** `proxima` holds ONE instant — the next
        occurrence — so the 06:45 weigh-in nudge that already went out this
        morning now reads as tomorrow 06:45 and is correctly absent here.
        Anything else would mean re-implementing the bot's cron expander in this
        repo, including its vixie-cron rule that day-of-month and day-of-week
        are OR'd when both are restricted, and then hoping the two agree.

        Deliberately **no lower bound**, which mirrors `db.vencidos()` on the bot
        side: an active reminder whose instant is already past has not been sent
        and will go out on the next 30-second tick. Filtering those away would
        hide the backlog the coach is about to deliver. They come back flagged
        `overdue`.

        The day boundary is **Europe/Madrid**, which is neither UTC nor the
        device's timezone. The bot's cron is evaluated in Madrid wall-clock, so
        `45 6 * * *` is 06:45 there all year and its UTC value moves with DST;
        a window built in any other zone is an hour wrong on the two changeover
        Sundays, which is exactly when the 06:45 and 21:45 rows sit near it.
        """
        zona = _madrid()
        ahora = (now or datetime.now(timezone.utc)).astimezone(zona)
        hoy = ahora.date()
        # `datetime.combine(day + 1, time.min)`, never `inicio + timedelta(days=1)`
        # on an aware datetime: the second one adds 24 hours, and a DST day is
        # not 24 hours long.
        inicio = datetime.combine(hoy, datetime.min.time(), tzinfo=zona)
        fin = datetime.combine(hoy + timedelta(days=1), datetime.min.time(), tzinfo=zona)

        with self._Session() as s:
            filas = list(
                s.scalars(
                    select(Recordatorio)
                    .where(Recordatorio.activo.is_(True), Recordatorio.proxima < fin)
                    .order_by(Recordatorio.proxima)
                )
            )

        salida = []
        for r in filas:
            cuando = r.proxima
            if cuando.tzinfo is None:  # SQLite hands back naive values
                cuando = cuando.replace(tzinfo=timezone.utc)
            local = cuando.astimezone(zona)
            salida.append(
                {
                    "id": r.id,
                    # For a row with a `plantilla` the coach regenerates the body
                    # at send time, so this is a title, not the message he will
                    # receive. The view labels it as such.
                    "text": r.texto,
                    "at": local.strftime("%H:%M"),
                    "when": local.isoformat(),
                    "overdue": local < inicio,
                    "recurring": bool(r.cron),
                    "fixed": r.origen == "fijo",
                    "template": r.plantilla,
                }
            )
        return salida

    def get_all_reminders(self) -> list[dict]:
        """Todas las filas, activas o no, para la pantalla de gestión."""
        with self._Session() as se:
            filas = list(se.scalars(select(Recordatorio).order_by(Recordatorio.proxima)))
        return [
            {
                "id": r.id,
                "texto": r.texto,
                "proxima": r.proxima,
                "cron": r.cron,
                "clave": r.clave,
                "origen": r.origen,
                "plantilla": r.plantilla,
                "activo": bool(r.activo),
            }
            for r in filas
        ]

    def add_reminder(self, texto: str, proxima: datetime, cron: str | None = None) -> int:
        """Alta de un aviso del usuario. Devuelve el id de la fila.

        Siempre `origen="usuario"` y sin `clave`: las filas `fijo` las siembra
        el bot con su clave de idempotencia, y una fila fija creada desde aquí
        colisionaría con esa siembra en el arranque siguiente del bot.
        """
        limpio = (texto or "").strip()
        if not limpio:
            raise ValueError("El aviso necesita un texto.")
        if proxima.tzinfo is None:
            raise ValueError("`proxima` debe llevar zona horaria.")
        with self._Session() as se:
            fila = Recordatorio(
                texto=limpio[:500],
                proxima=proxima,
                cron=cron,
                origen="usuario",
                activo=True,
                creado=datetime.now(timezone.utc),
            )
            se.add(fila)
            se.commit()
            return fila.id

    def delete_reminder(self, rid: int) -> bool:
        """Borra un aviso **del usuario**. Los `fijo` no se tocan desde la app.

        Son la siembra del bot (pesaje, entreno, sueño, check-in): borrarlos
        aquí en el PC solo haría que el bot los re-sembrara en su siguiente
        arranque, con otro id — un borrado que parece funcionar y no funciona.
        Se devuelve False en vez de lanzar: la fila puede haber desaparecido
        entre el render y el toque.
        """
        with self._Session() as se:
            fila = se.get(Recordatorio, int(rid))
            if fila is None or fila.origen == "fijo":
                return False
            se.delete(fila)
            se.commit()
            return True

    def set_reminder_active(self, rid: int, activo: bool) -> bool:
        """Pausa o reactiva un aviso del usuario (los `fijo` son del bot)."""
        with self._Session() as se:
            fila = se.get(Recordatorio, int(rid))
            if fila is None or fila.origen == "fijo":
                return False
            fila.activo = bool(activo)
            se.commit()
            return True

    def touch_reminder(self, rid: int, proxima: datetime) -> None:
        """Refresca `proxima` tras materializar ocurrencias — **solo en SQLite**.

        Lo llama `notificaciones.sync()`, que ya ha comprobado el backend: en el
        PostgreSQL compartido `proxima` la avanza el bot al disparar, y un
        segundo escritor es como un aviso acaba sonando dos veces.
        """
        with self._Session() as se:
            fila = se.get(Recordatorio, int(rid))
            if fila is not None:
                fila.proxima = proxima
                se.commit()

    # ── notes ───────────────────────────────────────────────
    def get_session_note(self, on_date: str | date | None = None) -> str | None:
        """The whole-session note for a day, or `None` when there is none.

        `None` is the normal answer: no day has one until Alex writes it, and no
        day the coach logged ever will.
        """
        dia = _fecha(on_date) if on_date else _hoy()
        with self._Session() as s:
            fila = s.get(NotaSesion, dia)
        return fila.nota if fila else None

    def set_session_note(self, note: str | None, on_date: str | date | None = None) -> str | None:
        """Write (or clear) the session note for a day. Returns what was stored.

        Blank or `None` deletes the row — an emptied box means "no note", not "a
        note that is empty". The return value is the text **as stored**, so a
        caller that sent more than `NOTE_MAX_LEN` characters can render the
        trimmed version back instead of showing text the database does not hold.

        Needs no workout rows: a session note can be written for a day with
        nothing logged yet, and stays put when the exercises are logged later.
        """
        dia = _fecha(on_date) if on_date else _hoy()
        limpia = clean_note(note)
        with self._Session() as s:
            fila = s.get(NotaSesion, dia)
            if limpia is None:
                if fila:
                    s.delete(fila)
            elif fila:
                fila.nota = limpia
                fila.creado = _now()
            else:
                s.add(NotaSesion(fecha=dia, nota=limpia, creado=_now()))
            s.commit()
        return limpia

    def get_session_notes(self, limit: int = 60) -> list[dict]:
        """The most recent session notes, oldest first. Same shape as `get_weights`."""
        with self._Session() as s:
            filas = list(s.scalars(select(NotaSesion).order_by(NotaSesion.fecha)))
        return [
            {"date": n.fecha.isoformat(), "note": n.nota, "timestamp": _epoch(n.creado)}
            for n in filas[-limit:]
        ]

    def get_exercise_note(self, exercise: str, on_date: str | date | None = None) -> str | None:
        """The note attached to one exercise on one day, or `None`.

        Reads the newest row for that pair, the same way `get_last_sets` picks
        its row: nothing stops two rows existing for one exercise on one day, and
        the last one written is the one on screen.
        """
        dia = _fecha(on_date) if on_date else _hoy()
        with self._Session() as s:
            fila = s.scalar(
                select(Entreno)
                .where(Entreno.ejercicio == exercise, Entreno.fecha == dia)
                .order_by(Entreno.id.desc())
                .limit(1)
            )
        return fila.nota if fila else None

    def set_exercise_note(
        self, exercise: str, note: str | None, on_date: str | date | None = None
    ) -> bool:
        """Attach (or clear) a note on a logged exercise. `False` if there is no row.

        The note lives *in* the `entrenos` row, so there has to be one: this
        cannot invent a workout. `False` means "that exercise is not logged on
        that date" — the caller either logs it first (`WorkoutEntry.note` carries
        a note in with the sets) or writes a session note instead. Returning it
        rather than raising keeps the failure visible without a `try` at every
        call site.
        """
        dia = _fecha(on_date) if on_date else _hoy()
        limpia = clean_note(note)
        with self._Session() as s:
            fila = s.scalar(
                select(Entreno)
                .where(Entreno.ejercicio == exercise, Entreno.fecha == dia)
                .order_by(Entreno.id.desc())
                .limit(1)
            )
            if fila is None:
                return False
            fila.nota = limpia
            s.commit()
        return True

    def get_day_notes(self, on_date: str | date | None = None) -> dict:
        """Everything written about one day, in one call and one session.

        `{"session": str | None, "exercises": {exercise: note}}`. Only exercises
        that actually have a note appear in the inner dict, so it is read with
        `.get(name)` and a missing key is the normal case, not an error.
        """
        dia = _fecha(on_date) if on_date else _hoy()
        with self._Session() as s:
            sesion = s.get(NotaSesion, dia)
            filas = list(
                s.scalars(select(Entreno).where(Entreno.fecha == dia).order_by(Entreno.id))
            )
        return {
            "session": sesion.nota if sesion else None,
            "exercises": {f.ejercicio: f.nota for f in filas if f.nota},
        }

    # ── session duration ────────────────────────────────────
    def get_session_duration(self, on_date: str | date | None = None) -> int | None:
        """How long that day's session lasted, in seconds, or `None`.

        `None` is the ordinary answer and always will be for most days: every
        session logged before this existed has no duration, and neither does
        anything the Telegram coach writes. Render nothing for it — never
        `"0m"`, which claims a workout took no time.
        """
        dia = _fecha(on_date) if on_date else _hoy()
        with self._Session() as s:
            fila = s.get(DuracionSesion, dia)
        return int(fila.segundos) if fila else None

    def set_session_duration(
        self, seconds: int | float | None, on_date: str | date | None = None
    ) -> int | None:
        """Write (or clear) the duration of a day's session. Returns what was stored.

        `None` or anything at or below zero deletes the row: an emptied field
        means "no duration", and a row saying zero would be a session that took
        no time. The return value is the number **as stored**, so a caller can
        render it back instead of the value it sent.

        Raises `ValueError` when the span is longer than `MAX_SESSION_SECONDS` —
        see `clean_duration` for why that is a refusal and not a clamp. The
        message is user-facing English and can be shown as it is.

        Needs no workout rows, like `set_session_note`. That matters more here
        than it does for notes: with the date now chosen per exercise, the
        duration can be set before the first exercise of that day is logged,
        and it stays put as the exercises arrive.
        """
        dia = _fecha(on_date) if on_date else _hoy()
        limpio = clean_duration(seconds)
        with self._Session() as s:
            fila = s.get(DuracionSesion, dia)
            if limpio is None:
                if fila:
                    s.delete(fila)
            elif fila:
                fila.segundos = limpio
                fila.creado = _now()
            else:
                s.add(DuracionSesion(fecha=dia, segundos=limpio, creado=_now()))
            s.commit()
        return limpio

    def get_session_durations(self, limit: int = 60) -> list[dict]:
        """The most recent timed days, oldest first. Same shape as `get_weights`.

        `{"date": iso, "seconds": int, "timestamp": float}`. Only days that were
        actually timed appear, so the list is shorter than the training history
        and a missing day is the normal case, not a gap to explain.
        """
        with self._Session() as s:
            filas = list(s.scalars(select(DuracionSesion).order_by(DuracionSesion.fecha)))
        return [
            {"date": d.fecha.isoformat(), "seconds": int(d.segundos), "timestamp": _epoch(d.creado)}
            for d in filas[-limit:]
        ]

    def get_duration_map(self) -> dict[str, int]:
        """Every timed day as `{iso date: seconds}`, in one query.

        For a screen that renders many days at once: History would otherwise ask
        per card, which is one round trip per session on a list that can be a
        year long. Unlimited on purpose — the table holds at most one small row
        per training day, so a full year is a couple of hundred rows, and a
        `limit` here would silently blank the durations on the oldest cards
        while the rest of the card rendered fine.

        Read it with `.get(iso)`: a day with no row is a day that was not timed.
        """
        with self._Session() as s:
            filas = list(s.scalars(select(DuracionSesion)))
        return {d.fecha.isoformat(): int(d.segundos) for d in filas}

    # ── backup / restore ────────────────────────────────────
    BACKUP_VERSION = 2

    def export_all(self) -> dict:
        with self._Session() as s:
            prefs = {
                p.clave: p.valor
                for p in s.scalars(select(Preferencia))
                if p.clave not in SECRET_PREF_KEYS
            }
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
                # Everything except the secrets: a key belongs to this device
                # and this person, not to the document being restored. Wiping
                # it would log the coach out on the exact operation people
                # perform when they have just moved to a new phone and are
                # least able to go and find the key again.
                s.execute(delete(Preferencia).where(Preferencia.clave.notin_(SECRET_PREF_KEYS)))
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
                # Belt and braces with the export side: a document written
                # before `SECRET_PREF_KEYS` existed still carries the key, and
                # importing one must not point this device's coach at whoever
                # made that backup — nor bill them for it.
                if str(k) in SECRET_PREF_KEYS:
                    continue
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
                        # v2 documents have no notes and never will — this is the
                        # frozen four-table format. Read anyway, with `.get()`, so
                        # a hand-assembled document that carries one is not
                        # silently stripped. `notas_sesion` and
                        # `duraciones_sesion` are deliberately left alone by this
                        # importer: a v2 file cannot restore either, so wiping
                        # them here would destroy data with nothing to put back.
                        # Use `backup.py` for a full restore.
                        nota=clean_note(wo.get("note")),
                    )
                )
                counts["workouts"] += 1
            s.commit()
        return counts

    # ── destructive operations ──────────────────────────────
    def clear_workouts(self):
        """Drop the training history — session notes and durations included.

        A session note is *about* a session: leaving `notas_sesion` behind would
        keep "slept 5 h, dropped the weights" for a day with no workout left to
        explain, and the next export would carry it to the new phone. A duration
        is about a session in exactly the same way — "1h 12m" for a day with no
        exercises left is a session that, as far as this database is concerned,
        never happened.
        """
        with self._Session() as s:
            s.execute(delete(Entreno))
            s.execute(delete(NotaSesion))
            s.execute(delete(DuracionSesion))
            s.commit()

    def clear_all(self):
        with self._Session() as s:
            for modelo in (Entreno, NotaSesion, DuracionSesion, Peso, Perfil, Preferencia):
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
                    nota=clean_note(entry.note),
                )
            )
            s.commit()

    def replace_workout(self, entry: WorkoutEntry) -> int:
        """Save `entry`, replacing any row already holding that exercise/date.

        `save_workout()` always INSERTs, which is right for the training screen:
        it owns the session it is writing and writes it once. It is wrong for
        anything that can be *re-*submitted — the in-app coach's confirmation
        card, where Alex can tap Save, notice a typo, correct it and tap Save
        again. Two rows for one exercise on one day double every metric that
        sums them, and nothing raises: `entrenos` has no unique constraint on
        (fecha, ejercicio) because a superset legitimately produces two rows
        under different names.

        Returns how many rows it removed, so a caller can say "replaced" rather
        than "saved" and Alex can see that something was overwritten.
        """
        day = _fecha(entry.date)
        with self._Session() as s:
            existing = list(
                s.scalars(
                    select(Entreno).where(Entreno.fecha == day, Entreno.ejercicio == entry.exercise)
                )
            )
            for fila in existing:
                s.delete(fila)
            s.add(
                Entreno(
                    fecha=day,
                    ejercicio=entry.exercise,
                    grupo=entry.muscle_group,
                    fase=entry.phase,
                    series=entry.sets,
                    creado=_as_local(datetime.fromtimestamp(entry.timestamp)),
                    nota=clean_note(entry.note),
                )
            )
            s.commit()
        return len(existing)

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
                note=f.nota,
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

    def get_last_sets(self, exercise: str, before: date | None = None) -> list[dict] | None:
        """The sets from the previous time `exercise` was trained.

        `before` is the date of the session being *logged*, and it exists
        because sessions are not always logged on the day they happened —
        forgetting the phone at home and typing Monday's workout in on
        Wednesday is a case this app supports on purpose.

        Without it the query returns the newest row in the table, full stop, so
        back-dating Monday would prefill it with Wednesday's numbers: weights
        from a session that, from Monday's point of view, has not happened yet.
        Silently wrong in the worst place, since the prefill is what gets
        confirmed with one tap and becomes the record.

        Left optional and defaulting to the old behaviour: today's session,
        which is the common case, wants the latest row and passing nothing
        still gets it.
        """
        with self._Session() as s:
            consulta = select(Entreno).where(Entreno.ejercicio == exercise)
            if before is not None:
                # Strictly earlier: a row already saved for the same day is
                # this very session being edited, not the previous one.
                consulta = consulta.where(Entreno.fecha < before)
            fila = s.scalar(consulta.order_by(Entreno.fecha.desc(), Entreno.id.desc()).limit(1))
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
