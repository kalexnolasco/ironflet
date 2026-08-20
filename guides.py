"""Consejos de referencia dentro de la app: entreno y nutrición.

Consejos cortos y propios, basados en principios generales de fuerza y
nutrición. No derivan de ninguna publicación concreta de terceros.
"""

from __future__ import annotations

GUIDES: dict[str, dict] = {
    "training": {
        "title_key": "Entreno",
        "icon": "🏋️",
        "tips": [
            (
                "Calienta primero",
                "5–10 min de cardio suave más movilidad dinámica para las "
                "articulaciones que vas a entrenar. Nada de estiramientos "
                "estáticos antes de las series pesadas.",
            ),
            (
                "Sobrecarga progresiva",
                "Busca añadir una repetición o un salto pequeño de peso cada "
                "semana cuando llegues al tope del rango con técnica limpia.",
            ),
            (
                "Descansa entre series",
                "60–90 s para hipertrofia (8–12 reps), 2–3 min para fuerza "
                "(4–6 reps). La respiración te dice cuándo empezar la siguiente.",
            ),
            (
                "Técnica antes que ego",
                "Baja el peso antes que perder la técnica. El tempo y el rango "
                "de recorrido construyen más músculo que perseguir un número.",
            ),
            (
                "Apunta cada sesión",
                "Registra peso, repeticiones y sensaciones. Los patrones te "
                "dicen cuándo apretar, descargar o cambiar un ejercicio.",
            ),
            (
                "Descarga cada 4–8 semanas",
                "Baja el volumen un 30–50 % durante una semana. La fatiga se "
                "acumula en silencio — una descarga suele desbloquear un récord "
                "la semana siguiente.",
            ),
            (
                "El sueño es el suplemento",
                "7–9 h de sueño hacen más por la recuperación que cualquier "
                "suplemento legal. Priorízalo antes que los pre-entrenos.",
            ),
        ],
    },
    "nutrition": {
        "title_key": "Nutrición",
        "icon": "🥗",
        "tips": [
            (
                "Objetivo de proteína",
                "1,6–2,2 g/kg de peso corporal si entrenas en serio. Repártela "
                "en 3–5 comidas — 0,3 g/kg por comida es de sobra.",
            ),
            (
                "El balance calórico manda",
                "Ganar músculo: +200 a +500 kcal sobre mantenimiento. "
                "Perder grasa: −300 a −500 kcal por debajo. Todo lo demás es "
                "ajuste fino.",
            ),
            (
                "Carbohidratos alrededor del entreno",
                "El cuerpo aprovecha mejor los carbohidratos en las 2–3 h "
                "alrededor de una sesión dura. Pon ahí la comida más alta en "
                "carbohidratos.",
            ),
            (
                "Grasas para las hormonas",
                "No bajes la grasa de ~0,8 g/kg. La testosterona, los "
                "estrógenos y la recuperación pagan el precio.",
            ),
            (
                "Hidratación",
                "Unos 35 ml por kg de peso, más los días de entreno. La orina "
                "color paja es la comprobación más simple.",
            ),
            (
                "Comida real primero",
                "Llena el 80 % del plato con alimentos poco procesados. Los "
                "suplementos son extras, no sustitutos.",
            ),
            (
                "La paciencia gana a la perfección",
                "Elige un plan que puedas sostener 6 meses. La dieta «perfecta» "
                "que abandonas en 3 semanas pierde contra la decente que mantienes.",
            ),
        ],
    },
}


def guide_ids() -> list[str]:
    return list(GUIDES.keys())


def guide_icon(gid: str) -> str:
    return GUIDES[gid]["icon"]


def guide_title_key(gid: str) -> str:
    return GUIDES[gid]["title_key"]


def guide_tips(gid: str) -> list[tuple[str, str]]:
    g = GUIDES.get(gid)
    return g["tips"] if g else []
