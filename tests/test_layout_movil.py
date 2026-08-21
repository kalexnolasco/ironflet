"""Lo que solo se ve con la app instalada en un teléfono.

Cuatro cosas que la suite de 1727 tests daba por buenas porque **ninguna de
ellas es un error**: el árbol de controles se construye, los textos son los
correctos, nada lanza. Simplemente no caben, o no se pintan como se leen. Se
cazaron mirando capturas del emulador una a una, y este fichero existe para que
la próxima vez las cace pytest.

No se puede medir píxeles sin un motor de render, así que ninguno de estos
tests mide píxeles. Cada uno comprueba la **propiedad estructural** de la que
dependía el fallo — que es lo que de verdad hay que congelar, porque el número
concreto de píxeles cambia con la pantalla y la propiedad no.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import flet as ft
import pytest

from theme import LIGHT, set_palette


@pytest.fixture(autouse=True)
def paleta_clara():
    set_palette(LIGHT)
    yield
    set_palette(LIGHT)


def _hijos(control):
    """Los controles directos, sea cual sea el contenedor."""
    if isinstance(control, (list, tuple)):
        return list(control)
    return list(getattr(control, "controls", None) or [])


# ── el temporizador de descanso ─────────────────────────────────────────


def _timer():
    from components.timer import RestTimer

    page = MagicMock()
    page.width = 400
    return RestTimer(page)


def test_la_fila_de_descanso_puede_envolver_en_vez_de_salirse():
    """El botón «Parar» salía cortado por el borde derecho de la pantalla.

    Siete controles (cuatro presets, sonido, vibración y Parar) en una `Row`
    con `wrap=True` — que no envuelve nunca si nadie le dice dónde acaba la
    línea. Dentro de la `Row` exterior el hijo recibe ancho infinito; el
    `expand=True` es lo que lo acota. En `build_large` el mismo control vive
    dentro de una `Column`, que ya lo acota, y por eso allí nunca falló.
    """
    fila = _timer().build()
    controles = _hijos(fila)
    assert len(controles) == 2, "dial y controles"
    _dial, botones = controles

    assert botones.wrap is True, "sin wrap no hay nada que envolver"
    assert botones.expand, (
        "la fila de controles necesita ancho acotado para envolver; sin "
        "`expand` recibe infinito y el último botón se sale de la pantalla"
    )


def test_el_modo_zen_no_necesita_expand_porque_ya_esta_acotado():
    """La contraparte: acota por Column, y por eso allí no hace falta.

    Está aquí para que quien quite el `expand` de arriba vea por qué existe.
    """
    grande = _timer().build_large()
    columna = grande.content
    assert isinstance(columna, ft.Column)
    fila_botones = _hijos(columna)[-1]
    assert fila_botones.wrap is True


# ── la galería de fotos ─────────────────────────────────────────────────


#: El `child_aspect_ratio` con el que la fecha salía cortada, medido en un
#: Pixel de 1080×2340. No es un cálculo — la aritmética de "132 de miniatura
#: más una línea de 9 pt" daba de sobra y aun así se cortaba, porque el ancho
#: real de celda es menor que `_THUMB_PX` una vez el GridView descuenta su
#: spacing. Lo que se congela aquí es la observación, que es lo único que de
#: verdad se sabe.
RATIO_QUE_CORTABA = 0.82


def test_la_celda_de_la_galeria_deja_sitio_para_la_fecha():
    """La fecha bajo la miniatura salía cortada por la mitad.

    `child_aspect_ratio` es ancho/alto: **bajarlo da más alto**. Cualquier
    valor igual o mayor que el que se vio fallar vuelve a recortar la
    etiqueta, así que el test pide margen por debajo, no un número exacto.
    """
    import views.photos_view as pv

    page = MagicMock()
    page.width = 400
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
    vista = pv.PhotosView(page, MagicMock())

    # Con la lista vacía la vista pinta el estado vacío y no monta rejilla.
    filas = [{"date": "2026-08-21", "file": "2026-08-21.jpg", "path": None, "note": None}]
    pantalla = vista._grid(filas)
    grid = next(c for c in _todos_los_controles(pantalla) if isinstance(c, ft.GridView))

    assert grid.child_aspect_ratio < RATIO_QUE_CORTABA, (
        f"con {RATIO_QUE_CORTABA} la fecha se cortaba a media altura en el "
        f"emulador; {grid.child_aspect_ratio} no deja más sitio que aquello"
    )
    # Y que nadie lo arregle dándole tanto alto que la rejilla quede vacía.
    assert grid.child_aspect_ratio > 0.5, "una celda el doble de alta que ancha es un hueco"


def _todos_los_controles(raiz):
    """Recorrido en profundidad del árbol, sin repetir."""
    vistos: set[int] = set()
    pila = [raiz]
    while pila:
        nodo = pila.pop()
        if nodo is None or id(nodo) in vistos:
            continue
        vistos.add(id(nodo))
        yield nodo
        if isinstance(nodo, (list, tuple)):
            pila.extend(nodo)
            continue
        for attr in ("content", "controls", "actions", "title"):
            hijo = getattr(nodo, attr, None)
            if hijo is not None:
                pila.append(hijo)


# ── el campo de fecha de nacimiento ─────────────────────────────────────


def test_el_formato_de_fecha_va_en_el_hint_no_en_el_label():
    """«Nacimiento (AAAA-MM-DD)» no cabe en media fila.

    El label flotante envolvía a dos líneas y la primera se pintaba encima del
    borde inferior del campo Nombre, que está justo arriba. El formato vive
    ahora en el `hint_text`, que solo se ve con el campo vacío — que es
    exactamente cuando hace falta.
    """
    import views.profile as pf

    page = MagicMock()
    page.width = 400
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
    vista = pf.ProfileView(page, MagicMock())
    vista._form_values = {}

    campo = vista._text_input("Nacimiento", "birthdate", hint="AAAA-MM-DD")
    assert campo.label == "Nacimiento"
    assert campo.hint_text == "AAAA-MM-DD"
    assert len(campo.label) <= 12, (
        "un label de más de ~12 caracteres no cabe en media fila y envuelve "
        "encima del campo de arriba"
    )


# ── el markdown del coach ───────────────────────────────────────────────


def test_la_negrita_del_coach_no_se_lee_con_asteriscos():
    """«Hoy toca **Pecho-Bíceps + Abs**» se leía con los asteriscos puestos.

    El modelo responde en markdown y la burbuja pintaba `ft.Text(value=...)`.
    """
    from views.agent_view import spans_markdown

    spans = spans_markdown("Hoy toca **Pecho-Bíceps** hoy")
    textos = [s.text for s in spans]
    assert "".join(textos) == "Hoy toca Pecho-Bíceps hoy", "los asteriscos se van"

    negritas = [s for s in spans if s.style and s.style.weight == ft.FontWeight.W_700]
    assert [s.text for s in negritas] == ["Pecho-Bíceps"]


def test_el_texto_sin_marcas_pasa_entero_y_sin_tocar():
    """Lo que escribe Alex es texto plano y debe salir tal cual.

    Un asterisco suelto («3*8») es multiplicación, no cursiva.
    """
    from views.agent_view import spans_markdown

    for crudo in ("Hice 4 series de sentadilla a 80 por 8", "3*8 a 60 kg", ""):
        spans = spans_markdown(crudo)
        assert "".join(s.text for s in spans) == crudo
        assert all(s.style is None for s in spans), f"nada que estilar en {crudo!r}"


def test_los_encabezados_pierden_la_almohadilla():
    from views.agent_view import spans_markdown

    spans = spans_markdown("## Resumen\nDos series")
    assert "".join(s.text for s in spans) == "Resumen\nDos series"


def test_la_cursiva_tambien_y_sin_comerse_la_negrita():
    from views.agent_view import spans_markdown

    spans = spans_markdown("uno **dos** tres *cuatro* cinco")
    assert "".join(s.text for s in spans) == "uno dos tres cuatro cinco"
    estilados = {s.text: s.style for s in spans if s.style}
    assert estilados["dos"].weight == ft.FontWeight.W_700
    assert estilados["cuatro"].italic is True


def test_la_burbuja_del_chat_usa_el_conversor_y_no_el_texto_crudo():
    """Los tres de arriba prueban el conversor; este, que la burbuja lo llame.

    Sin esto, `spans_markdown` puede quedarse perfecta y sin usar — que es
    exactamente el estado del que venimos, con `ft.Text(value=b.text)` pintando
    los asteriscos.
    """
    import views.agent_view as av

    page = MagicMock()
    page.width = 400
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
    vista = av.AgentView(page, MagicMock())

    fila = vista._bubble(av.Bubble(who="coach", text="Hoy toca **Pecho-Bíceps**"))
    texto = next(c for c in _todos_los_controles(fila) if isinstance(c, ft.Text))

    assert texto.spans, "la burbuja tiene que pintar spans, no una cadena cruda"
    assert not texto.value, "con `value` puesto, Flet ignora los spans"
    assert "**" not in "".join(s.text for s in texto.spans)
