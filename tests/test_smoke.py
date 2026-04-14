"""Smoke tests that build every view in both languages and every routine.

These don't spin up a real Flet runtime — they just verify that the Python
build pipeline (i18n translations, routine data, view construction) doesn't
blow up under any combination of language × routine × phase × day.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import i18n
from data import ROUTINES, set_active_routine
from storage import Storage
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
        "set_language": lambda lang: None,
        "set_routine": lambda r: None,
    }
    return page


@pytest.fixture
def store(tmp_path):
    return Storage(str(tmp_path / "test.db"))


@pytest.mark.parametrize("lang", ["en", "es"])
@pytest.mark.parametrize("routine_id", [r.id for r in ROUTINES])
def test_all_views_build(lang, routine_id, page_mock, store):
    page_mock.data["store"] = store
    i18n.set_language(lang)
    set_active_routine(routine_id)
    for cls in [HomeView, PlanView, WorkoutView, BrowseView, HistoryView, ProfileView]:
        view = cls(page_mock, store)
        if hasattr(view, "on_show"):
            view.on_show()
        view.build()


@pytest.mark.parametrize("lang", ["en", "es"])
def test_plan_phase_detail_builds(lang, page_mock, store):
    page_mock.data["store"] = store
    i18n.set_language(lang)
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
    i18n.set_language("en")
    set_active_routine("cambiatufisico")
    wv = WorkoutView(page_mock, store)
    wv.phase_id = 1
    wv.day_idx = 0
    wv.build()
    assert wv._current_exercise_raw() != ""
