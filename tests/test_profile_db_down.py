"""Settings must say the database is unreachable, not render nothing.

Every read on that screen goes to the shared PostgreSQL that the Telegram bot
in ../agente/ also writes to, so a restart, a lock or a stopped container is an
ordinary event here. Unguarded, the exception came out of `build()` and the
screen rendered as blank — which in a gym is indistinguishable from a crash,
and says none of the reassuring part: the data is in Postgres, it is not lost,
this phone just cannot reach it.

The guard has to cover the **whole** render. The first version wrapped only the
two reads at the top of `build()` and left the weight section, which runs its
own query further down, still able to produce the blank screen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import flet as ft

from views.profile import ProfileView


class BaseCaida:
    """Every method raises, whichever one the screen happens to call."""

    def __init__(self, falla_en: str | None = None):
        self.falla_en = falla_en

    def __getattr__(self, name):
        def metodo(*a, **k):
            if self.falla_en in (None, name):
                raise RuntimeError("connection refused")
            return {} if name == "get_profile" else None

        return metodo


def _vista(store):
    page = MagicMock(spec=ft.Page)
    page.width, page.height, page.data = 400, 800, {}
    return ProfileView(page, store)


def _textos(control) -> str:
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
    return " ".join(fuera)


def test_la_base_caida_no_deja_la_pantalla_en_blanco():
    texto = _textos(_vista(BaseCaida()).build())
    assert texto.strip(), "Settings rendered nothing at all"
    assert "no pudo cargar" in texto.lower() or "algo falló" in texto.lower()


def test_conserva_el_titulo_de_la_pantalla():
    """Otherwise it reads as "the app replaced itself", not "no data here"."""
    assert "Ajustes" in _textos(_vista(BaseCaida()).build())


def test_ofrece_reintentar():
    assert "reintentar" in _textos(_vista(BaseCaida()).build()).lower()


def test_on_show_no_revienta_antes_del_primer_render():
    """`on_show()` runs before `build()`, so an exception there pre-empts the
    error card entirely — there would be nothing left to render it."""
    vista = _vista(BaseCaida())
    vista.on_show()
    assert vista._form_values == {}


def test_el_fallo_tardio_de_la_seccion_de_peso_tambien_esta_cubierto():
    """THE NARROW-TRY REGRESSION. `get_weights()` is called well after the two
    reads at the top of `build()`, so guarding only those left one live path
    straight back to the blank screen."""
    store = BaseCaida(falla_en="get_weights")
    texto = _textos(_vista(store).build())
    assert texto.strip()
    assert "Ajustes" in texto


# ── el formato de los campos del formulario ─────────────────────────────


def test_una_altura_entera_no_lleva_decimal():
    """«178.0» no es como nadie contesta cuánto mide.

    `height_cm` se guarda como float y el campo lo pintaba con `str()`.
    """
    from views.profile import _texto_de_campo

    assert _texto_de_campo(178.0) == "178"
    assert _texto_de_campo(178) == "178"


def test_una_altura_con_media_la_conserva():
    """178,5 sí es una altura que alguien apunta."""
    from views.profile import _texto_de_campo

    assert _texto_de_campo(178.5) == "178.5"


def test_un_campo_vacio_sigue_vacio():
    from views.profile import _texto_de_campo

    assert _texto_de_campo(None) == ""
    assert _texto_de_campo("") == ""
    assert _texto_de_campo(0) == ""


# ── la sección del widget, que solo existe en Android ───────────────────


def _ajustes(monkeypatch, tmp_path):
    """Un `ProfileView` con el entorno de Android fingido.

    Sin `FLET_APP_STORAGE_DATA`, `widget.disponible()` es False y la sección
    entera devuelve `[]` — así que en el escritorio NADIE la construye, y así
    es como un `ghost_button(icon=...)` llegó a la APK y tumbó la pantalla de
    Ajustes con un `TypeError`. Fingir el entorno es lo que hace que esta rama
    se ejecute en CI.
    """
    from unittest.mock import MagicMock

    import views.profile as pf

    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    page = MagicMock()
    page.width = 400
    page.height = 800
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda i, **k: None}
    vista = pf.ProfileView(page, MagicMock())
    vista._form_values = {}
    return vista


def test_la_seccion_del_widget_se_construye_en_android(monkeypatch, tmp_path):
    """Construirla es la mitad del test: un kwarg de más aquí revienta."""
    vista = _ajustes(monkeypatch, tmp_path)
    trozos = vista._widget_section()
    assert trozos, "en Android la sección tiene que existir"


def test_fuera_de_android_no_hay_seccion_del_widget(monkeypatch):
    """Un botón que no puede hacer nada es peor que la ausencia del botón."""
    from unittest.mock import MagicMock

    import views.profile as pf

    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    page = MagicMock()
    page.data = {"refresh_current": lambda: None}
    vista = pf.ProfileView(page, MagicMock())
    assert vista._widget_section() == []


def test_el_boton_del_widget_deja_la_nota_y_lo_dice(monkeypatch, tmp_path):
    """El camino entero: tocar el botón escribe la petición y avisa."""
    import widget

    vista = _ajustes(monkeypatch, tmp_path)
    trozos = vista._widget_section()

    botones = [c for c in _todos(trozos) if getattr(c, "on_click", None)]
    assert botones, "la sección tiene que traer un botón"
    botones[0].on_click(None)

    assert (tmp_path / widget.FICHERO_PIN).exists(), "la nota para Dart"
    nivel, texto = vista._widget_msg
    assert nivel == "success"
    assert "preguntar" in texto, "no se promete que esté hecho: lo decide el lanzador"


def test_si_no_se_puede_pedir_explica_la_via_manual(monkeypatch, tmp_path):
    """Con `false`, el botón no puede quedarse mudo."""
    import widget

    vista = _ajustes(monkeypatch, tmp_path)
    monkeypatch.setattr(widget, "pedir_colocacion", lambda *a, **k: False)

    botones = [c for c in _todos(vista._widget_section()) if getattr(c, "on_click", None)]
    botones[0].on_click(None)

    nivel, texto = vista._widget_msg
    assert nivel == "error"
    assert "Widgets" in texto, "hay que decir dónde está el selector"


def _todos(raiz):
    """Recorrido en profundidad de un árbol de controles."""
    vistos: set[int] = set()
    pila = list(raiz) if isinstance(raiz, list) else [raiz]
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
