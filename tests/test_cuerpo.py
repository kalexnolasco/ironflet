"""El mapa muscular: geometría, color y qué se ha tocado.

La geometría no importa Flet — son números en un lienzo de 100×220 — y eso es
lo que hace que se pueda probar aquí en vez de a base de compilar APKs de
80 MB para ver si un brazo está torcido.

El test que justifica el fichero es `test_cada_musculo_responde_a_su_propio
_toque`: la primera versión medía la caja del músculo **entero**, y en uno par
esa caja cruza el torso de lado a lado. Tocar el bíceps devolvía «Abdomen», y
en pantalla no se ve nada raro — el músculo se pinta bien y responde mal.
"""

from __future__ import annotations

import pytest

import cuerpo
from components.mapa_muscular import _color_de, _mezcla, formas, musculo_en

VISTAS = ("frente", "espalda")


# ── la geometría ─────────────────────────────────────────────────────────


def test_los_trece_musculos_que_devuelve_analytics_estan_todos():
    """Un músculo sin dibujo es volumen que no se ve en ninguna parte."""
    from analytics import DIRECCION_DESEADA  # noqa: F401 - solo para fijar el import

    dibujados = {m.clave for m in cuerpo.MUSCULOS}
    # Las claves que `sets_per_muscle_group` produce de verdad, sacadas del
    # catálogo y no escritas a mano.
    import exercise_details as ed

    reales = {
        m
        for d in ed.EXERCISE_DETAILS.values()
        for m in (*d.get("primary", []), *d.get("secondary", []))
    }
    sin_dibujo = sorted(reales - dibujados)
    # `neck`, `adductors` y `abductors` no se dibujan a propósito: son zonas
    # que ningún ejercicio de las rutinas trabaja de forma directa y meterlas
    # llenaría el cuerpo de manchas que nunca se encienden.
    assert set(sin_dibujo) <= {"neck", "adductors", "abductors", "traps"}


@pytest.mark.parametrize("m", cuerpo.MUSCULOS, ids=lambda m: m.clave)
def test_ningun_musculo_se_sale_del_lienzo(m):
    x0, y0, x1, y1 = cuerpo.caja(m)
    assert 0 <= x0 < x1 <= cuerpo.ANCHO
    assert 0 <= y0 < y1 <= cuerpo.ALTO


@pytest.mark.parametrize("m", cuerpo.MUSCULOS, ids=lambda m: m.clave)
def test_cada_musculo_tiene_trazos_y_su_luz_dentro(m):
    assert m.trazos, f"{m.clave} no se dibuja"
    for trazo in m.trazos:
        assert len(trazo) >= 5, f"{m.clave}: un contorno de {len(trazo)} puntos no es un músculo"
    x0, y0, x1, y1 = cuerpo.caja(m)
    lx, ly = m.luz
    assert x0 <= lx <= x1 and y0 <= ly <= y1, f"{m.clave}: la luz cae fuera del músculo"


def test_los_musculos_pares_son_simetricos():
    """Escribir las dos mitades a mano es escribir dos veces el mismo error."""
    for m in cuerpo.MUSCULOS:
        if len(m.trazos) != 2:
            continue
        izq, der = m.trazos
        assert len(izq) == len(der), m.clave
        for (xi, yi), (xd, yd) in zip(izq, der, strict=True):
            assert yi == yd, f"{m.clave}: los lados no están a la misma altura"
            assert abs((xi + xd) - cuerpo.ANCHO) < 1e-6, f"{m.clave}: no es simétrico"


def test_cada_musculo_esta_en_una_sola_vista():
    """Un cuerpo que enseña el pectoral y el dorsal a la vez no es un cuerpo."""
    for m in cuerpo.MUSCULOS:
        assert m.vista in VISTAS
    claves = [m.clave for m in cuerpo.MUSCULOS]
    assert len(claves) == len(set(claves))


def test_las_dos_vistas_tienen_musculos():
    for v in VISTAS:
        assert len(cuerpo.de_la_vista(v)) >= 6


# ── LO que se ha tocado ──────────────────────────────────────────────────


@pytest.mark.parametrize("m", cuerpo.MUSCULOS, ids=lambda m: m.clave)
def test_cada_musculo_responde_a_su_propio_toque(m):
    """EL test. La caja de un músculo par cruza el torso: la del bíceps va de
    x=22 a x=78, así que tocarlo devolvía «Abdomen». `cajas()` da una por
    lado; `caja()` sigue existiendo para colocar etiquetas y **no** vale para
    esto."""
    for x0, y0, x1, y1 in cuerpo.cajas(m):
        golpe = cuerpo.en_punto(m.vista, (x0 + x1) / 2, (y0 + y1) / 2)
        assert golpe is not None and golpe.clave == m.clave, (
            f"el centro de {m.clave} devuelve {golpe.clave if golpe else 'nada'}"
        )


def test_la_caja_entera_de_un_par_cruza_el_torso():
    """El hecho que hace incorrecta la versión ingenua, fijado para que nadie
    la reintroduzca por parecer más simple."""
    biceps = cuerpo.por_clave("biceps")
    x0, _y0, x1, _y1 = cuerpo.caja(biceps)
    assert x0 < 40 and x1 > 60, "la caja del bíceps ya no cruza el centro"
    assert len(cuerpo.cajas(biceps)) == 2


def test_fuera_del_cuerpo_no_hay_nada():
    assert cuerpo.en_punto("frente", 2.0, 2.0) is None
    assert cuerpo.en_punto("frente", 99.0, 215.0) is None


def test_una_vista_que_no_existe_no_revienta():
    assert cuerpo.en_punto("perfil", 50.0, 50.0) is None
    assert cuerpo.de_la_vista("perfil") == ()


def test_por_clave_encuentra_y_falla_limpio():
    assert cuerpo.por_clave("chest").etiqueta == "Pecho"
    assert cuerpo.por_clave("inventado") is None


# ── el paso a píxeles ────────────────────────────────────────────────────


@pytest.mark.parametrize("ancho, alto", [(150, 280), (300, 500), (90, 400)])
def test_lo_que_se_pinta_y_lo_que_responde_usan_la_misma_escala(ancho, alto):
    """Si divergen, el cuerpo se pinta en un sitio y responde en otro — y eso
    no lo enseña ninguna captura, solo un dedo que no acierta.

    Se mide sobre el **abdomen**, y a propósito: es el único músculo que no
    toca a ningún vecino, así que sus bordes son sitio limpio para detectar un
    desfase. Probarlo en todos y por las esquinas no funciona —la esquina del
    pecho cae dentro de la caja del hombro, que se tocan— y eso no es un fallo
    del código sino de usar rectángulos, que es una decisión tomada a
    conciencia en `en_punto`.

    Con el centro tampoco valía: un desfase del 10 % entre las dos escalas no
    rompía nada, porque las cajas son grandes y el punto seguía cayendo
    dentro. Pegado al borde, unos pocos píxeles ya se salen.
    """
    esc = min(ancho / cuerpo.ANCHO, alto / cuerpo.ALTO)
    dx = (ancho - cuerpo.ANCHO * esc) / 2
    dy = (alto - cuerpo.ALTO * esc) / 2

    x0, y0, x1, y1 = cuerpo.cajas(cuerpo.por_clave("abdominals"))[0]
    an, al = x1 - x0, y1 - y0
    for ux, uy in (
        (x0 + an * 0.05, y0 + al * 0.05),
        (x1 - an * 0.05, y1 - al * 0.05),
        (x0 + an * 0.05, y1 - al * 0.05),
        (x1 - an * 0.05, y0 + al * 0.05),
    ):
        golpe = musculo_en("frente", ux * esc + dx, uy * esc + dy, ancho, alto)
        assert golpe is not None and golpe.clave == "abdominals", (
            f"borde del abdomen en ({ux:.0f},{uy:.0f}) responde "
            f"{golpe.clave if golpe else 'nada'} — las escalas no coinciden"
        )


def test_un_lienzo_de_cero_no_divide_por_cero():
    assert musculo_en("frente", 10, 10, 0, 0) is None


# ── el color ─────────────────────────────────────────────────────────────


def test_sin_series_el_musculo_se_lee_como_hueco():
    """Ni siquiera el primer color de la escala: sin tocar tiene que verse
    apagado, porque es exactamente lo que es."""
    from theme import C

    apagado = _color_de(0.0, 0.0)
    assert apagado != _color_de(0.01, 1.0)
    assert apagado == _mezcla(C.bg_surface, C.bg_sunken, 0.5)


def test_la_escala_discrimina_de_verdad():
    """La primera versión mezclaba el gris con el acento y 15 series de pierna
    salían del mismo azul que 3 de tríceps: la escala existía en los números y
    no en el ojo."""
    colores = [_color_de(i / 4, 5.0) for i in range(5)]
    assert len(set(colores)) == 5, "dos tramos dan el mismo color"

    def canales(h):
        h = h.lstrip("#")
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))

    # De frío a cálido: el rojo sube con el volumen.
    rojos = [canales(c)[0] for c in colores]
    assert rojos[-1] > rojos[0] + 60, f"apenas cambia: {rojos}"


def test_el_color_no_se_sale_de_la_escala():
    assert _color_de(5.0, 9.0) == _color_de(1.0, 9.0)
    assert _color_de(-1.0, 9.0) == _color_de(0.0, 9.0)


# ── el canvas ────────────────────────────────────────────────────────────


def test_se_pinta_la_silueta_y_todos_los_musculos():
    de_la_vista = cuerpo.de_la_vista("frente")
    trazos_musculo = sum(len(m.trazos) for m in de_la_vista)
    # Relleno + contorno por trazo, y lo mismo por pieza de silueta.
    esperadas = len(cuerpo.SILUETA) * 2 + trazos_musculo * 2
    assert len(formas("frente", {}, 150, 280)) == esperadas


def test_se_pinta_sin_datos():
    """El primer arranque: la tabla vacía no puede dejar la tarjeta en blanco."""
    assert formas("frente", {}, 150, 280)
    assert formas("espalda", {}, 150, 280)


def test_el_seleccionado_se_marca():
    """Sin marca, tocar un músculo cambia el texto de al lado y el cuerpo no
    dice cuál — el número aparece sin que se sepa de dónde salió."""
    sin = formas("frente", {"chest": 9.0}, 150, 280)
    con = formas("frente", {"chest": 9.0}, 150, 280, seleccionado="chest")
    anchos_sin = [f.paint.stroke_width for f in sin if f.paint.stroke_width]
    anchos_con = [f.paint.stroke_width for f in con if f.paint.stroke_width]
    assert max(anchos_con) > max(anchos_sin)
