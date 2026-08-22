"""Las dos pantallas del finde, dentro de Comida.

`tests/test_finde.py` comprueba las reglas (cuánto, en qué orden, qué aguanta);
esto comprueba que llegan a la pantalla y que la pantalla no se traga el diario
cuando algo falla. La vista se importa contra el `nutrition` de verdad, porque
`finde.py` lee el menú y los objetivos reales — un `nutrition` falso probaría el
falso.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import date
from unittest.mock import MagicMock

import flet as ft
import pytest

import finde

SABADO = date(2026, 8, 22)
DOMINGO = date(2026, 8, 23)
MIERCOLES = date(2026, 8, 19)


@pytest.fixture
def view():
    """La vista real contra la base de datos de este proceso."""
    from storage import Storage

    store = Storage(os.environ["TEST_DATABASE_URL"])
    # Importar limpio: los tests de `test_nutrition_view.py` dejan un stub de
    # `nutrition` puesto, y aquí hace falta el módulo de verdad.
    sys.modules.pop("views.nutrition_view", None)
    module = importlib.import_module("views.nutrition_view")

    page = MagicMock()
    page.data = {"refresh_current": lambda: None, "store": store}
    v = module.NutritionView(page, store)
    try:
        yield v
    finally:
        sys.modules.pop("views.nutrition_view", None)


def walk(control):
    """Todos los controles, **en el orden en que se leen en pantalla**.

    El `walk` de `test_nutrition_view.py` usa un stack y por tanto los devuelve
    del revés; ahí da igual porque nadie mira el orden. Aquí media prueba es
    sobre el orden — si la entrada al finde va arriba o abajo, si los pasos van
    numerados de uno en adelante — así que este recorre en profundidad y con
    los hijos en su orden.
    """
    out, seen = [], set()

    def bajar(c):
        if c is None or id(c) in seen:
            return
        seen.add(id(c))
        out.append(c)
        kids = getattr(c, "controls", None)
        if isinstance(kids, list):
            for k in kids:
                bajar(k)
        kid = getattr(c, "content", None)
        if isinstance(kid, ft.Control):
            bajar(kid)

    bajar(control)
    return out


def textos(control) -> list[str]:
    return [str(c.value) for c in walk(control) if isinstance(c, ft.Text) and c.value]


def junto(control) -> str:
    return " | ".join(textos(control))


def pinchable_con(root, fragmento: str):
    """El control pinchable más ajustado que contenga ese texto."""
    hits = [
        c
        for c in walk(root)
        if getattr(c, "on_click", None) and any(fragmento in t for t in textos(c))
    ]
    assert hits, f"nada pinchable con {fragmento!r} en: {junto(root)}"
    return min(hits, key=lambda c: len(textos(c)))


# ── la entrada desde el diario ───────────────────────────────────────────


def test_el_sabado_la_entrada_va_arriba_del_todo(view, monkeypatch):
    """El sábado se abre Comida para ver la lista, no para apuntar el desayuno."""
    monkeypatch.setattr(finde, "es_dia_de_compra", lambda *_a, **_k: True)
    monkeypatch.setattr(finde, "es_dia_de_prep", lambda *_a, **_k: False)

    todos = textos(view.build())
    entrada = next(i for i, t in enumerate(todos) if "compra" in t.lower())
    comidas = next(i for i, t in enumerate(todos) if t == "Comidas")
    assert entrada < comidas, "la entrada al finde quedó por debajo del diario"


def test_entre_semana_la_entrada_baja_al_final(view, monkeypatch):
    """Un miércoles el diario manda: la lista sigue ahí, pero no estorba."""
    monkeypatch.setattr(finde, "es_dia_de_compra", lambda *_a, **_k: False)
    monkeypatch.setattr(finde, "es_dia_de_prep", lambda *_a, **_k: False)

    todos = textos(view.build())
    entrada = next(i for i, t in enumerate(todos) if t == "El finde")
    comidas = next(i for i, t in enumerate(todos) if t == "Comidas")
    assert entrada > comidas


def test_el_domingo_la_entrada_habla_de_cocinar(view, monkeypatch):
    monkeypatch.setattr(finde, "es_dia_de_compra", lambda *_a, **_k: False)
    monkeypatch.setattr(finde, "es_dia_de_prep", lambda *_a, **_k: True)
    assert "Hoy toca cocinar" in junto(view.build())


def test_si_el_finde_revienta_el_diario_sigue_en_pie(view, monkeypatch):
    """Una tarjeta rota no puede costar la pantalla que sí funciona."""
    monkeypatch.setattr(
        finde,
        "lista_de_la_compra",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    pantalla = junto(view.build())
    assert "Comidas" in pantalla
    assert "finde" not in pantalla.lower()


# ── el sábado ────────────────────────────────────────────────────────────


def test_la_compra_lista_las_secciones_y_las_cantidades(view):
    view.finde = "compra"
    pantalla = junto(view.build())
    assert "Fruta y verdura" in pantalla.upper() or "FRUTA Y VERDURA" in pantalla
    assert "Pechuga de pollo (cruda)" in pantalla
    assert "1,05 kg" in pantalla


def test_tachar_una_cosa_la_marca_y_cuenta(view):
    view.finde = "compra"
    view.build()
    assert view._cogido == set()

    view._toggle_cogido("rice_white")
    pantalla = junto(view.build())
    assert "1 de 16" in pantalla

    view._toggle_cogido("rice_white")
    assert "1 de 16" not in junto(view.build()), "destachar no deshizo la marca"


def test_lo_tachado_se_pinta_distinto(view):
    from theme import C

    view.finde = "compra"
    view._toggle_cogido("rice_white")
    marcados = [
        c for c in walk(view.build()) if isinstance(c, ft.Icon) and c.name == ft.Icons.CHECK_CIRCLE
    ]
    assert len(marcados) == 1
    assert marcados[0].color == C.accent


def test_la_lista_no_recuerda_lo_tachado_la_semana_que_viene(view):
    """Abrir la pantalla empieza el carro vacío. Una lista a medias de hace
    siete días es peor que ninguna."""
    view._abrir_finde("compra")
    view._toggle_cogido("apple")
    view._abrir_finde("compra")
    assert view._cogido == set()


def test_el_aviso_de_un_objetivo_imposible_llega_a_la_pantalla(view, monkeypatch):
    falsa = finde.Compra(
        articulos=(finde.Articulo("apple", "Manzana", 700.0, "Fruta y verdura"),),
        dias=7,
        kcal_objetivo=900,
        factor=0.5,
        aviso="Con 900 kcal no sale este menú.",
    )
    monkeypatch.setattr(finde, "lista_de_la_compra", lambda *_a, **_k: falsa)
    view.finde = "compra"
    assert "Con 900 kcal no sale este menú." in junto(view.build())


# ── el domingo ───────────────────────────────────────────────────────────


def test_la_preparacion_numera_los_pasos_y_da_el_tiempo(view):
    view.finde = "prep"
    pantalla = junto(view.build())
    assert "Pollo al horno — 200 °C, dar la vuelta a mitad" in pantalla
    assert "min" in pantalla
    assert "de reloj, no de sumar los pasos" in pantalla


def test_el_aviso_de_congelar_se_ve(view):
    """El salmón aguanta dos días y el menú son siete: hay que decirlo."""
    view.finde = "prep"
    assert "congela" in junto(view.build()).lower()


def test_los_pasos_van_numerados_en_orden(view):
    view.finde = "prep"
    numeros = [t for t in textos(view.build()) if t.isdigit()]
    assert numeros == [str(i) for i in range(1, len(numeros) + 1)]


# ── navegación ───────────────────────────────────────────────────────────


def test_las_pestanas_cambian_de_pantalla(view):
    view.finde = "compra"
    pinchable_con(view.build(), "Domingo · Cocina").on_click(None)
    assert view.finde == "prep"


def test_atras_vuelve_al_diario(view):
    view.finde = "prep"
    assert view.handle_back() is True
    assert view.finde == ""
    assert "Comidas" in junto(view.build())


def test_atras_desde_el_diario_no_lo_consume_el_finde(view):
    """Con la pantalla cerrada, Atrás debe seguir llegando a `main`."""
    assert view.finde == ""
    assert view.handle_back() is False


def test_la_entrada_abre_la_pantalla(view, monkeypatch):
    monkeypatch.setattr(finde, "es_dia_de_compra", lambda *_a, **_k: True)
    monkeypatch.setattr(finde, "es_dia_de_prep", lambda *_a, **_k: False)
    pinchable_con(view.build(), "Hoy toca la compra").on_click(None)
    assert view.finde == "compra"


def test_si_el_calculo_falla_en_la_pantalla_se_dice(view, monkeypatch):
    monkeypatch.setattr(
        finde,
        "plan_de_preparacion",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    view.finde = "prep"
    pantalla = view.build()
    assert "No se pudo calcular" in junto(pantalla)
    # Y las pestañas siguen ahí: quedarse atrapado en la pantalla que falló
    # sería el segundo fallo.
    assert pinchable_con(pantalla, "Sábado · Compra") is not None


def test_la_pantalla_dice_la_nota_comun_una_sola_vez(view):
    """Contar apariciones, no buscar la cadena: el fallo era la repetición."""
    view.finde = "prep"
    pantalla = junto(view.build())
    assert pantalla.count("Aguanta 4 días") == 1
    assert "salvo donde diga otra cosa" in pantalla


def test_la_del_salmon_sigue_en_su_tarjeta(view):
    """La excepción es lo que cambia lo que haces, y va donde se está mirando."""
    view.finde = "prep"
    assert "Solo aguanta 2 días" in junto(view.build())


def test_la_leche_se_pide_en_litros(view):
    view.finde = "compra"
    pantalla = junto(view.build())
    assert "1,75 l" in pantalla
    assert "1,81 kg" not in pantalla, "nadie compra leche en kilos"
