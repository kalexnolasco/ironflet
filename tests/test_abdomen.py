"""abdomen.py — la rutina de abdomen que se hace todos los días.

Existe porque el plan de Alex ya lo pedía y la app no lo daba: su calendario
dice «+ Abs» cinco veces por semana y los tres días de la fase 1 no llevan un
solo ejercicio de abdomen en su lista.

Lo que más se vigila aquí es la **rotación**, porque su primera versión estaba
mal de una forma que solo se ve mirando dos días seguidos: el día D daba
[A, B, C] y el D+1 daba [B, C, D], o sea la plancha tres días seguidos. Los
tests pasaban igual — cada día tenía tres ejercicios de tres familias.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import abdomen
from storage import Storage

HOY = date(2026, 9, 1)


@pytest.fixture
def store(tmp_path):
    return Storage(f"sqlite:///{tmp_path / 'abdomen.db'}")


# ── el pool ──────────────────────────────────────────────────────────────


def test_todos_los_nombres_del_pool_existen(store):
    """EL test. Un nombre inventado aquí abre un historial paralelo del mismo
    movimiento sin que nada falle (trampa 2), y esto ya cazó uno: «Hanging Leg
    Raise», que no existe — el del catálogo es «Knee/Hip Raise On Parallel
    Bars».
    """
    import extras

    conocidos = {n.lower() for n in extras.nombres_conocidos()}
    malos = [n for n in abdomen.nombres_del_pool() if n.lower() not in conocidos]
    assert malos == [], f"nombres que la app no sabe guardar: {malos}"


def test_todos_son_de_abdomen():
    """Un pectoral colado en el pool se haría todos los días sin que nadie
    revisara por qué el abdomen no avanza."""
    import catalogo

    for nombre in abdomen.nombres_del_pool():
        e = catalogo.por_nombre(nombre)
        assert e is not None, f"{nombre} no está en el catálogo"
        assert e.grupo == "Abs", f"{nombre} es de {e.grupo}, no de abdomen"


def test_ningun_ejercicio_en_dos_familias():
    vistos: dict[str, str] = {}
    for familia, pool in abdomen.FAMILIAS.items():
        for n in pool:
            assert n not in vistos, f"{n} está en {vistos[n]} y en {familia}"
            vistos[n] = familia


def test_las_familias_tienen_el_mismo_tamano():
    """No es estético: la rotación reparte por igual y una familia más corta
    haría que sus ejercicios salieran más veces que los de las otras."""
    tamanos = {len(p) for p in abdomen.FAMILIAS.values()}
    assert len(tamanos) == 1, f"familias de distinto tamaño: {tamanos}"


# ── la rotación ──────────────────────────────────────────────────────────


def test_el_mismo_dia_da_siempre_lo_mismo(store):
    """Un ejercicio que cambia entre dos miradas es uno que nadie termina."""
    a = abdomen.de_hoy(store, HOY, cuantos=3)
    b = abdomen.de_hoy(store, HOY, cuantos=3)
    assert a == b


def test_cada_dia_trae_una_de_cada_familia(store):
    for i in range(30):
        dia = HOY + timedelta(days=i)
        ejs = abdomen.de_hoy(store, dia, cuantos=3)
        familias = {abdomen.familia_de(e) for e in ejs}
        assert len(familias) == 3, f"{dia}: {ejs} cubre {familias}"


def test_ningun_dia_repite_nada_del_anterior(store):
    """El fallo de la primera versión, que los tests de entonces no veían.

    Ataba la rueda de las familias a la del ejercicio, así que el día D daba
    [A, B, C] y el D+1 [B, C, D]: la plancha tres días seguidos, cada día con
    sus tres familias en su sitio.
    """
    previo: tuple[str, ...] = ()
    for i in range(60):
        dia = HOY + timedelta(days=i)
        ejs = abdomen.de_hoy(store, dia, cuantos=3)
        repes = set(ejs) & set(previo)
        assert not repes, f"{dia} repite {repes} del día anterior"
        previo = ejs


def test_con_cinco_al_dia_la_promesa_es_menor_y_esta_dicha(store):
    """Cinco de quince: dos días seguidos cubren diez del pool y el solape es
    aritmética, no un fallo del reparto. Lo que sigue garantizado es que dentro
    de un mismo día no se repite nada — y que el docstring lo dice.
    """
    assert "Ningún día repite un ejercicio del día anterior" in abdomen.de_hoy.__doc__
    assert "cinco al día ya no se puede prometer" in abdomen.de_hoy.__doc__

    for i in range(10):
        ejs = abdomen.de_hoy(store, HOY + timedelta(days=i), cuantos=5)
        assert len(set(ejs)) == 5


def test_no_se_repite_ejercicio_dentro_del_mismo_dia(store):
    for n in range(1, abdomen.MAX_POR_DIA + 1):
        for i in range(20):
            ejs = abdomen.de_hoy(store, HOY + timedelta(days=i), cuantos=n)
            assert len(set(ejs)) == len(ejs), f"{ejs} repite dentro del día"


def test_en_un_ciclo_completo_salen_todos(store):
    """Con 3 familias × 5 ejercicios, quince días bastan para verlos todos.
    Si alguno no sale nunca, sobra del pool."""
    vistos = set()
    for i in range(15):
        vistos.update(abdomen.de_hoy(store, HOY + timedelta(days=i), cuantos=3))
    assert vistos == abdomen.nombres_del_pool()


def test_con_menos_de_tres_al_dia_no_se_come_siempre_la_misma_familia(store):
    """Con `cuantos=2` y las familias fijas, los oblicuos no se harían nunca."""
    familias = set()
    for i in range(9):
        for e in abdomen.de_hoy(store, HOY + timedelta(days=i), cuantos=2):
            familias.add(abdomen.familia_de(e))
    assert familias == set(abdomen.FAMILIAS)


def test_el_numero_por_dia_se_respeta_y_se_acota(store):
    assert len(abdomen.de_hoy(store, HOY, cuantos=1)) == 1
    assert len(abdomen.de_hoy(store, HOY, cuantos=5)) == 5
    assert len(abdomen.de_hoy(store, HOY, cuantos=99)) == abdomen.MAX_POR_DIA
    assert len(abdomen.de_hoy(store, HOY, cuantos=0)) == 1


# ── el interruptor ───────────────────────────────────────────────────────


def test_apagado_de_fabrica(store):
    """Encendido por defecto sería meterle tres ejercicios en la sesión a quien
    nunca los pidió."""
    assert abdomen.activo(store) is False
    assert abdomen.por_dia(store) == abdomen.POR_DIA_DEFECTO


def test_encender_y_apagar(store):
    abdomen.configurar(store, activo=True)
    assert abdomen.activo(store) is True
    abdomen.configurar(store, activo=False)
    assert abdomen.activo(store) is False


def test_cambiar_uno_no_pisa_el_otro(store):
    abdomen.configurar(store, activo=True, por_dia=4)
    abdomen.configurar(store, activo=False)
    assert abdomen.por_dia(store) == 4, "apagar se llevó por delante el número"


def test_el_numero_se_acota_al_guardar(store):
    abdomen.configurar(store, por_dia=99)
    assert abdomen.por_dia(store) == abdomen.MAX_POR_DIA
    abdomen.configurar(store, por_dia=0)
    assert abdomen.por_dia(store) == 1


@pytest.mark.parametrize("basura", ["no json", "[]", "null", '{"por_dia": "cuatro"}', ""])
def test_una_pref_corrupta_no_impide_entrenar(store, basura):
    store.set_pref(abdomen.PREF_KEY, basura)
    assert abdomen.activo(store) is False
    assert abdomen.por_dia(store) == abdomen.POR_DIA_DEFECTO


def test_una_base_muerta_tampoco():
    class Rota:
        def get_pref(self, *_a, **_k):
            raise RuntimeError("sin base")

    assert abdomen.activo(Rota()) is False
    assert abdomen.de_hoy(Rota(), HOY)


# ── la capa sobre el día ─────────────────────────────────────────────────


def test_apagado_no_toca_el_dia(store):
    from data import TrainingDay

    dia = TrainingDay(name="Chest - Biceps", exercises=["Smith Bench Press"])
    assert abdomen.dia_con_abdomen(dia, store, HOY).exercises == ["Smith Bench Press"]


def test_encendido_lo_anade_al_final(store):
    from data import TrainingDay

    abdomen.configurar(store, activo=True, por_dia=3)
    dia = TrainingDay(name="Chest - Biceps", exercises=["Smith Bench Press"])
    ampliado = abdomen.dia_con_abdomen(dia, store, HOY)

    assert ampliado.exercises[0] == "Smith Bench Press"
    assert ampliado.exercises[1:] == list(abdomen.de_hoy(store, HOY))


def test_el_dia_de_la_rutina_no_se_muta_nunca(store):
    """`data.ROUTINES` se comparte entre fases: un ejercicio colado ahí estaría
    en el plan de las 24 semanas."""
    from data import TrainingDay

    abdomen.configurar(store, activo=True)
    dia = TrainingDay(name="X", exercises=["Smith Bench Press"])
    original = list(dia.exercises)
    abdomen.dia_con_abdomen(dia, store, HOY).exercises.append("intruso")
    assert dia.exercises == original


def test_copia_incluso_apagado(store):
    from data import TrainingDay

    dia = TrainingDay(name="X", exercises=["Smith Bench Press"])
    assert abdomen.dia_con_abdomen(dia, store, HOY) is not dia


def test_no_duplica_lo_que_el_dia_ya_tiene(store):
    """El día 2 de la rutina ya prescribe `Cable Crunch` en algunas fases."""
    from data import TrainingDay

    abdomen.configurar(store, activo=True, por_dia=3)
    toca = abdomen.de_hoy(store, HOY)
    dia = TrainingDay(name="X", exercises=["Smith Bench Press", toca[0]])
    ampliado = abdomen.dia_con_abdomen(dia, store, HOY)
    assert ampliado.exercises.count(toca[0]) == 1


def test_el_dia_suelto_es_solo_abdomen(store):
    abdomen.configurar(store, activo=True, por_dia=3)
    dia = abdomen.dia_suelto(store, HOY)
    assert dia.exercises == list(abdomen.de_hoy(store, HOY))


def test_el_dia_suelto_se_llama_abs_y_no_abdomen(store):
    """El nombre va literal a `entrenos.grupo` (trampa 22) y «Abs» es el
    vocabulario que la app ya usa. Un segundo nombre para lo mismo parte la
    agrupación de Historial en dos."""
    assert abdomen.dia_suelto(store, HOY).name == "Abs"


def test_es_de_abdomen_distingue_las_posiciones(store):
    from data import TrainingDay

    abdomen.configurar(store, activo=True, por_dia=2)
    dia = TrainingDay(name="X", exercises=["A", "B"])
    assert abdomen.es_de_abdomen(dia, 1, store, HOY) is False
    assert abdomen.es_de_abdomen(dia, 2, store, HOY) is True
    assert abdomen.es_de_abdomen(dia, 3, store, HOY) is True
    assert abdomen.es_de_abdomen(dia, 4, store, HOY) is False


def test_apagado_nada_es_de_abdomen(store):
    from data import TrainingDay

    dia = TrainingDay(name="X", exercises=["A"])
    assert abdomen.es_de_abdomen(dia, 1, store, HOY) is False


# ── el borrador ──────────────────────────────────────────────────────────


def test_el_borrador_conserva_las_series_del_abdomen(store):
    """Mismo agujero que con los extras (trampa 32): el abdomen no está en la
    rutina, así que `fit_to_routine` tiraría sus filas al restaurar."""
    from workout_draft import DraftStore

    abdomen.configurar(store, activo=True, por_dia=3)
    from exercises import exercise_key

    claves = DraftStore(store)._extra_keys()
    for n in abdomen.de_hoy(store):
        assert exercise_key(n) in claves


def test_apagado_el_borrador_no_los_menciona(store):
    from workout_draft import DraftStore

    assert DraftStore(store)._extra_keys() == ()


# ── las pantallas ────────────────────────────────────────────────────────


def _walk(control):
    import flet as ft

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
    import flet as ft

    return " | ".join(str(c.value) for c in _walk(control) if isinstance(c, ft.Text) and c.value)


@pytest.fixture
def ajustes(store):
    from unittest.mock import MagicMock

    from views.profile import ProfileView

    page = MagicMock()
    page.width = 400
    page.data = {"refresh_current": lambda: None, "navigate_to": lambda *a, **k: None}
    return ProfileView(page, store)


def test_ajustes_apagado_no_lista_ejercicios(ajustes, store):
    """Con el interruptor apagado, enseñar los de hoy sería prometer algo que
    no va a pasar."""
    texto = _textos(ajustes._abdomen_section())
    assert "Abdomen todos los días" in texto
    assert not any(n in texto for n in abdomen.nombres_del_pool())


def test_ajustes_encendido_ensena_los_de_hoy(ajustes, store):
    """«Añadir abdomen a cada día» es vago hasta que se ven los tres nombres."""
    abdomen.configurar(store, activo=True, por_dia=3)
    texto = _textos(ajustes._abdomen_section())
    assert "HOY TE TOCA" in texto
    for n in abdomen.de_hoy(store):
        assert n in texto


def test_el_interruptor_enciende_de_verdad(ajustes, store):
    import flet as ft

    interruptor = next(c for c in _walk(ajustes._abdomen_section()) if isinstance(c, ft.Switch))
    interruptor.on_change(type("E", (), {"control": type("C", (), {"value": True})()})())
    assert abdomen.activo(store) is True


def test_una_base_muerta_no_tumba_ajustes(ajustes, monkeypatch):
    monkeypatch.setattr(
        abdomen, "activo", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert ajustes._abdomen_section() is not None


@pytest.fixture
def inicio(store):
    from unittest.mock import MagicMock

    from views.home import HomeView

    page = MagicMock()
    page.width = 400
    page.data = {
        "refresh_current": lambda: None,
        "navigate_to": lambda *a, **k: None,
        "store": store,
    }
    return HomeView(page, store)


def test_inicio_no_ensena_nada_si_esta_apagado(inicio, store):
    assert inicio._abdomen_card() is None


def test_inicio_ensena_lo_que_toca(inicio, store):
    """La tarjeta que hace verdad el «cada día»: los días de descanso es el
    único sitio donde hacer abdomen."""
    abdomen.configurar(store, activo=True, por_dia=3)
    texto = _textos(inicio._abdomen_card())
    assert "Abdomen de hoy" in texto
    assert abdomen.de_hoy(store)[0] in texto


def test_inicio_deja_de_invitar_cuando_ya_esta_hecho(inicio, store):
    """Una tarjeta que sigue pidiendo algo que acabas de hacer enseña a
    ignorarla."""
    from datetime import date as _date

    from storage import WorkoutEntry

    abdomen.configurar(store, activo=True, por_dia=3)
    for n in abdomen.de_hoy(store):
        store.save_workout(
            WorkoutEntry(
                date=_date.today().isoformat(),
                exercise=n,
                muscle_group="Abs",
                phase=1,
                sets=[{"weight": 0, "reps": 15}],
            )
        )
    texto = _textos(inicio._abdomen_card())
    assert "Abdomen hecho" in texto
    assert "Abdomen de hoy" not in texto


def test_inicio_dice_por_donde_seguir_a_medias(inicio, store):
    from datetime import date as _date

    from storage import WorkoutEntry

    abdomen.configurar(store, activo=True, por_dia=3)
    toca = abdomen.de_hoy(store)
    store.save_workout(
        WorkoutEntry(
            date=_date.today().isoformat(),
            exercise=toca[0],
            muscle_group="Abs",
            phase=1,
            sets=[{"weight": 0, "reps": 15}],
        )
    )
    texto = _textos(inicio._abdomen_card())
    assert "1 de 3" in texto
    assert toca[1] in texto


def test_lo_hecho_se_mide_contra_el_historial_no_contra_un_flag(inicio, store):
    """Un flag habría que ponerlo al guardar, y una sesión abandonada a medias
    lo dejaría mintiendo."""
    abdomen.configurar(store, activo=True, por_dia=3)
    assert inicio._abdomen_hechos(abdomen.de_hoy(store)) == []


@pytest.fixture
def entreno(store):
    """La vista de entreno, importada **sin recargar el módulo**.

    Recargarlo con `sys.modules.pop` fue lo primero que hizo este fixture,
    copiado de otro que sí lo necesitaba. Rompía `test_workout_exercise_date`:
    este fichero va primero por orden alfabético, así que dejaba el módulo
    recién recargado debajo de un test que hace `monkeypatch` sobre el que él
    ya tenía. Un fallo que solo aparece en la suite entera y nunca ejecutando
    el fichero solo. Trampa 33.
    """
    from unittest.mock import MagicMock

    from views.workout import WorkoutView

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
    return v


def test_la_sesion_lleva_el_abdomen_al_final(entreno, store):
    de_la_rutina = list(entreno._routine_day().exercises)
    assert entreno._current_day().exercises == de_la_rutina

    abdomen.configurar(store, activo=True, por_dia=3)
    ampliado = entreno._current_day().exercises
    assert ampliado[: len(de_la_rutina)] == de_la_rutina
    assert ampliado[len(de_la_rutina) :] == list(abdomen.de_hoy(store))


def test_la_lista_de_dias_cuenta_el_abdomen(entreno, store):
    """Contar solo los de la rutina prometía siete y entregaba diez, y la
    diferencia no se veía hasta estar dentro."""
    dia = entreno._routine_day()
    assert entreno._cuenta_del_dia(dia) == f"{len(dia.exercises)} ejercicios"

    abdomen.configurar(store, activo=True, por_dia=3)
    assert entreno._cuenta_del_dia(dia) == f"{len(dia.exercises)} ejercicios + 3 de abdomen"


def test_la_sesion_suelta_es_solo_abdomen(entreno, store):
    abdomen.configurar(store, activo=True, por_dia=3)
    entreno.empezar_abdomen()
    assert entreno.solo_abdomen is True
    assert entreno._current_day().exercises == list(abdomen.de_hoy(store))
    assert entreno._current_day().name == "Abs"


def test_la_sesion_suelta_no_duplica_el_abdomen(entreno, store):
    """`_current_day` le añade el abdomen a cada día; en una sesión que *es*
    abdomen, hacerlo otra vez lo pondría dos veces."""
    abdomen.configurar(store, activo=True, por_dia=3)
    entreno.empezar_abdomen()
    ejercicios = entreno._current_day().exercises
    assert len(ejercicios) == len(set(ejercicios)) == 3


def test_atras_sale_del_modo_abdomen_y_no_a_una_lista_de_dias(entreno, store):
    """El chip «Atrás» de la cabecera llevaba a los días de una fase que no se
    estaba entrenando: repetía las tres líneas de `handle_back` en vez de
    llamarlo, y no se enteró de que había un modo nuevo."""
    abdomen.configurar(store, activo=True)
    entreno.empezar_abdomen()

    entreno._back_to_days()
    assert entreno.solo_abdomen is False
    assert entreno.show_phase_list is True
    assert entreno.show_day_list is False


def test_el_boton_atras_hace_lo_mismo_que_el_del_movil(entreno, store):
    """Su docstring promete «same promise as the hardware back button», y esto
    lo comprueba en vez de confiar en que siga siendo verdad."""
    abdomen.configurar(store, activo=True)

    entreno.empezar_abdomen()
    entreno._back_to_days()
    por_el_chip = (entreno.solo_abdomen, entreno.show_phase_list, entreno.show_day_list)

    entreno.empezar_abdomen()
    entreno.handle_back()
    por_el_movil = (entreno.solo_abdomen, entreno.show_phase_list, entreno.show_day_list)

    assert por_el_chip == por_el_movil


def test_terminar_una_sesion_de_abdomen_deja_la_pantalla_limpia(entreno, store):
    """Si no, la siguiente vez que se abra Entreno habría que salir de algo
    que nadie pidió."""
    abdomen.configurar(store, activo=True)
    entreno.empezar_abdomen()
    entreno._reset()
    assert entreno.solo_abdomen is False
