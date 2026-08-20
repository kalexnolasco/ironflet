"""A chart that cannot show the change is not a chart.

`bar_chart` scaled every series from zero. For a magnitude that is right — a
light session really should draw a short bar. For a series that lives in a
narrow band a long way from zero it is useless: seven body-weight readings
spanning 82.0-84.2 kg came out as 110, 109, 109, 108, 107, 108, 107 px, so
**2.2 kg of change was three pixels of a hundred and ten**. The estimated-1RM
progression in History had the identical shape, for the identical reason.

The other half of the fix matters as much as the first: a cropped axis that
does not say it is cropped is a nicer-looking lie, so `axis_note()` has to
produce a caption whenever the floor is lifted, and has to stay quiet when it
is not.
"""

from __future__ import annotations

import flet as ft
import pytest

from components.charts import axis_note, bar_chart

PESOS = [84.2, 83.8, 84.0, 83.1, 82.6, 82.9, 82.0]
ALTURA = 110


def alturas(chart) -> list[int]:
    """The drawn height of each bar, in order."""
    return [col.controls[1].height for col in chart.controls]


# ── the regression ───────────────────────────────────────────────────────


def test_desde_cero_el_peso_corporal_es_ilegible():
    """Documents the old behaviour rather than just deleting it."""
    chart = bar_chart(PESOS, height=ALTURA)
    alto = alturas(chart)
    assert max(alto) - min(alto) <= 5, "if this grew, the zero-baseline maths changed"


def test_con_auto_el_mismo_peso_se_lee():
    chart = bar_chart(PESOS, height=ALTURA, baseline="auto")
    alto = alturas(chart)
    assert max(alto) - min(alto) > ALTURA * 0.5, (
        "2.2 kg of body weight has to be visible on a 110 px chart"
    )


def test_el_orden_de_las_barras_sigue_el_de_los_datos():
    """Rescaling must not reorder anything: bar i is still value i."""
    chart = bar_chart(PESOS, height=ALTURA, baseline="auto")
    alto = alturas(chart)
    esperado = sorted(range(len(PESOS)), key=lambda i: PESOS[i])
    obtenido = sorted(range(len(alto)), key=lambda i: alto[i])
    assert obtenido == esperado


# ── saying so ────────────────────────────────────────────────────────────


def test_un_eje_recortado_lo_declara():
    chart = bar_chart(PESOS, height=ALTURA, baseline="auto")
    nota = axis_note(chart)
    assert nota and "not 0" in nota


def test_un_eje_desde_cero_no_dice_nada():
    assert axis_note(bar_chart(PESOS, height=ALTURA)) is None


def test_la_nota_no_saca_decimales_feos():
    """`81.67` in a caption reads as a measurement, not as an axis label."""
    nota = axis_note(bar_chart(PESOS, height=ALTURA, baseline="auto"))
    numero = nota.split("at ")[1].split(",")[0]
    assert len(numero.split(".")[-1]) <= 1 if "." in numero else True


def test_una_serie_que_toca_cero_no_recorta():
    """Volume can genuinely be near zero; lifting that floor would lie."""
    chart = bar_chart([0.0, 500.0, 1200.0], height=ALTURA, baseline="auto")
    assert chart.chart_floor == 0.0
    assert axis_note(chart) is None


# ── edge cases that used to divide by zero or vanish ─────────────────────


def test_todos_los_valores_iguales():
    chart = bar_chart([80.0, 80.0, 80.0], height=ALTURA, baseline="auto")
    alto = alturas(chart)
    assert all(h > 0 for h in alto)
    assert len(set(alto)) == 1


def test_un_solo_valor():
    chart = bar_chart([80.0], height=ALTURA, baseline="auto")
    assert alturas(chart) == [ALTURA]


def test_serie_vacia_no_revienta_y_no_declara_eje():
    chart = bar_chart([], height=ALTURA, baseline="auto")
    assert isinstance(chart, ft.Container)
    assert axis_note(chart) is None


def test_valores_negativos_no_producen_alturas_negativas():
    """Nothing in this app logs a negative, but a bar of height -40 would be a
    Flutter assertion crash rather than a wrong picture."""
    chart = bar_chart([-5.0, 10.0, 20.0], height=ALTURA, baseline="auto")
    assert all(h >= 0 for h in alturas(chart))


def test_el_defecto_sigue_siendo_cero():
    """Every existing caller must keep the behaviour it was written against."""
    assert bar_chart([10.0, 20.0], height=ALTURA).chart_floor == 0.0


@pytest.mark.parametrize("modo", ["zero", "auto"])
def test_ninguna_barra_desaparece(modo):
    chart = bar_chart([100.0, 100.1, 100.2], height=ALTURA, baseline=modo)
    assert all(h >= 2 for h in alturas(chart))
