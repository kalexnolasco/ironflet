"""El cuerpo en pantalla: pintarlo, colorearlo y saber qué se ha tocado.

La geometría vive en `cuerpo.py` y no sabe nada de Flet — son números. Este
módulo es el que los convierte en `flet.canvas`, les pone color según lo que
Alex ha entrenado y traduce un toque en un músculo.

## El color dice cuánto, no cuál

Cada músculo se pinta en una escala de un solo tono: **apagado si no lo has
tocado, encendido si lo has machacado**. Un color por músculo sería bonito y
no diría nada — la pregunta que contesta esta pantalla es «qué llevo flojo», y
esa se contesta buscando lo oscuro.

La escala es **relativa a la semana**, no absoluta: 12 series de pecho son
muchas o pocas según lo que hayas hecho con lo demás, y una escala fija
obligaría a decidir un número de series «correcto» que depende de la rutina, la
fase y la persona. El músculo más trabajado marca el máximo y el resto se lee
contra él.

## El volumen, sin 3D

`PaintRadialGradient` con el foco donde daría la luz: es lo que hace que una
silueta plana se lea como un cuerpo, y cuesta un gradiente por músculo.

Desde 0.0.1 el móvil enseña un cuerpo 3D anatómico (`cuerpo3d.py`) y esto es lo
que se ve cuando aquel no puede: en el PC, en los tests, o si el visor falla.
`color_de` y `mezcla` son públicas porque las usan los dos.
"""

from __future__ import annotations

import flet as ft
import flet.canvas as cv

import cuerpo
from theme import C

#: Cuántos puntos por curva. Catmull-Rom convertido a cúbicas: cada par de
#: vértices da una Bézier, así que esto no es resolución sino cuántos tramos
#: tiene el contorno — y es el número de vértices, no un parámetro.
_TENSION = 6.0


def _cubicas(pts: tuple[tuple[float, float], ...], esc: float, dx: float, dy: float):
    """El contorno como elementos de `cv.Path`, suavizado y escalado.

    Catmull-Rom: cada tramo entre dos vértices se convierte en una cúbica cuyos
    tiradores salen de la dirección que traen los vecinos. Sin esto, un
    contorno de ocho puntos se ve como un octógono y un cuerpo no tiene
    esquinas.
    """
    n = len(pts)

    def punto(i):
        x, y = pts[i % n]
        return (x * esc + dx, y * esc + dy)

    p0 = punto(0)
    elementos = [cv.Path.MoveTo(p0[0], p0[1])]
    for i in range(n):
        a, b, c, d = punto(i - 1), punto(i), punto(i + 1), punto(i + 2)
        c1 = (b[0] + (c[0] - a[0]) / _TENSION, b[1] + (c[1] - a[1]) / _TENSION)
        c2 = (c[0] - (d[0] - b[0]) / _TENSION, c[1] - (d[1] - b[1]) / _TENSION)
        elementos.append(cv.Path.CubicTo(c1[0], c1[1], c2[0], c2[1], c[0], c[1]))
    elementos.append(cv.Path.Close())
    return elementos


def mezcla(hex_a: str, hex_b: str, t: float) -> str:
    """Interpola dos colores `#rrggbb`. `t=0` da el primero.

    Pública porque el cuerpo 3D también mezcla —el color del escenario sale de
    la paleta y no de un hex escrito a mano (trampa 5)."""

    def leer(h):
        h = h.lstrip("#")
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))

    a, b = leer(hex_a), leer(hex_b)
    t = max(0.0, min(1.0, t))
    return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * t):02x}" for i in range(3))


def _con_alfa(hex_color: str, alfa: float) -> str:
    """`#rrggbb` + opacidad, en el `#aarrggbb` que Flutter espera."""
    return f"#{round(max(0.0, min(1.0, alfa)) * 255):02x}{hex_color.lstrip('#')}"


def color_de(intensidad: float, series: float) -> str:
    """El color de un músculo según lo trabajado que esté.

    **Cuatro tramos y no un degradado de un solo tono.** El primer intento
    mezclaba el gris del fondo con el acento, y con 15 series de pierna y 3 de
    tríceps los dos salían azules: la escala existía en los números y no en el
    ojo. Un mapa de calor que no discrimina es un dibujo bonito.

    Es pública —y no `_color_de`— desde que hay dos cuerpos: el plano de este
    módulo y el de `cuerpo3d`. Que los dos pregunten aquí es lo que impide que
    la misma semana salga naranja en una pantalla y roja en la otra.

    Los colores salen todos de la paleta —`accent`, `success`, `warning`,
    `danger`— porque ninguna vista puede escribir un hex (trampa 5), y de paso
    la escala sigue al tema cuando cambia. Su orden aquí no es semántico: no
    dice «bien» y «mal», dice «poco» y «mucho», y por eso el rojo es lo más
    trabajado y no un error.
    """
    if series <= 0:
        # Ni siquiera el primer color de la escala: sin tocar tiene que leerse
        # como un hueco, porque es exactamente lo que es.
        return mezcla(C.bg_surface, C.bg_sunken, 0.5)

    tramos = ((0.0, C.accent), (0.4, C.success), (0.7, C.warning), (1.0, C.danger))
    for i in range(len(tramos) - 1):
        t0, c0 = tramos[i]
        t1, c1 = tramos[i + 1]
        if intensidad <= t1:
            return mezcla(c0, c1, (intensidad - t0) / (t1 - t0) if t1 > t0 else 0.0)
    # Por `mezcla` también en el extremo. Devolver el color de la paleta a
    # pelo salía en mayúsculas mientras el resto salía en minúsculas: Flutter
    # se traga los dos y el único que se entera es quien compare cadenas.
    return mezcla(tramos[-1][1], tramos[-1][1], 0.0)


def formas(
    vista: str,
    volumen: dict[str, float],
    ancho: float,
    alto: float,
    seleccionado: str = "",
) -> list:
    """Las formas del canvas para una vista, ya coloreadas.

    `volumen` es `analytics.sets_per_muscle_group().totals` — series por
    músculo, con las claves inglesas que ese módulo devuelve, sin tocar.
    """
    esc = min(ancho / cuerpo.ANCHO, alto / cuerpo.ALTO)
    dx = (ancho - cuerpo.ANCHO * esc) / 2
    dy = (alto - cuerpo.ALTO * esc) / 2

    # El máximo de la semana marca la escala. Ver `## El color dice cuánto`.
    presentes = [volumen.get(m.clave, 0.0) for m in cuerpo.de_la_vista(vista)]
    tope = max([*presentes, *volumen.values(), 0.0]) or 1.0

    salida = []

    # La silueta, debajo de todo: es lo que hace que un cuerpo con un solo
    # músculo entrenado siga pareciendo un cuerpo y no cuatro manchas.
    piel = ft.Paint(color=C.bg_sunken, style=ft.PaintingStyle.FILL)
    borde = ft.Paint(
        color=C.border, style=ft.PaintingStyle.STROKE, stroke_width=1.0, anti_alias=True
    )
    for trazo in cuerpo.SILUETA:
        elementos = _cubicas(trazo, esc, dx, dy)
        salida.append(cv.Path(elementos, paint=piel))
        salida.append(cv.Path(elementos, paint=borde))

    for m in cuerpo.de_la_vista(vista):
        series = volumen.get(m.clave, 0.0)
        intensidad = min(1.0, series / tope) if series > 0 else 0.0

        base = color_de(intensidad, series)
        brillo = mezcla(base, "#ffffff", 0.32)

        luz = (m.luz[0] * esc + dx, m.luz[1] * esc + dy)
        x0, y0, x1, y1 = cuerpo.caja(m)
        radio = max((x1 - x0), (y1 - y0)) * esc * 0.75

        relleno = ft.Paint(
            gradient=ft.PaintRadialGradient(
                center=luz,
                radius=max(radio, 1.0),
                colors=[_con_alfa(brillo, 0.95), _con_alfa(base, 1.0)],
                color_stops=[0.0, 1.0],
            ),
            style=ft.PaintingStyle.FILL,
            anti_alias=True,
        )
        contorno = ft.Paint(
            color=C.accent_2 if m.clave == seleccionado else C.bg_page,
            style=ft.PaintingStyle.STROKE,
            stroke_width=2.0 if m.clave == seleccionado else 0.8,
            anti_alias=True,
        )
        for trazo in m.trazos:
            elementos = _cubicas(trazo, esc, dx, dy)
            salida.append(cv.Path(elementos, paint=relleno))
            salida.append(cv.Path(elementos, paint=contorno))

    return salida


def musculo_en(vista: str, x: float, y: float, ancho: float, alto: float):
    """El músculo bajo un toque en píxeles de pantalla, o `None`.

    Deshace la misma escala que usó `formas`. Que las dos usen la fórmula
    idéntica no es casualidad: si divergen, el cuerpo se pinta en un sitio y
    responde en otro, y eso no lo enseña ninguna captura.
    """
    esc = min(ancho / cuerpo.ANCHO, alto / cuerpo.ALTO)
    if esc <= 0:
        return None
    dx = (ancho - cuerpo.ANCHO * esc) / 2
    dy = (alto - cuerpo.ALTO * esc) / 2
    return cuerpo.en_punto(vista, (x - dx) / esc, (y - dy) / esc)
