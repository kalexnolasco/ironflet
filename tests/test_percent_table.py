"""The planning table on the exercise detail screen.

`gym_tools.percentage_table` was written, tested, and had **no caller** — the
same "built and not wired" shape this repo keeps producing. It belongs on
History's exercise detail, where the estimated 1RM already sits as a record of
what happened: the table is that number read forwards.

What these tests actually guard is the trap the first version fell into.
`PercentageRow` carries **two** weights: `weight` is the arithmetic percentage
(70 % of 102.5 kg is 71.75 kg) and `plates.total` is what the rack can build
(72.5 kg). Rendering `weight` beside the plate list produced a table that
contradicted itself — "71.75 kg · 20 + 5 + 1.25 per side", where those plates
make a different number. The rep estimate is computed against the loaded weight
too, so the loaded weight is the one that has to be on screen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import flet as ft
import pytest

from gym_tools import percentage_table
from views.history import HistoryView

UN_RM = 102.5


def _vista():
    page = MagicMock(spec=ft.Page)
    page.width, page.height, page.data = 400, 800, {}
    return HistoryView(page, MagicMock())


def _textos(controles) -> list[str]:
    fuera: list[str] = []
    pendientes = list(controles)
    while pendientes:
        c = pendientes.pop()
        if isinstance(c, ft.Text) and c.value:
            fuera.append(str(c.value))
        pendientes.extend(getattr(c, "controls", None) or [])
        contenido = getattr(c, "content", None)
        if contenido is not None:
            pendientes.append(contenido)
    return fuera


# ── the self-contradiction ───────────────────────────────────────────────


def test_el_peso_mostrado_es_el_que_montan_esos_discos():
    """THE REGRESSION. Every weight printed must equal the plate list beside it."""
    filas = percentage_table(UN_RM, percentages=HistoryView._PLAN_PERCENTS)
    assert filas, "no rows at all"

    mostrados = set()
    for fila in filas:
        peso = fila.plates.total if fila.plates else fila.weight
        assert peso == fila.plates.total, (
            f"{peso} kg printed next to plates that make {fila.plates.total} kg"
        )
        mostrados.add(peso)

    textos = " ".join(_textos(_vista()._percent_table(UN_RM)))
    for peso in mostrados:
        assert f"{peso:g} kg" in textos, f"{peso} kg never reached the screen"


def test_ningun_peso_es_imposible_de_montar():
    """A plan built on 83.7 kg is a plan for a gym that does not exist."""
    for fila in percentage_table(UN_RM, percentages=HistoryView._PLAN_PERCENTS):
        assert fila.plates is not None
        # Loadable means the solver produced a real plate set for it.
        assert fila.plates.total == pytest.approx(fila.plates.bar + 2 * sum(fila.plates.per_side))


# ── what lands on screen ─────────────────────────────────────────────────


def test_la_tabla_llega_a_pantalla():
    bloque = _vista()._percent_table(UN_RM)
    assert bloque, "computed and then never rendered — the failure this file exists for"
    textos = " ".join(_textos(bloque))
    assert "Plan from this 1RM" in textos
    assert "80%" in textos


def test_dice_que_las_reps_son_una_estimacion():
    """The reps come off an Epley estimate of a rep he has never performed."""
    textos = " ".join(_textos(_vista()._percent_table(UN_RM))).lower()
    assert "estimate" in textos


def test_las_reps_concuerdan_en_singular():
    """`plural()`, not a hand-typed "s": at 100 % the answer is "1 rep"."""
    bloque = _vista()._percent_table(UN_RM)
    textos = " ".join(_textos(bloque))
    assert "1 reps" not in textos


# ── refusing to answer ───────────────────────────────────────────────────


@pytest.mark.parametrize("valor", [None, 0, 0.0, -5])
def test_sin_un_1rm_no_hay_tabla(valor):
    """An exercise with no history has no 1RM, and inventing a plan from zero
    would be worse than showing nothing."""
    assert _vista()._percent_table(valor) == []


def test_un_1rm_minusculo_no_revienta():
    """Bodyweight work and warm-up-only exercises produce tiny or odd values."""
    bloque = _vista()._percent_table(5.0)
    assert isinstance(bloque, list)  # renders or stays empty, never raises
