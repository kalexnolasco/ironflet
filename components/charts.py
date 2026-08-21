"""Las gráficas, dibujadas por Flet y no apiladas a mano.

Hasta 0.13 esto componía barras con `ft.Container` de altura calculada, y el
docstring presumía de no tener dependencias externas. No las tenía porque no
hacían falta: **Flet trae `BarChart` y `LineChart` desde la 0.22** y este
módulo los estaba reimplementando peor. Lo que se ganaba con los Containers
—ninguna dependencia nueva— ya lo daba la caja; lo que se perdía era todo lo
demás: ejes, rejilla, tooltips que siguen al dedo, y una línea, que para una
serie temporal dice lo que una fila de barras no puede.

Lo que **no** cambia es el contrato, porque `views/profile.py` y
`views/history.py` dependen de él:

* `bar_chart(values, labels, color, height, baseline)` → un control con el
  atributo `chart_floor`.
* `axis_note(chart)` → la frase que confiesa un eje recortado, o `None`.

`line_chart()` es nuevo y es para lo que de verdad pedía una línea: el peso
corporal y la progresión de 1RM son series en el tiempo, no magnitudes
comparadas, y siete barras separadas esconden precisamente la tendencia que se
mira. Acepta una segunda serie opcional para la media móvil — el peso de un
día es ruido, y la media es la señal por la que se decide si el plan va bien.
"""

from __future__ import annotations

import flet as ft

from theme import C

#: Aire que se deja por arriba y por abajo al calcular la base. Sin él la
#: lectura más baja es un muñón de dos píxeles y la más alta toca el techo, que
#: se lee como "se sale de la gráfica".
_PAD = 0.15


def _floor_for(values: list[float], baseline: str) -> float:
    """De dónde arrancan las barras.

    `"zero"` es lo honesto para una magnitud —volumen, series, reps— donde la
    altura de la barra *es* la cantidad y un eje recortado exageraría un cambio
    pequeño.

    `"auto"` existe para las series que viven en una franja estrecha y lejos
    del cero, donde una base en cero es honesta e inútil a partes iguales. El
    peso corporal es el caso que lo forzó: siete pesajes entre 82,0 y 84,2 kg
    se dibujaban como 110, 109, 109, 108, 107, 108, 107 px — 2,2 kg de cambio
    en **tres píxeles**, en la única gráfica por la que se guía una
    recomposición. La progresión de 1RM tenía el mismo problema por lo mismo:
    a nadie le sube el banca desde cero.

    Un eje recortado puede engañar, así que quien use `"auto"` tiene que
    decirlo — la gráfica devuelve la base que usó en `chart_floor`.
    """
    if baseline != "auto" or not values:
        return 0.0
    low, high = min(values), max(values)
    span = high - low
    if span <= 0:
        # Todas las lecturas idénticas: una base justo por debajo las mantiene
        # visibles en vez de aplastar la gráfica entera contra el cero.
        return max(0.0, low - max(abs(low) * 0.01, 0.5))
    return max(0.0, low - span * _PAD)


def _vacio(height: int) -> ft.Control:
    hueco = ft.Container(
        content=ft.Text("Sin datos", color=C.text_muted, size=11, italic=True),
        alignment=ft.alignment.center,
        height=height,
    )
    hueco.chart_floor = 0.0
    return hueco


def _etiquetas_eje(labels: list[str], cuantas: int) -> list[ft.ChartAxisLabel]:
    """Las etiquetas del eje X, saltando las que no caben.

    En un móvil de ~390 px lógicos caben unas seis antes de solaparse, así que
    con más puntos se pinta una de cada n — la primera y la última siempre,
    que son las que sitúan la serie en el tiempo.

    La última se añade **descartando la anterior si queda pegada**. Con 22
    lecturas el paso sale 4, así que se elegían la 20 y la 21: dos etiquetas
    consecutivas en el borde derecho, que en pantalla salieron una encima de
    otra («08-2008-21»).

    El listón es el propio paso, no una fracción inventada: el paso ya es la
    separación que se consideró legible para esta serie, así que dos etiquetas
    más juntas que eso no caben por definición. Con series cortas el paso es 1,
    todas las posiciones entran y la rama no llega a ejecutarse.
    """
    if not labels:
        return []
    paso = max(1, (cuantas + 5) // 6)
    indices = [i for i in range(cuantas) if i % paso == 0]
    ultimo = cuantas - 1
    if ultimo not in indices:
        if indices and ultimo - indices[-1] < paso:
            indices.pop()
        indices.append(ultimo)

    salida = []
    for i in indices:
        texto = labels[i] if i < len(labels) else ""
        if not texto:
            continue
        salida.append(
            ft.ChartAxisLabel(
                value=i,
                label=ft.Text(texto, size=8, color=C.text_muted),
            )
        )
    return salida


def bar_chart(
    values: list[float],
    labels: list[str] | None = None,
    color: str | None = None,
    height: int = 120,
    baseline: str = "zero",
) -> ft.Control:
    """Barras para una magnitud: volumen, series, reps.

    Mismo contrato que la versión de Containers, incluido `chart_floor`.
    """
    # Por defecto None y resuelto aquí: un color evaluado en el `def` congelaría
    # la paleta que estuviera activa al importar.
    color = color or C.chart_bar
    if not values:
        # Se llega por la ruta normal — el detalle abre en "1RM est.", que está
        # vacío para los ejercicios de peso corporal o solo de calentamiento.
        return _vacio(height)

    labels = labels or []
    floor = _floor_for(values, baseline)
    top = max(values)
    # Un techo pegado al dato máximo deja la barra más alta tocando el borde.
    techo = top + max((top - floor) * 0.08, 0.5)

    grupos = [
        ft.BarChartGroup(
            x=i,
            bar_rods=[
                ft.BarChartRod(
                    from_y=floor,
                    to_y=v,
                    width=14,
                    color=color,
                    tooltip=f"{v:g}",
                    border_radius=ft.border_radius.only(top_left=4, top_right=4),
                )
            ],
        )
        for i, v in enumerate(values)
    ]

    chart = ft.BarChart(
        bar_groups=grupos,
        min_y=floor,
        max_y=techo,
        height=height,
        bottom_axis=ft.ChartAxis(labels=_etiquetas_eje(labels, len(values)), labels_size=18),
        # Sin eje izquierdo a propósito: en 390 px lógicos, cuatro cifras de
        # ordenada roban el ancho que necesitan las barras, y el tooltip ya da
        # el valor exacto de la que interesa.
        left_axis=ft.ChartAxis(show_labels=False),
        horizontal_grid_lines=ft.ChartGridLines(color=C.border, width=1, dash_pattern=[3, 4]),
        tooltip_bgcolor=C.bg_sunken,
        interactive=True,
        expand=True,
    )
    # Se informa, no se esconde: una gráfica cuyo eje no empieza en cero tiene
    # que poder decirlo, o es solo una mentira más bonita.
    chart.chart_floor = floor
    return chart


def line_chart(
    values: list[float],
    labels: list[str] | None = None,
    color: str | None = None,
    height: int = 140,
    baseline: str = "auto",
    trend: list[float] | None = None,
) -> ft.Control:
    """Una línea para una serie en el tiempo: peso corporal, 1RM estimado.

    `trend` dibuja una segunda serie por encima, más fina y sin puntos — la
    media móvil. Es la mitad que importa: el peso de un día concreto sube y
    baja con la sal y la hora a la que te pesaste, y decidir sobre ese número
    es decidir sobre ruido.

    La base es `"auto"` por defecto, al revés que en `bar_chart`, porque una
    serie temporal de peso o de 1RM nunca arranca en cero y una línea plana en
    lo alto del marco no dice nada.
    """
    color = color or C.accent
    if not values:
        return _vacio(height)

    labels = labels or []
    referencia = values + [v for v in (trend or []) if v is not None]
    floor = _floor_for(referencia, baseline)
    top = max(referencia)
    margen = max((top - floor) * 0.1, 0.5)

    series = [
        ft.LineChartData(
            data_points=[ft.LineChartDataPoint(i, v) for i, v in enumerate(values)],
            stroke_width=2,
            color=color,
            curved=True,
            stroke_cap_round=True,
            # Relleno bajo la curva: en una serie de una sola línea es lo que
            # separa "una línea en una caja" de algo que se lee de un vistazo.
            below_line_bgcolor=ft.Colors.with_opacity(0.12, color),
            point=ft.ChartCirclePoint(color=color, radius=3, stroke_width=0),
        )
    ]
    if trend:
        series.append(
            ft.LineChartData(
                data_points=[
                    ft.LineChartDataPoint(i, v) for i, v in enumerate(trend) if v is not None
                ],
                stroke_width=1,
                color=C.text_muted,
                curved=True,
                dash_pattern=[4, 3],
            )
        )

    chart = ft.LineChart(
        data_series=series,
        min_y=floor,
        max_y=top + margen,
        min_x=0,
        max_x=max(0, len(values) - 1),
        height=height,
        bottom_axis=ft.ChartAxis(labels=_etiquetas_eje(labels, len(values)), labels_size=18),
        left_axis=ft.ChartAxis(show_labels=False),
        horizontal_grid_lines=ft.ChartGridLines(color=C.border, width=1, dash_pattern=[3, 4]),
        tooltip_bgcolor=C.bg_sunken,
        interactive=True,
        expand=True,
    )
    chart.chart_floor = floor
    return chart


def axis_note(chart: ft.Control) -> str | None:
    """«La escala empieza en 82, no en 0» — o None cuando arranca en cero.

    Un ayudante en vez de que cada llamante mire `chart_floor`: la nota es la
    otra mitad de `baseline="auto"`, y la mitad que se olvida.
    """
    floor = getattr(chart, "chart_floor", 0.0) or 0.0
    if floor <= 0:
        return None
    # Un decimal y sin ceros de cola: la base es un número calculado, y "81,67"
    # en un pie de gráfica se lee como una medida en vez de como una escala.
    # Coma decimal, además: es la única frase de esta app que llevaba un punto,
    # y en una pantalla en español «81.4» canta.
    texto = f"{floor:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"La escala empieza en {texto}, no en 0"
