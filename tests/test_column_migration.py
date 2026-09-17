"""Adding a column must not break the databases that already exist.

`create_all()` creates missing **tables** and silently ignores missing
**columns**. So adding one to a model works on every fresh database — every
test, every new install, every CI run — and breaks every database that is
already out there, on the first read, with `no such column`.

That is what `entrenos.nota` did. Every query against `entrenos` failed, which
is History, Home and the training screen. On the PC one `ALTER TABLE` fixes it.
**On the phone there is no console**: the APK carries its own SQLite file, it
survives app updates, and the only other route was "export a backup, uninstall,
reinstall, restore" — which works right up to the first time it is forgotten.

The whole suite is blind to this by construction: fixtures build fresh
databases, and a fresh database is exactly the case that never breaks. These
tests build an **old** one on purpose.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

from storage import Base, Storage, add_missing_columns, sqlite_url

# `entrenos` as it was shipped before the notes column existed, plus a row, so
# the test also proves the data survives.
ESQUEMA_VIEJO = """
CREATE TABLE entrenos (
  id INTEGER PRIMARY KEY, fecha DATE, ejercicio VARCHAR(120),
  grupo VARCHAR(120), fase INTEGER, series TEXT, creado TIMESTAMP
);
INSERT INTO entrenos (fecha, ejercicio, grupo, fase, series, creado)
VALUES ('2026-08-10','Barbell Bench Press','Chest',2,
        '[{"weight": 60, "reps": 8}]','2026-08-10 10:00:00');
CREATE TABLE preferencias (clave VARCHAR(60) PRIMARY KEY, valor TEXT);
INSERT INTO preferencias VALUES ('routine','cambiatufisico');
"""


@pytest.fixture
def base_vieja(tmp_path):
    """A SQLite file with the pre-notes schema, like the one on Alex's phone."""
    ruta = tmp_path / "ironflet.db"
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA_VIEJO)
    con.commit()
    con.close()
    return ruta


# ── the regression ───────────────────────────────────────────────────────


def test_abrir_una_base_vieja_no_revienta(base_vieja):
    """THE UPGRADE. Without the migration this raises `no such column`."""
    store = Storage(sqlite_url(base_vieja))
    filas = store.get_all()
    assert len(filas) == 1, "the workout that was already there disappeared"
    assert filas[0].exercise == "Barbell Bench Press"
    assert filas[0].sets == [{"weight": 60, "reps": 8}]


def test_los_datos_que_ya_estaban_no_se_tocan(base_vieja):
    store = Storage(sqlite_url(base_vieja))
    assert store.get_pref("routine") == "cambiatufisico"
    assert store.get_all()[0].note is None, "an absent note must read as None, not as junk"


def test_la_columna_nueva_queda_utilizable(base_vieja):
    store = Storage(sqlite_url(base_vieja))
    store.set_exercise_note("Barbell Bench Press", "seat on hole 4", "2026-08-10")
    assert store.get_exercise_note("Barbell Bench Press", "2026-08-10") == "seat on hole 4"


def test_es_idempotente(base_vieja):
    store = Storage(sqlite_url(base_vieja))
    assert add_missing_columns(store._engine) == [], "second pass tried to add something again"


def test_declara_lo_que_anade(tmp_path):
    """The return value is what a caller would log, so it must be truthful."""
    ruta = tmp_path / "x.db"
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA_VIEJO)
    con.commit()
    con.close()
    engine = create_engine(sqlite_url(ruta))
    anadidas = add_missing_columns(engine)
    assert "entrenos.nota" in anadidas


# ── the guard rails ──────────────────────────────────────────────────────


def test_no_toca_una_tabla_que_no_existe(tmp_path):
    """Missing tables are `create_all`'s job; this must not invent them."""
    ruta = tmp_path / "vacia.db"
    sqlite3.connect(ruta).close()
    engine = create_engine(sqlite_url(ruta))
    assert add_missing_columns(engine) == []
    assert inspect(engine).get_table_names() == []


def test_no_borra_una_columna_de_mas(tmp_path):
    """A column the models no longer declare must be left alone.

    Dropping it is how a migration deletes training history, and this one is
    additive by design.
    """
    ruta = tmp_path / "extra.db"
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA_VIEJO)
    con.execute("ALTER TABLE entrenos ADD COLUMN campo_viejo TEXT")
    con.execute("UPDATE entrenos SET campo_viejo = 'no me borres'")
    con.commit()
    con.close()

    engine = create_engine(sqlite_url(ruta))
    add_missing_columns(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT campo_viejo FROM entrenos")).scalar() == "no me borres"


def test_una_base_ilegible_no_impide_arrancar(tmp_path):
    """A database that will not describe itself must not stop the app opening."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    engine.dispose()  # cerrado a propósito
    assert isinstance(add_missing_columns(engine), list)


def test_todas_las_columnas_declaradas_acaban_existiendo(base_vieja):
    """Not just `nota`: whatever the models declare for `entrenos` must be there.

    Written against the metadata rather than a hardcoded list so the next added
    column is covered without anyone remembering to come back here.
    """
    store = Storage(sqlite_url(base_vieja))
    tabla = Base.metadata.tables["entrenos"]
    presentes = {c["name"] for c in inspect(store._engine).get_columns("entrenos")}
    faltan = {c.name for c in tabla.columns if c.nullable} - presentes
    assert not faltan, f"declared but still missing after the migration: {sorted(faltan)}"


# ── a new TABLE, which is a different problem ────────────────────────────


def test_una_tabla_nueva_aparece_en_una_base_vieja(base_vieja):
    """`duraciones_sesion` did not exist when Alex's phone wrote this file.

    A missing table is the half of the problem `create_all()` *does* solve, and
    that is exactly why the session duration is a table and not a column on
    `entrenos`: a new NOT NULL column would have been skipped by
    `add_missing_columns` (see the test below) and every read of the table would
    have failed on the first start after the update.
    """
    store = Storage(sqlite_url(base_vieja))
    assert "duraciones_sesion" in inspect(store._engine).get_table_names()

    store.set_session_duration(4320, "2026-08-10")
    assert store.get_session_duration("2026-08-10") == 4320
    # …and the workout that was already in the file is still there.
    assert len(store.get_all()) == 1


def test_la_migracion_sigue_sin_anadir_columnas_not_null(tmp_path):
    """The rule that made the duration a table. Do not relax it.

    A NOT NULL column cannot be added to a table that already has rows, so this
    reports and skips rather than half-applying — and anything needing one has
    to be designed around it, as the duration was.
    """
    ruta = tmp_path / "notnull.db"
    con = sqlite3.connect(ruta)
    # `creado` is NOT NULL in the model and `nota` is nullable. Leaving both out
    # is what makes this test sharp: only one of them may come back.
    con.executescript(
        """
        CREATE TABLE entrenos (
          id INTEGER PRIMARY KEY, fecha DATE, ejercicio VARCHAR(120),
          grupo VARCHAR(120), fase INTEGER, series TEXT
        );
        INSERT INTO entrenos (fecha, ejercicio) VALUES ('2026-08-10','Squat');
        """
    )
    con.commit()
    con.close()

    engine = create_engine(sqlite_url(ruta))
    anadidas = add_missing_columns(engine)
    presentes = {c["name"] for c in inspect(engine).get_columns("entrenos")}

    assert "entrenos.nota" in anadidas and "nota" in presentes
    assert "entrenos.creado" not in anadidas, "a NOT NULL column was added to a table with rows"
    assert "creado" not in presentes
    assert Base.metadata.tables["entrenos"].columns["creado"].nullable is False
