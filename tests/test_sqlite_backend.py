"""El backend SQLite: el único que queda, y el que lleva Alex encima.

Hasta 0.12 este fichero existía para probar una PARIDAD: cada test corría dos
veces, contra SQLite y contra PostgreSQL, porque una fila que se guardara
distinto según el motor era un error de datos silencioso — nada falla, y el
número simplemente está mal meses después.

En 0.13 se jubiló el PC y con él PostgreSQL. La paridad dejó de ser una
pregunta, pero los tests NO se borraron: lo que comprobaban de SQLite sigue
siendo exactamente lo que hay que comprobar, y algunos de ellos (los PRAGMAs,
el redondeo de instantes, la cascada de borrado) documentan trampas que solo
existen en este motor. Lo único que se fue es el segundo parámetro.

Nada aquí importa el bot de Telegram: ya no hay bot que importar.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

import storage
from storage import (
    Entreno,
    Perfil,
    Storage,
    WorkoutEntry,
    is_sqlite_url,
    resolve_db_url,
    running_on_android,
    sqlite_url,
)

TODAY = date.today()

# Slugs used by the cascade test. Prefixed so they cannot collide with the
# seeded catalogue on the shared `entrenador_test` database.
PROBE_SLUG = "zz-parity-probe-food"


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path) -> Storage:
    """Un `Storage` sobre un fichero nuevo por test.

    `tmp_path` es de ámbito función, así que el aislamiento sale gratis: cada
    test estrena base y ninguno puede ensuciar al siguiente. Antes esto estaba
    parametrizado sobre dos motores y la mitad PostgreSQL compartía servidor
    con las demás suites, que es de donde venían los rojos intermitentes.
    """
    return Storage(sqlite_url(tmp_path / "ironflet.db"))


@pytest.fixture
def sqlite_store(tmp_path) -> Storage:
    """SQLite only, for the tests that are about SQLite itself."""
    return Storage(sqlite_url(tmp_path / "ironflet.db"))


def a_set(weight, reps, **extra):
    return {"weight": weight, "reps": reps, **extra}


def log(store: Storage, day: date, exercise: str, sets: list[dict], phase: int = 1):
    store.save_workout(
        WorkoutEntry(
            date=day.isoformat(),
            exercise=exercise,
            muscle_group="Test",
            phase=phase,
            sets=sets,
        )
    )


# ── workouts, and the JSON column that holds the sets ────────────────────


def test_workout_round_trips(store):
    log(store, TODAY, "Squat", [a_set(100.0, 5), a_set(102.5, 3)])

    (entry,) = store.get_all()
    assert entry.date == TODAY.isoformat()
    assert entry.exercise == "Squat"
    assert entry.muscle_group == "Test"
    assert entry.phase == 1
    assert entry.sets == [
        {"weight": 100.0, "reps": 5},
        {"weight": 102.5, "reps": 3},
    ]


def test_json_sets_survive_verbatim(store):
    """The set dict is the payload. Every key, every type, both engines.

    On Postgres `series` is a real `json` column; on SQLite it is TEXT round
    tripped through `json.dumps`/`json.loads`. Floats must not become strings,
    ints must not become floats, and the optional `rir`/`type` keys — absent on
    everything the Telegram coach writes — must come back exactly as stored.
    The unknown key is deliberate: `CLAUDE.md` requires readers to tolerate keys
    they do not know, so the column must not drop them either.
    """
    sets = [
        {"weight": 60.0, "reps": 10, "type": "warmup"},
        {"weight": 102.5, "reps": 8, "rir": 2},
        {"weight": 102.5, "reps": 6, "rir": 0, "type": "failure", "notes": "left knee"},
    ]
    log(store, TODAY, "Bench Press", sets)

    (entry,) = store.get_all()
    assert entry.sets == sets
    stored = entry.sets[1]
    assert isinstance(stored["weight"], float)
    assert isinstance(stored["reps"], int) and not isinstance(stored["reps"], bool)
    assert "rir" not in entry.sets[0]  # absent stays absent, never None-filled
    assert entry.sets[2]["notes"] == "left knee"


def test_empty_set_list_round_trips(store):
    """An exercise logged with no sets is `[]`, never None."""
    log(store, TODAY, "Plank", [])

    (entry,) = store.get_all()
    assert entry.sets == []
    assert store.get_last_sets("Plank") == []


def test_get_last_sets_is_none_for_an_unknown_exercise(store):
    assert store.get_last_sets("Never Done This") is None


def test_history_is_ordered_and_windowed(store):
    """Date ordering and range filtering: SQLite compares ISO date strings.

    It has no date type — `Date` is stored as `YYYY-MM-DD` text and compared
    lexicographically, which is only correct because the format is zero-padded
    ISO. Postgres compares real dates. This asserts the two agree, including
    across a month boundary where a non-padded format would sort wrong.
    """
    for offset in (0, 1, 40):
        log(store, TODAY - timedelta(days=offset), "Squat", [a_set(100.0, 5)])

    history = store.get_exercise_history("Squat")
    assert [h.date for h in history] == [
        (TODAY - timedelta(days=40)).isoformat(),
        (TODAY - timedelta(days=1)).isoformat(),
        TODAY.isoformat(),
    ]

    newest = store.get_all()[0]
    assert newest.date == TODAY.isoformat()


def test_week_stats_match_on_both_engines(store):
    """The home-screen numbers. Sessions are days, warm-ups are not tonnage."""
    for i in range(3):
        log(store, TODAY, f"Exercise {i}", [a_set(60.0, 10, type="warmup"), a_set(100.0, 5)])
    log(store, TODAY - timedelta(days=2), "Squat", [a_set(80.0, 5)])
    log(store, TODAY - timedelta(days=30), "Squat", [a_set(200.0, 5)])  # outside the window

    assert store.get_week_stats() == {"sessions": 2, "sets": 4, "volume": 1900.0}


def test_streak_counts_weeks_on_both_engines(store):
    """`get_streak` reads distinct dates back out of the database.

    On SQLite those arrive as ISO strings unless the result processor turns them
    into `date` objects; `analytics.training_streak` does date arithmetic on
    them, so a string would raise or, worse, compare wrong.
    """
    this_monday = TODAY - timedelta(days=TODAY.weekday())
    for weeks_ago in (1, 2, 3):
        monday = this_monday - timedelta(days=7 * weeks_ago)
        for d in range(5):
            log(store, monday + timedelta(days=d), "Squat", [a_set(100.0, 5)])

    assert store.get_streak() == 3


def test_clear_workouts_leaves_the_rest(store):
    log(store, TODAY, "Squat", [a_set(100.0, 5)])
    store.save_weight(80.0)

    store.clear_workouts()

    assert store.get_all() == []
    assert store.get_latest_weight() == 80.0


# ── body weight ──────────────────────────────────────────────────────────


def test_one_weight_per_day_the_second_corrects_the_first(store):
    """The date is the primary key, so this is an upsert on both engines."""
    store.save_weight(80.0, TODAY.isoformat())
    store.save_weight(79.4, TODAY.isoformat())

    weights = store.get_weights()
    assert len(weights) == 1
    assert weights[0]["kg"] == 79.4
    assert store.get_latest_weight() == 79.4


def test_weights_come_back_in_date_order(store):
    for offset, kg in ((5, 82.0), (0, 80.0), (2, 81.0)):
        store.save_weight(kg, (TODAY - timedelta(days=offset)).isoformat())

    assert [w["kg"] for w in store.get_weights()] == [82.0, 81.0, 80.0]
    assert store.get_latest_weight() == 80.0


def test_delete_weight_takes_the_date(store):
    store.save_weight(80.0, TODAY.isoformat())
    store.save_weight(81.0, (TODAY - timedelta(days=1)).isoformat())

    store.delete_weight(TODAY.isoformat())

    assert [w["kg"] for w in store.get_weights()] == [81.0]


def test_no_weights_is_none_not_zero(store):
    assert store.get_latest_weight() is None
    assert store.get_weights() == []


# ── profile and preferences ──────────────────────────────────────────────


def test_profile_round_trips(store):
    store.set_profile("Alex", "1990-05-14", 178.5, "male", "high")

    assert store.get_profile() == {
        "name": "Alex",
        "birthdate": "1990-05-14",
        "height_cm": 178.5,
        "sex": "male",
        "activity_level": "high",
    }


def test_profile_is_a_single_row_updated_in_place(store):
    store.set_profile("Alex", "1990-05-14", 178.5, "male", "high")
    store.set_profile("Alex", "1990-05-14", 179.0, "male", "moderate")

    with store._Session() as s:
        assert len(list(s.scalars(select(Perfil)))) == 1
    assert store.get_profile()["height_cm"] == 179.0
    assert store.get_profile()["activity_level"] == "moderate"


def test_empty_profile_has_defaults(store):
    assert store.get_profile()["activity_level"] == "moderate"
    assert store.get_profile()["height_cm"] == 0.0


def test_prefs_round_trip(store):
    assert store.get_pref("routine", "cambiatufisico") == "cambiatufisico"
    store.set_pref("routine", "push-pull-legs")
    assert store.get_pref("routine") == "push-pull-legs"
    store.set_pref("routine", "upper-lower")
    assert store.get_pref("routine") == "upper-lower"


# ── backup round trip ────────────────────────────────────────────────────


def test_backup_round_trips_on_both_engines(store):
    """Export on one engine, import on the other: this is the phone↔PC path.

    Only the four tables `export_all` covers, which is what it claims today —
    the nutrition and user-routine tables are not in the payload.
    """
    log(store, TODAY, "Squat", [a_set(100.0, 5, rir=2), a_set(102.5, 3)])
    store.save_weight(80.4, TODAY.isoformat())
    store.set_profile("Alex", "1990-05-14", 178.5, "male", "high")
    store.set_pref("routine", "recomp-ppl-ul")

    payload = store.export_all()

    store.clear_all()
    assert store.get_all() == []

    counts = store.import_all(payload)

    assert counts == {"workouts": 1, "weights": 1, "prefs": 1, "profile": 1}
    (entry,) = store.get_all()
    assert entry.sets == [{"weight": 100.0, "reps": 5, "rir": 2}, {"weight": 102.5, "reps": 3}]
    assert store.get_weights()[0]["kg"] == 80.4
    assert store.get_profile()["name"] == "Alex"
    assert store.get_pref("routine") == "recomp-ppl-ul"


# ── nutrition cascade: the reason PRAGMA foreign_keys exists ─────────────


def test_an_untuned_sqlite_really_does_orphan_the_rows(tmp_path):
    """The negative control: proof the pragma is load-bearing, not decoration.

    Same file, same schema, one engine built by `create_db_engine` and one by
    raw `create_engine`. If this test ever passes with the orphan count at zero,
    SQLite changed its default and the pragma became optional — check before
    deleting anything.
    """
    import routine_builder

    path = tmp_path / "ironflet.db"
    tuned = Storage(sqlite_url(path))
    routine_builder.ensure_tables(tuned)

    # Hasta 0.21 la sonda eran un alimento y su ración. Con la nutrición fuera,
    # la cascada que se prueba es la de las rutinas de usuario — mismo
    # `ondelete="CASCADE"`, misma pregunta, y sigue siendo la que de verdad
    # importa: `user_routine_phases` cuelga de `user_routines`.
    pk = routine_builder.save_draft(tuned, routine_builder.draft_from_builtin("upper-lower"))

    untuned = create_engine(sqlite_url(path))  # no PRAGMA foreign_keys=ON
    with untuned.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 0
        c.exec_driver_sql("PRAGMA busy_timeout=5000")
        antes = c.exec_driver_sql(
            "SELECT COUNT(*) FROM user_routine_phases WHERE routine_id = :i", {"i": pk}
        ).scalar()
        assert antes, "la sonda no dejó fases que huerfanar"
        c.exec_driver_sql("DELETE FROM user_routines WHERE id = :i", {"i": pk})
        c.commit()
        left_behind = c.exec_driver_sql(
            "SELECT COUNT(*) FROM user_routine_phases WHERE routine_id = :i", {"i": pk}
        ).scalar()

    assert left_behind == antes, "SQLite now enforces foreign keys by default — revisit the pragmas"

    # And the tuned engine, on the same file, refuses to leave that behind.
    with tuned._engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


# ── timestamps: the one real behavioural difference ──────────────────────


def test_timestamps_round_trip_to_the_same_instant(store):
    """A workout's `timestamp` must survive the write, on both engines.

    `DateTime(timezone=True)` is a `timestamptz` on Postgres and a naive string
    on SQLite. `storage._as_local` normalises everything to local time on the way
    in and `_epoch` reads naive values as local on the way out, so the pair
    cancels out and both engines return the instant that went in.
    """
    when = datetime(2026, 3, 14, 19, 45, 30).astimezone().timestamp()
    store.save_workout(
        WorkoutEntry(
            date="2026-03-14",
            exercise="Squat",
            muscle_group="Test",
            phase=1,
            sets=[a_set(100.0, 5)],
            timestamp=when,
        )
    )

    (entry,) = store.get_all()
    assert entry.timestamp == pytest.approx(when, abs=1e-3)
    assert store.export_all()["workouts"][0]["timestamp"] == pytest.approx(when, abs=1e-3)


def test_weight_timestamp_round_trips(store):
    before = datetime.now().timestamp()
    store.save_weight(80.0, TODAY.isoformat())
    after = datetime.now().timestamp()

    assert before - 1 <= store.get_weights()[0]["timestamp"] <= after + 1


def test_sqlite_drops_the_offset_so_never_write_utc(sqlite_store):
    """The documented difference, pinned so it cannot surprise anyone twice.

    Writing a **UTC-aware** datetime straight to the column — bypassing
    `_as_local` — stores UTC wall-clock text, which is then read back naive and
    interpreted as *local*. The instant shifts by the local offset. Postgres
    would have kept it. This is why every write in `storage.py` goes through
    `_as_local()` and nothing calls `datetime.now(timezone.utc)`.

    Skipped where the machine runs on UTC: there the offset is zero and there is
    nothing to observe.
    """
    offset = datetime.now().astimezone().utcoffset()
    if not offset:
        pytest.skip("machine is on UTC: the offset this test measures is zero")

    utc_now = datetime.now(timezone.utc)
    with sqlite_store._Session() as s:
        s.add(
            Entreno(
                fecha=TODAY,
                ejercicio="Raw UTC",
                grupo="Test",
                fase=1,
                series=[],
                creado=utc_now,  # deliberately NOT through _as_local
            )
        )
        s.commit()

    (entry,) = sqlite_store.get_all()
    drift = entry.timestamp - utc_now.timestamp()
    assert drift == pytest.approx(-offset.total_seconds(), abs=1e-3)

    # The supported path has no drift at all.
    sqlite_store.clear_workouts()
    sqlite_store.save_workout(
        WorkoutEntry(
            date=TODAY.isoformat(),
            exercise="Squat",
            muscle_group="Test",
            phase=1,
            sets=[],
            timestamp=utc_now.timestamp(),
        )
    )
    (ok,) = sqlite_store.get_all()
    assert ok.timestamp == pytest.approx(utc_now.timestamp(), abs=1e-3)


# ── engine wiring ────────────────────────────────────────────────────────


def test_every_pooled_connection_gets_the_pragmas(sqlite_store):
    """The pragmas are per connection, so the pool must apply them per checkout.

    Two connections are held open at once to force the pool to hand out a second
    one rather than reuse the first.
    """
    engine = sqlite_store._engine
    with engine.connect() as first, engine.connect() as second:
        for c in (first, second):
            assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert c.exec_driver_sql("PRAGMA synchronous").scalar() == 1  # NORMAL
            assert c.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000


def test_sqlite_engine_allows_cross_thread_use(sqlite_store):
    """Flet calls back from more than one thread; pysqlite refuses by default."""
    assert sqlite_store._engine.dialect.name == "sqlite"
    assert sqlite_store.is_sqlite is True
    assert sqlite_store._engine.pool._pre_ping is False

    results: list[int] = []

    def work():
        with sqlite_store._Session() as s:
            results.append(s.execute(text("SELECT 1")).scalar())

    threads = [threading.Thread(target=work) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert results == [1, 1, 1, 1]


def test_missing_parent_directory_is_created(tmp_path):
    """ "unable to open database file" reads like corruption; it is a mkdir."""
    nested = tmp_path / "does" / "not" / "exist" / "ironflet.db"
    almacen = Storage(sqlite_url(nested))
    almacen.save_weight(80.0)

    assert nested.exists()
    assert almacen.get_latest_weight() == 80.0


# ── URL resolution ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Neutralise anything the ambient shell exports into the precedence chain."""
    monkeypatch.delenv("IRONFLET_SQLITE", raising=False)
    monkeypatch.delenv("ANDROID_ROOT", raising=False)
    monkeypatch.delenv("ANDROID_DATA", raising=False)


def test_explicit_url_beats_everything(monkeypatch, tmp_path):
    """An operator who named a database means it — including on a phone."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///from-env.db")
    monkeypatch.setenv("ANDROID_ROOT", "/system")
    monkeypatch.setenv("ANDROID_DATA", "/data")

    assert resolve_db_url("sqlite+pysqlite:///explicit.db") == "sqlite+pysqlite:///explicit.db"


def test_database_url_manda_sobre_la_ruta_por_defecto(monkeypatch):
    """Nombrar una base es una orden, también en el móvil: los tests la usan."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///from-env.db")
    monkeypatch.setenv("ANDROID_ROOT", "/system")
    monkeypatch.setenv("ANDROID_DATA", "/data")

    assert resolve_db_url() == "sqlite+pysqlite:///from-env.db"


def test_android_without_database_url_gets_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ANDROID_ROOT", "/system")
    monkeypatch.setenv("ANDROID_DATA", "/data")
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))

    url = resolve_db_url()

    assert is_sqlite_url(url)
    assert make_url(url).database == str(tmp_path / storage.SQLITE_FILENAME)


def test_sin_database_url_siempre_es_el_sqlite_de_este_dispositivo(monkeypatch, tmp_path):
    """La regla se invirtió en 0.13, y merece quedar escrita.

    Hasta 0.12 este test defendía lo contrario: el escritorio NO debía caer en
    un fichero local, porque hacerlo lo desconectaba en silencio del
    PostgreSQL que compartía con el bot de Telegram. Jubilado el PC, ese
    peligro no existe — no hay base compartida de la que desconectarse — y el
    fichero local pasó de accidente temido a destino correcto.

    `FLET_APP_STORAGE_DATA` sigue decidiendo DÓNDE vive el fichero, nunca SI se
    usa SQLite. Esa parte no cambió.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("IRONFLET_SQLITE", raising=False)
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))

    url = resolve_db_url()
    assert is_sqlite_url(url)
    assert make_url(url).database == str(tmp_path / storage.SQLITE_FILENAME)


def test_ironflet_sqlite_forces_the_mobile_path(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    monkeypatch.setenv("IRONFLET_SQLITE", "1")

    assert make_url(resolve_db_url()).database == str(tmp_path / storage.SQLITE_FILENAME)


def test_ironflet_sqlite_can_name_a_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    target = tmp_path / "elsewhere.db"
    monkeypatch.setenv("IRONFLET_SQLITE", str(target))

    assert make_url(resolve_db_url()).database == str(target)


@pytest.mark.parametrize("falsy", ["", "0", "false", "no"])
def test_ironflet_sqlite_off_cae_en_la_ruta_por_defecto(monkeypatch, falsy, tmp_path):
    """Apagar el forzado no apaga SQLite: solo devuelve la elección de ruta a
    `sqlite_path()`. Antes esto caía en PostgreSQL; ya no hay adónde caer."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("IRONFLET_SQLITE", falsy)
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))

    assert resolve_db_url() == storage.sqlite_url(tmp_path / storage.SQLITE_FILENAME)


def test_sqlite_url_handles_an_absolute_path(tmp_path):
    """Four slashes, not three: `sqlite:///abs` would open a *relative* file."""
    target = tmp_path / "ironflet.db"
    assert sqlite_url(target).startswith("sqlite+pysqlite:////")
    assert make_url(sqlite_url(target)).database == str(target)


def test_android_probe_is_false_on_this_machine():
    """The suite runs on a desktop; if this is ever True the probe is too loose."""
    assert running_on_android() is False


def test_android_probe_needs_both_runtime_variables(monkeypatch):
    """`ANDROID_ROOT` alone shows up in SDK shells that are not phones."""
    monkeypatch.setenv("ANDROID_ROOT", "/system")
    assert running_on_android() is False

    monkeypatch.setenv("ANDROID_DATA", "/data")
    assert running_on_android() is True
