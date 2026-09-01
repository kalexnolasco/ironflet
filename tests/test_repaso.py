"""repaso.py — la única función de la app que gasta dinero por su cuenta.

Todo lo demás llama al modelo porque Alex escribió algo. Esto lo llama solo,
una vez por semana, y le cobra a su tarjeta. Así que lo que más se prueba aquí
no es que funcione: es que **no se dispare cuando no debe**.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import repaso
from storage import Storage

LUNES = date(2026, 8, 31)
MARTES = date(2026, 9, 1)
LUNES_SIGUIENTE = LUNES + timedelta(days=7)


@pytest.fixture
def store(tmp_path):
    s = Storage(f"sqlite:///{tmp_path / 'r.db'}")
    import agent

    agent.save_key(s, "sk-or-v1-" + "a" * 48)
    return s


# ── cuándo NO se dispara ─────────────────────────────────────────────────


def test_apagado_de_fabrica(store):
    """Encendido por defecto sería empezar a cobrarle sin preguntarle."""
    assert repaso.activo(store) is False
    assert repaso.toca(store, LUNES) is False


def test_apagado_no_toca_nunca(store):
    repaso.configurar(store, activo=False)
    assert repaso.toca(store, LUNES) is False


def test_solo_el_dia_elegido(store):
    repaso.configurar(store, activo=True, dia=0)  # lunes
    assert repaso.toca(store, LUNES) is True
    assert repaso.toca(store, MARTES) is False


def test_una_vez_por_semana_y_no_una_por_arranque(store):
    """Lo que impide que abrir la app cinco veces un lunes cueste cinco
    llamadas."""
    repaso.configurar(store, activo=True, dia=0)
    assert repaso.toca(store, LUNES) is True

    repaso.guardar(store, "el repaso", hoy=LUNES)
    assert repaso.toca(store, LUNES) is False


def test_la_semana_siguiente_vuelve_a_tocar(store):
    repaso.configurar(store, activo=True, dia=0)
    repaso.guardar(store, "el de esta semana", hoy=LUNES)
    assert repaso.toca(store, LUNES_SIGUIENTE) is True


def test_va_por_semana_iso_no_por_siete_dias(store):
    """«Han pasado 7 días» se desplaza cada vez que uno llega tarde, y en dos
    meses el repaso del lunes cae en jueves."""
    repaso.configurar(store, activo=True, dia=0)
    # Se generó tarde, el miércoles de esa semana.
    repaso.guardar(store, "tarde", hoy=LUNES + timedelta(days=2))
    # El lunes siguiente toca igual, aunque no hayan pasado 7 días desde aquello.
    assert repaso.toca(store, LUNES_SIGUIENTE) is True


def test_sin_clave_no_toca(tmp_path):
    """Sin clave la llamada fallaría igual; preguntarlo antes ahorra el
    intento y el mensaje de error que nadie pidió."""
    s = Storage(f"sqlite:///{tmp_path / 'sinclave.db'}")
    repaso.configurar(s, activo=True, dia=0)
    assert repaso.toca(s, LUNES) is False


def test_un_fallo_gasta_la_semana(store):
    """Sin esto, un error de red convierte el repaso en un reintento por cada
    arranque — y cada uno que llegue a la API se cobra."""
    repaso.configurar(store, activo=True, dia=0)
    repaso.marcar_intento(store, LUNES)
    assert repaso.toca(store, LUNES) is False
    assert repaso.ultimo(store).hay is False, "un intento fallido no deja texto"


# ── lo que guarda ────────────────────────────────────────────────────────


def test_guarda_texto_coste_y_modelo(store):
    repaso.guardar(store, "  Bajaste 0,4 kg.  ", coste=0.0123, modelo="x/y", hoy=LUNES)
    r = repaso.ultimo(store)
    assert r.texto == "Bajaste 0,4 kg."
    assert r.fecha == LUNES.isoformat()
    assert r.coste == 0.0123
    assert r.modelo == "x/y"
    assert r.hay is True


def test_solo_guarda_el_ultimo(store):
    """No es un historial: es la nota de esta semana, y la de hace un mes no la
    lee nadie. Además lo hace barato de guardar — una pref, no un blob."""
    repaso.guardar(store, "viejo", hoy=LUNES)
    repaso.guardar(store, "nuevo", hoy=LUNES_SIGUIENTE)
    assert repaso.ultimo(store).texto == "nuevo"


def test_sin_nada_guardado_no_hay_repaso(store):
    assert repaso.ultimo(store).hay is False


def test_cambiar_el_dia_no_pisa_el_interruptor(store):
    repaso.configurar(store, activo=True, dia=0)
    repaso.configurar(store, dia=3)
    assert repaso.activo(store) is True
    assert repaso.dia_semana(store) == 3


@pytest.mark.parametrize("basura", ["no json", "[]", "null", '{"dia": "lunes"}', ""])
def test_una_pref_corrupta_lo_deja_apagado(store, basura):
    """Apagado es el fallo seguro: lo contrario sería cobrar por un JSON roto."""
    store.set_pref(repaso.PREF_KEY, basura)
    assert repaso.activo(store) is False
    assert repaso.toca(store, LUNES) is False


def test_una_base_muerta_no_dispara_nada():
    class Rota:
        def get_pref(self, *_a, **_k):
            raise RuntimeError("sin base")

    assert repaso.activo(Rota()) is False
    assert repaso.toca(Rota(), LUNES) is False


# ── la generación ────────────────────────────────────────────────────────


async def test_generar_marca_la_semana_antes_de_llamar(store, monkeypatch):
    """Si la llamada revienta a mitad, lo que no puede pasar es que el
    siguiente arranque lo intente otra vez y lo vuelva a pagar."""
    repaso.configurar(store, activo=True, dia=0)

    import agent

    def _revienta(self, *_a, **_k):
        assert repaso.toca(store, LUNES) is False, "llamó a la API sin gastar la semana"
        raise RuntimeError("sin red")

    monkeypatch.setattr(agent.Coach, "ask", _revienta)
    assert await repaso.generar(store, LUNES) is None
    assert repaso.toca(store, LUNES) is False


async def test_generar_guarda_lo_que_dice_el_coach(store, monkeypatch):
    import agent

    monkeypatch.setattr(
        agent.Coach,
        "ask",
        lambda self, *_a, **_k: agent.Reply(
            text="Tres sesiones y −0,4 kg.", charged=0.004, served_by="modelo/x"
        ),
    )
    r = await repaso.generar(store, LUNES)
    assert r is not None and r.texto == "Tres sesiones y −0,4 kg."
    assert r.coste == 0.004
    assert repaso.ultimo(store).texto == r.texto


async def test_una_respuesta_vacia_no_se_guarda(store, monkeypatch):
    """Una tarjeta en blanco en Inicio es peor que ninguna tarjeta."""
    import agent

    monkeypatch.setattr(agent.Coach, "ask", lambda self, *_a, **_k: agent.Reply(text="   "))
    assert await repaso.generar(store, LUNES) is None
    assert repaso.ultimo(store).hay is False


async def test_un_error_del_modelo_no_se_guarda(store, monkeypatch):
    import agent

    monkeypatch.setattr(
        agent.Coach, "ask", lambda self, *_a, **_k: agent.Reply(text="", error="402 sin crédito")
    )
    assert await repaso.generar(store, LUNES) is None
    assert repaso.ultimo(store).hay is False


def test_el_prompt_pide_lo_que_cabe_en_una_tarjeta():
    """Se lee en Inicio, no en una pantalla de informe: un texto largo ahí no
    se lee entero."""
    assert "tres o cuatro frases" in repaso.PROMPT.lower()
    assert "herramientas" in repaso.PROMPT
    assert "no propongas tarjetas" in repaso.PROMPT.lower()
