"""Guards for `views/shared_ui.py` — plurals, dialog geometry, the down-database card.

Three unrelated helpers in one file because they are one idea: things that were
being written by hand in five views and getting written wrong in three of them.
No database and no running app.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import flet as ft
import pytest

import views.shared_ui as shared_ui
from theme import DARK, LIGHT, set_palette
from views.shared_ui import (
    DIALOG_CHROME_H,
    DIALOG_MARGIN,
    DIALOG_MAX_W,
    DIALOG_MIN_W,
    FALLBACK_PAGE_W,
    db_error_card,
    db_error_screen,
    describe_db_error,
    dialog_height,
    dialog_width,
    is_db_error,
    plural,
)

MODULE_PATH = Path(shared_ui.__file__)


@pytest.fixture(autouse=True)
def light_palette():
    set_palette(LIGHT)
    yield
    set_palette(LIGHT)


def texts(control) -> list[str]:
    """Every string rendered anywhere under `control`."""
    found: list[str] = []
    seen: set[int] = set()

    def walk(node) -> None:
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


# ── plurals ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "0 series"),  # el cero es plural, y el cero pasa
        (1, "1 serie"),
        (2, "2 series"),
        (12, "12 series"),
        (1.0, "1 serie"),  # un float que vale exactamente uno sigue siendo uno
        (0.5, "0.5 series"),  # media serie no es "0.5 serie"
        (1.5, "1.5 series"),
        (2.0, "2 series"),  # y nunca "2.0 series"
    ],
)
def test_plural_agrees_with_its_number(count, expected):
    assert plural(count, "serie") == expected


@pytest.mark.parametrize(
    ("singular", "esperado"),
    [
        ("serie", "series"),  # acaba en vocal → -s
        ("día", "días"),  # vocal acentuada, también -s
        ("fase", "fases"),
        ("ejercicio", "ejercicios"),
        ("alimento", "alimentos"),
        ("semana", "semanas"),
        ("mes", "meses"),  # consonante → -es
        ("calentamiento", "calentamientos"),
    ],
)
def test_plural_sigue_la_regla_espanola(singular, esperado):
    """`-s` tras vocal, `-es` tras consonante.

    Con la regla inglesa que había antes, "mes" salía "mess" y nadie lo veía
    hasta tener la pantalla delante.
    """
    assert plural(2, singular) == f"2 {esperado}"


def test_plural_conoce_las_que_mueven_la_tilde():
    """`sesión` → `sesiones`, no `sesiónes`. Ninguna regla mecánica lo saca."""
    assert plural(1, "sesión") == "1 sesión"
    assert plural(3, "sesión") == "3 sesiones"
    assert plural(2, "repetición") == "2 repeticiones"


def test_plural_respeta_la_caja_del_original():
    """La misma función sirve en una cabecera en mayúsculas y en una frase."""
    assert plural(3, "SERIE") == "3 SERIES"
    assert plural(2, "MES") == "2 MESES"


def test_plural_takes_an_irregular_form():
    """La forma explícita sigue mandando sobre cualquier regla."""
    assert plural(1, "lunes", "lunes") == "1 lunes"
    assert plural(3, "lunes", "lunes") == "3 lunes"


# ── dialog geometry ─────────────────────────────────────────────────────


def test_dialog_width_follows_a_narrow_window():
    page = MagicMock()
    page.width = 360
    assert dialog_width(page) == 360 - DIALOG_MARGIN


def test_dialog_width_stops_growing_on_a_desktop_window():
    page = MagicMock()
    page.width = 1920
    assert dialog_width(page) == DIALOG_MAX_W


def test_dialog_width_never_goes_below_readable():
    page = MagicMock()
    page.width = 300
    assert dialog_width(page) == DIALOG_MIN_W


@pytest.mark.parametrize("reported", [None, "420", float("nan"), float("inf"), 0, -100])
def test_dialog_width_falls_back_when_the_page_cannot_say(reported):
    """A page before its first frame, or a stub. Never arithmetic on nonsense."""
    page = MagicMock()
    page.width = reported
    assert dialog_width(page) == FALLBACK_PAGE_W - DIALOG_MARGIN


def test_dialog_width_falls_back_on_a_bare_mock():
    """`MagicMock().width` is a mock, not a number — and it is truthy.

    A plain `page.width or 420` would hand that mock into a layout and fail
    somewhere unrelated. Every test in this repo builds dialogs with a mock, so
    this is the path most exercised.
    """
    assert dialog_width(MagicMock()) == FALLBACK_PAGE_W - DIALOG_MARGIN


def test_dialog_height_is_capped_by_the_window_not_by_the_wish():
    page = MagicMock()
    page.height = 640
    assert dialog_height(page, 600) == 640 - DIALOG_CHROME_H
    # And a modest wish is granted in full.
    assert dialog_height(page, 300) == 300


def test_dialog_height_is_always_a_number():
    """A scrolling Column needs a bounded box; None would make it unscrollable."""
    page = MagicMock()
    page.height = 200  # absurdly short
    assert isinstance(dialog_height(page, 520), (int, float))
    assert dialog_height(page, 520) > 0


# ── the database is down ────────────────────────────────────────────────


class _FakeDriverError(Exception):
    pass


_FakeDriverError.__module__ = "sqlalchemy.exc"


def test_a_driver_exception_is_recognised_as_the_database():
    assert is_db_error(_FakeDriverError("connection refused"))
    assert is_db_error(ConnectionRefusedError("no route"))


def test_a_plain_bug_is_not_blamed_on_the_database():
    """Saying "database" about a KeyError sends Alex to restart Postgres."""
    assert not is_db_error(KeyError("volume"))
    headline, _body = describe_db_error(KeyError("volume"))
    assert "database" not in headline.lower()


def test_the_database_message_says_nothing_is_lost():
    """The one fact that matters when the screen is empty in a gym."""
    _headline, body = describe_db_error(_FakeDriverError("connection refused"))
    assert "se ha perdido" not in body.lower().replace("nada de lo que apuntaste se ha perdido", "")
    assert "nada de lo que apuntaste se ha perdido" in body.lower()


def test_error_card_shows_the_reason_and_the_technical_detail():
    card = db_error_card(_FakeDriverError("could not connect to server"))
    blob = " | ".join(texts(card))
    assert "No se llega a la base de datos" in blob
    assert "could not connect to server" in blob  # searchable, not swallowed
    assert "_FakeDriverError" in blob


def test_error_card_retry_button_calls_back():
    calls = []
    card = db_error_card(_FakeDriverError("down"), on_retry=lambda: calls.append(1))
    buttons = [c for c in _walk(card) if getattr(c, "on_click", None)]
    assert buttons, "the card offers no way to try again"
    buttons[0].on_click(None)
    assert calls == [1]


def test_error_card_without_a_retry_offers_no_dead_button():
    card = db_error_card(_FakeDriverError("down"))
    assert not [c for c in _walk(card) if getattr(c, "on_click", None)]


def test_error_screen_keeps_the_screen_heading():
    """So the failure reads as "this screen has no data", not "the app is gone"."""
    screen = db_error_screen("History & Progress", _FakeDriverError("down"))
    assert "History & Progress" in texts(screen)


def test_a_very_long_exception_is_trimmed():
    card = db_error_card(_FakeDriverError("x" * 5000))
    longest = max(len(t) for t in texts(card))
    assert longest <= 220


def _walk(node, seen=None):
    seen = seen if seen is not None else set()
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk(item, seen)
        return
    yield node
    for attr in ("content", "controls", "actions", "title"):
        yield from _walk(getattr(node, attr, None), seen)


# ── theme rules ─────────────────────────────────────────────────────────


def test_no_hardcoded_colour_in_the_module():
    """No view helper may write a hex value; every colour goes through `C`."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b", source)


def test_the_card_follows_the_active_palette():
    """Colours are resolved inside the call, never frozen at import."""
    light = db_error_card(_FakeDriverError("down"))
    set_palette(DARK)
    dark = db_error_card(_FakeDriverError("down"))
    assert light.bgcolor == LIGHT.bg_surface
    assert dark.bgcolor == DARK.bg_surface
