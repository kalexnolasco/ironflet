"""El sábado y el domingo: qué comprar y qué cocinar.

Alex lo describió como su rutina, literal: «mañana sábado haré las compras
para la semana y el domingo realizaremos todas las preparaciones, quiero que
el agente me ayude a ello». La app ya sabía qué come — `nutrition.TEMPLATE_DAY`
lleva el menú del plan con sus gramos — y sabía cuántas calorías busca. Lo que
faltaba era juntarlo: multiplicar por siete, agrupar por alimento y decirlo en
unidades de supermercado.

## Lo que este módulo NO hace

**No inventa un menú.** Sale del que ya está en `nutrition.py`, que a su vez
sale de la sección 4 del plan. Si el menú cambia, la compra cambia sola; no hay
una segunda copia de qué come Alex.

**No decide macros.** Lee los objetivos vigentes con `targets_for()` — los que
el coach pudo haber cambiado el lunes — y escala. Un plan de compra que ignore
un cambio de objetivos manda a comprar la semana anterior.

## Por qué las secciones están escritas a mano

Se puede deducir el macro dominante de un alimento y agrupar por ahí, y sería
automático y no haría falta mantenerlo. Y estaría mal: el plátano y el arroz
son los dos hidratos y están en pasillos distintos. **Una lista de la compra se
ordena por dónde están las cosas en la tienda**, que es un hecho del mundo y no
de la tabla nutricional. De ahí `_SECCION`, con «Otros» para lo que no conozca.

## El escalado, y su límite

Escalar la plantilla entera por el ratio de calorías es lo simple y es lo que
se hace — pero el plan dice explícitamente qué recortar cuando hay que bajar
(«el aceite de la cena, nunca la proteína»). Así que el escalado **respeta la
proteína**: los alimentos proteicos se dejan intactos y el ajuste recae sobre
los demás. Cuando ni así se llega, `Compra.aviso` lo dice en vez de callarse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

#: En qué parte del supermercado está cada cosa, en el orden en que se recorre.
#: Escrito a mano a propósito — ver el docstring del módulo.
_SECCION: dict[str, str] = {
    # Frescos: proteína
    "chicken_breast": "Carnicería y pescadería",
    "turkey_breast": "Carnicería y pescadería",
    "beef_mince_5": "Carnicería y pescadería",
    "pork_loin": "Carnicería y pescadería",
    "salmon": "Carnicería y pescadería",
    "tuna_canned": "Despensa",
    "cod": "Carnicería y pescadería",
    "eggs": "Frescos",
    # Lácteos
    "skyr": "Frescos",
    "milk_semi": "Frescos",
    "yogurt_natural": "Frescos",
    "cottage_cheese": "Frescos",
    "cheese_fresh": "Frescos",
    # Fruta y verdura
    "banana": "Fruta y verdura",
    "apple": "Fruta y verdura",
    "orange": "Fruta y verdura",
    "berries": "Fruta y verdura",
    "vegetables_mixed": "Fruta y verdura",
    "potato": "Fruta y verdura",
    "sweet_potato": "Fruta y verdura",
    "tomato": "Fruta y verdura",
    "avocado": "Fruta y verdura",
    "spinach": "Fruta y verdura",
    # Despensa
    "oats": "Despensa",
    "rice_white": "Despensa",
    "rice_brown": "Despensa",
    "pasta": "Despensa",
    "bread_wholemeal": "Despensa",
    "lentils": "Despensa",
    "chickpeas": "Despensa",
    "beans_black": "Despensa",
    "olive_oil": "Despensa",
    "walnuts": "Despensa",
    "almonds": "Despensa",
    "peanut_butter": "Despensa",
    "honey": "Despensa",
    "whey_protein": "Despensa",
}

#: El orden del recorrido. Lo que no esté en `_SECCION` cae en «Otros», al
#: final, que es donde uno vuelve a por lo que se le olvidó.
ORDEN_SECCIONES: tuple[str, ...] = (
    "Fruta y verdura",
    "Carnicería y pescadería",
    "Frescos",
    "Despensa",
    "Otros",
)

#: Un alimento cuenta como proteico si más de un tercio de sus calorías lo son.
#: Es la frontera que separa lo que el escalado no toca de lo que sí.
_UMBRAL_PROTEICO = 0.33

#: Por debajo de esto no se escala nada: recortar un 3 % de la compra semanal
#: no cambia nada y sí llena la lista de cifras raras.
_ESCALADO_MINIMO = 0.05

#: Y por debajo de ESTE factor ya no se escala: se avisa. Recortar los hidratos
#: a menos de la mitad no es ajustar el menú del plan, es cocinar otro menú, y
#: la lista saldría con «63 g de manzana para la semana». El módulo sabe hacer
#: una regla de tres; lo que no puede es rediseñar la dieta.
_FACTOR_MINIMO = 0.5


#: Lo que se vende por volumen, y su densidad en g/ml. La tabla nutricional
#: está en gramos porque las etiquetas europeas lo están — la propia plantilla
#: escribe `258.0,  # 250 ml`. Pero **la leche no se compra en kilos**: en la
#: pantalla salía «Leche semidesnatada 1,81 kg», que es correcto y no lo dice
#: nadie en una tienda. Aquí se deshace esa conversión para escribirlo.
_LIQUIDOS: dict[str, float] = {
    "milk_semi": 1.03,
    "olive_oil": 0.916,
}


@dataclass(frozen=True)
class Articulo:
    """Un alimento y cuánto hace falta para la semana."""

    slug: str
    nombre: str
    gramos: float
    seccion: str
    #: g/ml cuando se compra por volumen; 0 cuando se compra por peso.
    densidad: float = 0.0

    def cantidad(self) -> str:
        """La cantidad como se lee en una lista: «1,05 kg», «280 g», «1,75 l».

        Coma decimal aquí y punto en el resto de la app es deliberado: un kilo
        con cinco decimales no se lee, y esta es la única pantalla donde la
        cifra se escribe para copiarla a mano en una tienda.
        """
        if self.densidad > 0:
            ml = self.gramos / self.densidad
            if ml >= 1000:
                return _con_coma(ml / 1000) + " l"
            return f"{round(ml):g} ml"
        if self.gramos >= 1000:
            return _con_coma(self.gramos / 1000) + " kg"
        return f"{round(self.gramos):g} g"


def _con_coma(valor: float) -> str:
    """`1.05` → `"1,05"`, `1.40` → `"1,4"`, `2.00` → `"2"`."""
    return f"{valor:.2f}".rstrip("0").rstrip(".").replace(".", ",")


@dataclass(frozen=True)
class Compra:
    """La lista de la semana, ya agrupada y ordenada por el recorrido."""

    articulos: tuple[Articulo, ...]
    dias: int
    kcal_objetivo: float
    factor: float
    aviso: str = ""

    def por_seccion(self) -> list[tuple[str, list[Articulo]]]:
        """`[(sección, artículos)]` en el orden en que se recorre la tienda."""
        agrupado: dict[str, list[Articulo]] = {}
        for art in self.articulos:
            agrupado.setdefault(art.seccion, []).append(art)
        return [(s, agrupado[s]) for s in ORDEN_SECCIONES if s in agrupado]


@dataclass(frozen=True)
class Tarea:
    """Un paso de la preparación del domingo."""

    titulo: str
    detalle: str
    minutos: int
    #: Qué hacer con lo que no llega al domingo siguiente. Vacío si aguanta.
    conservacion: str = ""


@dataclass(frozen=True)
class Preparacion:
    """El domingo: qué cocinar, cuánto y en qué orden."""

    tareas: tuple[Tarea, ...]
    dias: int
    consejo: str = ""
    #: Minutos de reloj, no la suma de los pasos: el arroz hierve mientras el
    #: pollo está en el horno.
    minutos_totales: int = 0
    #: La advertencia de conservación que valdría para casi todo, dicha una
    #: sola vez. En la pantalla, la misma frase repetida en cuatro de cinco
    #: tarjetas ocupaba media pantalla y dejaba de leerse — incluida la única
    #: que era distinta, la del salmón. Lo que se repite se dice arriba; en la
    #: tarjeta solo queda lo que se sale de la norma.
    conservacion_comun: str = ""


def _plantilla(store: Any) -> tuple[tuple[str, str, float], ...]:
    from nutrition import TEMPLATE_DAY

    return TEMPLATE_DAY


def _catalogo() -> dict[str, Any]:
    from nutrition import SEED_FOODS

    return {f.slug: f for f in SEED_FOODS}


def _es_proteico(comida: Any) -> bool:
    kcal = float(getattr(comida, "kcal", 0) or 0)
    if kcal <= 0:
        return False
    return (float(getattr(comida, "protein", 0) or 0) * 4) / kcal >= _UMBRAL_PROTEICO


def lista_de_la_compra(store: Any, dias: int = 7, hoy: date | None = None) -> Compra:
    """Lo que hay que comprar para `dias` días del menú del plan.

    Escala a los objetivos vigentes respetando la proteína: si hay que quitar
    calorías, salen de los hidratos y las grasas, que es lo que dice el plan.
    """
    catalogo = _catalogo()
    dia = hoy or date.today()

    # Cuántas calorías pide el objetivo de hoy, y cuántas trae la plantilla.
    objetivo = 0.0
    try:
        from nutrition import targets_for

        objetivo = float((targets_for(store, dia) or {}).get("kcal") or 0)
    except Exception:
        pass

    gramos: dict[str, float] = {}
    for _comida, slug, g in _plantilla(store):
        gramos[slug] = gramos.get(slug, 0.0) + float(g)

    kcal_plantilla = sum(
        (gramos[s] / 100) * float(getattr(catalogo[s], "kcal", 0) or 0)
        for s in gramos
        if s in catalogo
    )

    factor = 1.0
    aviso = ""
    if objetivo > 0 and kcal_plantilla > 0:
        desvio = abs(objetivo - kcal_plantilla) / kcal_plantilla
        if desvio > _ESCALADO_MINIMO:
            # Las proteicas no se tocan; el ajuste entero recae sobre el resto.
            kcal_prot = sum(
                (gramos[s] / 100) * float(getattr(catalogo[s], "kcal", 0) or 0)
                for s in gramos
                if s in catalogo and _es_proteico(catalogo[s])
            )
            kcal_resto = kcal_plantilla - kcal_prot
            margen = objetivo - kcal_prot
            factor = (margen / kcal_resto) if (kcal_resto > 0 and margen > 0) else 0.0
            if factor < _FACTOR_MINIMO:
                # Dos casos, un solo mensaje: o el objetivo no llega ni para la
                # proteína del menú, o llega tan justo que lo demás habría que
                # recortarlo a menos de la mitad. En ambos la respuesta honesta
                # es la misma — recortar proteína para cuadrar calorías es lo
                # que el plan prohíbe, y este módulo no rediseña la dieta.
                factor = _FACTOR_MINIMO
                aviso = (
                    f"Con {round(objetivo)} kcal no sale este menú: habría que recortar "
                    "más de la mitad de los hidratos. La lista va al mínimo razonable — "
                    "habla con el entrenador antes de comprar así."
                )

    articulos = []
    for slug, g in gramos.items():
        comida = catalogo.get(slug)
        if comida is None:
            continue
        escala = 1.0 if _es_proteico(comida) else factor
        articulos.append(
            Articulo(
                slug=slug,
                nombre=str(getattr(comida, "name", slug)),
                gramos=g * escala * dias,
                seccion=_SECCION.get(slug, "Otros"),
                densidad=_LIQUIDOS.get(slug, 0.0),
            )
        )

    # Dentro de su sección, por nombre: es como se busca en un papel.
    orden = {s: i for i, s in enumerate(ORDEN_SECCIONES)}
    articulos.sort(key=lambda a: (orden.get(a.seccion, 99), a.nombre))

    return Compra(
        articulos=tuple(articulos),
        dias=dias,
        kcal_objetivo=objetivo,
        factor=factor,
        aviso=aviso,
    )


#: Cómo se cocina cada cosa a granel, cuánto tarda y **cuántos días aguanta en
#: la nevera**. Ese tercer número es el que hace honesto el plan: sin él, el
#: domingo mandaba cocinar salmón para comerlo el sábado siguiente. Lo que no
#: llega a la semana se cocina a medias y se congela, y la tarea lo dice.
#: Solo lo que se prepara por lotes: la fruta no se cocina y el skyr sale de la
#: nevera tal cual.
_COCINADO: dict[str, tuple[str, int, int]] = {
    "rice_white": ("Arroz — hervir y enfriar rápido para repartir", 35, 4),
    "rice_brown": ("Arroz integral — hervir y enfriar rápido", 45, 4),
    "pasta": ("Pasta — al dente, se termina de hacer al recalentar", 20, 4),
    "chicken_breast": ("Pollo al horno — 200 °C, dar la vuelta a mitad", 40, 4),
    "turkey_breast": ("Pavo — se compra hecho, solo repartir", 5, 7),
    "salmon": ("Salmón al horno — 180 °C, con limón", 25, 2),
    "potato": ("Patata — al horno con la piel o cocida", 45, 4),
    "sweet_potato": ("Boniato — al horno", 45, 4),
    "vegetables_mixed": ("Verdura — saltear o al horno con aceite", 20, 4),
    "lentils": ("Lentejas — remojo la noche antes", 60, 5),
    "chickpeas": ("Garbanzos — remojo la noche antes", 60, 5),
    "eggs": ("Huevos cocidos — 10 min desde que hierve", 15, 7),
}


def plan_de_preparacion(store: Any, dias: int = 7, hoy: date | None = None) -> Preparacion:
    """El domingo: qué cocinar, en qué cantidad y en qué orden.

    El orden no es arbitrario: **lo que más tarda primero**, porque el horno y
    el fuego trabajan solos mientras se prepara lo siguiente. Por eso los
    minutos totales no son la suma de los pasos.
    """
    compra = lista_de_la_compra(store, dias=dias, hoy=hoy)

    crudas: list[tuple[str, str, int, str]] = []
    for art in compra.articulos:
        receta = _COCINADO.get(art.slug)
        if receta is None:
            continue
        titulo, minutos, aguanta = receta
        nota = ""
        if aguanta < dias:
            sobran = dias - aguanta
            nota = (
                f"Aguanta {aguanta} días en nevera: congela lo de los {sobran} últimos"
                if aguanta > 2
                else f"Solo aguanta {aguanta} días: cocina para {aguanta} y congela el resto crudo"
            )
        crudas.append((titulo, f"{art.cantidad()} · {art.nombre}", minutos, nota))

    # La nota que le toca a la mayoría se dice una vez arriba; en las tarjetas
    # solo se queda la que dice algo distinto. Umbral en la mitad: con dos de
    # cinco repetidas la repetición todavía no molesta, y sacarlas arriba
    # obligaría a mirar dos sitios para saber qué pasa con una.
    comun = ""
    notas = [n for _t, _d, _m, n in crudas if n]
    if len(notas) > len(crudas) / 2:
        comun = max(set(notas), key=notas.count)

    tareas = [
        Tarea(
            titulo=titulo,
            detalle=detalle,
            minutos=minutos,
            conservacion="" if nota == comun else nota,
        )
        for titulo, detalle, minutos, nota in crudas
    ]

    tareas.sort(key=lambda t: -t.minutos)
    if tareas:
        tareas.append(
            Tarea(
                titulo=f"Repartir en túpers — {dias} días",
                detalle="Etiqueta cada uno con su día antes de meterlo en la nevera",
                minutos=15,
            )
        )

    # Reloj, no suma: el más largo marca el ritmo y el resto cabe dentro. Se
    # suma un cuarto de los demás como margen de trasteo, que es más honesto
    # que prometer que todo sale en paralelo perfecto.
    if tareas:
        mayor = max(t.minutos for t in tareas)
        resto = sum(t.minutos for t in tareas) - mayor
        total = mayor + round(resto * 0.25)
    else:
        total = 0

    consejo = ""
    if tareas:
        consejo = f"Empieza por «{tareas[0].titulo.split(' — ')[0]}»: mientras se hace, entra lo siguiente."

    return Preparacion(
        tareas=tuple(tareas),
        dias=dias,
        consejo=consejo,
        minutos_totales=total,
        conservacion_comun=comun,
    )


def es_dia_de_compra(hoy: date | None = None) -> bool:
    """Sábado. El día que Alex dijo que compra."""
    return (hoy or date.today()).weekday() == 5


def es_dia_de_prep(hoy: date | None = None) -> bool:
    """Domingo. El día que Alex dijo que cocina."""
    return (hoy or date.today()).weekday() == 6
