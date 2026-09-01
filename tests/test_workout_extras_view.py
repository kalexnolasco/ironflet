"""El buscador de ejercicios dentro de la sesión.

`tests/test_extras.py` cubre la capa de datos; esto cubre lo que solo se ve en
pantalla — y una de las dos cosas que prueba salió de mirar el emulador, no de
leer el código: buscar «crunch» un día de pecho dejaba al usuario en un
callejón sin salida, porque el filtro de grupo viene preseleccionado.
"""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import MagicMock

import flet as ft
import pytest

import catalogo
import extras


@pytest.fixture
def vista():
    from storage import Storage

    store = Storage(os.environ["TEST_DATABASE_URL"])
    store.set_pref(extras.PREF_KEY, "")
    sys.modules.pop("views.workout", None)
    modulo = importlib.import_module("views.workout")

    page = MagicMock()
    page.width = 400
    page.data = {
        "refresh_current": lambda: None,
        "store": store,
        "navigate_to": lambda *a, **k: None,
    }
    v = modulo.WorkoutView(page, store)
    v.phase_id = 1
    v.day_idx = 0
    try:
        yield v
    finally:
        store.set_pref(extras.PREF_KEY, "")
        sys.modules.pop("views.workout", None)


def _walk(control):
    out, seen = [], set()

    def bajar(c):
        if c is None or id(c) in seen:
            return
        seen.add(id(c))
        out.append(c)
        for k in getattr(c, "controls", None) or []:
            bajar(k)
        for attr in ("content", "title"):
            hijo = getattr(c, attr, None)
            if isinstance(hijo, ft.Control):
                bajar(hijo)

    bajar(control)
    return out


def _textos(control) -> str:
    return " | ".join(str(c.value) for c in _walk(control) if isinstance(c, ft.Text) and c.value)


def _dialogo(vista):
    vista._ask_add_exercise()
    return vista.page.open.call_args[0][0]


# ── el grupo del día ─────────────────────────────────────────────────────


def test_arranca_filtrado_por_lo_que_se_entrena_hoy(vista):
    """Abrirlo en «Abs Triset, Alternate DB Curl» —los dos primeros de 875 por
    orden alfabético— es abrirlo en el sitio menos útil posible."""
    assert vista._grupo_del_dia() == "Chest"
    texto = _textos(_dialogo(vista))
    assert "Barbell Bench Press" in texto


def test_un_dia_con_nombre_raro_no_filtra_nada(vista, monkeypatch):
    from data import TrainingDay

    monkeypatch.setattr(vista, "_routine_day", lambda: TrainingDay("Lo que sea", []))
    assert vista._grupo_del_dia() == ""


def test_sin_dia_no_hay_grupo(vista, monkeypatch):
    monkeypatch.setattr(vista, "_routine_day", lambda: None)
    assert vista._grupo_del_dia() == ""


# ── el callejón sin salida ───────────────────────────────────────────────


def test_buscar_algo_de_otro_grupo_lo_encuentra_igual(vista):
    """Salió del emulador: «crunch» un día de pecho decía «Nada con ese
    nombre» teniendo 21 resultados en Abs. Un buscador que contesta «nada»
    cuando tiene la respuesta es peor que uno lento.
    """
    assert catalogo.buscar("crunch", "Chest") == ()
    assert catalogo.buscar("crunch", "") != ()

    dlg = _dialogo(vista)
    campo = next(c for c in _walk(dlg) if isinstance(c, ft.TextField))
    campo.value = "crunch"
    campo.on_change(None)

    texto = _textos(dlg)
    assert "Nada con ese nombre" not in texto
    assert "Nada de Chest con ese nombre" in texto
    assert "Crunch" in texto


def test_si_de_verdad_no_hay_nada_lo_dice(vista):
    dlg = _dialogo(vista)
    campo = next(c for c in _walk(dlg) if isinstance(c, ft.TextField))
    campo.value = "qwertyuiop"
    campo.on_change(None)
    assert "Nada con ese nombre" in _textos(dlg)


# ── añadir y quitar desde el diálogo ─────────────────────────────────────


def test_anadir_desde_el_dialogo_lo_mete_en_la_sesion(vista):
    dlg = _dialogo(vista)
    fila = next(
        c for c in _walk(dlg) if getattr(c, "on_click", None) and "Cable Crossover" in _textos(c)
    )
    fila.on_click(None)

    assert "Cable Crossover" in extras.de_hoy(vista.store)
    assert "Cable Crossover" in vista._current_day().exercises


def test_lo_que_ya_esta_en_el_plan_no_se_puede_anadir(vista):
    """Añadirlo otra vez sería el mismo ejercicio dos veces en un día."""
    del_dia = vista._routine_day().exercises[0]
    dlg = _dialogo(vista)
    texto = _textos(dlg)
    assert "ya está en el plan de hoy" in texto

    from exercises import exercise_key

    fila = next(
        (
            c
            for c in _walk(dlg)
            if getattr(c, "on_click", None) and exercise_key(del_dia) in _textos(c)
        ),
        None,
    )
    assert fila is None, "el que ya está en el plan no debería ser pinchable"


def test_el_dia_de_la_rutina_sigue_intacto_tras_anadir(vista):
    original = list(vista._routine_day().exercises)
    extras.anadir(vista.store, "Cable Crossover")
    assert vista._current_day().exercises[-1] == "Cable Crossover"
    assert vista._routine_day().exercises == original


def test_atras_cierra_el_dialogo_antes_de_salir_de_la_pantalla(vista):
    """Sin esto, un back con el diálogo puesto sale de la pantalla del
    ejercicio y lo deja flotando sobre la lista del día."""
    vista.show_day_list = False
    _dialogo(vista)
    assert vista._add_dialog is not None
    assert vista.handle_back() is True
    assert vista._add_dialog is None
    assert vista.show_day_list is False, "se llevó por delante la pantalla además del diálogo"
