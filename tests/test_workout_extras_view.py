"""El buscador de ejercicios dentro de la sesión.

`tests/test_extras.py` cubre la capa de datos; esto cubre lo que solo se ve en
pantalla — y una de las dos cosas que prueba salió de mirar el emulador, no de
leer el código: buscar «crunch» un día de pecho dejaba al usuario en un
callejón sin salida, porque el filtro de grupo viene preseleccionado.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import flet as ft
import pytest

import catalogo
import extras


@pytest.fixture
def vista():
    from storage import Storage

    # Sin recargar el módulo. Hacía `sys.modules.pop` porque `test_nutrition_view`
    # dejaba un stub de `nutrition` puesto y había que deshacerlo; ese fichero
    # se fue con la nutrición en 0.21, y con él la razón. Recargar por si acaso
    # es lo que rompió a un vecino la última vez (trampa 33).
    from views.workout import WorkoutView

    store = Storage(os.environ["TEST_DATABASE_URL"])
    store.set_pref(extras.PREF_KEY, "")

    page = MagicMock()
    page.width = 400
    page.data = {
        "refresh_current": lambda: None,
        "store": store,
        "navigate_to": lambda *a, **k: None,
    }
    v = WorkoutView(page, store)
    v.phase_id = 1
    v.day_idx = 0
    try:
        yield v
    finally:
        store.set_pref(extras.PREF_KEY, "")


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
    assert "Press banca con barra" in texto  # el nombre que se PINTA


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
    """Se toca lo que se lee («Cruces en polea») y se guarda la clave («Cable
    Crossover»). Ese salto es toda la capa de traducción, en un test."""
    import nombres_es

    dlg = _dialogo(vista)
    visible = nombres_es.ejercicio("Cable Crossover")
    assert visible != "Cable Crossover", "la traducción dejó de aplicarse"

    fila = next(c for c in _walk(dlg) if getattr(c, "on_click", None) and visible in _textos(c))
    fila.on_click(None)

    assert "Cable Crossover" in extras.de_hoy(vista.store)
    assert "Cable Crossover" in vista._current_day().exercises
    assert visible not in extras.de_hoy(vista.store), "guardó el nombre traducido"


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


# ── entreno libre: ejercicios sueltos, sin rutina ────────────────────────


def test_el_entreno_libre_solo_lleva_lo_que_elijas(vista):
    """«Llego al gimnasio sin plan y hago cuatro cosas». Antes había que
    entrar por una fase y un día, o sea fingir que hoy tocaba pecho — y esa
    mentira acaba en `entrenos.grupo`, que es lo que agrupa Historial."""
    extras.anadir(vista.store, "Cable Crossover")
    extras.anadir(vista.store, "Pec Deck")
    vista.empezar_libre()

    assert vista.libre is True
    assert vista._current_day().exercises == ["Cable Crossover", "Pec Deck"]
    assert vista._current_day().name == "Free"


def test_el_dia_libre_se_llama_free_y_no_libre(vista):
    """Ese nombre va literal a `entrenos.grupo` (trampa 22), donde el
    vocabulario es inglés — «Chest - Biceps», «Upper Power», «Abs»."""
    extras.anadir(vista.store, "Pec Deck")
    vista.empezar_libre()
    assert vista._current_day().name == "Free"


def test_el_entreno_libre_respeta_el_abdomen(vista):
    """Está encendido para todos los días, y un entreno libre es un día."""
    import abdomen

    abdomen.configurar(vista.store, activo=True, por_dia=3)
    extras.anadir(vista.store, "Pec Deck")
    vista.empezar_libre()

    ejercicios = vista._current_day().exercises
    assert ejercicios[0] == "Pec Deck"
    assert ejercicios[1:] == list(abdomen.de_hoy(vista.store))


def test_el_entreno_libre_no_duplica_lo_elegido(vista):
    extras.anadir(vista.store, "Pec Deck")
    vista.empezar_libre()
    ejercicios = vista._current_day().exercises
    assert len(ejercicios) == len(set(ejercicios))


def test_atras_sale_del_entreno_libre(vista):
    extras.anadir(vista.store, "Pec Deck")
    vista.empezar_libre()
    assert vista.handle_back() is True
    assert vista.libre is False
    assert vista.show_phase_list is True


def test_terminar_deja_la_pantalla_limpia(vista):
    extras.anadir(vista.store, "Pec Deck")
    vista.empezar_libre()
    vista._reset()
    assert vista.libre is False


def test_libre_y_abdomen_no_se_pisan(vista):
    """Empezar uno tiene que apagar el otro, o `_current_day` decidiría por
    orden de los `if` en vez de por lo que se pidió."""
    import abdomen

    abdomen.configurar(vista.store, activo=True)
    vista.empezar_abdomen()
    assert (vista.solo_abdomen, vista.libre) == (True, False)
    vista.empezar_libre()
    assert (vista.solo_abdomen, vista.libre) == (False, True)


def test_cambiar_de_modo_no_arrastra_lo_tecleado(vista):
    """Pasó en el emulador: entrar en «Libre» desde una sesión de pesas dejaba
    60 kg × 10 prellenados en el primer abdominal.

    `_sets_by_ex` guarda lo escrito **por posición**, así que la posición 0 de
    un día es la posición 0 del siguiente. A un toque de Guardar y del
    historial.
    """
    vista._sets_by_ex = {0: [{"weight": "60", "reps": "10", "rir": "3", "type": "normal"}]}
    vista._logged_ex = {0}

    vista.empezar_libre()

    assert vista._sets_by_ex == {}
    assert vista._logged_ex == set()


def test_cambiar_de_modo_guarda_antes_lo_que_habia(vista, monkeypatch):
    """Limpiar es correcto; perder lo escrito, no. El borrador se persiste
    primero, igual que al salir con Atrás."""
    guardados = []
    monkeypatch.setattr(vista, "_persist_draft", lambda *a, **k: guardados.append(1))
    vista.empezar_libre()
    assert guardados, "cambió de modo sin guardar el borrador de la sesión que deja"


def test_un_libre_sin_nada_elegido_pide_abrir_el_buscador(vista):
    """Si no, la pantalla sale con el abdomen del día —o con nada— y sin decir
    de dónde ha salido."""
    assert extras.de_hoy(vista.store) == ()
    vista.empezar_libre()
    assert vista._abrir_buscador_al_pintar is True


def test_un_libre_con_ejercicios_no_abre_nada(vista):
    extras.anadir(vista.store, "Pec Deck")
    vista.empezar_libre()
    assert vista._abrir_buscador_al_pintar is False
