"""El cuerpo humano, dibujado por músculos y coloreado con lo que entrenas.

Alex: «que se vea el cuerpo humano… seleccionable». Los datos ya estaban:
`analytics.sets_per_muscle_group` lleva desde 0.4 devolviendo series por
músculo —`chest`, `lats`, `quadriceps`, trece en total— y lo único que la app
hacía con ellas era una lista de barras. Una lista contesta «cuántas series de
dorsal», que no es la pregunta; la pregunta es **qué llevas flojo**, y esa se
contesta de un vistazo o no se contesta.

## Geometría como datos, no como dibujo

Cada músculo es una lista de trazos y cada trazo una curva cerrada de puntos.
Nada aquí importa Flet: son números en un lienzo de 100×220, y quien los pinta
decide con qué. Eso tiene dos consecuencias que valen el rodeo:

* se puede **probar la geometría sin abrir una app** — que ningún músculo se
  salga del lienzo, que los pares izquierda/derecha sean simétricos, que no
  falte ninguno de los trece;
* y se pudo **verificar mirándolo**, renderizando el mismo dato a SVG en el
  escritorio, antes de compilar un APK de 85 MB para ver si un brazo estaba
  torcido.

## Este es el cuerpo de repuesto

Desde 0.0.1 hay un cuerpo **3D de verdad** —`cuerpo3d.py`, anatómico y
girable— y es el que se ve en el móvil. Este mapa plano no se retiró porque el
3D necesita un `ft.WebView`, que solo existe en Android y iOS: en el PC, en los
tests y en cualquier sitio donde el visor no arranque, la pantalla de histórico
cae aquí. Un cuerpo peor es mejor que una pantalla rota.

Lo que da la sensación de volumen sin geometría es el **sombreado**: cada
músculo se pinta con un degradado radial cuyo foco está donde le daría la luz,
y eso en una silueta plana basta para que se lea como un cuerpo. `flet.canvas`
trae `PaintRadialGradient`, así que el volumen sale del pintor.

La escala de color es **la misma** que la del 3D —`mapa_muscular.color_de`, que
los dos llaman—, para que la misma semana no salga naranja en una pantalla y
roja en la otra.

## Las coordenadas

Lienzo **100 de ancho × 220 de alto**, el eje Y hacia abajo como en pantalla, y
el cuerpo centrado en x=50. Quien pinta escala; aquí no hay píxeles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: El lienzo en el que están dadas todas las coordenadas.
ANCHO = 100.0
ALTO = 220.0

#: Un punto de control «vacío» para las curvas suaves: cuando un trazo se
#: describe solo con vértices, el pintor los une con cúbicas cuyos tiradores
#: salen de la propia dirección del contorno.
Punto = tuple[float, float]


@dataclass(frozen=True)
class Musculo:
    """Un músculo: cómo se llama, cómo se dibuja y en qué vista se ve.

    `clave` es la que devuelve `analytics.sets_per_muscle_group().totals` — no
    se traduce ni se inventa, porque es la que trae los datos.
    """

    clave: str
    etiqueta: str
    #: "frente" | "espalda". Ninguno está en las dos: un cuerpo que enseña el
    #: pectoral y el dorsal a la vez no es un cuerpo, es un diagrama.
    vista: str
    #: Uno o más contornos cerrados. Dos cuando el músculo es par
    #: (izquierda/derecha), que es casi siempre.
    trazos: tuple[tuple[Punto, ...], ...] = field(default_factory=tuple)
    #: Dónde cae la luz dentro del músculo, en coordenadas del lienzo. Es lo
    #: que le da el bulto.
    luz: Punto = (50.0, 50.0)


def _espejo(trazo: tuple[Punto, ...]) -> tuple[Punto, ...]:
    """El mismo contorno al otro lado del eje. Un cuerpo es simétrico y
    escribir las dos mitades a mano es escribir dos veces el mismo error."""
    return tuple((ANCHO - x, y) for x, y in trazo)


# ── Vista frontal ────────────────────────────────────────────────────────

_PECTORAL_IZQ = (
    (49.0, 42.0),
    (41.0, 41.0),
    (35.0, 45.0),
    (34.0, 52.0),
    (37.0, 58.0),
    (44.0, 60.0),
    (49.0, 57.0),
    (49.0, 50.0),
)
_DELTOIDE_IZQ = (
    (35.0, 40.0),
    (29.0, 42.0),
    (25.0, 48.0),
    (25.0, 55.0),
    (30.0, 57.0),
    (34.0, 52.0),
    (36.0, 45.0),
)
_BICEPS_IZQ = (
    (28.0, 57.0),
    (24.0, 61.0),
    (22.0, 69.0),
    (24.0, 77.0),
    (29.0, 77.0),
    (31.0, 69.0),
    (31.0, 61.0),
)
_ANTEBRAZO_IZQ = (
    (25.0, 79.0),
    (21.0, 85.0),
    (20.0, 94.0),
    (21.0, 102.0),
    (26.0, 102.0),
    (27.0, 93.0),
    (28.0, 84.0),
)
_ABDOMEN = (
    (43.0, 62.0),
    (39.0, 66.0),
    (38.0, 78.0),
    (39.0, 90.0),
    (44.0, 96.0),
    (50.0, 97.0),
    (56.0, 96.0),
    (61.0, 90.0),
    (62.0, 78.0),
    (61.0, 66.0),
    (57.0, 62.0),
    (50.0, 61.0),
)
_CUADRICEPS_IZQ = (
    (41.0, 104.0),
    (36.0, 112.0),
    (35.0, 126.0),
    (37.0, 140.0),
    (43.0, 143.0),
    (46.0, 136.0),
    (47.0, 120.0),
    (47.0, 108.0),
)
_GEMELO_IZQ = (
    (39.0, 156.0),
    (36.0, 163.0),
    (36.0, 176.0),
    (39.0, 186.0),
    (44.0, 185.0),
    (45.0, 174.0),
    (45.0, 161.0),
)

# ── Vista trasera ────────────────────────────────────────────────────────

_TRAPECIO = (
    (50.0, 35.0),
    (42.0, 37.0),
    (36.0, 44.0),
    (39.0, 52.0),
    (50.0, 55.0),
    (61.0, 52.0),
    (64.0, 44.0),
    (58.0, 37.0),
)
# El dorsal va a los **lados** y la espalda media al centro, que es donde
# están: solapados, el centro del dorsal caía dentro de la caja de la espalda
# media y tocarlo devolvía el músculo de al lado.
_DORSAL_IZQ = (
    (46.0, 56.0),
    (38.0, 55.0),
    (32.0, 62.0),
    (32.0, 74.0),
    (38.0, 84.0),
    (44.0, 83.0),
    (46.0, 70.0),
)
_ESPALDA_MEDIA = (
    (50.0, 56.0),
    (43.0, 58.0),
    (41.0, 66.0),
    (43.0, 76.0),
    (50.0, 79.0),
    (57.0, 76.0),
    (59.0, 66.0),
    (57.0, 58.0),
)

_LUMBAR = (
    (44.0, 84.0),
    (40.0, 88.0),
    (40.0, 98.0),
    (44.0, 103.0),
    (56.0, 103.0),
    (60.0, 98.0),
    (60.0, 88.0),
    (56.0, 84.0),
)
_TRICEPS_IZQ = (
    (28.0, 56.0),
    (23.0, 60.0),
    (21.0, 69.0),
    (24.0, 77.0),
    (29.0, 76.0),
    (31.0, 68.0),
    (31.0, 60.0),
)
_GLUTEO_IZQ = (
    (48.0, 103.0),
    (41.0, 104.0),
    (36.0, 111.0),
    (37.0, 121.0),
    (44.0, 125.0),
    (48.0, 119.0),
    (49.0, 109.0),
)
_ISQUIO_IZQ = (
    (41.0, 126.0),
    (36.0, 132.0),
    (35.0, 144.0),
    (38.0, 154.0),
    (44.0, 153.0),
    (46.0, 142.0),
    (47.0, 129.0),
)

#: Los trece músculos, con la clave que trae los datos. El orden es el de
#: pintado: de atrás hacia delante, para que un músculo que solape a otro
#: quede encima donde toca.
MUSCULOS: tuple[Musculo, ...] = (
    # Frente
    Musculo(
        "shoulders", "Hombros", "frente", (_DELTOIDE_IZQ, _espejo(_DELTOIDE_IZQ)), luz=(28.0, 48.0)
    ),
    Musculo("chest", "Pecho", "frente", (_PECTORAL_IZQ, _espejo(_PECTORAL_IZQ)), luz=(42.0, 49.0)),
    Musculo("biceps", "Bíceps", "frente", (_BICEPS_IZQ, _espejo(_BICEPS_IZQ)), luz=(23.0, 66.0)),
    Musculo(
        "forearms",
        "Antebrazos",
        "frente",
        (_ANTEBRAZO_IZQ, _espejo(_ANTEBRAZO_IZQ)),
        luz=(20.0, 90.0),
    ),
    Musculo("abdominals", "Abdomen", "frente", (_ABDOMEN,), luz=(50.0, 74.0)),
    Musculo(
        "quadriceps",
        "Cuádriceps",
        "frente",
        (_CUADRICEPS_IZQ, _espejo(_CUADRICEPS_IZQ)),
        luz=(41.0, 122.0),
    ),
    Musculo("calves", "Gemelos", "frente", (_GEMELO_IZQ, _espejo(_GEMELO_IZQ)), luz=(40.0, 173.0)),
    # Espalda
    Musculo("traps", "Trapecio", "espalda", (_TRAPECIO,), luz=(50.0, 46.0)),
    Musculo("lats", "Dorsal", "espalda", (_DORSAL_IZQ, _espejo(_DORSAL_IZQ)), luz=(40.0, 69.0)),
    Musculo("middle back", "Espalda media", "espalda", (_ESPALDA_MEDIA,), luz=(50.0, 62.0)),
    Musculo("lower back", "Lumbar", "espalda", (_LUMBAR,), luz=(50.0, 93.0)),
    Musculo(
        "triceps", "Tríceps", "espalda", (_TRICEPS_IZQ, _espejo(_TRICEPS_IZQ)), luz=(23.0, 66.0)
    ),
    Musculo("glutes", "Glúteos", "espalda", (_GLUTEO_IZQ, _espejo(_GLUTEO_IZQ)), luz=(42.0, 114.0)),
    Musculo(
        "hamstrings", "Isquios", "espalda", (_ISQUIO_IZQ, _espejo(_ISQUIO_IZQ)), luz=(41.0, 142.0)
    ),
)

#: La silueta: cabeza, torso, brazos y piernas, **cada uno su propio trazo**.
#:
#: Empezó siendo un único contorno de 28 puntos que rodeaba todo el cuerpo, y
#: se veía mal por una razón que solo aparece al mirarlo: suavizar un polígono
#: con curvas lo **encoge** hacia dentro, y encoge más donde más cerrado gira.
#: Los brazos, que son la parte estrecha, salían dos píxeles más finos que sus
#: propios músculos — el bíceps flotaba al lado del brazo.
#:
#: Por partes cada pieza se cuadra con lo que lleva dentro, y de paso se lee.
SILUETA: tuple[tuple[Punto, ...], ...] = (
    # Cabeza
    (
        (50.0, 7.0),
        (43.0, 9.0),
        (40.0, 17.0),
        (43.0, 26.0),
        (50.0, 29.0),
        (57.0, 26.0),
        (60.0, 17.0),
        (57.0, 9.0),
    ),
    # Cuello: solapa con la cabeza arriba y con el torso abajo a propósito.
    # Dibujados con hueco entre medias, la cabeza flotaba sobre los hombros.
    ((45.0, 24.0), (44.0, 32.0), (50.0, 38.0), (56.0, 32.0), (55.0, 24.0)),
    # Torso: hombros anchos, cintura estrecha, cadera
    (
        (50.0, 33.0),
        (38.0, 36.0),
        (30.0, 43.0),
        (29.0, 55.0),
        (31.0, 72.0),
        (33.0, 88.0),
        (35.0, 100.0),
        (50.0, 103.0),
        (65.0, 100.0),
        (67.0, 88.0),
        (69.0, 72.0),
        (71.0, 55.0),
        (70.0, 43.0),
        (62.0, 36.0),
    ),
    # Brazo izquierdo: deltoides → bíceps → antebrazo → mano
    (
        (32.0, 42.0),
        (25.0, 45.0),
        (21.0, 54.0),
        (19.0, 64.0),
        (17.0, 76.0),
        (15.0, 90.0),
        (14.0, 102.0),
        (16.0, 108.0),
        (22.0, 108.0),
        (25.0, 100.0),
        (26.0, 86.0),
        (28.0, 72.0),
        (30.0, 60.0),
        (33.0, 50.0),
    ),
    (
        (68.0, 42.0),
        (75.0, 45.0),
        (79.0, 54.0),
        (81.0, 64.0),
        (83.0, 76.0),
        (85.0, 90.0),
        (86.0, 102.0),
        (84.0, 108.0),
        (78.0, 108.0),
        (75.0, 100.0),
        (74.0, 86.0),
        (72.0, 72.0),
        (70.0, 60.0),
        (67.0, 50.0),
    ),
    # Pierna izquierda: muslo, rodilla, gemelo, tobillo
    (
        (36.0, 100.0),
        (32.0, 114.0),
        (31.0, 132.0),
        (33.0, 148.0),
        (34.0, 158.0),
        (33.0, 172.0),
        (34.0, 190.0),
        (35.0, 205.0),
        (43.0, 206.0),
        (45.0, 190.0),
        (46.0, 172.0),
        (47.0, 156.0),
        (48.0, 140.0),
        (49.0, 120.0),
        (49.0, 104.0),
    ),
    (
        (64.0, 100.0),
        (68.0, 114.0),
        (69.0, 132.0),
        (67.0, 148.0),
        (66.0, 158.0),
        (67.0, 172.0),
        (66.0, 190.0),
        (65.0, 205.0),
        (57.0, 206.0),
        (55.0, 190.0),
        (54.0, 172.0),
        (53.0, 156.0),
        (52.0, 140.0),
        (51.0, 120.0),
        (51.0, 104.0),
    ),
)


def de_la_vista(vista: str) -> tuple[Musculo, ...]:
    """Los músculos de una vista, en orden de pintado."""
    return tuple(m for m in MUSCULOS if m.vista == vista)


def por_clave(clave: str) -> Musculo | None:
    for m in MUSCULOS:
        if m.clave == clave:
            return m
    return None


def caja(m: Musculo) -> tuple[float, float, float, float]:
    """`(x0, y0, x1, y1)` que encierra al músculo entero, los dos lados.

    Sirve para colocar una etiqueta o centrar la vista. **No sirve para saber
    qué se ha tocado**: en un músculo par esta caja cruza el torso de lado a
    lado — la del bíceps va de x=22 a x=78 y se traga el abdomen entero. Para
    eso está `cajas()`, y `en_punto` usa esa.
    """
    puntos = [p for trazo in m.trazos for p in trazo]
    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    return (min(xs), min(ys), max(xs), max(ys))


def cajas(m: Musculo) -> tuple[tuple[float, float, float, float], ...]:
    """Una caja **por trazo**: la del brazo izquierdo y la del derecho.

    La diferencia con `caja()` es todo lo que hay entre las dos, que es el
    torso. Tocar el bíceps devolvía «Abdomen» hasta que esto existió, y en la
    pantalla no se nota nada raro — el músculo se pinta bien y responde mal.
    """
    salida = []
    for trazo in m.trazos:
        xs = [p[0] for p in trazo]
        ys = [p[1] for p in trazo]
        salida.append((min(xs), min(ys), max(xs), max(ys)))
    return tuple(salida)


def en_punto(vista: str, x: float, y: float) -> Musculo | None:
    """Qué músculo hay en ese punto del lienzo, o `None`.

    Por caja y no por polígono a propósito: los músculos de una vista no se
    solapan casi nunca, un dedo en un móvil mide unos 9 mm, y un test de
    punto-en-polígono costaría diez veces más código para acertar lo mismo.
    Donde sí se solapan —el trapecio sobre la espalda media— gana **el de caja
    más pequeña**, que es el más específico.
    """
    candidatos = []
    for m in de_la_vista(vista):
        for x0, y0, x1, y1 in cajas(m):
            if x0 <= x <= x1 and y0 <= y <= y1:
                candidatos.append(((x1 - x0) * (y1 - y0), m))
                break
    if not candidatos:
        return None
    return min(candidatos, key=lambda t: t[0])[1]
