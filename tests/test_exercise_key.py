"""The exercise key is a contract, not a formatting detail.

`exercise_key()` turns `"Squat [5×12,10,8,8,8]"` into `"Squat"`. That stripped
name is what lands in `entrenos.ejercicio`, and the Telegram coach in
`../agente/` writes and reads the very same column through its own
`a_canonico()` mapping.

If the normalisation drifts, nothing raises: rows simply stop matching. The
history splits in two — the app writing one key, the bot another — and the
progression the whole plan depends on quietly stops aggregating.

These tests freeze the behaviour so that any change has to be deliberate.
They must keep passing through the English-only refactor, when `exercise_key`
moves out of `i18n.py` into `exercises.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from data import ROUTINES

try:  # después del refactor vivirá en exercises.py
    from exercises import exercise_key
except ImportError:  # pragma: no cover - ruta previa al refactor
    from i18n import exercise_key


RAIZ = Path(__file__).resolve().parent.parent
BOT = RAIZ.parent / "agente" / "entrenador" / "entrenos.py"

# Medido sobre las 8 rutinas de data.py el 13/08/2026. Si cambian, es porque
# alguien añadió ejercicios (sube el número) o rompió la normalización (baja).
CADENAS_ESPERADAS = 282
CLAVES_ESPERADAS = 104


def cadenas_de_ejercicio() -> set[str]:
    return {
        ejercicio
        for rutina in ROUTINES
        for fase in rutina.phases
        for dia in rutina.days_for_phase(fase.id)
        for ejercicio in dia.exercises
    }


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Barbell Row", "Barbell Row"),
        ("Squat [5×12,10,8,8,8]", "Squat"),
        ("Pec Deck *", "Pec Deck"),
        ("Hanging Abs [5×max]", "Hanging Abs"),
        ("V-Pulldown + V-Row [comp] [4×8+8]", "V-Pulldown + V-Row"),
        ("Cable Curl [triple drop] [2×10+10+10]", "Cable Curl"),
        ("Barbell Bench Press [4×10,10,8,6+12↓]", "Barbell Bench Press"),
    ],
)
def test_formas_conocidas(entrada, esperado):
    assert exercise_key(entrada) == esperado


def test_es_idempotente():
    """Aplicarla dos veces no puede cambiar el resultado."""
    for cadena in cadenas_de_ejercicio():
        una = exercise_key(cadena)
        assert exercise_key(una) == una, cadena


def test_nunca_deja_corchetes_ni_asterisco():
    for clave in map(exercise_key, cadenas_de_ejercicio()):
        assert "[" not in clave and "]" not in clave, clave
        assert not clave.endswith("*"), clave
        assert clave == clave.strip(), repr(clave)


def test_el_colapso_de_variantes_se_mantiene():
    """Las variantes de un ejercicio deben caer en la MISMA clave.

    Es lo que agrega la progresión entre fases: `Squat [4×8-10]` de la fase 2 y
    `Squat [5×5]` de la fase 6 son el mismo ejercicio.
    """
    cadenas = cadenas_de_ejercicio()
    claves = {exercise_key(c) for c in cadenas}
    assert len(cadenas) == CADENAS_ESPERADAS, (
        f"{len(cadenas)} cadenas, esperaba {CADENAS_ESPERADAS}: "
        "si has añadido ejercicios, actualiza la constante a conciencia"
    )
    assert len(claves) == CLAVES_ESPERADAS, (
        f"{len(claves)} claves, esperaba {CLAVES_ESPERADAS}: la normalización cambió"
    )


def nombres_canonicos_del_bot() -> list[str]:
    """Lee EJERCICIOS del bot SIN importarlo.

    Importar `entrenador.entrenos` arrastra `config.py`, que hace
    `os.environ.setdefault` con el `.env` de producción: eso metería la
    contraseña real y la URL de producción en el proceso de pytest.
    Se parsea con `ast` para no ejecutar nada.
    """
    arbol = ast.parse(BOT.read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and any(
            getattr(t, "id", None) == "EJERCICIOS" for t in nodo.targets
        ):
            return [k.value for k in nodo.value.keys]
    raise AssertionError("No encontré EJERCICIOS en entrenos.py del bot")


@pytest.mark.skipif(not BOT.is_file(), reason="el bot no está en este despliegue")
def test_el_bot_y_la_app_hablan_de_los_mismos_ejercicios():
    """El contrato cruzado: cada ejercicio que escribe el bot existe aquí.

    Si esto falla, el bot está guardando entrenos bajo claves que la app no
    reconoce, y viceversa: dos historiales paralelos sin ningún error visible.
    """
    claves = {exercise_key(c) for c in cadenas_de_ejercicio()}
    delbot = nombres_canonicos_del_bot()
    huerfanos = [n for n in delbot if n not in claves]
    assert not huerfanos, (
        f"{len(huerfanos)} ejercicios del bot no existen en las rutinas de la app: "
        f"{huerfanos}. Añádelos a data.py o corrige EJERCICIOS en "
        "agente/entrenador/entrenos.py"
    )
    assert len(delbot) == 28, f"el bot declara {len(delbot)} ejercicios, esperaba 28"


@pytest.mark.skipif(not BOT.is_file(), reason="el bot no está en este despliegue")
def test_leer_el_bot_no_carga_su_entorno():
    """La lectura por ast no debe traerse la configuración de producción."""
    import os

    antes = os.environ.get("DATABASE_URL")
    nombres_canonicos_del_bot()
    assert os.environ.get("DATABASE_URL") == antes
