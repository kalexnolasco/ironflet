"""In-app reference tips for training, nutrition, and women-fitness.

Short, original tips based on general strength-training / nutrition principles.
Not derived from any specific third-party publication.
"""

from __future__ import annotations

GUIDES: dict[str, dict] = {
    "training": {
        "title_key": "Training",
        "icon": "🏋️",
        "tips": {
            "en": [
                (
                    "Warm up first",
                    "5–10 min of light cardio plus dynamic mobility for the "
                    "joints you will train. Skip static stretching before heavy sets.",
                ),
                (
                    "Progressive overload",
                    "Aim to add a rep or a small weight jump each week when you "
                    "hit the top of the rep range with clean form.",
                ),
                (
                    "Rest between sets",
                    "60–90 s for hypertrophy (8–12 reps), 2–3 min for strength "
                    "(4–6 reps). Your breath tells you when to start the next set.",
                ),
                (
                    "Form over ego",
                    "Lower the weight rather than lose technique. Tempo and range of "
                    "motion drive growth more than chasing a number.",
                ),
                (
                    "Track every session",
                    "Log weight, reps and RPE. Patterns tell you when to push, "
                    "deload or change an exercise.",
                ),
                (
                    "Deload every 4–8 weeks",
                    "Drop volume by 30–50 % for one week. Fatigue accumulates silently "
                    "— deloads often unlock a new PR the week after.",
                ),
                (
                    "Sleep is the supplement",
                    "7–9 h of sleep does more for recovery than any legal supplement. "
                    "Prioritise it before pre-workouts.",
                ),
            ],
            "es": [
                (
                    "Calienta primero",
                    "5–10 min de cardio suave y movilidad dinámica en las "
                    "articulaciones que vas a trabajar. Evita estiramientos estáticos "
                    "antes de series pesadas.",
                ),
                (
                    "Sobrecarga progresiva",
                    "Intenta sumar una repetición o un salto pequeño de peso cada "
                    "semana cuando llegues al tope del rango con técnica limpia.",
                ),
                (
                    "Descanso entre series",
                    "60–90 s para hipertrofia (8–12 reps), 2–3 min para fuerza "
                    "(4–6 reps). Tu respiración te dice cuándo empezar la siguiente.",
                ),
                (
                    "Técnica antes que ego",
                    "Baja el peso antes que perder forma. El tempo y el rango "
                    "de movimiento hacen crecer más que el número en la barra.",
                ),
                (
                    "Registra cada sesión",
                    "Anota peso, reps y RPE. Los patrones te dicen cuándo apretar, "
                    "descargar o cambiar ejercicio.",
                ),
                (
                    "Descarga cada 4–8 semanas",
                    "Baja el volumen 30–50 % durante una semana. La fatiga acumulada "
                    "suele desbloquear un PR la semana siguiente.",
                ),
                (
                    "Dormir es el suplemento",
                    "7–9 h de sueño hacen más por la recuperación que cualquier "
                    "suplemento legal. Prioriza esto antes que los pre-entrenos.",
                ),
            ],
        },
    },
    "nutrition": {
        "title_key": "Nutrition",
        "icon": "🥗",
        "tips": {
            "en": [
                (
                    "Protein target",
                    "1.6–2.2 g/kg of bodyweight if you lift seriously. Spread it across "
                    "3–5 meals — 0.3 g/kg per meal is plenty.",
                ),
                (
                    "Calorie balance rules",
                    "Muscle gain: +200 to +500 kcal over maintenance. "
                    "Fat loss: −300 to −500 kcal under maintenance. Everything else "
                    "is fine-tuning.",
                ),
                (
                    "Carbs around training",
                    "Your body uses carbs best on the 2–3 h around a hard session. "
                    "Plan the biggest carb meal there.",
                ),
                (
                    "Fats for hormones",
                    "Don't drop fat below ~0.8 g/kg. Testosterone, estrogen and "
                    "recovery all pay the price.",
                ),
                (
                    "Hydration",
                    "Roughly 35 ml per kg of bodyweight, more on training days. "
                    "Straw-coloured urine is the simplest check.",
                ),
                (
                    "Whole foods first",
                    "Fill 80 % of the plate with minimally-processed foods. "
                    "Supplements are extras, not substitutes.",
                ),
                (
                    "Patience beats perfection",
                    "Pick a plan you can sustain 6 months. The ‘perfect’ diet you "
                    "abandon in 3 weeks beats nothing, but loses to the decent one you keep.",
                ),
            ],
            "es": [
                (
                    "Objetivo de proteína",
                    "1,6–2,2 g/kg de peso si entrenas en serio. Repártela en "
                    "3–5 comidas — 0,3 g/kg por comida es suficiente.",
                ),
                (
                    "Balance calórico manda",
                    "Ganar músculo: +200 a +500 kcal sobre mantenimiento. "
                    "Perder grasa: −300 a −500 kcal. Lo demás es ajuste fino.",
                ),
                (
                    "Carbos cerca del entrenamiento",
                    "El cuerpo aprovecha mejor los carbos 2–3 h alrededor de una "
                    "sesión dura. Coloca ahí la comida de carbos más grande.",
                ),
                (
                    "Grasas para las hormonas",
                    "No bajes las grasas de ~0,8 g/kg. Testosterona, estrógenos y "
                    "recuperación lo pagan.",
                ),
                (
                    "Hidratación",
                    "Unos 35 ml por kg de peso, más los días de entrenamiento. "
                    "El color de la orina (pajizo claro) es el indicador fácil.",
                ),
                (
                    "Comida real primero",
                    "Llena el 80 % del plato con alimentos mínimamente procesados. "
                    "Los suplementos son extras, no sustitutos.",
                ),
                (
                    "La paciencia gana",
                    "Elige una dieta que puedas mantener 6 meses. La ‘perfecta’ que "
                    "abandonas en 3 semanas pierde contra la decente que mantienes.",
                ),
            ],
        },
    },
    "women": {
        "title_key": "Women Fitness",
        "icon": "💪",
        "tips": {
            "en": [
                (
                    "Lifting heavy doesn't 'bulk'",
                    "Adding visible size takes years and hormones you don't have. "
                    "Heavy compound lifts shape more than they enlarge.",
                ),
                (
                    "Glutes grow with hinge + stretch",
                    "Romanian deadlifts, hip thrusts, deep lunges and split squats "
                    "hit the glutes where they respond best.",
                ),
                (
                    "Track the full cycle",
                    "Strength often peaks in the follicular phase (days 1–14) and dips "
                    "pre-period. Log workouts alongside your cycle and plan heavy sessions "
                    "on your strong days.",
                ),
                (
                    "Don't fear the scale jump",
                    "Water retention, glycogen and muscle all add weight without adding fat. "
                    "Trust the mirror and the tape measure over a 1-day scale reading.",
                ),
                (
                    "Protein is not optional",
                    "1.6–2.2 g/kg still applies. Under-eating protein is the most common "
                    "reason a program stalls.",
                ),
                (
                    "Strength floor over cardio",
                    "Cardio supports the goal; strength training builds the shape. "
                    "Two to four strength sessions per week is the minimum.",
                ),
                (
                    "Rest is training",
                    "Muscle adapts between sessions, not during. One or two full rest days "
                    "per week are non-negotiable.",
                ),
            ],
            "es": [
                (
                    "Levantar pesado no ‘infla’",
                    "Ganar volumen visible lleva años y hormonas que no tienes. Los "
                    "básicos pesados moldean más de lo que agrandan.",
                ),
                (
                    "El glúteo crece con bisagra + estiramiento",
                    "Peso muerto rumano, hip thrust, zancadas profundas y split squats "
                    "atacan el glúteo donde mejor responde.",
                ),
                (
                    "Registra el ciclo completo",
                    "La fuerza suele picar en la fase folicular (días 1–14) y baja "
                    "antes del periodo. Anota entrenos junto al ciclo y coloca sesiones "
                    "pesadas en tus días fuertes.",
                ),
                (
                    "No temas un salto en la báscula",
                    "Agua, glucógeno y músculo suman peso sin sumar grasa. Confía en "
                    "el espejo y la cinta antes que en una lectura de un día.",
                ),
                (
                    "La proteína no es opcional",
                    "1,6–2,2 g/kg también aquí. Comer poca proteína es el motivo "
                    "más común de que un plan se estanque.",
                ),
                (
                    "Fuerza base, cardio apoyo",
                    "El cardio ayuda, la fuerza da forma. Dos a cuatro sesiones de "
                    "pesas por semana es el mínimo.",
                ),
                (
                    "El descanso también entrena",
                    "El músculo se adapta entre sesiones, no durante. Uno o dos días "
                    "completos de descanso por semana son innegociables.",
                ),
            ],
        },
    },
}


def guide_ids() -> list[str]:
    return list(GUIDES.keys())


def guide_icon(gid: str) -> str:
    return GUIDES[gid]["icon"]


def guide_title_key(gid: str) -> str:
    return GUIDES[gid]["title_key"]


def guide_tips(gid: str, lang: str) -> list[tuple[str, str]]:
    g = GUIDES.get(gid)
    if not g:
        return []
    return g["tips"].get(lang) or g["tips"].get("en") or []
