"""Home: the numbers say their unit, and a dead database says so.

Home is the first screen the app opens on. When its reads raised, the app came
up on nothing at all — and with Profile and Plan only reachable *from* Home,
there was no way to get anywhere to find out why.

`current_program_week`, `day_totals` and `targets_for` are patched at their
import site in `views.home`: this file is about what Home renders, not about
re-testing `program_week.py`.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import flet as ft
import pytest

from program_week import ProgramStart, ProgramWeek, StartSource, WeekStatus
from theme import LIGHT, set_palette

VIEW_PROFILE = 5


@pytest.fixture(autouse=True)
def light_palette():
    set_palette(LIGHT)
    yield
    set_palette(LIGHT)


class FakeStore:
    def __init__(self, stats=None, streak=2, today=(), fail=None):
        self.stats = stats or {"sessions": 3, "sets": 42, "volume": 12345.0}
        self.streak = streak
        self.today = list(today)
        self.fail = fail

    def _check(self):
        if self.fail is not None:
            raise self.fail

    def get_streak(self):
        self._check()
        return self.streak

    def get_week_stats(self):
        self._check()
        return dict(self.stats)

    def get_today(self):
        self._check()
        return list(self.today)


def unknown_week() -> ProgramWeek:
    """The fresh-install state: no start date, so no week to name."""
    return ProgramWeek(
        status=WeekStatus.UNKNOWN,
        start=ProgramStart(day=None, source=StartSource.UNKNOWN),
        routine_id="recomp-ppl-ul",
        total_weeks=6,
        today=date.today(),
    )


@pytest.fixture
def home(monkeypatch):
    """A HomeView whose three outside modules are stubbed, plus its store."""
    import views.home as home_module

    monkeypatch.setattr(home_module, "current_program_week", lambda store: unknown_week())
    monkeypatch.setattr(home_module, "day_totals", lambda store, day: {})
    monkeypatch.setattr(home_module, "targets_for", lambda store, day: {})

    def build(store):
        page = MagicMock()
        page.width = 400
        page.height = 800
        page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
        view = home_module.HomeView(page, store)
        view.on_show()
        return view

    return build


def texts(control) -> list[str]:
    found: list[str] = []
    seen: set[int] = set()

    def walk(node):
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if isinstance(node, ft.Text) and isinstance(node.value, str):
            found.append(node.value)
        for attr in ("content", "controls", "actions", "title", "spans"):
            walk(getattr(node, attr, None))

    walk(control)
    return found


def tooltips(control) -> list[str]:
    found: list[str] = []
    seen: set[int] = set()

    def walk(node):
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        tip = getattr(node, "tooltip", None)
        if isinstance(tip, str) and tip:
            found.append(tip)
        for attr in ("content", "controls", "actions", "title"):
            walk(getattr(node, attr, None))

    walk(control)
    return found


# ── the shortened volume ────────────────────────────────────────────────


def test_volume_tile_carries_the_real_figure(home):
    """`12.3k` under a "Vol (kg)" caption still does not say 12,300 kilos."""
    view = home(FakeStore(stats={"sessions": 3, "sets": 42, "volume": 12345.0}))
    tree = view.build()
    assert "12.3k" in texts(tree)
    assert any("12,345 kg" in t for t in tooltips(tree)), (
        "the shortened number must say what it really is somewhere"
    )


def test_volume_tooltip_names_the_window_and_the_arithmetic(home):
    view = home(FakeStore())
    tips = " | ".join(tooltips(view.build()))
    assert "Peso × reps" in tips
    assert "últimos 7 días" in tips.lower()


# ── the database is down ────────────────────────────────────────────────


class _DriverError(Exception):
    pass


_DriverError.__module__ = "sqlalchemy.exc"


def test_a_dead_database_does_not_open_the_app_on_nothing(home):
    view = home(FakeStore(fail=_DriverError("could not connect to server")))
    rendered = " | ".join(texts(view.build()))
    assert "No se llega a la base de datos" in rendered
    assert "could not connect to server" in rendered


def test_on_show_does_not_raise_when_the_week_cannot_be_read(monkeypatch):
    """`on_show` runs inside `navigate_to`, before `build()`.

    An exception there takes the whole navigation down rather than one screen,
    so Home would refuse to open at all rather than open with a message.
    """
    import views.home as home_module

    def explode(store):
        raise _DriverError("server closed the connection")

    monkeypatch.setattr(home_module, "current_program_week", explode)
    page = MagicMock()
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
    view = home_module.HomeView(page, FakeStore())
    view.on_show()  # must not raise
    assert view._week is None
