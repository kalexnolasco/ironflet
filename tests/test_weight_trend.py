"""The weight trend on the Profile screen.

`analytics.moving_average` was written for this, documented in CLAUDE.md, and
had **zero callers** — the screen plotted raw daily weigh-ins and nothing else.
Raw weight is the wrong number to steer by: it swings about a kilo on water and
gut content, and this plan adjusts on ±0.3 kg/week. A reader comparing two raw
bars four days apart can easily conclude the opposite of what is happening.

These tests are about the number that reaches the screen, not about the
average itself (`tests/test_analytics.py` owns that). What they pin down is the
part a view gets wrong: the window it compares against, and refusing to report
a rate when there is not enough history to support one.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import flet as ft
import pytest

from views.profile import ProfileView

HOY = date.today()


class StoreFalso:
    def __init__(self, weights):
        self._weights = weights

    def get_weights(self):
        return list(self._weights)

    def get_profile(self):
        return {}

    def get_latest_weight(self):
        return self._weights[-1]["kg"] if self._weights else None

    def get_pref(self, key, default=None):
        return default

    def set_pref(self, key, value):
        pass


def vista(weights):
    page = MagicMock(spec=ft.Page)
    page.width, page.height, page.data = 400, 800, {}
    return ProfileView(page, StoreFalso(weights))


def serie(pares):
    """`[(días_atrás, kg), ...]` → the shape `get_weights()` returns, oldest first."""
    filas = [
        {"date": (HOY - timedelta(days=d)).isoformat(), "kg": kg, "id": str(i)}
        for i, (d, kg) in enumerate(pares)
    ]
    return sorted(filas, key=lambda r: r["date"])


# ── refusing to answer ───────────────────────────────────────────────────


def test_sin_pesajes_no_hay_tendencia():
    media, ritmo = vista([])._trend([])
    assert media is None and ritmo is None


def test_pocos_dias_dan_media_pero_no_ritmo():
    """THE POINT. Four days of data can show "-1.8 kg/week" off one salty meal.

    Reporting that number would have Alex cutting calories over water weight,
    so the rate is withheld until there is a fortnight behind it.
    """
    datos = serie([(3, 82.0), (2, 81.0), (1, 81.5), (0, 80.8)])
    media, ritmo = vista(datos)._trend(datos)
    assert media is not None, "the average itself is fine from day one"
    assert ritmo is None, "a weekly rate off four days is noise wearing a number"


def test_a_partir_de_dos_semanas_si_hay_ritmo():
    datos = serie([(d, 82.0 - d * 0.0) for d in range(20, -1, -1)])
    _, ritmo = vista(datos)._trend(datos)
    assert ritmo is not None


# ── the number itself ────────────────────────────────────────────────────


def test_una_bajada_constante_sale_con_el_signo_correcto():
    """0.1 kg/day for three weeks is -0.7 kg/week."""
    datos = serie([(d, 85.0 - (20 - d) * 0.1) for d in range(20, -1, -1)])
    _, ritmo = vista(datos)._trend(datos)
    assert ritmo == pytest.approx(-0.7, abs=0.05)


def test_un_peso_estable_da_ritmo_cero():
    datos = serie([(d, 80.0) for d in range(20, -1, -1)])
    media, ritmo = vista(datos)._trend(datos)
    assert media == pytest.approx(80.0)
    assert ritmo == pytest.approx(0.0, abs=0.01)


def test_una_subida_sale_positiva():
    datos = serie([(d, 78.0 + (20 - d) * 0.05) for d in range(20, -1, -1)])
    _, ritmo = vista(datos)._trend(datos)
    assert ritmo > 0


def test_un_pico_de_un_dia_no_domina_el_ritmo():
    """What the moving average is for: one bad reading must not move the verdict."""
    limpio = [(d, 80.0) for d in range(20, -1, -1)]
    con_pico = [(d, 82.5 if d == 0 else 80.0) for d in range(20, -1, -1)]

    _, ritmo_limpio = vista(serie(limpio))._trend(serie(limpio))
    _, ritmo_pico = vista(serie(con_pico))._trend(serie(con_pico))

    assert abs(ritmo_pico - ritmo_limpio) < 0.5, (
        "a single +2.5 kg reading moved the weekly rate by more than half a kilo — "
        "that is the raw-scale noise this is supposed to filter out"
    )


# ── what lands on screen ─────────────────────────────────────────────────


def _textos(control) -> list[str]:
    fuera: list[str] = []
    pendientes = [control]
    while pendientes:
        c = pendientes.pop()
        if isinstance(c, ft.Text) and c.value:
            fuera.append(str(c.value))
        pendientes.extend(getattr(c, "controls", None) or [])
        contenido = getattr(c, "content", None)
        if contenido is not None:
            pendientes.append(contenido)
    return fuera


def test_sin_datos_no_se_pintan_las_fichas():
    """No empty "— kg" tiles on a first run: the section simply is not there."""
    assert vista([])._trend_chips([]) == []


def test_con_datos_las_fichas_llegan_a_pantalla():
    datos = serie([(d, 85.0 - (20 - d) * 0.1) for d in range(20, -1, -1)])
    chips = vista(datos)._trend_chips(datos)
    assert chips, "the trend was computed and then never rendered"

    texto = " ".join(t for c in chips for t in _textos(c))
    assert "MEDIA 7 DÍAS" in texto
    assert "POR SEMANA" in texto
    assert "kg" in texto


def test_con_pocos_dias_dice_que_faltan_datos():
    """Silence would read as "no change"; it has to say why there is no number."""
    datos = serie([(3, 82.0), (2, 81.0), (1, 81.5), (0, 80.8)])
    texto = " ".join(t for c in vista(datos)._trend_chips(datos) for t in _textos(c))
    assert "a los" in texto.lower()
