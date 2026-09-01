"""nombres_es.py — español en pantalla, inglés en la base.

Alex: «todo lo que tiene la apk tiene que estar en español… Elliptical». Y
tiene razón. Lo que no puede pasar es que esa traducción llegue al disco:
`entrenos.ejercicio` guarda el nombre inglés, que es la clave con la que se
agrupa el historial (trampa 2). Traducir el dato partiría meses de series en
dos idiomas sin que nada fallara.

    lo que se guarda es inglés · lo que se ve es español · nadie traduce al revés

Ese «nadie traduce al revés» es lo que más se vigila aquí.
"""

from __future__ import annotations

import pytest

import catalogo
import nombres_es
from data import EXERCISE_CATALOG, MUSCLE_GROUPS, ROUTINES
from exercises import exercise_key

# ── lo que Alex pidió, literal ───────────────────────────────────────────


def test_elliptical_es_eliptica():
    """El ejemplo que dio, y el que más claro deja el problema."""
    assert nombres_es.ejercicio("Elliptical") == "Elíptica"


def test_los_de_sus_rutinas_estan_todos_traducidos():
    """Los ~100 que ve todos los días. Ni uno puede quedarse en inglés."""
    claves = {
        exercise_key(e)
        for r in ROUTINES
        for dias in r.days_by_phase.values()
        for d in dias
        for e in d.exercises
    }
    sin = sorted(c for c in claves if nombres_es.ejercicio(c) == c)
    assert sin == [], f"sin traducir en las rutinas: {sin}"


def test_el_catalogo_de_casa_esta_traducido():
    de_casa = {n for grupo in EXERCISE_CATALOG.values() for n in grupo}
    sin = sorted(n for n in de_casa if nombres_es.ejercicio(n) == n)
    assert sin == [], f"sin traducir en EXERCISE_CATALOG: {sin}"


def test_los_grupos_musculares_estan_en_espanol():
    for g in MUSCLE_GROUPS:
        assert nombres_es.grupo(g) != g or g == "Cardio", f"{g} sin traducir"
    assert nombres_es.grupo("Chest") == "Pecho"
    assert nombres_es.grupo("Abs") == "Abdomen"


@pytest.mark.parametrize(
    "ingles, esperado",
    [
        ("Chest - Biceps", "Pecho - Bíceps"),
        ("Back - Triceps", "Espalda - Tríceps"),
        ("Shoulder - Leg", "Hombro - Pierna"),
        ("Upper Power", "Torso fuerza"),
        ("Workout A", "Sesión A"),
        ("Abs", "Abdomen"),
        ("Free", "Libre"),
    ],
)
def test_los_nombres_de_dia(ingles, esperado):
    assert nombres_es.dia(ingles) == esperado


# ── LA invariante: nadie traduce al revés ────────────────────────────────


def test_traducir_nunca_cambia_la_clave():
    """El nombre traducido no puede volver a la base por ningún camino.

    Se comprueba al derecho: pasar un nombre ya traducido por `exercise_key`
    daría una clave que no existe en ninguna rutina, y ahí es donde se partiría
    el historial.
    """
    claves = {
        exercise_key(e)
        for r in ROUTINES
        for dias in r.days_by_phase.values()
        for d in dias
        for e in d.exercises
    }
    for clave in claves:
        traducido = nombres_es.ejercicio(clave)
        if traducido == clave:
            continue
        assert traducido not in claves, (
            f"«{traducido}» es a la vez traducción y clave: guardarlo por error no se notaría"
        )


def test_ninguna_traduccion_colisiona_con_otra():
    """Dos ejercicios distintos con el mismo nombre en pantalla serían dos
    filas idénticas en el buscador y una elección a ciegas."""
    from collections import Counter

    vistos = Counter(nombres_es.ejercicio(e.nombre) for e in catalogo.todos())
    repes = [n for n, c in vistos.items() if c > 1]
    assert repes == [], f"mismo nombre en pantalla para ejercicios distintos: {repes[:5]}"


def test_lo_que_no_sabe_traducir_se_queda_en_ingles():
    """Media traducción —«Press Ab Crunch»— no es ni una cosa ni otra: no se
    puede buscar en ninguno de los dos idiomas y parece un fallo."""
    assert nombres_es.ejercicio("Atlas Stone Trainer") == "Atlas Stone Trainer"
    assert nombres_es.ejercicio("") == ""


def test_las_combinaciones_se_traducen_por_partes():
    assert nombres_es.ejercicio("Bi-set: Barbell Curl + DB Curl") == (
        "Biserie: Curl con barra + Curl con mancuernas"
    )
    assert nombres_es.ejercicio("SS: Squat + Lying Leg Curl") == (
        "Superserie: Sentadilla + Femoral tumbado"
    )


# ── la búsqueda tiene que entender los dos idiomas ───────────────────────


@pytest.mark.parametrize(
    "consulta, esperado",
    [
        ("sentadilla", "Squat"),
        ("squat", "Squat"),
        ("elíptica", "Elliptical"),
        ("eliptica", "Elliptical"),
        ("elliptical", "Elliptical"),
        ("dominadas", "Pull-ups"),
        ("femoral", "Lying Leg Curl"),
    ],
)
def test_se_busca_en_espanol_y_en_ingles(consulta, esperado):
    """Enseñar «Sentadilla» y no encontrarla al escribirla es el peor de los
    dos mundos: el nombre inglés sigue siendo el de la base y el que aparece
    en cualquier cosa que Alex haya leído antes."""
    encontrados = [e.nombre for e in catalogo.buscar(consulta, limite=99)]
    assert esperado in encontrados, f"«{consulta}» no encuentra {esperado}"


def test_la_traduccion_no_rompe_el_orden_de_la_busqueda():
    """Lo que empieza por lo buscado sigue saliendo primero."""
    r = catalogo.buscar("squat", limite=10)
    assert r and r[0].nombre.lower().startswith("squat")


# ── el widget, que se mira junto a la app ────────────────────────────────


def test_el_widget_habla_el_mismo_idioma_que_inicio(tmp_path):
    """Hasta 0.19 el widget dejaba el nombre en inglés a propósito, y el
    comentario explicaba por qué. Ese argumento se dio la vuelta cuando Inicio
    empezó a traducirlo: uno diciendo «Chest-Biceps» y la otra «Pecho -
    Bíceps» es justo la doble lengua que se quería evitar."""
    import widget
    from storage import Storage

    store = Storage(f"sqlite:///{tmp_path / 'w.db'}")
    linea = widget._linea_entreno(store, __import__("datetime").date(2026, 9, 1))
    assert "Chest" not in linea and "Biceps" not in linea


def test_el_widget_sigue_guardando_lo_de_siempre(tmp_path):
    """La traducción es de pantalla: el JSON del puente lleva texto ya
    formateado, y eso no cambia — lo que cambia es en qué idioma."""
    import widget
    from storage import Storage

    store = Storage(f"sqlite:///{tmp_path / 'w2.db'}")
    datos = widget.payload(store)
    assert set(datos) == {"entreno", "peso", "kcal", "proteina"}


def test_los_chips_de_grupo_estan_en_espanol_en_los_dos_sitios(tmp_path):
    """Se me escapó uno: traduje los de Browse y dejé los del buscador de la
    sesión en inglés, en la misma pantalla donde todo lo demás ya estaba
    traducido. Dos listas de lo mismo, dos idiomas."""
    import os
    from unittest.mock import MagicMock

    import flet as ft

    from storage import Storage
    from views.browse import BrowseView
    from views.workout import WorkoutView

    store = Storage(os.environ["TEST_DATABASE_URL"])
    page = MagicMock()
    page.width = 400
    page.data = {
        "refresh_current": lambda: None,
        "store": store,
        "navigate_to": lambda *a, **k: None,
    }

    def _textos_de(control):
        out, seen = [], set()

        def bajar(c):
            if c is None or id(c) in seen:
                return
            seen.add(id(c))
            if isinstance(c, ft.Text) and c.value:
                out.append(str(c.value))
            for k in getattr(c, "controls", None) or []:
                bajar(k)
            hijo = getattr(c, "content", None)
            if isinstance(hijo, ft.Control):
                bajar(hijo)

        bajar(control)
        return out

    # El catálogo
    de_browse = _textos_de(BrowseView(page, store).build())
    assert "Pecho" in de_browse and "Chest" not in de_browse

    # Y el buscador de la sesión
    v = WorkoutView(page, store)
    v.phase_id, v.day_idx = 1, 0
    v._ask_add_exercise()
    del_dialogo = _textos_de(page.open.call_args[0][0])
    assert "Pecho" in del_dialogo, "los chips del buscador siguen en inglés"
    assert "Chest" not in del_dialogo
