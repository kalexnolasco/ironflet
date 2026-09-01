"""El repaso semanal: la vez que el entrenador escribe él.

Hasta 0.20 el coach solo contestaba. Sabía leer los entrenos, el peso, la
comida y las fotos, y sabía —desde 0.15— quién es Alex; pero nada de eso se
movía si no le preguntaba. Un entrenador que solo habla cuando le hablas es un
buscador con buenas maneras.

Esto es lo contrario: **una vez por semana mira los datos y escribe**. Tres o
cuatro frases: qué pasó, qué dice el peso, y una cosa que cambiar.

## Apagado de fábrica, y por buena razón

Esto **gasta dinero de Alex sin que él toque nada**. Es la única función de la
app que hace una llamada de pago por su cuenta, así que:

* se enciende a mano en Ajustes, nunca por defecto;
* corre **una vez por semana** y no una por arranque — `_ya_toca` mira el
  número de semana ISO, no un «han pasado 7 días» que se desplaza;
* guarda **lo que costó** junto al texto, y la pantalla lo enseña;
* y si falla, falla en silencio y se reintenta la semana siguiente. Un error de
  red no puede convertirse en una tarjeta roja en Inicio por algo que el
  usuario no pidió.

## Un texto, no una conversación

Se guarda el último y se pisa. No es un historial: es la nota de esta semana, y
la de hace un mes no la va a leer nadie. Eso también lo hace barato de guardar
— una pref, no un blob que crece.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

PREF_KEY = "repaso_semanal"

#: Lunes. El repaso mira la semana que acaba de cerrarse, así que el día
#: natural es el primero de la siguiente.
DIA_DEFECTO = 0

#: Lo que se le pide. Corto a propósito: esto se lee en una tarjeta de Inicio,
#: no en una pantalla de informe, y un texto largo ahí no se lee entero.
PROMPT = (
    "Escribe el repaso de mi semana. Mira lo que he entrenado, mi peso, mis "
    "medidas y lo que he comido — usa las herramientas antes de decir nada. "
    "Tres o cuatro frases como mucho, en segunda persona, sin saludo ni "
    "despedida: qué he hecho, qué dice el peso, y UNA cosa concreta que cambiar "
    "esta semana. Si algo va bien, dilo con el número delante. No propongas "
    "tarjetas ni me pidas que guarde nada."
)


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
    """Apagado hasta que alguien lo enciende. Gasta dinero por su cuenta."""
    return bool(_leer(store).get("activo", False))


def dia_semana(store: Any) -> int:
    """0 = lunes … 6 = domingo."""
    try:
        return int(_leer(store).get("dia", DIA_DEFECTO)) % 7
    except (TypeError, ValueError):
        return DIA_DEFECTO


def configurar(store: Any, *, activo: bool | None = None, dia: int | None = None) -> None:
    estado = _leer(store)
    if activo is not None:
        estado["activo"] = bool(activo)
    if dia is not None:
        estado["dia"] = int(dia) % 7
    with contextlib.suppress(Exception):
        store.set_pref(PREF_KEY, json.dumps(estado, ensure_ascii=False))


@dataclass(frozen=True)
class Repaso:
    """Lo que el coach escribió, cuándo y qué costó."""

    texto: str
    fecha: str = ""
    coste: float = 0.0
    modelo: str = ""

    @property
    def hay(self) -> bool:
        return bool(self.texto.strip())


def ultimo(store: Any) -> Repaso:
    """El repaso guardado. Uno solo: no es un historial, es la nota de ahora."""
    estado = _leer(store)
    return Repaso(
        texto=str(estado.get("texto") or ""),
        fecha=str(estado.get("fecha") or ""),
        coste=float(estado.get("coste") or 0.0),
        modelo=str(estado.get("modelo") or ""),
    )


def _semana_iso(dia: date) -> str:
    año, semana, _ = dia.isocalendar()
    return f"{año}-W{semana:02d}"


def toca(store: Any, hoy: date | None = None) -> bool:
    """¿Toca escribir uno hoy?

    Por **número de semana ISO** y no por «han pasado siete días»: lo segundo
    se desplaza cada vez que uno llega tarde, y en dos meses el repaso del
    lunes cae en jueves.
    """
    dia = hoy or date.today()
    if not activo(store):
        return False
    if dia.weekday() != dia_semana(store):
        return False
    try:
        from agent import has_key

        if not has_key(store):
            return False
    except Exception:
        return False
    return _leer(store).get("semana") != _semana_iso(dia)


def guardar(store: Any, texto: str, coste: float = 0.0, modelo: str = "", hoy: date | None = None):
    """Guarda el repaso y marca la semana como hecha."""
    dia = hoy or date.today()
    estado = _leer(store)
    estado.update(
        {
            "texto": texto.strip(),
            "fecha": dia.isoformat(),
            "semana": _semana_iso(dia),
            "coste": round(float(coste or 0.0), 4),
            "modelo": modelo,
        }
    )
    with contextlib.suppress(Exception):
        store.set_pref(PREF_KEY, json.dumps(estado, ensure_ascii=False))


def marcar_intento(store: Any, hoy: date | None = None) -> None:
    """Da la semana por gastada aunque haya fallado.

    Sin esto, un error de red convierte el repaso en un reintento por cada
    arranque de la app — y cada reintento que sí llegue a la API se cobra. La
    semana que viene se prueba otra vez, que es pronto de sobra.
    """
    estado = _leer(store)
    estado["semana"] = _semana_iso(hoy or date.today())
    with contextlib.suppress(Exception):
        store.set_pref(PREF_KEY, json.dumps(estado, ensure_ascii=False))


async def generar(store: Any, hoy: date | None = None) -> Repaso | None:
    """Le pide el repaso al coach y lo guarda. `None` si no salió.

    Marca la semana **antes** de llamar: si la llamada revienta a mitad, lo que
    no puede pasar es que el siguiente arranque lo intente otra vez y lo vuelva
    a pagar.
    """
    dia = hoy or date.today()
    marcar_intento(store, dia)

    try:
        import asyncio

        from agent import Coach

        # `to_thread` y no una llamada directa, por lo mismo que en el chat:
        # `ask` hace HTTP síncrono y bloquearía el bucle de eventos de Flet —
        # o sea, congelaría la pantalla mientras el modelo piensa.
        coach = Coach(store, today=dia)
        respuesta = await asyncio.to_thread(coach.ask, PROMPT)
    except Exception:
        return None

    if respuesta is None or not getattr(respuesta, "ok", False):
        return None
    texto = (getattr(respuesta, "text", "") or "").strip()
    if not texto:
        return None

    guardar(
        store,
        texto,
        coste=getattr(respuesta, "charged", 0.0) or 0.0,
        modelo=getattr(respuesta, "served_by", "") or "",
        hoy=dia,
    )
    return ultimo(store)
