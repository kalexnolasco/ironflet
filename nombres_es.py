"""Los nombres de ejercicio, en español y **solo para la pantalla**.

Alex: «todo lo que tiene la apk tiene que estar en español… Elliptical». Y
tiene razón como usuario. Lo que no puede pasar es que esa traducción llegue a
la base de datos: `entrenos.ejercicio` guarda el nombre **inglés**, que es la
clave con la que se agrupa el historial (trampa 2). Traducir el dato partiría
en dos meses de series sin que nada fallara.

Así que esto es una **capa de presentación**, exactamente igual que
`MEAL_LABELS` traduce `"breakfast"` a «Desayuno» sin que la clave deje de ser
`breakfast`. La regla, en una línea:

    lo que se guarda es inglés · lo que se ve es español · nadie traduce al revés

`tests/test_nombres_es.py` comprueba que ninguna vista guarda lo traducido, que
es lo único que hace segura esta función.

## Por qué hay dos mecanismos y no uno

Los **~100 que prescriben las rutinas** están escritos a mano en `EXACTOS`:
son los que Alex lee todos los días y merecen sonar como los llamaría un
entrenador español, no como una traducción. «Skull Crushers» es «press
francés», que no se parece en nada palabra por palabra.

Los otros **~775 del catálogo** se componen por reglas. El inglés ordena
`MODIFICADOR + EQUIPO + MOVIMIENTO` y el español `MOVIMIENTO + MODIFICADOR +
con EQUIPO`, así que no basta con sustituir palabras: hay que reordenar.
Cuando una regla no llega, **se devuelve el nombre inglés tal cual**, que es
peor que una buena traducción y mucho mejor que una inventada.
"""

from __future__ import annotations

import re
from functools import lru_cache

# ── Los que Alex ve todos los días ───────────────────────────────────────
#
# A mano porque un entrenador español no dice «aplastadores de cráneo». La
# clave es el nombre que va a la base; el valor, lo que se pinta.
EXACTOS: dict[str, str] = {
    "Abs Triset": "Triserie de abdomen",
    "Alternate DB Curl": "Curl alterno con mancuernas",
    "Alternate Hammer Curl": "Curl martillo alterno",
    "Arnold Press": "Press Arnold",
    "Barbell Bench Press": "Press banca con barra",
    "Barbell Curl": "Curl con barra",
    "Barbell Lunges": "Zancadas con barra",
    "Barbell Military Press": "Press militar con barra",
    "Barbell Row": "Remo con barra",
    "Behind-Neck Lat Pulldown": "Jalón tras nuca",
    "Bulgarian Split Squat": "Sentadilla búlgara",
    "Cable Crossover": "Cruces en polea",
    "Cable Crunch": "Crunch en polea",
    "Cable Curl": "Curl en polea",
    "Cable Lateral Raises": "Elevaciones laterales en polea",
    "Cable Rear Delts": "Deltoides posterior en polea",
    "Calf Press": "Gemelo en prensa",
    "Calf Press + Seated": "Gemelo en prensa + sentado",
    "DB Curl": "Curl con mancuernas",
    "DB Lunges": "Zancadas con mancuernas",
    "DB Row": "Remo con mancuerna",
    "DB Shoulder Press": "Press de hombro con mancuernas",
    "Deadlift": "Peso muerto",
    "Dips": "Fondos",
    "EZ Bar Curl": "Curl con barra Z",
    "EZ Bar Preacher Curl": "Curl predicador con barra Z",
    "EZ Bar Skull Crushers": "Press francés con barra Z",
    "Face Pull": "Face pull",
    "Front Lat Pulldown": "Jalón al pecho",
    "Hammer Curl": "Curl martillo",
    "Hanging Abs": "Elevaciones colgado",
    "Hip Thrust": "Empuje de cadera",
    "Incline Barbell Bench Press": "Press inclinado con barra",
    "Incline DB Curl": "Curl inclinado con mancuernas",
    "Incline DB Flyes": "Aperturas inclinadas con mancuernas",
    "Incline DB Press": "Press inclinado con mancuernas",
    "Incline Machine Press": "Press inclinado en máquina",
    "Lateral Raises": "Elevaciones laterales",
    "Leg Extensions": "Extensiones de cuádriceps",
    "Leg Press": "Prensa de piernas",
    "Lunges": "Zancadas",
    "Lying + Seated Leg Curl": "Femoral tumbado + sentado",
    "Lying Leg Curl": "Femoral tumbado",
    "Machine Flyes": "Aperturas en máquina",
    "Machine Lateral Raises": "Elevaciones laterales en máquina",
    "Overhead Extension": "Extensión de tríceps sobre la cabeza",
    "Parallel Bar Dips": "Fondos en paralelas",
    "Pec Deck": "Contractor de pecho",
    "Plank": "Plancha",
    "Plate Front Raises": "Elevaciones frontales con disco",
    "Pull-ups": "Dominadas",
    "Push-ups": "Flexiones",
    "Reverse Curl": "Curl inverso",
    "Reverse Pushdown": "Extensión de tríceps inversa",
    "Romanian Deadlift": "Peso muerto rumano",
    "Rope Pushdown": "Extensión de tríceps con cuerda",
    "Seated Cable Row": "Remo sentado en polea",
    "Seated Calf Raise": "Gemelo sentado",
    "Seated DB Press": "Press sentado con mancuernas",
    "Seated Leg Curl": "Femoral sentado",
    "Simultaneous DB Curl": "Curl simultáneo con mancuernas",
    "Skull Crushers": "Press francés",
    "Skull Crushers + Close-Grip": "Press francés + agarre cerrado",
    "Smith Bench Press": "Press banca en multipower",
    "Smith Close-Grip Press": "Press cerrado en multipower",
    "Squat": "Sentadilla",
    "Standing Calf Raise": "Gemelo de pie",
    "Standing Rear Delts": "Deltoides posterior de pie",
    "Straight Bar Curl": "Curl con barra recta",
    "T-Bar Row": "Remo en T",
    "Triceps Pushdown": "Extensión de tríceps en polea",
    "V-Grip Lat Pulldown": "Jalón con agarre en V",
    "V-Pulldown + V-Row": "Jalón en V + remo en V",
    "Treadmill": "Cinta de correr",
    "Bike": "Bicicleta estática",
    "Elliptical": "Elíptica",
    "HIIT Intervals": "Intervalos HIIT",
    "Decline Press": "Press declinado",
    "Close-Grip Bench Press": "Press banca con agarre cerrado",
    "Flat Machine Press": "Press plano en máquina",
    "Incline Flyes": "Aperturas inclinadas",
    "Reverse Barbell Row": "Remo con barra en supinación",
    "DB Skull Crushers": "Press francés con mancuernas",
    "Smith Military Press": "Press militar en multipower",
    "Floor Obliques": "Oblicuos en el suelo",
    "Leg Raises": "Elevaciones de piernas",
    "Hyperextensions": "Hiperextensiones",
    "Triceps Kickback": "Patada de tríceps",
    "Upright Row": "Remo al mentón",
    "Front Raises": "Elevaciones frontales",
    "Rear Delts": "Deltoides posterior",
    "Chest Press": "Press de pecho",
    "Machine Row": "Remo en máquina",
    "Seated Row": "Remo sentado",
    "Preacher Curl": "Curl predicador",
    "Wrist Curl": "Curl de muñeca",
    "Shrugs": "Encogimientos",
    "Good Mornings": "Buenos días",
    "Crunch": "Crunch",
    "Sit-ups": "Abdominales",
    "Russian Twist": "Giro ruso",
    "Side Bridge": "Plancha lateral",
    "Mountain Climbers": "Escaladores",
    "Burpees": "Burpees",
    "DB Rear Delts": "Deltoides posterior con mancuernas",
}

# ── Las piezas con que se compone el resto ───────────────────────────────

#: El equipo, que en español va al final: «con mancuernas», «en polea».
#: La preposición viaja con el término porque no es la misma para todos.
_EQUIPO: dict[str, str] = {
    "barbell": "con barra",
    "dumbbell": "con mancuernas",
    "dumbbells": "con mancuernas",
    "kettlebell": "con kettlebell",
    "kettlebells": "con kettlebells",
    "cable": "en polea",
    "cables": "en polea",
    "machine": "en máquina",
    "smith": "en multipower",
    "smith machine": "en multipower",
    "band": "con goma",
    "bands": "con gomas",
    "resistance band": "con goma",
    "ez-bar": "con barra Z",
    "ez bar": "con barra Z",
    "e-z bar": "con barra Z",
    "plate": "con disco",
    "medicine ball": "con balón medicinal",
    "exercise ball": "en fitball",
    "stability ball": "en fitball",
    "bosu ball": "en bosu",
    "foam roll": "con rodillo",
    "rope": "con cuerda",
    "chain": "con cadenas",
    "sled": "con trineo",
    "weighted": "con lastre",
    "bodyweight": "con el peso del cuerpo",
    "pulley": "en polea",
    "low pulley": "en polea baja",
    "high pulley": "en polea alta",
    "leverage": "en máquina de palanca",
    "lever": "en máquina de palanca",
    "suspended": "en suspensión",
    "trx": "en TRX",
    "bench": "en banco",
    "box": "en cajón",
    "floor": "en el suelo",
    "wall": "en la pared",
    "roller": "con rueda",
    "ab roller": "con rueda abdominal",
    "landmine": "en landmine",
    "attachment": "con agarre",
    "handle": "con agarre",
    "strap": "con correas",
    "straps": "con correas",
    "vest": "con chaleco",
    "log": "con log",
    "axle": "con barra axle",
    "trap bar": "con barra hexagonal",
}

#: Cómo se hace: postura, ángulo, agarre. En español van tras el movimiento.
_MODIFICADOR: dict[str, str] = {
    "incline": "inclinado",
    "decline": "declinado",
    "flat": "plano",
    "seated": "sentado",
    "standing": "de pie",
    "lying": "tumbado",
    "kneeling": "de rodillas",
    "bent-over": "inclinado al frente",
    "bent over": "inclinado al frente",
    "one-arm": "a una mano",
    "single-arm": "a una mano",
    "single leg": "a una pierna",
    "one-leg": "a una pierna",
    "alternate": "alterno",
    "alternating": "alterno",
    "reverse": "inverso",
    "close-grip": "con agarre cerrado",
    "wide-grip": "con agarre abierto",
    "narrow grip": "con agarre cerrado",
    "neutral grip": "con agarre neutro",
    "overhead": "sobre la cabeza",
    "behind the back": "por detrás",
    "behind neck": "tras nuca",
    "front": "frontal",
    "side": "lateral",
    "lateral": "lateral",
    "rear": "posterior",
    "hanging": "colgado",
    "assisted": "asistido",
    "explosive": "explosivo",
    "isometric": "isométrico",
    "sumo": "sumo",
    "romanian": "rumano",
    "bulgarian": "búlgaro",
    "hack": "hack",
    "zercher": "zercher",
    "goblet": "goblet",
    "cross-body": "cruzado",
    "twisting": "con giro",
    "wide": "abierto",
    "narrow": "cerrado",
    "high": "alto",
    "low": "bajo",
    "palms-up": "en supinación",
    "palms-down": "en pronación",
    "supinated": "en supinación",
    "pronated": "en pronación",
    "two-arm": "a dos manos",
    "double": "doble",
    "single": "simple",
    "split": "en split",
    "staggered": "escalonado",
    "external": "externa",
    "internal": "interna",
    "straight-arm": "con brazo recto",
    "bent-arm": "con brazo flexionado",
    "straight-leg": "con pierna recta",
    "bent-knee": "con rodilla flexionada",
    "hang": "desde suspensión",
    "power": "de potencia",
    "partial": "parcial",
    "full": "completo",
    "eccentric": "excéntrico",
    "negative": "negativo",
    "paused": "con pausa",
    "tempo": "a tempo",
    "cross": "cruzado",
    "diagonal": "diagonal",
    "rotational": "rotacional",
    "unilateral": "unilateral",
    "prone": "boca abajo",
    "supine": "boca arriba",
    "half": "medio",
    "quarter": "cuarto",
    "stance": "de base",
}

#: El movimiento. Es la cabeza de la frase en español.
_MOVIMIENTO: dict[str, str] = {
    "bench press": "press banca",
    "press": "press",
    "chest press": "press de pecho",
    "shoulder press": "press de hombro",
    "military press": "press militar",
    "overhead press": "press militar",
    "push press": "push press",
    "curl": "curl",
    "hammer curl": "curl martillo",
    "preacher curl": "curl predicador",
    "concentration curl": "curl concentrado",
    "row": "remo",
    "upright row": "remo al mentón",
    "pulldown": "jalón",
    "lat pulldown": "jalón",
    "pullover": "pullover",
    "pushdown": "extensión de tríceps",
    "extension": "extensión",
    "leg extension": "extensión de cuádriceps",
    "triceps extension": "extensión de tríceps",
    "raise": "elevación",
    "lateral raise": "elevaciones laterales",
    "front raise": "elevaciones frontales",
    "calf raise": "elevación de gemelo",
    "leg raise": "elevación de piernas",
    "fly": "aperturas",
    "flyes": "aperturas",
    "flys": "aperturas",
    "squat": "sentadilla",
    "front squat": "sentadilla frontal",
    "deadlift": "peso muerto",
    "lunge": "zancada",
    "lunges": "zancadas",
    "step-up": "subida al cajón",
    "step up": "subida al cajón",
    "hip thrust": "empuje de cadera",
    "glute bridge": "puente de glúteo",
    "good morning": "buenos días",
    "shrug": "encogimiento",
    "dip": "fondo",
    "dips": "fondos",
    "pull-up": "dominada",
    "pull up": "dominada",
    "pullup": "dominada",
    "chin-up": "dominada supina",
    "push-up": "flexión",
    "push up": "flexión",
    "pushup": "flexión",
    "crunch": "crunch",
    "sit-up": "abdominal",
    "situp": "abdominal",
    "plank": "plancha",
    "twist": "giro",
    "clean": "cargada",
    "snatch": "arrancada",
    "jerk": "envión",
    "thruster": "thruster",
    "swing": "swing",
    "burpee": "burpee",
    "jump": "salto",
    "stretch": "estiramiento",
    "pull": "tirón",
    "carry": "paseo",
    "hold": "isométrico",
    "kickback": "patada",
    "pull-in": "encogimiento de piernas",
    "leg press": "prensa de piernas",
    "leg curl": "femoral",
    "hyperextension": "hiperextensión",
    "back extension": "extensión lumbar",
    "face pull": "face pull",
    "shoulder": "hombro",
    "wrist": "muñeca",
    "rollout": "rueda abdominal",
    "windmill": "molino",
    "bound": "salto en zancada",
    "throw": "lanzamiento",
    "drag": "arrastre",
    "sprint": "esprint",
    "run": "carrera",
    "walk": "paseo",
    "circle": "círculo",
    "circles": "círculos",
    "bend": "flexión lateral",
    "lift": "levantamiento",
    "rotation": "rotación",
    "abduction": "abducción",
    "adduction": "aducción",
    "flexion": "flexión",
    "pulse": "pulso",
    "hop": "salto",
    "skip": "skipping",
    "climb": "escalada",
    "mountain climber": "escalador",
    "flutter kick": "tijeras",
    "scissor": "tijeras",
    "bridge": "puente",
    "superman": "superman",
    "bird dog": "bird dog",
    "dead bug": "dead bug",
    "hollow": "hollow",
    "pull through": "pull through",
    "high pull": "tirón alto",
    "muscle-up": "muscle-up",
    "toe touch": "toque de puntas",
    "heel touch": "toque de talón",
}

#: Partes del cuerpo, para cuando aparecen sueltas.
_CUERPO: dict[str, str] = {
    "chest": "pecho",
    "back": "espalda",
    "shoulders": "hombros",
    "biceps": "bíceps",
    "triceps": "tríceps",
    "forearm": "antebrazo",
    "forearms": "antebrazos",
    "abs": "abdomen",
    "abdominals": "abdomen",
    "obliques": "oblicuos",
    "glutes": "glúteos",
    "hamstring": "isquios",
    "hamstrings": "isquios",
    "quads": "cuádriceps",
    "quadriceps": "cuádriceps",
    "calf": "gemelo",
    "calves": "gemelos",
    "calve": "gemelo",
    "hip": "cadera",
    "hips": "caderas",
    "neck": "cuello",
    "lower back": "lumbar",
    "traps": "trapecio",
    "lats": "dorsal",
    "adductor": "aductor",
    "abductor": "abductor",
    "groin": "aductores",
    "leg": "pierna",
    "legs": "piernas",
    "arm": "brazo",
    "arms": "brazos",
    "knee": "rodilla",
    "ankle": "tobillo",
    "delt": "deltoides",
    "delts": "deltoides",
    "deltoid": "deltoides",
    "pec": "pectoral",
    "oblique": "oblicuo",
    "tibialis": "tibial",
    "spine": "columna",
    "wrist": "muñeca",
    "elbow": "codo",
    "thigh": "muslo",
    "core": "core",
}

#: Los grupos que la app usa como pestañas y como `entrenos.grupo`.
GRUPOS: dict[str, str] = {
    "Chest": "Pecho",
    "Back": "Espalda",
    "Shoulder": "Hombro",
    "Shoulders": "Hombros",
    "Biceps": "Bíceps",
    "Triceps": "Tríceps",
    "Leg": "Pierna",
    "Legs": "Piernas",
    "Abs": "Abdomen",
    "Cardio": "Cardio",
    "Otros": "Otros",
    "Free": "Libre",
    "Rest": "Descanso",
}

#: Los prefijos de combinación, que se conservan y traducen aparte.
_PREFIJOS: dict[str, str] = {
    "Bi-set:": "Biserie:",
    "SS:": "Superserie:",
    "Triset:": "Triserie:",
}


#: Palabras que unen y no dicen nada por sí solas. Que sobre un «with» no
#: puede impedir traducir «Squats - With Bands»: el equipo ya está reconocido y
#: la preposición viaja dentro de «con gomas».
_RELLENO = frozenset(
    [
        "with",
        "and",
        "or",
        "the",
        "a",
        "an",
        "of",
        "on",
        "in",
        "to",
        "for",
        "at",
        "from",
        "your",
        "both",
        "each",
        "other",
        "s",
        "using",
    ]
)

#: Plurales que el inglés forma y las tablas guardan en singular. Antes que
#: duplicar cien entradas, se prueba quitando la marca de plural.
_SUFIJOS_PLURAL = ("s", "es")


def _busca(texto: str, tabla: dict[str, str]) -> tuple[str, str] | None:
    """La entrada más larga de `tabla` que aparece en `texto`, y el resto.

    La más larga y no la primera: «bench press» tiene que ganar a «press», o
    todo acaba llamándose «press» a secas.
    """
    bajo = texto.lower()
    mejor = None
    patron = None
    for clave in tabla:
        # El plural va en el propio patrón: «curls» encuentra «curl» sin que
        # haya que escribir las dos formas en cada tabla.
        p = rf"(?<![a-z]){re.escape(clave)}(?:es|s)?(?![a-z])"
        if re.search(p, bajo) and (mejor is None or len(clave) > len(mejor)):
            mejor, patron = clave, p
    if mejor is None:
        return None
    resto = re.sub(patron, " ", bajo, count=1)
    return tabla[mejor], " ".join(resto.split())


def _componer(nombre: str) -> str:
    """Traduce por reglas: movimiento, luego modificadores, luego equipo.

    Devuelve el nombre original si no reconoce el movimiento. Un nombre a
    medio traducir —«Barbell Hip Halo con barra»— es peor que uno en inglés:
    parece un fallo, y no se puede buscar ni en un idioma ni en el otro.
    """
    hallado = _busca(nombre, _MOVIMIENTO)
    if hallado is None:
        return nombre
    movimiento, resto = hallado

    partes = [movimiento]

    equipo = ""
    hallado_eq = _busca(resto, _EQUIPO)
    if hallado_eq:
        equipo, resto = hallado_eq

    # Los modificadores, en el orden en que aparecían.
    modificadores = []
    while True:
        hallado_mod = _busca(resto, _MODIFICADOR)
        if hallado_mod is None:
            break
        mod, resto = hallado_mod
        if mod not in modificadores:
            modificadores.append(mod)

    cuerpo = []
    while True:
        hallado_c = _busca(resto, _CUERPO)
        if hallado_c is None:
            break
        c, resto = hallado_c
        if c not in cuerpo:
            cuerpo.append(c)

    # Lo que sobra sin traducir, quitando las palabras de unión. Si aún queda
    # algo con letras, el nombre dice cosas que este módulo no entiende y
    # traducirlo a medias engañaría: «Press Ab Crunch» no es ni una cosa ni
    # otra, y no se puede buscar en ninguno de los dos idiomas.
    sobra = [w for w in re.findall(r"[a-z]+", resto) if w not in _RELLENO]
    if sobra:
        return nombre

    if cuerpo:
        partes.append("de " + " y ".join(cuerpo))
    partes += modificadores
    if equipo:
        partes.append(equipo)
    frase = " ".join(partes)
    return frase[:1].upper() + frase[1:]


@lru_cache(maxsize=1)
def _colisiones() -> frozenset[str]:
    """Los nombres cuya traducción ya usa otro ejercicio del catálogo.

    Pasa cinco veces en 875, y cuatro son **el mismo movimiento con dos
    nombres** en la propia base: «DB Shoulder Press» y «Dumbbell Shoulder
    Press», «Squat with Bands» y «Squats - With Bands». La traducción los
    revela, que está bien; lo que no puede es dejar dos filas idénticas en el
    buscador y una elección a ciegas.

    Así que gana uno —el de casa si lo hay, y si no el alfabético, que es
    arbitrario pero estable— y el otro se queda en inglés. Verlos distintos es
    peor que verlos traducidos y mejor que verlos iguales.
    """
    try:
        import catalogo

        entradas = catalogo.todos()
    except Exception:
        return frozenset()

    por_traduccion: dict[str, list] = {}
    for e in entradas:
        # `_traducir` y no `ejercicio`: llamarse a sí misma aquí sería una
        # recursión infinita a través de este mismo caché.
        por_traduccion.setdefault(_traducir(e.nombre), []).append(e)

    perdedores = set()
    for traduccion, grupo_ in por_traduccion.items():
        if len(grupo_) < 2 or traduccion in {e.nombre for e in grupo_}:
            continue
        ordenados = sorted(grupo_, key=lambda e: (not e.de_la_casa, e.nombre))
        perdedores.update(e.nombre for e in ordenados[1:])
    return frozenset(perdedores)


def _traducir(clave: str) -> str:
    """La traducción sin mirar colisiones. Solo para `_colisiones`."""
    limpio = clave.strip()
    exacto = EXACTOS.get(limpio)
    if exacto:
        return exacto
    for prefijo, es in _PREFIJOS.items():
        if limpio.startswith(prefijo):
            cuerpo = limpio[len(prefijo) :].strip()
            return f"{es} {' + '.join(_traducir(x.strip()) for x in cuerpo.split('+'))}"
    if "+" in limpio:
        return " + ".join(_traducir(x.strip()) for x in limpio.split("+"))
    return _componer(limpio)


@lru_cache(maxsize=2048)
def ejercicio(clave: str) -> str:
    """El nombre en español de un ejercicio. **Solo para pintar.**

    Nunca al revés: lo que se guarda en `entrenos.ejercicio` es la clave que
    entra aquí, no lo que sale.
    """
    if not clave:
        return ""
    limpio = clave.strip()

    # Lo escrito a mano manda siempre: son los que Alex lee a diario y ninguno
    # colisiona (`tests/test_nombres_es.py` lo comprueba).
    exacto = EXACTOS.get(limpio)
    if exacto:
        return exacto

    if limpio in _colisiones():
        return limpio
    return _traducir(limpio)


def grupo(nombre: str) -> str:
    """«Chest» → «Pecho». El nombre inglés sigue siendo el de la base."""
    return GRUPOS.get((nombre or "").strip(), nombre)


def dia(nombre: str) -> str:
    """«Chest - Biceps» → «Pecho - Bíceps», sin tocar `entrenos.grupo`.

    Los días se llaman con grupos musculares unidos por separadores, y a veces
    con un prefijo («D1: Chest + Abs») o un sufijo («Upper Power»). Se traduce
    lo que se reconoce y se deja lo demás, que es lo honesto: media traducción
    de un nombre propio se lee peor que el nombre entero.
    """
    texto = (nombre or "").strip()
    if not texto:
        return ""

    directo = GRUPOS.get(texto)
    if directo:
        return directo

    def _trozo(t: str) -> str:
        t = t.strip()
        return GRUPOS.get(t, _EXTRA_DIA.get(t.lower(), t))

    # Se parte por los separadores conservándolos, para no perder la forma.
    piezas = re.split(r"(\s*[-+/]\s*|:\s*)", texto)
    return "".join(p if re.match(r"^\s*[-+/:]\s*$", p) else _trozo(p) for p in piezas)


#: Palabras que solo aparecen en nombres de día.
_EXTRA_DIA: dict[str, str] = {
    "upper": "Torso",
    "lower": "Pierna",
    "upper power": "Torso fuerza",
    "lower power": "Pierna fuerza",
    "upper hypertrophy": "Torso hipertrofia",
    "lower hypertrophy": "Pierna hipertrofia",
    "push": "Empuje",
    "pull": "Tirón",
    "full body a": "Cuerpo completo A",
    "full body b": "Cuerpo completo B",
    "full body c": "Cuerpo completo C",
    "workout a": "Sesión A",
    "workout b": "Sesión B",
    "arms": "Brazos",
    "rest": "Descanso",
    "free": "Libre",
}


def reset_cache() -> None:
    ejercicio.cache_clear()
    _colisiones.cache_clear()
