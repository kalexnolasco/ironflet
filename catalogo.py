"""Los 876 ejercicios de la Free Exercise DB, buscables desde la app.

Alex pidió «más ejercicios, pueden haber miles». La sorpresa fue que ya
estaban: la app lleva desde 0.6 bajando imágenes de
[Free Exercise DB](https://github.com/yuhonas/free-exercise-db) (Unlicense,
dominio público) — 876 movimientos con músculo, equipo, nivel y foto. Lo que
faltaba no era la fuente, era que la app los conociese: `EXERCISE_CATALOG`
lista 67 nombres escritos a mano y ese era todo el vocabulario del selector.

## Qué viaja en el APK y qué no

`assets/exercise_db.json` — 174 KB con nombre, músculos, equipo, nivel y
mecánica. **Las instrucciones se quedaron fuera** (700 de los 873 KB del
original) porque no las pinta nadie todavía.

Las **imágenes no viajan**: 876 × 2 fotos × 72 KB son 126 MB, cuatro veces
más grande que la app entera. Se bajan una a una la primera vez que hacen
falta, por el camino que `asset_manager` ya tenía para reparar el tarball.

## La regla que evita partir el historial

Los nombres de la base **no** son los de la app: ella dice `Barbell Bench
Press` y la base dice `Barbell Bench Press - Medium Grip`. De 114 nombres que
la app usa, solo 13 coinciden literalmente.

Eso importa porque el nombre **es** la clave con la que se guarda cada serie
(`exercise_key`, trampa 2). Añadir el press de banca de la base al lado del de
la app crearía dos historiales del mismo ejercicio, sin que nada fallase.

Así que **manda el nombre de la app**. `exercise_images.EXERCISE_IMAGE` ya
mapea nombre de la app → slug de la base, y ese diccionario se lee aquí al
revés: un ejercicio de la base cuyo slug ya pertenece a un nombre de la app se
ofrece **con el nombre de la app**. Los demás entran con el suyo, que es único
y estable. `nombre_canonico()` es esa traducción y `tests/test_catalogo.py`
comprueba que ningún ejercicio del catálogo grande puede entrar con un nombre
que duplique a uno de los de casa.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FICHERO = "exercise_db.json"

#: Los músculos de la base son ingleses y de grano fino (`middle back`,
#: `lats`, `traps`). Esto los agrupa en las ocho familias que la app ya usa en
#: `EXERCISE_CATALOG`, para que el filtro por grupo signifique lo mismo en las
#: dos listas. Traduce a español porque **es texto de pantalla**, no clave: la
#: clave sigue siendo el nombre del ejercicio (trampa 22).
GRUPO_POR_MUSCULO: dict[str, str] = {
    "chest": "Chest",
    "lats": "Back",
    "middle back": "Back",
    "lower back": "Back",
    "traps": "Back",
    "shoulders": "Shoulder",
    "neck": "Shoulder",
    "biceps": "Biceps",
    "forearms": "Biceps",
    "triceps": "Triceps",
    "quadriceps": "Leg",
    "hamstrings": "Leg",
    "glutes": "Leg",
    "calves": "Leg",
    "adductors": "Leg",
    "abductors": "Leg",
    "abdominals": "Abs",
}

#: Cómo se dice en la pantalla. Sí se traduce: son etiquetas, no claves.
ES_EQUIPO: dict[str, str] = {
    "barbell": "barra",
    "dumbbell": "mancuernas",
    "cable": "polea",
    "machine": "máquina",
    "body only": "peso corporal",
    "kettlebells": "kettlebell",
    "bands": "gomas",
    "medicine ball": "balón medicinal",
    "exercise ball": "fitball",
    "foam roll": "rodillo",
    "e-z curl bar": "barra Z",
    "other": "otro",
}

ES_NIVEL: dict[str, str] = {
    "beginner": "básico",
    "intermediate": "intermedio",
    "expert": "avanzado",
}

ES_CATEGORIA: dict[str, str] = {
    "strength": "fuerza",
    "stretching": "estiramiento",
    "plyometrics": "pliométrico",
    "powerlifting": "powerlifting",
    "olympic weightlifting": "halterofilia",
    "strongman": "strongman",
    "cardio": "cardio",
}


@dataclass(frozen=True)
class Ejercicio:
    """Una entrada del catálogo grande, ya traducida a la lengua de la app."""

    nombre: str
    slug: str
    grupo: str
    equipo: str
    nivel: str
    categoria: str
    #: True cuando este movimiento ya tenía nombre propio en la app. El nombre
    #: de arriba es entonces el de casa, no el de la base.
    de_la_casa: bool = False

    def descripcion(self) -> str:
        """La línea de debajo del nombre: «barra · fuerza · intermedio»."""
        piezas = [
            ES_EQUIPO.get(self.equipo, self.equipo),
            ES_CATEGORIA.get(self.categoria, self.categoria),
            ES_NIVEL.get(self.nivel, self.nivel),
        ]
        return " · ".join(p for p in piezas if p)


def _ruta() -> Path:
    """Donde vive el JSON. Junto a este módulo, dentro del APK."""
    return Path(__file__).parent / "assets" / FICHERO


def _sin_tildes(texto: str) -> str:
    """`Pájaro` → `pajaro`. Buscar «triceps» tiene que encontrar «tríceps»."""
    plano = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in plano if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=1)
def _nombres_prescritos() -> frozenset[str]:
    """Los nombres que alguna rutina o el catálogo de casa usan de verdad.

    No son todos los de `EXERCISE_IMAGE`: cinco de sus entradas son **las
    mitades de los bi-sets** («Bi-set: Barbell + DB Skull Crushers» tiene la
    foto de cada mitad), útiles para ofrecerlas sueltas pero que nadie
    prescribe por su cuenta.
    """
    from data import EXERCISE_CATALOG, ROUTINES
    from exercises import exercise_key

    nombres = {n for grupo in EXERCISE_CATALOG.values() for n in grupo}
    for rutina in ROUTINES:
        for dias in rutina.days_by_phase.values():
            for dia in dias:
                nombres.update(exercise_key(e) for e in dia.exercises)
    return frozenset(nombres)


@lru_cache(maxsize=1)
def _por_slug_de_casa() -> dict[str, str]:
    """slug de la base → nombre de la app, leyendo `EXERCISE_IMAGE` al revés.

    Ese diccionario existe para las fotos, y de paso es la única tabla que dice
    qué movimiento de la base es «el mismo» que uno de los nuestros.

    Dos nombres de la app pueden apuntar al mismo slug — `Incline DB Flyes` y
    `Incline Flyes` comparten `Incline_Dumbbell_Flyes`— y solo uno puede ganar,
    porque ofrecer los dos sería el mismo movimiento con dos historiales.
    **Gana el que alguna rutina prescribe**, que es el nombre bajo el que Alex
    ya tiene series guardadas; entre dos igual de vivos, el alfabético, que es
    arbitrario pero estable y evita que la lista baile entre arranques.
    """
    from exercise_images import EXERCISE_IMAGE

    vivos = _nombres_prescritos()
    salida: dict[str, str] = {}
    for nombre, slug in sorted(EXERCISE_IMAGE.items(), key=lambda kv: (kv[0] not in vivos, kv[0])):
        if slug and slug not in salida:
            salida[slug] = nombre
    return salida


def nombre_canonico(slug: str, nombre_base: str) -> tuple[str, bool]:
    """El nombre con el que este movimiento debe guardarse, y si es de casa.

    Manda el de la app cuando existe. Es lo que impide que «Barbell Bench
    Press - Medium Grip» abra un segundo historial al lado del press de banca
    que Alex lleva meses registrando.
    """
    de_casa = _por_slug_de_casa().get(slug)
    return (de_casa, True) if de_casa else (nombre_base, False)


@lru_cache(maxsize=1)
def todos() -> tuple[Ejercicio, ...]:
    """El catálogo entero, ordenado por nombre. Vacío si el fichero no está.

    Nunca lanza: un catálogo grande que falta deja la app con los 67 de
    siempre, que es degradar; una excepción aquí deja la pantalla en blanco.
    """
    try:
        crudo = json.loads(_ruta().read_text(encoding="utf-8"))
    except Exception:
        return ()
    if not isinstance(crudo, list):
        return ()

    salida = []
    for fila in crudo:
        if not isinstance(fila, dict):
            continue
        slug = str(fila.get("id") or "")
        base = str(fila.get("name") or "")
        if not slug or not base:
            continue
        musculos = fila.get("primaryMuscles") or []
        grupo = GRUPO_POR_MUSCULO.get(musculos[0] if musculos else "", "")
        if fila.get("category") == "cardio":
            grupo = "Cardio"
        nombre, de_casa = nombre_canonico(slug, base)
        salida.append(
            Ejercicio(
                nombre=nombre,
                slug=slug,
                grupo=grupo or "Otros",
                equipo=str(fila.get("equipment") or ""),
                nivel=str(fila.get("level") or ""),
                categoria=str(fila.get("category") or ""),
                de_la_casa=de_casa,
            )
        )

    # Un nombre, una fila. Dos entradas pueden acabar en el mismo nombre porque
    # la base trae el mismo movimiento con dos slugs — la app llama «Alternate
    # Hammer Curl» al slug `Hammer_Curls` y la base tiene además un
    # `Alternate_Hammer_Curl`. Guardan en el mismo historial, así que no parten
    # nada, pero en el selector serían dos filas idénticas. **Gana la de casa**:
    # su foto es la que el móvil ya tiene bajada.
    unicos: dict[str, Ejercicio] = {}
    for e in salida:
        previo = unicos.get(e.nombre.lower())
        if previo is None or (e.de_la_casa and not previo.de_la_casa):
            unicos[e.nombre.lower()] = e
    return tuple(sorted(unicos.values(), key=lambda e: e.nombre.lower()))


def grupos() -> tuple[str, ...]:
    """Los grupos que el catálogo grande sabe llenar, en el orden de la app."""
    from data import MUSCLE_GROUPS

    presentes = {e.grupo for e in todos()}
    orden = [g for g in MUSCLE_GROUPS if g in presentes]
    return tuple(orden + sorted(presentes - set(orden)))


def buscar(consulta: str = "", grupo: str = "", limite: int = 60) -> tuple[Ejercicio, ...]:
    """Busca por nombre y filtra por grupo.

    Ordena por dónde cae lo buscado: primero lo que **empieza** por ahí, luego
    lo que lo contiene. Escribir «curl» debe ofrecer `Curl` antes que
    `Alternate Hammer Curl`, y sin eso una lista de 876 devuelve 40 resultados
    en orden alfabético donde el que buscabas está el decimoséptimo.

    Los de casa suben dentro de su tramo: son los que Alex ya usa.
    """
    q = _sin_tildes(consulta.strip())
    fuente = [e for e in todos() if not grupo or e.grupo == grupo]
    if not q:
        return tuple(sorted(fuente, key=lambda e: (not e.de_la_casa, e.nombre.lower()))[:limite])

    puntuados = []
    for e in fuente:
        plano = _sin_tildes(e.nombre)
        if plano.startswith(q):
            rango = 0
        elif f" {q}" in plano:  # empieza una palabra
            rango = 1
        elif q in plano:
            rango = 2
        else:
            continue
        puntuados.append((rango, not e.de_la_casa, len(e.nombre), e.nombre.lower(), e))
    puntuados.sort(key=lambda t: t[:4])
    return tuple(t[4] for t in puntuados[:limite])


def por_nombre(nombre: str) -> Ejercicio | None:
    """El ejercicio que se guarda bajo ese nombre, si el catálogo lo conoce."""
    objetivo = nombre.strip().lower()
    for e in todos():
        if e.nombre.lower() == objetivo:
            return e
    return None


def slug_de(nombre: str) -> str:
    """El slug de la imagen para un nombre, mirando primero la tabla de casa.

    `exercise_images.image_props` sigue siendo quien decide cómo se pinta; esto
    solo resuelve el slug para los ejercicios que solo conoce el catálogo
    grande, que no están en `EXERCISE_IMAGE`.
    """
    from exercise_images import EXERCISE_IMAGE

    directo = EXERCISE_IMAGE.get(nombre)
    if directo:
        return directo
    e = por_nombre(nombre)
    return e.slug if e else ""


def reset_cache() -> None:
    """Para los tests, que cambian `EXERCISE_IMAGE` bajo los pies."""
    todos.cache_clear()
    _por_slug_de_casa.cache_clear()
    _nombres_prescritos.cache_clear()
