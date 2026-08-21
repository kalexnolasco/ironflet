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
