"""Abdomen todos los días, que es lo que el plan pide y la app no daba.

Alex: «debe haber una sección especial para abdominales, la idea es hacer cada
día». No es un capricho — es un agujero. El calendario de su fase 1 dice
**«+ Abs» cinco veces por semana**:

    Chest-Biceps · Back-Triceps + Abs · Rest · Shoulder-Leg · Chest-Biceps + Abs

y los tres días que se entrenan de verdad (`Chest - Biceps`, `Back - Triceps`,
`Shoulder - Leg`) no llevan **un solo ejercicio de abdomen** en su lista. El
«+ Abs» vivía en `week_rotation`, que es texto de distribución y no llega a la
pantalla de entreno. El plan lo prometía, la sesión no lo entregaba.

## Rota por función, no al azar

Lo fácil sería barajar los 93 ejercicios de abdomen del catálogo y sacar tres.
Y algunos días saldrían tres crunches, que es media hora trabajando lo mismo.

El abdomen hace tres trabajos distintos y un día completo toca los tres:
**flexión** (acercar el pecho a la cadera), **inferior** (acercar la cadera al
pecho) y **antiextensión u oblicuos** (aguantar sin moverse, o rotar). Por eso
el pool está partido en familias y cada día sale uno de cada — la variedad está
*dentro* de la familia, y la estructura del día no cambia.

## El mismo día da el mismo abdomen

`de_hoy()` es determinista sobre la fecha: abrir la app dos veces un martes no
cambia lo que toca. Un ejercicio que cambia bajo el dedo entre dos miradas es
un ejercicio que nadie termina.

## No es un extra

Los de `extras.py` valen para hoy y los pone Alex a mano. Esto es una decisión
permanente que se toma una vez y se cumple sola: si está activo, aparece al
final de **cada** día de entreno, y los días de descanso hay una sesión suya
propia. Se apaga desde Ajustes; el interruptor y el número por día son lo único
que se guarda.
"""

from __future__ import annotations

import contextlib
import json
from datetime import date
from typing import Any

PREF_KEY = "abdomen"

#: Cuántos al día por defecto. Tres es un día de abdomen completo —uno por
#: familia— y sigue cabiendo al final de una sesión de pesas sin alargarla.
POR_DIA_DEFECTO = 3

#: El tope. Más de cinco al día, todos los días, es una rutina de abdomen y no
#: un complemento; para eso está el editor de rutinas.
MAX_POR_DIA = 5

#: Las tres cosas que hace el abdomen, cada una con sus ejercicios. Los nombres
#: son los del catálogo (`catalogo.py` / `EXERCISE_CATALOG`) porque **son la
#: clave con la que se guarda cada serie** — trampa 2. Un nombre inventado aquí
#: abre un historial paralelo sin que nada falle.
#:
#: Dentro de cada familia van de menos a más exigentes, y esa es la única razón
#: del orden: quien empiece por el principio del pool encuentra primero lo que
#: puede hacer.
FAMILIAS: dict[str, tuple[str, ...]] = {
    "Flexión": (
        "Crunch - Hands Overhead",
        "3/4 Sit-Up",
        "Cross-Body Crunch",
        "Cable Crunch",
        "Decline Crunch",
    ),
    "Inferior": (
        "Bent-Knee Hip Raise",
        "Flat Bench Leg Pull-In",
        "Hanging Abs",
        "Decline Reverse Crunch",
        "Knee/Hip Raise On Parallel Bars",
    ),
    "Oblicuos y antiextensión": (
        "Plank",
        "Floor Obliques",
        "Side Bridge",
        "Russian Twist",
        "Cocoons",
    ),
}

ORDEN_FAMILIAS: tuple[str, ...] = tuple(FAMILIAS)


def _leer(store: Any) -> dict:
    try:
        crudo = store.get_pref(PREF_KEY, None)
    except Exception:
        return {}
    if not crudo:
        return {}
    try:
        datos = json.loads(crudo)
    except (TypeError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def activo(store: Any) -> bool:
    """¿Se añade abdomen a los días? Apagado hasta que alguien lo enciende.

    Encendido por defecto sería meterle ejercicios en la sesión a quien nunca
    los pidió, y el primer día que abriera Entreno se encontraría tres
    movimientos que no reconoce al final de su rutina.
    """
    return bool(_leer(store).get("activo", False))


def por_dia(store: Any) -> int:
    """Cuántos al día. Entre uno y `MAX_POR_DIA`."""
    try:
        n = int(_leer(store).get("por_dia", POR_DIA_DEFECTO))
    except (TypeError, ValueError):
        return POR_DIA_DEFECTO
    return max(1, min(MAX_POR_DIA, n))


def configurar(store: Any, *, activo: bool | None = None, por_dia: int | None = None) -> None:
    """Enciende, apaga o cambia cuántos. Lo que no se pasa no se toca."""
    estado = _leer(store)
    if activo is not None:
        estado["activo"] = bool(activo)
    if por_dia is not None:
        estado["por_dia"] = max(1, min(MAX_POR_DIA, int(por_dia)))
    with contextlib.suppress(Exception):
        store.set_pref(PREF_KEY, json.dumps(estado))


def de_hoy(store: Any, hoy: date | None = None, cuantos: int | None = None) -> tuple[str, ...]:
    """Los ejercicios de abdomen que tocan hoy, uno por familia.

    Determinista sobre la fecha: el mismo día devuelve siempre lo mismo, dos
    veces seguidas y en dos arranques distintos de la app.

    Con `cuantos` mayor que el número de familias, la cuarta ronda vuelve a la
    primera familia con **otro** ejercicio, que es lo que se quiere: repetir
    familia antes que repetir ejercicio.

    **Ningún día repite un ejercicio del día anterior** con el número por
    defecto. Pidiendo cinco al día ya no se puede prometer: son cinco de
    quince, y dos días seguidos cubren diez del pool. Ahí manda el tamaño del
    pool, no el reparto — y el arreglo sería más ejercicios por familia, no más
    aritmética.
    """
    dia = hoy or date.today()
    n = cuantos if cuantos is not None else por_dia(store)
    n = max(1, min(MAX_POR_DIA, n))

    ordinal = dia.toordinal()

    # Dos ruedas que giran por separado, y ese es el punto.
    #
    # `arranque` decide en qué **orden** salen las familias, para que con menos
    # de tres al día no se coma siempre la misma —con `cuantos=2` los oblicuos
    # no se harían nunca—. El **ejercicio**, en cambio, se elige por la familia
    # y el día, nunca por la posición en que se muestra.
    #
    # Atarlos fue el primer intento y salía mal: el día D daba [A, B, C] y el
    # D+1 daba [B, C, D], o sea la plancha tres días seguidos. Cada familia
    # tiene que avanzar **una vez al día**, y el `+ j * 2` las desfasa entre sí
    # para que las tres no recorran su pool en paralelo.
    arranque = ordinal % len(ORDEN_FAMILIAS)
    salida: list[str] = []
    for i in range(n):
        j = (arranque + i) % len(ORDEN_FAMILIAS)
        # Con más ejercicios que familias, la segunda vuelta repite familia —a
        # propósito, antes eso que repetir ejercicio— y `vuelta` es lo que hace
        # que el ejercicio sea otro. Sin él, pedir cuatro al día devolvía el
        # primero dos veces.
        vuelta = i // len(ORDEN_FAMILIAS)
        pool = FAMILIAS[ORDEN_FAMILIAS[j]]
        salida.append(pool[(ordinal + j * 2 + vuelta) % len(pool)])
    return tuple(salida)


def familia_de(nombre: str) -> str:
    """A qué familia pertenece un ejercicio, o «» si no es del pool."""
    for familia, pool in FAMILIAS.items():
        if nombre in pool:
            return familia
    return ""


def nombres_del_pool() -> frozenset[str]:
    return frozenset(n for pool in FAMILIAS.values() for n in pool)


def dia_con_abdomen(dia: Any, store: Any, hoy: date | None = None):
    """El día de la rutina **más** el abdomen de hoy, como un `TrainingDay`.

    Copia, como `extras.dia_con_extras`: el de `data.ROUTINES` se comparte
    entre fases y añadirle algo lo dejaría en el plan para siempre.

    Va **antes** que los extras y después de la rutina, para que el orden en
    pantalla sea siempre el mismo: lo que manda el plan, lo que se hace cada
    día, y lo que se añadió hoy.
    """
    from data import TrainingDay

    if dia is None:
        return None
    if not activo(store):
        return TrainingDay(name=dia.name, exercises=list(dia.exercises))

    ya = {e.lower() for e in dia.exercises}
    nuevos = [x for x in de_hoy(store, hoy) if x.lower() not in ya]
    return TrainingDay(name=dia.name, exercises=[*dia.exercises, *nuevos])


def dia_suelto(store: Any, hoy: date | None = None):
    """Un día que es **solo** abdomen, para las jornadas sin pesas.

    «La idea es hacer cada día», y Alex entrena cuatro o cinco: sin esto, los
    días de descanso se quedan sin abdomen y «cada día» pasa a ser «los días
    que voy al gimnasio», que es justo lo que no pidió.
    """
    from data import TrainingDay

    # «Abs» y no «Abdomen»: este nombre va literal a `entrenos.grupo` (trampa
    # 22) y es el vocabulario que la app ya usa —`EXERCISE_CATALOG["Abs"]`, el
    # «+ Abs» del calendario—. Un segundo nombre para lo mismo parte la
    # agrupación de Historial en dos sin que nada falle.
    return TrainingDay(name="Abs", exercises=list(de_hoy(store, hoy)))


def es_de_abdomen(dia: Any, indice: int, store: Any, hoy: date | None = None) -> bool:
    """¿La posición `indice` la puso esta rutina de abdomen?

    Se pregunta contra el día **original**, igual que `extras.es_extra`.
    """
    if dia is None or indice < 0 or not activo(store):
        return False
    cuantos = len(
        [x for x in de_hoy(store, hoy) if x.lower() not in {e.lower() for e in dia.exercises}]
    )
    return len(dia.exercises) <= indice < len(dia.exercises) + cuantos
