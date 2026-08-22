"""Lo que el coach sabe de Alex y no vuelve a preguntar.

Hasta ahora el coach empezaba de cero en cada arranque de la app. Sabía leer su
historial, su peso y su comida — todo lo que está en la base de datos — pero no
sabía que entrena a las siete antes de trabajar, que no come pescado, que la
rodilla izquierda protesta en sentadilla profunda. Eso hay que contárselo cada
vez, y por eso no se le contaba.

## Hechos, no conversación

Guardar la conversación entera sería caro e inútil: un blob que crece sin
límite en `preferencias` y un mes de chat re-facturado en cada pregunta. Lo que
cambia el producto son **veinte líneas** — las que uno le diría a un entrenador
nuevo el primer día. Eso es lo que se guarda aquí, y por eso cabe entero en el
prompt de sistema en vez de detrás de una herramienta.

## Por qué en el prompt y no en una herramienta

`build_system_prompt` está escrito para ser idéntico byte a byte entre
peticiones, porque así la caché de prompt de OpenRouter funciona. Meter los
hechos ahí **invalida la caché cada vez que se edita uno** — y eso está bien:
se editan unas pocas veces en la vida del producto, no una vez al día como
pasaría con la fecha. A cambio, el coach nunca puede *no* saberlos, que es
justo lo contrario de lo que pasa con una herramienta que el modelo decide si
llama o no.

## El coach no escribe aquí

Igual que con los entrenos, el peso y los objetivos: el modelo **propone** un
hecho (`propose_memory`), la vista pinta la tarjeta y Alex toca Guardar. La
garantía es estructural — ninguna herramienta llega a estas funciones — y no
una instrucción en el prompt que un modelo pueda ignorar. Ver la trampa 14.

## Los límites, y por qué existen

Estos hechos viajan en **cada** pregunta que Alex hace, y los paga. Sin tope,
un coach entusiasta acaba guardando «hoy ha dicho que estaba cansado» treinta
veces y el prompt engorda para siempre. `MAX_HECHOS` y `MAX_LARGO` son ese
tope, y `anadir` empuja el más viejo cuando se llena en vez de fallar: un
límite que rompe la escritura es un límite que se descubre en el peor momento.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

#: La clave en `preferencias`. NO va en `SECRET_PREF_KEYS`: esto no es una
#: credencial, es exactamente lo que uno quiere que sobreviva a un cambio de
#: móvil — y el backup ya lleva su peso, sus fotos y su comida.
PREF = "coach_memoria"

#: Cuántos hechos como mucho. Veinte líneas es lo que uno le cuenta a un
#: entrenador nuevo; treinta ya es un expediente y se paga en cada pregunta.
MAX_HECHOS = 30

#: Y cuánto puede ocupar cada uno. Un «hecho» de un párrafo es una conversación
#: disfrazada, que es justo lo que este módulo evita.
MAX_LARGO = 200

#: Las categorías, en el orden en que se muestran. Son etiquetas de pantalla y
#: de agrupación, no contrato de datos: el hecho es el texto.
CATEGORIAS: tuple[tuple[str, str], ...] = (
    ("rutina", "Horarios y rutina"),
    ("comida", "Comida"),
    ("cuerpo", "Lesiones y molestias"),
    ("objetivo", "Objetivos"),
    ("otro", "Otros"),
)

_CLAVES = {c for c, _ in CATEGORIAS}


@dataclass(frozen=True)
class Hecho:
    """Una línea de lo que el coach sabe."""

    texto: str
    categoria: str = "otro"
    #: ISO. Para poder decir «esto lo apuntaste en marzo» cuando ya no sea
    #: verdad — una lesión curada sigue en la lista hasta que alguien la quita.
    creado: str = ""

    def etiqueta(self) -> str:
        for clave, nombre in CATEGORIAS:
            if clave == self.categoria:
                return nombre
        return "Otros"


def _normaliza(texto: str) -> str:
    return " ".join(str(texto or "").split())[:MAX_LARGO]


def _categoria(valor: Any) -> str:
    clave = str(valor or "").strip().lower()
    return clave if clave in _CLAVES else "otro"


def leer(store: Any) -> list[Hecho]:
    """Los hechos guardados, en el orden en que se añadieron.

    Nunca lanza. Una pref corrupta — o de una versión futura con otra forma —
    devuelve la lista vacía: un coach sin memoria funciona, un coach que
    revienta al arrancar no.
    """
    try:
        crudo = store.get_pref(PREF)
    except Exception:
        return []
    if not crudo:
        return []
    try:
        datos = json.loads(crudo)
    except (TypeError, ValueError):
        return []
    if not isinstance(datos, list):
        return []

    hechos = []
    for fila in datos:
        if isinstance(fila, str):  # forma vieja: una lista de cadenas
            texto, categoria, creado = fila, "otro", ""
        elif isinstance(fila, dict):
            texto = fila.get("texto") or fila.get("text") or ""
            categoria = _categoria(fila.get("categoria"))
            creado = str(fila.get("creado") or "")
        else:
            continue
        texto = _normaliza(texto)
        if texto:
            hechos.append(Hecho(texto=texto, categoria=categoria, creado=creado))
    return hechos[:MAX_HECHOS]


def _guardar(store: Any, hechos: list[Hecho]) -> None:
    store.set_pref(
        PREF,
        json.dumps(
            [{"texto": h.texto, "categoria": h.categoria, "creado": h.creado} for h in hechos],
            ensure_ascii=False,
        ),
    )


def anadir(store: Any, texto: str, categoria: str = "otro", hoy: date | None = None) -> Hecho:
    """Guarda un hecho y lo devuelve. Duplicado exacto = no-op.

    Al llegar a `MAX_HECHOS` empuja el más antiguo. Fallar aquí sería fallar
    justo cuando alguien está contando algo, que es el peor momento posible.
    """
    limpio = _normaliza(texto)
    if not limpio:
        raise ValueError("un hecho vacío no dice nada")

    hechos = leer(store)
    for h in hechos:
        if h.texto.lower() == limpio.lower():
            return h

    nuevo = Hecho(
        texto=limpio,
        categoria=_categoria(categoria),
        creado=(hoy or date.today()).isoformat(),
    )
    hechos.append(nuevo)
    _guardar(store, hechos[-MAX_HECHOS:])
    return nuevo


def borrar(store: Any, texto: str) -> bool:
    """Quita el hecho con ese texto. `False` si no estaba."""
    limpio = _normaliza(texto).lower()
    hechos = leer(store)
    quedan = [h for h in hechos if h.texto.lower() != limpio]
    if len(quedan) == len(hechos):
        return False
    _guardar(store, quedan)
    return True


def reemplazar(store: Any, hechos: list[Hecho]) -> None:
    """Deja exactamente esta lista. Para la pantalla de edición."""
    limpios = []
    vistos = set()
    for h in hechos:
        texto = _normaliza(h.texto)
        if not texto or texto.lower() in vistos:
            continue
        vistos.add(texto.lower())
        limpios.append(Hecho(texto=texto, categoria=_categoria(h.categoria), creado=h.creado))
    _guardar(store, limpios[:MAX_HECHOS])


def vacia(store: Any) -> bool:
    return not leer(store)


def para_prompt(store: Any) -> str:
    """Los hechos como bloque de texto para el prompt de sistema.

    Vacío cuando no hay ninguno — y ese vacío es lo que hace que el coach
    proponga la entrevista en vez de adivinar.
    """
    hechos = leer(store)
    if not hechos:
        return ""

    por_categoria: dict[str, list[str]] = {}
    for h in hechos:
        por_categoria.setdefault(h.categoria, []).append(h.texto)

    lineas = []
    for clave, nombre in CATEGORIAS:
        if clave in por_categoria:
            lineas.append(f"{nombre}:")
            lineas += [f"- {t}" for t in por_categoria[clave]]
    return "\n".join(lineas)
