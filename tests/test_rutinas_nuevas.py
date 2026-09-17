"""Las rutinas añadidas en 0.18: PHUL, StrongLifts, Arnold y Full Body.

No son inventadas — son programas publicados, transcritos con sus series y
repeticiones originales. Lo único traducido son los nombres de los ejercicios,
y no al español: **al vocabulario que esta app ya usa**.

Eso último es lo que vigila este fichero. PHUL empieza por «Bench Press»; si se
hubiera copiado tal cual, una sentadilla hecha en PHUL habría abierto un
historial distinto del de CambiaTuFísico, sin que nada fallara (trampa 2).
"""

from __future__ import annotations

import pytest

import extras
from data import ROUTINES, Routine
from exercises import exercise_key

NUEVAS = ("phul", "stronglifts", "arnold", "full-body")


def _rutina(rid: str) -> Routine:
    return next(r for r in ROUTINES if r.id == rid)


def _ejercicios(r: Routine) -> list[str]:
    return [e for dias in r.days_by_phase.values() for d in dias for e in d.exercises]


@pytest.mark.parametrize("rid", NUEVAS)
def test_la_rutina_existe_y_se_puede_activar(rid):
    from data import active_routine, set_active_routine

    r = _rutina(rid)
    assert r.name and r.description
    set_active_routine(rid)
    try:
        assert active_routine().id == rid
        assert active_routine().days_for_phase(r.phases[0].id)
    finally:
        set_active_routine("cambiatufisico")


@pytest.mark.parametrize("rid", NUEVAS)
def test_todos_sus_ejercicios_existen(rid):
    """EL test. Un nombre que la app no conoce parte el historial en dos."""
    conocidos = {n.lower() for n in extras.nombres_conocidos()}
    malos = [e for e in _ejercicios(_rutina(rid)) if exercise_key(e).lower() not in conocidos]
    assert malos == [], f"{rid} usa nombres que la app no sabe guardar: {malos}"


@pytest.mark.parametrize("rid", NUEVAS)
def test_ninguna_introduce_una_clave_nueva(rid):
    """Se escribieron con el vocabulario de casa a propósito.

    Un ejercicio legítimamente nuevo tendría que añadirse también al catálogo y
    a `EXERCISE_IMAGE`; hasta entonces, una rutina que estrena nombre es una
    rutina cuyo historial no se junta con el del resto.
    """
    de_las_viejas = {
        exercise_key(e)
        for r in ROUTINES
        if r.id not in NUEVAS
        for dias in r.days_by_phase.values()
        for d in dias
        for e in d.exercises
    }
    mias = {exercise_key(e) for e in _ejercicios(_rutina(rid))}
    assert mias <= de_las_viejas, f"{rid} estrena: {sorted(mias - de_las_viejas)}"


@pytest.mark.parametrize("rid", NUEVAS)
def test_cada_fase_tiene_dias_y_cada_dia_ejercicios(rid):
    r = _rutina(rid)
    assert r.phases
    for fase in r.phases:
        dias = r.days_for_phase(fase.id)
        assert dias, f"{rid} fase {fase.id} sin días"
        for d in dias:
            assert d.name and d.exercises, f"{rid} · {d.name} vacío"


@pytest.mark.parametrize("rid", NUEVAS)
def test_los_esquemas_se_parsean(rid):
    """`[4×3-5]` tiene que leerlo `parse_scheme`, o la pantalla no sabe cuántas
    series poner y cae al defecto de la fase sin decir nada."""
    from progression import parse_scheme

    for e in _ejercicios(_rutina(rid)):
        if "[" not in e:
            continue
        assert parse_scheme(e) is not None, f"{rid}: no se entiende el esquema de «{e}»"


@pytest.mark.parametrize("rid", NUEVAS)
def test_la_prosa_de_las_fases_la_entienden_los_parsers(rid):
    """Trampa 24: `parse_rir` y `parse_prescribed_step` son bilingües, y una
    frase que ningún regex reconoce no falla — el objetivo de RIR simplemente
    desaparece de todas las filas."""
    from progression import is_deload

    for fase in _rutina(rid).phases:
        assert fase.notes, f"{rid} fase {fase.id} sin notas"
        # Ninguna de estas es de descarga; que no se lea como tal por accidente.
        assert not is_deload(fase), f"{rid} fase {fase.id} se lee como descarga"


def test_phul_conserva_su_estructura_original():
    """Cuatro días: dos de fuerza a 3-5 y dos de hipertrofia a 8-12."""
    dias = _rutina("phul").days_for_phase(1)
    assert [d.name for d in dias] == [
        "Upper Power",
        "Lower Power",
        "Upper Hypertrophy",
        "Lower Hypertrophy",
    ]
    assert "[4×3-5]" in dias[0].exercises[0]
    assert "[4×8-12]" in dias[2].exercises[0]


def test_stronglifts_hace_el_peso_muerto_a_una_serie():
    """1×5, no 5×5. Es la excepción del programa y copiarla mal son cuatro
    series de más en el ejercicio que más cuesta recuperar."""
    b = _rutina("stronglifts").days_for_phase(1)[1]
    muerto = next(e for e in b.exercises if "Deadlift" in e)
    assert "[1×5]" in muerto


def test_las_ocho_rutinas_tienen_id_unico():
    ids = [r.id for r in ROUTINES]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 8
