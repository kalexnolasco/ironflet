"""Ejercicios añadidos a mitad de sesión, sin tocar la rutina.

Estás entrenando, la máquina que tocaba está ocupada, o acabas la última serie
con ganas de meter algo más. Hasta ahora la única salida era editar la rutina —
cambiar el plan de las próximas 24 semanas para arreglar un martes.

Un extra es exactamente lo contrario de eso: **vale solo para hoy**. Mañana la
rutina vuelve a ser la que era, sin que nadie tenga que deshacer nada. Si un
movimiento merece quedarse, se añade a la rutina en su editor, que es donde
esa decisión se toma a propósito.

## Por qué es una capa y no una lista editable

`_current_day()` devuelve el `TrainingDay` de `data.ROUTINES`, que es un objeto
**compartido y mutable**: añadirle el extra directamente lo dejaría en el plan
para siempre, en todas las fases que reusan ese día, y sin fila en ninguna base
de datos que explicara de dónde salió. `dia_con_extras()` devuelve una copia.

## Por qué al final y no donde toque

Los extras se añaden al final de la lista y ahí se quedan. La vista de entreno
piensa en **posiciones** (`ex_idx`), y meter uno en medio movería todo lo que
viene detrás: el ejercicio en pantalla cambiaría bajo el dedo. Lo que sí está
indexado por nombre —el borrador a medio escribir y las sustituciones— no se
entera de nada, y por eso esto es seguro.

## Lo que un extra no puede ser

Un nombre que no exista ya en algún catálogo. `entrenos.ejercicio` es la clave
del historial (trampa 2), así que un nombre inventado abre una segunda historia
del mismo movimiento sin que nada falle. `es_valido()` lo comprueba contra el
catálogo de casa y contra los 876 de `catalogo.py`, que es de donde salen.
"""

from __future__ import annotations

import contextlib
import json
from datetime import date
from typing import Any

PREF_KEY = "extras_hoy"

#: Tope por sesión. No es una limitación técnica: veinte ejercicios extra en un
#: día es alguien que está entrenando con otra rutina, y lo que quiere es
#: editarla. El número existe para que una lista larguísima no convierta la
#: navegación por posiciones en un laberinto.
MAX_EXTRAS = 10


def _hoy(hoy: date | None = None) -> str:
    return (hoy or date.today()).isoformat()


def _leer(store: Any) -> dict:
    """El estado guardado. Nunca lanza: sin extras se entrena igual."""
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


def de_hoy(store: Any, hoy: date | None = None) -> tuple[str, ...]:
    """Los extras de hoy, en el orden en que se añadieron.

    Un estado con la fecha de ayer devuelve vacío en vez de borrarse: leer no
    debería escribir, y la siguiente escritura lo pisa de todas formas.
    """
    estado = _leer(store)
    if estado.get("date") != _hoy(hoy):
        return ()
    items = estado.get("items")
    if not isinstance(items, list):
        return ()
    vistos, salida = set(), []
    for x in items:
        if isinstance(x, str) and x.strip() and x.lower() not in vistos:
            vistos.add(x.lower())
            salida.append(x.strip())
    return tuple(salida[:MAX_EXTRAS])


def _guardar(store: Any, items: tuple[str, ...], hoy: date | None = None) -> None:
    with contextlib.suppress(Exception):
        store.set_pref(PREF_KEY, json.dumps({"date": _hoy(hoy), "items": list(items)}))


def nombres_conocidos() -> frozenset[str]:
    """Todo nombre bajo el que esta app sabe guardar una serie.

    Las tres fuentes juntas: el catálogo escrito a mano, lo que prescriben las
    rutinas (incluidas las que Alex se haya creado) y los 876 del catálogo
    grande.
    """
    from data import EXERCISE_CATALOG, ROUTINES
    from exercises import exercise_key

    nombres = {n for grupo in EXERCISE_CATALOG.values() for n in grupo}
    for rutina in ROUTINES:
        for dias in rutina.days_by_phase.values():
            for dia in dias:
                nombres.update(exercise_key(e) for e in dia.exercises)
    with contextlib.suppress(Exception):
        import catalogo

        nombres.update(e.nombre for e in catalogo.todos())
    return frozenset(nombres)


def es_valido(nombre: str) -> bool:
    """¿Se puede guardar bajo este nombre sin partir un historial?"""
    limpio = (nombre or "").strip()
    if not limpio:
        return False
    return limpio.lower() in {n.lower() for n in nombres_conocidos()}


def anadir(store: Any, nombre: str, hoy: date | None = None) -> bool:
    """Mete un ejercicio en la sesión de hoy. `False` si no cabe o no vale."""
    limpio = (nombre or "").strip()
    if not es_valido(limpio):
        return False
    actuales = de_hoy(store, hoy)
    if any(x.lower() == limpio.lower() for x in actuales):
        return False
    if len(actuales) >= MAX_EXTRAS:
        return False
    _guardar(store, (*actuales, limpio), hoy)
    return True


def quitar(store: Any, nombre: str, hoy: date | None = None) -> bool:
    """Saca un extra de la sesión. No toca lo ya registrado en `entrenos`.

    Quien lo llama tiene que haber comprobado que no está guardado ya: esto
    solo mantiene la lista, y borrar filas del historial es otra operación
    —deliberadamente— más difícil de hacer sin querer.
    """
    actuales = de_hoy(store, hoy)
    quedan = tuple(x for x in actuales if x.lower() != (nombre or "").strip().lower())
    if len(quedan) == len(actuales):
        return False
    _guardar(store, quedan, hoy)
    return True


def limpiar(store: Any, hoy: date | None = None) -> None:
    """Vacía los de hoy. Lo llama el final de la sesión."""
    _guardar(store, (), hoy)


def dia_con_extras(dia: Any, store: Any, hoy: date | None = None):
    """El día de la rutina **más** los extras, como un `TrainingDay` nuevo.

    Copia siempre, incluso sin extras: devolver el objeto de `data.ROUTINES`
    tal cual invita a que alguien le añada algo más adelante y se lleve por
    delante el plan de las 24 semanas sin enterarse.
    """
    from data import TrainingDay

    if dia is None:
        return None
    añadidos = [x for x in de_hoy(store, hoy) if x not in dia.exercises]
    return TrainingDay(name=dia.name, exercises=[*dia.exercises, *añadidos])


def es_extra(dia: Any, indice: int, store: Any, hoy: date | None = None) -> bool:
    """¿La posición `indice` la puso Alex hoy, o venía en la rutina?

    Se pregunta contra el día **original**, no contra el ampliado: la respuesta
    es «está más allá de donde acaba la rutina».
    """
    if dia is None or indice < 0:
        return False
    return indice >= len(dia.exercises) and bool(de_hoy(store, hoy))
