"""extras.py — ejercicios añadidos a mitad de sesión.

Tres cosas se vigilan aquí, y las tres son de pérdida silenciosa:

1. Que un extra **no se cuele en la rutina**. `_current_day()` devolvía el
   objeto de `data.ROUTINES`, que es compartido y mutable: añadirle algo lo
   dejaría en el plan de las 24 semanas.
2. Que el borrador **no tire las series** escritas en un extra. `fit_to_routine`
   descarta lo que no esté en la rutina, y un extra nunca lo está.
3. Que no se pueda guardar bajo un nombre inventado, que abriría un historial
   paralelo del mismo movimiento (trampa 2).
"""

from __future__ import annotations

from datetime import date

import pytest

import extras
from storage import Storage

HOY = date(2026, 8, 22)
AYER = date(2026, 8, 21)


@pytest.fixture
def store(tmp_path):
    return Storage(f"sqlite:///{tmp_path / 'extras.db'}")


# ── el ciclo básico ──────────────────────────────────────────────────────


def test_una_sesion_recien_empezada_no_tiene_extras(store):
    assert extras.de_hoy(store, HOY) == ()


def test_anadir_y_leer(store):
    assert extras.anadir(store, "Cable Crossover", HOY) is True
    assert extras.de_hoy(store, HOY) == ("Cable Crossover",)


def test_el_orden_es_el_de_llegada(store):
    for n in ("Cable Crossover", "Pec Deck", "Push-ups"):
        extras.anadir(store, n, HOY)
    assert extras.de_hoy(store, HOY) == ("Cable Crossover", "Pec Deck", "Push-ups")


def test_no_se_repite(store):
    assert extras.anadir(store, "Pec Deck", HOY) is True
    assert extras.anadir(store, "pec deck", HOY) is False
    assert len(extras.de_hoy(store, HOY)) == 1


def test_quitar(store):
    extras.anadir(store, "Pec Deck", HOY)
    extras.anadir(store, "Push-ups", HOY)
    assert extras.quitar(store, "pec deck", HOY) is True
    assert extras.de_hoy(store, HOY) == ("Push-ups",)
    assert extras.quitar(store, "Pec Deck", HOY) is False


def test_limpiar(store):
    extras.anadir(store, "Pec Deck", HOY)
    extras.limpiar(store, HOY)
    assert extras.de_hoy(store, HOY) == ()


# ── valen solo para hoy ──────────────────────────────────────────────────


def test_los_de_ayer_no_son_los_de_hoy(store):
    """Es lo que separa un extra de editar la rutina: mañana no está."""
    extras.anadir(store, "Pec Deck", AYER)
    assert extras.de_hoy(store, AYER) == ("Pec Deck",)
    assert extras.de_hoy(store, HOY) == ()


def test_leer_no_borra(store):
    """Leer con otra fecha no puede tirar lo guardado: si el reloj del móvil
    da un salto y vuelve, lo de hoy tiene que seguir ahí."""
    extras.anadir(store, "Pec Deck", HOY)
    extras.de_hoy(store, AYER)
    assert extras.de_hoy(store, HOY) == ("Pec Deck",)


# ── el nombre, que es la clave del historial ─────────────────────────────


def test_un_nombre_inventado_se_rechaza(store):
    """Abriría un segundo historial del mismo movimiento sin que nada falle."""
    assert extras.anadir(store, "Prensa Marciana", HOY) is False
    assert extras.de_hoy(store, HOY) == ()


def test_valen_los_del_catalogo_de_casa_y_los_del_grande(store):
    assert extras.es_valido("Cable Crossover") is True  # EXERCISE_CATALOG
    assert extras.es_valido("Ab Crunch Machine") is True  # solo catalogo.py
    assert extras.es_valido("") is False
    assert extras.es_valido("   ") is False


def test_lo_que_el_buscador_ofrece_se_puede_guardar():
    """El contrato entre las dos mitades: un botón que no hace nada al tocarlo
    es peor que un botón que no está."""
    import catalogo

    for e in catalogo.buscar("", limite=900):
        assert extras.es_valido(e.nombre), f"{e.nombre} se ofrece y se rechaza"


# ── el tope ──────────────────────────────────────────────────────────────


def test_hay_un_tope_por_sesion(store):
    import catalogo

    nombres = [e.nombre for e in catalogo.buscar("", limite=40)][: extras.MAX_EXTRAS + 3]
    puestos = sum(1 for n in nombres if extras.anadir(store, n, HOY))
    assert puestos == extras.MAX_EXTRAS
    assert len(extras.de_hoy(store, HOY)) == extras.MAX_EXTRAS


# ── la capa sobre el día, que es lo que ve la pantalla ───────────────────


def test_el_dia_ampliado_lleva_los_extras_al_final(store):
    from data import TrainingDay

    dia = TrainingDay(name="Chest-Biceps", exercises=["Barbell Bench Press", "Pec Deck"])
    extras.anadir(store, "Push-ups", HOY)
    ampliado = extras.dia_con_extras(dia, store, HOY)

    assert ampliado.exercises == ["Barbell Bench Press", "Pec Deck", "Push-ups"]
    assert ampliado.name == dia.name


def test_el_dia_de_la_rutina_no_se_toca_jamas(store):
    """EL test. `data.ROUTINES` se comparte entre fases y sobrevive a la
    sesión: un extra que se colara ahí estaría en el plan para siempre, en
    todas las fases que reusan ese día, y sin fila en ninguna base que lo
    explicara."""
    from data import TrainingDay

    dia = TrainingDay(name="Chest-Biceps", exercises=["Barbell Bench Press"])
    original = list(dia.exercises)

    extras.anadir(store, "Push-ups", HOY)
    ampliado = extras.dia_con_extras(dia, store, HOY)
    ampliado.exercises.append("Pec Deck")  # y aunque alguien lo modifique...

    assert dia.exercises == original, "el día de la rutina se mutó"


def test_copia_incluso_sin_extras(store):
    """Devolver el objeto original invita a que alguien le añada algo más
    adelante y se lleve el plan por delante sin enterarse."""
    from data import TrainingDay

    dia = TrainingDay(name="X", exercises=["Barbell Bench Press"])
    ampliado = extras.dia_con_extras(dia, store, HOY)
    assert ampliado is not dia
    assert ampliado.exercises == dia.exercises


def test_un_extra_que_ya_estaba_en_el_dia_no_se_duplica(store):
    from data import TrainingDay

    dia = TrainingDay(name="X", exercises=["Pec Deck"])
    extras.anadir(store, "Pec Deck", HOY)
    assert extras.dia_con_extras(dia, store, HOY).exercises == ["Pec Deck"]


def test_es_extra_distingue_lo_de_hoy_de_lo_de_la_rutina(store):
    from data import TrainingDay

    dia = TrainingDay(name="X", exercises=["Barbell Bench Press", "Pec Deck"])
    extras.anadir(store, "Push-ups", HOY)

    assert extras.es_extra(dia, 0, store, HOY) is False
    assert extras.es_extra(dia, 1, store, HOY) is False
    assert extras.es_extra(dia, 2, store, HOY) is True


def test_sin_dia_no_hay_nada_que_ampliar(store):
    assert extras.dia_con_extras(None, store, HOY) is None
    assert extras.es_extra(None, 0, store, HOY) is False


# ── el borrador, donde se perderían las series ───────────────────────────


def test_el_borrador_conserva_las_series_de_un_extra(store):
    """El fallo que este módulo casi mete: `fit_to_routine` tira las filas cuya
    clave no esté en la rutina, y un extra nunca lo está. Sin `extra_keys`, dos
    series escritas en un extra desaparecían al reabrir la app — en silencio,
    porque perder un borrador se lee como «no había nada guardado»."""
    from workout_draft import WorkoutDraft, fit_to_routine

    borrador = WorkoutDraft(
        routine_id="cambiatufisico",
        phase_id=1,
        day_idx=0,
        day_name=None,
        ex_idx=0,
        exercise="Barbell Bench Press",
        pending={"Ab Crunch Machine": [{"weight": "40", "reps": "12"}]},
        dates={},
        session_date=HOY.isoformat(),
    )

    # Que no esté ya en ese día es la premisa del test, no un detalle.
    from data import active_routine
    from exercises import exercise_key

    del_dia = {exercise_key(x) for x in active_routine().days_for_phase(1)[0].exercises}
    assert "Ab Crunch Machine" not in del_dia, "elige otro; este ya está en la rutina"

    sin_extras = fit_to_routine(borrador)
    con_extras = fit_to_routine(borrador, extra_keys=("Ab Crunch Machine",))

    assert sin_extras is not None
    assert "Ab Crunch Machine" not in sin_extras.pending, "sin extras debía tirarlo"
    assert "Ab Crunch Machine" in sin_extras.dropped

    assert con_extras is not None
    assert con_extras.pending["Ab Crunch Machine"] == [{"weight": "40", "reps": "12"}]
    assert "Ab Crunch Machine" not in con_extras.dropped


def test_el_draftstore_le_pasa_los_extras_al_ajuste(store):
    """Que la función acepte `extra_keys` no sirve si nadie se los da.

    Sin fecha fingida: `_extra_keys` lee los de *hoy* como hace en el móvil, y
    fijar una fecha aquí probaría un camino que no existe en producción.
    """
    from workout_draft import DraftStore

    extras.anadir(store, "Ab Crunch Machine")
    assert "Ab Crunch Machine" in DraftStore(store)._extra_keys()


def test_sin_base_de_datos_el_ajuste_no_revienta():
    from workout_draft import DraftStore

    class Rota:
        def get_pref(self, *_a, **_k):
            raise RuntimeError("sin base")

    assert DraftStore(Rota())._extra_keys() == ()


# ── robustez ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "basura", ["no es json", "[]", "null", '{"date": "2026-08-22", "items": "no lista"}', ""]
)
def test_una_pref_corrupta_deja_la_sesion_sin_extras_pero_viva(store, basura):
    store.set_pref(extras.PREF_KEY, basura)
    assert extras.de_hoy(store, HOY) == ()


def test_una_base_muerta_no_impide_entrenar():
    class Rota:
        def get_pref(self, *_a, **_k):
            raise RuntimeError("sin base")

        def set_pref(self, *_a, **_k):
            raise RuntimeError("sin base")

    assert extras.de_hoy(Rota(), HOY) == ()
    extras.limpiar(Rota(), HOY)  # no lanza
