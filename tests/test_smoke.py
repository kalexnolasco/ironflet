"""Smoke tests that build every view for every routine.

These don't spin up a real Flet runtime — they just verify that the Python
build pipeline (routine data, view construction) doesn't blow up under any
combination of routine × phase × day.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from data import ROUTINES, set_active_routine
from storage import Storage
from views.agent_view import AgentView
from views.browse import BrowseView
from views.history import HistoryView
from views.home import HomeView
from views.plan import PlanView
from views.profile import ProfileView
from views.workout import WorkoutView


@pytest.fixture
def page_mock():
    page = MagicMock()
    page.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "set_routine": lambda r: None,
    }
    return page


@pytest.fixture
def store():
    """Base de pruebas aparte, vaciada antes de cada test.

    Necesita PostgreSQL en marcha (`docker compose up -d` en la raíz). La URL
    sale de TEST_DATABASE_URL, o se deriva de DATABASE_URL cambiando la base.
    """
    from sqlalchemy.engine import make_url

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ.get("DATABASE_URL")
        if not base:
            pytest.skip("sin DATABASE_URL: no hay base de datos contra la que probar")
        # render_as_string, no str(): str() enmascara la contraseña.
        url = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)

    from storage import Base

    almacen = Storage(url)
    Base.metadata.create_all(almacen._engine)
    # Vaciar filas, NO `drop_all`. La base de test se comparte, y tirar las
    # tablas se las quita a cualquier otro pytest que esté a media consulta:
    # revienta con UndefinedTable en ficheros que no tienen nada que ver con
    # el cambio que se está probando. Costó cinco tiradas rojas distintas
    # localizarlo. En orden inverso de dependencias, para respetar las FK.
    with almacen._engine.begin() as con:
        for tabla in reversed(Base.metadata.sorted_tables):
            con.execute(tabla.delete())
    return almacen


@pytest.mark.parametrize("routine_id", [r.id for r in ROUTINES])
def test_all_views_build(routine_id, page_mock, store):
    page_mock.data["store"] = store
    set_active_routine(routine_id)
    for cls in [
        HomeView,
        PlanView,
        WorkoutView,
        BrowseView,
        HistoryView,
        ProfileView,
        AgentView,
    ]:
        view = cls(page_mock, store)
        if hasattr(view, "on_show"):
            view.on_show()
        view.build()


def test_plan_phase_detail_builds(page_mock, store):
    page_mock.data["store"] = store
    for routine in ROUTINES:
        set_active_routine(routine.id)
        pv = PlanView(page_mock, store)
        for idx in range(len(routine.phases)):
            pv.selected_phase_idx = idx
            days = routine.days_for_phase(routine.phases[idx].id)
            pv._expanded_days = {d.name for d in days}
            pv.build()


def test_workout_exercise_render(page_mock, store):
    page_mock.data["store"] = store
    set_active_routine("cambiatufisico")
    wv = WorkoutView(page_mock, store)
    wv.phase_id = 1
    wv.day_idx = 0
    wv.build()
    assert wv._current_exercise_raw() != ""
