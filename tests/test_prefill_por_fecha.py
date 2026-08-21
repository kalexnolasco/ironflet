"""The prefill must come from before the session, not from the newest row.

`get_last_sets` answers "what did I lift last time?", and the training screen
turns that answer into the numbers already sitting in the weight and reps
boxes. Those numbers get confirmed with a tap and become the record, so a
wrong answer here does not look like a bug — it looks like a workout.

Sessions are not always logged the day they happen. Forgetting the phone and
typing Monday in on Wednesday is a case this app supports on purpose, and the
old query ordered the whole table by date and took the top row regardless.
Back-dating Monday therefore prefilled it with Wednesday's weights: a session
that, from Monday's point of view, had not happened yet.

Nothing here imports the Telegram coach in ../agente/.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import delete

from storage import Entreno, Storage, WorkoutEntry

EJERCICIO = "Barbell Bench Press"
HOY = date.today()


@pytest.fixture
def store():
    """Storage with `entrenos` emptied. Same resolution as the other suites."""
    # `tests/conftest.py` da a cada proceso su propio SQLite. Antes aquí había
    # una cadena de precedencia con PostgreSQL y dos `pytest.skip`; sin
    # servidor al que caer, es una línea.
    url = os.environ["TEST_DATABASE_URL"]

    almacen = Storage(url)
    with almacen._Session() as s:
        s.execute(delete(Entreno))
        s.commit()
    return almacen


def anotar(store, dia: date, peso: float):
    store.save_workout(
        WorkoutEntry(
            date=dia.isoformat(),
            exercise=EJERCICIO,
            muscle_group="Chest",
            phase=1,
            sets=[{"weight": peso, "reps": 8}],
        )
    )


def peso_de(sets) -> float | None:
    return sets[0]["weight"] if sets else None


# ── the regression ───────────────────────────────────────────────────────


def test_sesion_retroactiva_no_ve_pesos_del_futuro(store):
    """Logging Monday on Wednesday must prefill from *last* Monday, not today."""
    lunes = HOY - timedelta(days=2)
    anotar(store, lunes - timedelta(days=7), 80.0)  # la sesión anterior de verdad
    anotar(store, HOY, 100.0)  # hoy, ya registrado

    assert peso_de(store.get_last_sets(EJERCICIO, before=lunes)) == 80.0, (
        "prefilled from a session that had not happened yet on the date being logged"
    )
    # Y esto es lo que hacía antes, documentado en vez de solo corregido:
    assert peso_de(store.get_last_sets(EJERCICIO)) == 100.0


def test_sin_before_sigue_dando_la_mas_reciente(store):
    """The common case — today's session — must be untouched by the change."""
    anotar(store, HOY - timedelta(days=7), 80.0)
    anotar(store, HOY - timedelta(days=3), 90.0)
    assert peso_de(store.get_last_sets(EJERCICIO)) == 90.0


def test_el_mismo_dia_no_cuenta_como_anterior(store):
    """A row already saved for that date is this session, not the previous one.

    Otherwise re-opening a half-saved session would prefill each exercise from
    itself and the previous session would become unreachable.
    """
    anotar(store, HOY - timedelta(days=7), 80.0)
    anotar(store, HOY, 100.0)
    assert peso_de(store.get_last_sets(EJERCICIO, before=HOY)) == 80.0


def test_sin_nada_anterior_devuelve_none(store):
    """First time back-dating an exercise: no history, and no invented number."""
    anotar(store, HOY, 100.0)
    assert store.get_last_sets(EJERCICIO, before=HOY - timedelta(days=30)) is None


def test_toma_la_mas_cercana_no_la_mas_antigua(store):
    for semanas, peso in ((4, 60.0), (3, 70.0), (1, 85.0)):
        anotar(store, HOY - timedelta(weeks=semanas), peso)
    objetivo = HOY - timedelta(days=2)
    assert peso_de(store.get_last_sets(EJERCICIO, before=objetivo)) == 85.0


def test_otro_ejercicio_no_contamina(store):
    anotar(store, HOY - timedelta(days=7), 80.0)
    store.save_workout(
        WorkoutEntry(
            date=(HOY - timedelta(days=1)).isoformat(),
            exercise="Squat",
            muscle_group="Legs",
            phase=1,
            sets=[{"weight": 140.0, "reps": 5}],
        )
    )
    assert peso_de(store.get_last_sets(EJERCICIO, before=HOY)) == 80.0
