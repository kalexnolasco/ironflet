"""Una gráfica que no puede enseñar el cambio no es una gráfica.

`bar_chart` escalaba toda serie desde cero. Para una magnitud eso está bien —
una sesión floja debe dibujar una barra corta. Para una serie que vive en una
franja estrecha y lejos del cero es inútil: siete pesajes entre 82,0 y 84,2 kg
salían como 110, 109, 109, 108, 107, 108, 107 px, o sea **2,2 kg de cambio en
tres píxeles de ciento diez**. La progresión de 1RM en Historial tenía la
misma forma por la misma razón.

La otra mitad del arreglo importa tanto como la primera: un eje recortado que
no dice que lo está es una mentira más bonita, así que `axis_note()` tiene que
producir un pie de gráfica siempre que se levante la base, y callarse cuando
no.

## Por qué estos tests miran el eje y no los píxeles

Hasta 0.13 las barras eran `ft.Container` de altura calculada y aquí se medían
esas alturas. Desde que las dibuja `ft.BarChart` no hay píxeles que medir —
los reparte Flutter en tiempo de render. Lo que se comprueba es **el rango del
eje**, que es de donde salían aquellas alturas: si `min_y`/`max_y` encierran
la serie de cerca, el cambio se ve; si van de cero al máximo, no. Es la misma
propiedad, un paso más arriba y sin depender de cómo se pinte.
"""

from __future__ import annotations

import flet as ft
import pytest

from components.charts import axis_note, bar_chart, line_chart

PESOS = [84.2, 83.8, 84.0, 83.1, 82.6, 82.9, 82.0]
ALTURA = 110


def rango(chart) -> float:
    """Lo que abarca el eje Y. Es lo que decide si un cambio se ve o no."""
    return chart.max_y - chart.min_y


def valores(chart) -> list[float]:
    """El `to_y` de cada barra, en orden."""
    return [g.bar_rods[0].to_y for g in chart.bar_groups]


# ── la regresión ─────────────────────────────────────────────────────────


def test_desde_cero_el_peso_corporal_es_ilegible():
    """Documenta el comportamiento viejo en vez de solo borrarlo.

    Con la base en cero el eje abarca 84 kg para enseñar 2,2 de variación: el
    cambio ocupa un 2,6 % del alto y es lo que se veía como tres píxeles.
    """
    chart = bar_chart(PESOS, height=ALTURA)
    variacion = max(PESOS) - min(PESOS)
    assert variacion / rango(chart) < 0.05, "si esto creció, cambió la base en cero"


def test_con_auto_el_mismo_peso_se_lee():
    chart = bar_chart(PESOS, height=ALTURA, baseline="auto")
    variacion = max(PESOS) - min(PESOS)
    assert variacion / rango(chart) > 0.5, (
        "2,2 kg de peso corporal tienen que ocupar la mitad larga de la gráfica"
    )


def test_el_orden_de_las_barras_sigue_el_de_los_datos():
    """Reescalar no puede reordenar nada: la barra i sigue siendo el valor i."""
    chart = bar_chart(PESOS, height=ALTURA, baseline="auto")
    assert valores(chart) == PESOS


def test_las_barras_arrancan_en_la_base_y_no_en_cero():
    """`from_y` es lo que hace que el recorte se dibuje.

    Con la base calculada pero las barras saliendo de cero, el eje estaría
    recortado y las barras se saldrían por abajo del marco.
    """
    chart = bar_chart(PESOS, height=ALTURA, baseline="auto")
    assert chart.chart_floor > 0
    for grupo in chart.bar_groups:
        assert grupo.bar_rods[0].from_y == chart.chart_floor


# ── decirlo ──────────────────────────────────────────────────────────────


def test_un_eje_recortado_lo_declara():
    chart = bar_chart(PESOS, height=ALTURA, baseline="auto")
    nota = axis_note(chart)
    assert nota and "no en 0" in nota


def test_un_eje_desde_cero_no_dice_nada():
    assert axis_note(bar_chart(PESOS, height=ALTURA)) is None


def test_la_nota_no_saca_decimales_feos():
    """«81.67» en un pie de gráfica se lee como una medida, no como una escala."""
    nota = axis_note(bar_chart(PESOS, height=ALTURA, baseline="auto"))
    numero = nota.split("empieza en ")[1].split(",")[0]
    assert len(numero.split(".")[-1]) <= 1 if "." in numero else True


def test_una_serie_que_toca_cero_no_recorta():
    """El volumen sí puede rondar el cero; levantar esa base sería mentir."""
    chart = bar_chart([0.0, 500.0, 1200.0], height=ALTURA, baseline="auto")
    assert chart.chart_floor == 0.0
    assert axis_note(chart) is None


# ── casos límite que antes dividían por cero o desaparecían ──────────────


def test_todos_los_valores_iguales():
    chart = bar_chart([80.0, 80.0, 80.0], height=ALTURA, baseline="auto")
    assert rango(chart) > 0, "un eje de rango cero es un assert de Flutter, no una gráfica"
    assert valores(chart) == [80.0, 80.0, 80.0]


def test_un_solo_valor():
    chart = bar_chart([80.0], height=ALTURA, baseline="auto")
    assert rango(chart) > 0
    assert valores(chart) == [80.0]


def test_serie_vacia_no_revienta_y_no_declara_eje():
    chart = bar_chart([], height=ALTURA, baseline="auto")
    assert isinstance(chart, ft.Container)
    assert axis_note(chart) is None


def test_valores_negativos_no_bajan_la_base_del_cero():
    """Nada en esta app apunta un negativo, pero un eje mal puesto es un
    assert de Flutter en vez de un dibujo equivocado."""
    chart = bar_chart([-5.0, 10.0, 20.0], height=ALTURA, baseline="auto")
    assert chart.chart_floor >= 0
    assert rango(chart) > 0


def test_el_defecto_sigue_siendo_cero():
    """Todo llamante existente conserva el comportamiento con el que se escribió."""
    assert bar_chart([10.0, 20.0], height=ALTURA).chart_floor == 0.0


@pytest.mark.parametrize("modo", ["zero", "auto"])
def test_el_techo_deja_aire_sobre_la_barra_mas_alta(modo):
    """Pegada al borde, la barra más alta parece cortada."""
    chart = bar_chart([100.0, 100.1, 100.2], height=ALTURA, baseline=modo)
    assert chart.max_y > max(valores(chart))


# ── la línea, para lo que es una serie en el tiempo ──────────────────────


def test_la_linea_encierra_la_serie_de_cerca():
    """Mismo problema que las barras, misma respuesta: base automática.

    Y aquí es el defecto, porque una línea de peso o de 1RM nunca arranca en
    cero.
    """
    chart = line_chart(PESOS, height=ALTURA)
    variacion = max(PESOS) - min(PESOS)
    assert variacion / (chart.max_y - chart.min_y) > 0.5
    assert axis_note(chart), "recortar el eje obliga a decirlo, también en la línea"


def test_la_linea_lleva_un_punto_por_lectura_y_en_orden():
    chart = line_chart(PESOS, height=ALTURA)
    puntos = chart.data_series[0].data_points
    assert [p.y for p in puntos] == PESOS
    assert [p.x for p in puntos] == list(range(len(PESOS)))


def test_la_media_movil_va_como_segunda_serie():
    """El peso de un día es ruido; la media es la señal.

    Dibujarla obliga a que el eje las abarque a las dos, o la tendencia se
    sale del marco.
    """
    media = [84.0, 83.9, 83.8, 83.6, 83.3, 83.1, 82.9]
    chart = line_chart(PESOS, height=ALTURA, trend=media)
    assert len(chart.data_series) == 2
    assert chart.min_y <= min(PESOS + media)
    assert chart.max_y >= max(PESOS + media)


def test_una_media_con_huecos_no_revienta():
    """`analytics.moving_average` devuelve None hasta tener ventana entera."""
    media = [None, None, 84.0, 83.7, 83.4, 83.1, 82.9]
    chart = line_chart(PESOS, height=ALTURA, trend=media)
    puntos = chart.data_series[1].data_points
    assert len(puntos) == 5, "los huecos se saltan, no se dibujan como ceros"


def test_la_linea_vacia_no_revienta():
    chart = line_chart([], height=ALTURA)
    assert isinstance(chart, ft.Container)
    assert axis_note(chart) is None


# ── las etiquetas del eje ────────────────────────────────────────────────


def test_las_etiquetas_del_eje_no_se_amontonan():
    """«08-2008-21»: dos etiquetas consecutivas en el borde, una sobre otra.

    Con 22 lecturas el paso sale 4, se elegían la 0, 4, 8, 12, 16, 20 y luego
    la última (21) por ser la última. Las dos del final quedaban pegadas.
    """
    fechas = [f"08-{d:02d}" for d in range(1, 23)]
    chart = line_chart([80.0 + i * 0.1 for i in range(22)], fechas, height=ALTURA)
    posiciones = [e.value for e in chart.bottom_axis.labels]

    assert posiciones == sorted(posiciones), "en orden"
    huecos = [b - a for a, b in zip(posiciones, posiciones[1:], strict=False)]
    assert min(huecos) >= 2, f"etiquetas pegadas en {posiciones}"


def test_el_eje_siempre_sitúa_el_principio_y_el_final():
    """Sin la primera y la última no se sabe qué periodo se está mirando."""
    fechas = [f"08-{d:02d}" for d in range(1, 23)]
    chart = line_chart([80.0] * 22, fechas, height=ALTURA)
    posiciones = [e.value for e in chart.bottom_axis.labels]
    assert posiciones[0] == 0
    assert posiciones[-1] == 21


@pytest.mark.parametrize("cuantas", [1, 2, 3, 5, 7, 12, 22, 40, 90])
def test_ningun_tamaño_de_serie_amontona_ni_se_queda_sin_etiquetas(cuantas):
    """Barrido: pocas lecturas, muchas, y los bordes de la división.

    Lo que se mide es la separación como **fracción del ancho**, no la
    distancia en índices: con 3 lecturas un hueco de 1 es medio gráfico y con
    22 es un 5 %, que es donde «08-20» y «08-21» se pisaron. Una etiqueta de
    8 pt ocupa alrededor del 9 % de un móvil, así que se pide un 10 %.
    """
    fechas = [f"d{i}" for i in range(cuantas)]
    chart = line_chart([80.0 + i * 0.1 for i in range(cuantas)], fechas, height=ALTURA)
    posiciones = [e.value for e in chart.bottom_axis.labels]

    assert posiciones, "siempre al menos una etiqueta"
    assert len(posiciones) <= 8, f"{len(posiciones)} etiquetas no caben en un móvil"
    if cuantas > 2:
        ancho = cuantas - 1
        huecos = [(b - a) / ancho for a, b in zip(posiciones, posiciones[1:], strict=False)]
        assert min(huecos) >= 0.10, (
            f"con {cuantas} lecturas quedan etiquetas a un {min(huecos):.0%} "
            f"del ancho: {posiciones}"
        )


def test_la_nota_del_eje_usa_coma_decimal():
    """«81.4» en una pantalla en español canta."""
    nota = axis_note(line_chart(PESOS, height=ALTURA))
    assert "." not in nota.split("empieza en ")[1].split(",")[0] + ""
    assert "," in nota
