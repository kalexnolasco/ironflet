"""In-app reference tips for training, nutrition, and women-fitness.

Short, original tips based on general strength-training / nutrition principles.
Not derived from any specific third-party publication.
"""

from __future__ import annotations

GUIDES: dict[str, dict] = {
    "training": {
        "title_key": "Training",
        "icon": "🏋️",
        "tips": [
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
    },
    "nutrition": {
        "title_key": "Nutrition",
        "icon": "🥗",
        "tips": [
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
    },
    "women": {
        "title_key": "Women Fitness",
        "icon": "💪",
        "tips": [
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
