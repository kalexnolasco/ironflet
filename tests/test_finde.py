"""finde.py — la compra del sábado y la preparación del domingo.

Lo que se fija aquí no es el contenido de la lista (ese sale del menú y
cambiará cuando el menú cambie) sino las reglas que la hacen usable: que sale
del menú de verdad y no de una copia, que escala a los objetivos vigentes sin
tocar la proteína, que las secciones van en el orden del supermercado y que la
preparación no manda cocinar el domingo algo que estará malo el jueves.
"""

from __future__ import annotations

from datetime import date

import pytest

import finde
import nutrition
from storage import Storage

SABADO = date(2026, 8, 22)
DOMINGO = date(2026, 8, 23)
MIERCOLES = date(2026, 8, 19)


@pytest.fixture
def store(tmp_path):
    return Storage(f"sqlite:///{tmp_path / 'finde.db'}")


# ── la lista sale del menú, no de una copia ──────────────────────────────


def test_la_lista_cubre_el_menu_entero_y_nada_mas(store):
    """Cada alimento del menú aparece una vez. Ni se pierde ni se duplica.

    Los slugs se toman de `nutrition.TEMPLATE_DAY`, no de una lista escrita a
    mano: un test que repita el menú deja de comprobar que la compra lo sigue
    y pasa a comprobar que dos copias coinciden.
    """
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    del_menu = {slug for _c, slug, _g in nutrition.TEMPLATE_DAY}
    de_la_lista = [a.slug for a in compra.articulos]

    assert set(de_la_lista) == del_menu
    assert len(de_la_lista) == len(set(de_la_lista)), (
        "un alimento repetido en dos comidas se listó dos veces"
    )


def test_los_gramos_son_los_del_menu_por_los_dias(store):
    """El pan sale en dos comidas: 40 g + 60 g. Por siete días, 700 g."""
    compra = finde.lista_de_la_compra(store, dias=7, hoy=SABADO)
    pan = next(a for a in compra.articulos if a.slug == "bread_wholemeal")
    assert pan.gramos == pytest.approx(700.0)
    assert pan.cantidad() == "700 g"


def test_los_dias_escalan_la_cantidad(store):
    tres = finde.lista_de_la_compra(store, dias=3, hoy=SABADO)
    seis = finde.lista_de_la_compra(store, dias=6, hoy=SABADO)
    g3 = {a.slug: a.gramos for a in tres.articulos}
    g6 = {a.slug: a.gramos for a in seis.articulos}
    assert all(g6[s] == pytest.approx(g3[s] * 2) for s in g3)


# ── el escalado respeta la proteína ──────────────────────────────────────


def test_recortar_calorias_no_recorta_la_proteina(store):
    """El plan lo dice: se recorta el aceite de la cena, nunca la proteína.

    Con un objetivo muy por debajo del menú, el pollo debe salir intacto y el
    ajuste entero debe recaer sobre el arroz y compañía.
    """
    nutrition.set_targets(store, kcal=2000, protein=115, fat=60, carbs=250, starts_on="2026-08-10")
    normal = finde.lista_de_la_compra(store, hoy=SABADO)

    pollo = next(a for a in normal.articulos if a.slug == "chicken_breast")
    arroz = next(a for a in normal.articulos if a.slug == "rice_white")

    assert pollo.gramos == pytest.approx(150.0 * 7), "el escalado tocó la proteína"
    assert arroz.gramos < 110.0 * 7, "el objetivo bajó y el arroz no se movió"
    assert normal.factor < 1.0
    assert not normal.aviso


def test_un_objetivo_imposible_avisa_en_vez_de_encoger_la_lista_a_la_nada(store):
    """900 kcal no dan para este menú. Se dice, no se hace la regla de tres.

    Sin el suelo, el factor salía 0,05: la lista mandaba comprar 63 g de
    manzana para toda la semana. Aritméticamente correcto y completamente
    inútil — es otro menú, no este recortado, y eso no lo decide un módulo.
    """
    nutrition.set_targets(store, kcal=900, protein=115, fat=30, carbs=80, starts_on="2026-08-10")
    compra = finde.lista_de_la_compra(store, hoy=SABADO)

    assert compra.aviso, "se recortó en silencio por debajo de lo que el plan permite"
    assert "entrenador" in compra.aviso
    assert compra.factor == finde._FACTOR_MINIMO

    pollo = next(a for a in compra.articulos if a.slug == "chicken_breast")
    assert pollo.gramos == pytest.approx(150.0 * 7), "el escalado tocó la proteína"
    manzana = next(a for a in compra.articulos if a.slug == "apple")
    assert manzana.gramos > 500, "la lista quedó en cantidades que no se compran"


def test_un_desvio_pequeno_no_mueve_la_lista(store):
    """El menú trae ~2668 y el objetivo por defecto es 2550: un 4 %.

    Recortar un 4 % de la compra semanal no cambia nada y sí llena la lista de
    cifras raras («1,01 kg de pollo»). Por debajo del umbral, factor 1.
    """
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    assert compra.factor == 1.0
    arroz = next(a for a in compra.articulos if a.slug == "rice_white")
    assert arroz.gramos == pytest.approx(110.0 * 7)


def test_un_objetivo_mas_alto_sube_los_hidratos(store):
    nutrition.set_targets(store, kcal=3400, protein=115, fat=95, carbs=420, starts_on="2026-08-10")
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    arroz = next(a for a in compra.articulos if a.slug == "rice_white")
    assert arroz.gramos > 110.0 * 7
    assert compra.factor > 1.0


def test_los_objetivos_vigentes_son_los_del_dia_de_la_compra(store):
    """Los targets son versionados: la compra usa los que estén en vigor.

    Si el coach cambió el objetivo para el lunes, la compra del sábado va con
    el objetivo de esta semana, no con el de la que viene.
    """
    nutrition.set_targets(store, kcal=2000, protein=115, fat=60, carbs=250, starts_on="2026-08-10")
    nutrition.set_targets(
        store, kcal=3400, protein=115, fat=95, carbs=420, starts_on="2026-08-24"
    )  # lunes

    assert finde.lista_de_la_compra(store, hoy=SABADO).kcal_objetivo == 2000
    assert finde.lista_de_la_compra(store, hoy=date(2026, 8, 25)).kcal_objetivo == 3400


# ── el orden del recorrido ───────────────────────────────────────────────


def test_las_secciones_van_en_el_orden_de_la_tienda(store):
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    secciones = [s for s, _ in compra.por_seccion()]
    orden = list(finde.ORDEN_SECCIONES)
    assert secciones == [s for s in orden if s in secciones]
    assert secciones[0] == "Fruta y verdura"


def test_dentro_de_la_seccion_va_por_nombre(store):
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    for _seccion, articulos in compra.por_seccion():
        nombres = [a.nombre for a in articulos]
        assert nombres == sorted(nombres)


def test_todo_el_menu_tiene_seccion_asignada(store):
    """«Otros» existe como red, pero nada del menú debería caer ahí.

    Un alimento sin sección no rompe nada — se lista al final — y por eso
    conviene que lo diga un test en vez de descubrirlo en la tienda.
    """
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    huerfanos = [a.nombre for a in compra.articulos if a.seccion == "Otros"]
    assert huerfanos == []


# ── cómo se lee una cantidad ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "gramos, esperado",
    [
        (280.0, "280 g"),
        (999.0, "999 g"),
        (1000.0, "1 kg"),
        (1050.0, "1,05 kg"),
        (1400.0, "1,4 kg"),
        (2450.0, "2,45 kg"),
        (104.6, "105 g"),
    ],
)
def test_la_cantidad_se_lee_como_en_una_lista(gramos, esperado):
    art = finde.Articulo(slug="x", nombre="X", gramos=gramos, seccion="Otros")
    assert art.cantidad() == esperado


# ── el domingo ───────────────────────────────────────────────────────────


def test_lo_que_mas_tarda_va_primero(store):
    """El horno trabaja solo. Empezar por lo corto es perder la tarde."""
    plan = finde.plan_de_preparacion(store, hoy=DOMINGO)
    cocinar = [t for t in plan.tareas if not t.titulo.startswith("Repartir")]
    minutos = [t.minutos for t in cocinar]
    assert minutos == sorted(minutos, reverse=True)


def test_repartir_va_al_final(store):
    plan = finde.plan_de_preparacion(store, hoy=DOMINGO)
    assert plan.tareas[-1].titulo.startswith("Repartir")


def test_el_tiempo_total_es_de_reloj_y_no_la_suma(store):
    """Mientras hierve el arroz entra el pollo: prometer la suma es mentir."""
    plan = finde.plan_de_preparacion(store, hoy=DOMINGO)
    suma = sum(t.minutos for t in plan.tareas)
    mayor = max(t.minutos for t in plan.tareas)
    assert mayor <= plan.minutos_totales < suma


def test_solo_se_cocina_lo_que_se_cocina(store):
    """Ni la manzana ni el skyr ni el aceite generan una tarea."""
    plan = finde.plan_de_preparacion(store, hoy=DOMINGO)
    detalles = " ".join(t.detalle for t in plan.tareas)
    for crudo in ("Manzana", "Plátano", "Skyr", "Aceite de oliva", "Nueces"):
        assert crudo not in detalles


def test_el_salmon_avisa_de_que_no_aguanta_la_semana(store):
    """El fallo que tenía la primera versión: salmón del domingo para el sábado.

    Dos días en nevera y siete de menú. La tarea tiene que decirlo, porque el
    plan sin esa línea es un plan que da comida en mal estado.
    """
    plan = finde.plan_de_preparacion(store, dias=7, hoy=DOMINGO)
    salmon = next(t for t in plan.tareas if "Salmón" in t.titulo)
    assert salmon.conservacion
    assert "congela" in salmon.conservacion.lower()


def test_lo_que_aguanta_no_lleva_nota(store):
    """El pavo en lonchas dura la semana: una nota ahí es ruido."""
    plan = finde.plan_de_preparacion(store, dias=7, hoy=DOMINGO)
    pavo = next(t for t in plan.tareas if "Pavo" in t.titulo)
    assert pavo.conservacion == ""


def test_la_conservacion_depende_de_los_dias_que_se_preparan(store):
    """No del alimento: el mismo salmón avisa a tres días y calla a dos.

    Dos días es lo que aguanta, así que cocinando para dos no sobra nada. A
    tres ya sobra uno, y ahí la nota es información y no ruido.
    """
    dos = finde.plan_de_preparacion(store, dias=2, hoy=DOMINGO)
    assert [t.titulo for t in dos.tareas if t.conservacion] == []

    tres = finde.plan_de_preparacion(store, dias=3, hoy=DOMINGO)
    con_nota = [t.titulo for t in tres.tareas if t.conservacion]
    assert any("Salmón" in t for t in con_nota)
    assert not any("Arroz" in t for t in con_nota), "el arroz aguanta cuatro días"


def test_las_cantidades_del_domingo_son_las_de_la_compra(store):
    """Un segundo cálculo de cuánto arroz cocer es un segundo sitio donde
    equivocarse. El plan lee la lista, no recalcula."""
    compra = finde.lista_de_la_compra(store, hoy=DOMINGO)
    plan = finde.plan_de_preparacion(store, hoy=DOMINGO)
    arroz_compra = next(a for a in compra.articulos if a.slug == "rice_white")
    arroz_plan = next(t for t in plan.tareas if "Arroz" in t.titulo)
    assert arroz_compra.cantidad() in arroz_plan.detalle


def test_el_consejo_nombra_la_primera_tarea(store):
    plan = finde.plan_de_preparacion(store, hoy=DOMINGO)
    primera = plan.tareas[0].titulo.split(" — ")[0]
    assert primera in plan.consejo


# ── los días ─────────────────────────────────────────────────────────────


def test_sabado_y_domingo():
    assert finde.es_dia_de_compra(SABADO) is True
    assert finde.es_dia_de_compra(DOMINGO) is False
    assert finde.es_dia_de_prep(DOMINGO) is True
    assert finde.es_dia_de_prep(MIERCOLES) is False
    assert finde.es_dia_de_compra(MIERCOLES) is False


# ── que no dependa de una base de datos rica ─────────────────────────────


def test_funciona_con_la_base_vacia(store):
    """Un móvil recién instalado también hace la compra."""
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    plan = finde.plan_de_preparacion(store, hoy=DOMINGO)
    assert compra.articulos and plan.tareas


# ── lo que solo se ve en la pantalla ─────────────────────────────────────


def test_los_liquidos_van_en_litros(store):
    """«Leche semidesnatada 1,81 kg» era correcto y no lo dice nadie.

    La tabla nutricional está en gramos porque las etiquetas europeas lo están
    — la plantilla escribe literalmente `258.0, # 250 ml`. En una lista de la
    compra hay que deshacer esa conversión.
    """
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    leche = next(a for a in compra.articulos if a.slug == "milk_semi")
    aceite = next(a for a in compra.articulos if a.slug == "olive_oil")

    assert leche.cantidad() == "1,75 l"
    assert aceite.cantidad() == "175 ml"
    assert "kg" not in leche.cantidad() and "g" not in aceite.cantidad().replace("ml", "")


def test_lo_solido_sigue_en_kilos(store):
    compra = finde.lista_de_la_compra(store, hoy=SABADO)
    pollo = next(a for a in compra.articulos if a.slug == "chicken_breast")
    assert pollo.cantidad() == "1,05 kg"


def test_la_nota_que_le_toca_a_casi_todo_se_dice_una_vez(store):
    """En pantalla, la misma frase en cuatro de cinco tarjetas ocupaba media
    pantalla y se dejaba de leer — incluida la única distinta, la del salmón,
    que es justo la que cambia lo que haces."""
    plan = finde.plan_de_preparacion(store, dias=7, hoy=DOMINGO)

    assert plan.conservacion_comun, "no se sacó arriba la nota repetida"
    assert "4 días" in plan.conservacion_comun

    con_nota = [t for t in plan.tareas if t.conservacion]
    assert len(con_nota) == 1, f"quedaron {len(con_nota)} notas en las tarjetas"
    assert "Salmón" in con_nota[0].titulo
    assert con_nota[0].conservacion != plan.conservacion_comun


def test_lo_que_queda_en_la_tarjeta_es_lo_que_se_sale_de_la_norma(store):
    """La regla, dicha al revés: ninguna tarjeta repite la nota común."""
    plan = finde.plan_de_preparacion(store, dias=7, hoy=DOMINGO)
    assert all(t.conservacion != plan.conservacion_comun for t in plan.tareas)


def test_con_pocas_repeticiones_no_se_saca_nada_arriba(store):
    """Umbral en la mitad: con dos de cinco, la repetición todavía no molesta
    y sacarla arriba obligaría a mirar dos sitios por cada tarea."""
    plan = finde.plan_de_preparacion(store, dias=3, hoy=DOMINGO)
    assert plan.conservacion_comun == ""
    assert any(t.conservacion for t in plan.tareas), "y la del salmón sigue en su tarjeta"
