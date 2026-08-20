"""
CambiaTuFísico routine data.
7 phases, 24 weeks of periodized training.

All strings are canonical English; there is no translation layer.
Exercise name (without any [..] bracket) is the DB key in storage.
"""

from dataclasses import dataclass


@dataclass
class Phase:
    id: int
    weeks: str
    name: str
    subtitle: str
    color: str
    scheme: str
    rest: str
    notes: str
    freq: str  # "high" or "low"


@dataclass
class TrainingDay:
    name: str
    exercises: list[str]


PHASES: list[Phase] = [
    Phase(
        1,
        "1-3",
        "Acondicionamiento",
        "Hipertrofia",
        "#00D4AA",
        "3×12",
        "1' sets / 2-3' exercises",
        "Sin fallo absoluto. 20' de cardio continuo tras las pesas. Abdomen 2 días/semana.",
        "high",
    ),
    Phase(
        2,
        "4-6",
        "Hipertrofia total",
        "Fallo muscular",
        "#FF6B35",
        "3×8-10",
        "1'30\" sets (max 2')",
        "Fallo en la última serie. Mismos ejercicios. 20' de cardio. Abdomen más intenso.",
        "high",
    ),
    Phase(
        3,
        "7-9",
        "Hipertrofia funcional",
        "Fuerza + hipertrofia",
        "#7C5CFC",
        "4×5-6 (*=3×8)",
        "2-2'30\" / 3' ex. / 1' on *",
        "Sube las cargas. *= 3×8 al fallo. 20' de cardio. Abdomen 5×8-12.",
        "high",
    ),
    Phase(
        4,
        "10",
        "Descarga",
        "Recuperación",
        "#FFD93D",
        "3-4×12",
        "1' sets / 2' exercises",
        "Intensidad baja, sin fallo. 3 días de cuerpo entero.",
        "low",
    ),
    Phase(
        5,
        "11-14",
        "Hipertrofia Weider",
        "Volumen alto",
        "#FF3366",
        "Ascending Pyramid",
        "1'30\" sets / 3' exercises",
        "5 días, 1 músculo/día. Fallo en todas las series menos la primera.",
        "low",
    ),
    Phase(
        6,
        "15-18",
        "Alta intensidad",
        "Drop sets + compuestos",
        "#FF8A5C",
        "Drop sets (e.g.: 10,8,6+12↓)",
        "1' sets / 3' exercises",
        "Drop sets en la última serie. 5' de cinta antes de las pesas.",
        "low",
    ),
    Phase(
        7,
        "19-24",
        "Definición",
        "Bi-series / superseries",
        "#4ECDC4",
        "BI 4×8+10 / SS 4×10+10",
        "Min. between blocks, 1-1'30\"",
        "Semanas 1-3: bi-series. Semanas 4-6: superseries antagonistas.",
        "high",
    ),
]


# ─── Exercises by phase ──────────────────────────────────────────────

DAYS_PHASE_1_3: list[TrainingDay] = [
    TrainingDay(
        "Chest - Biceps",
        [
            "Smith Bench Press",
            "Incline DB Flyes",
            "Incline DB Press",
            "Pec Deck *",
            "Straight Bar Curl",
            "EZ Bar Preacher Curl",
            "Alternate Hammer Curl *",
        ],
    ),
    TrainingDay(
        "Back - Triceps",
        [
            "Front Lat Pulldown",
            "DB Row",
            "Behind-Neck Lat Pulldown",
            "Seated Cable Row *",
            "EZ Bar Skull Crushers",
            "Smith Close-Grip Press",
            "Rope Pushdown *",
        ],
    ),
    TrainingDay(
        "Shoulder - Leg",
        [
            "Seated DB Press",
            "Arnold Press *",
            "Lateral Raises",
            "Standing Rear Delts",
            "Leg Extensions *",
            "Leg Press",
            "Romanian Deadlift",
            "Lying Leg Curl *",
            "Lunges",
            "Standing Calf Raise",
            "Seated Calf Raise *",
        ],
    ),
]

DAYS_PHASE_4: list[TrainingDay] = [
    TrainingDay(
        "Day 1 Full Body",
        [
            "Barbell Bench Press",
            "Front Lat Pulldown",
            "DB Shoulder Press",
            "Barbell Curl",
            "Triceps Pushdown",
            "Squat",
        ],
    ),
    TrainingDay(
        "Day 2 Full Body",
        [
            "Incline DB Press",
            "Barbell Row",
            "Arnold Press",
            "Alternate DB Curl",
            "Rope Pushdown",
            "Romanian Deadlift",
        ],
    ),
    TrainingDay(
        "Day 3 Full Body",
        [
            "Machine Flyes",
            "Seated Cable Row",
            "Lateral Raises",
            "Hammer Curl",
            "Skull Crushers",
            "DB Lunges",
        ],
    ),
]

DAYS_PHASE_5: list[TrainingDay] = [
    TrainingDay(
        "D1: Chest + Abs",
        [
            "Barbell Bench Press [5×12,10,8,8,8]",
            "Pec Deck [4×10,10,8,8]",
            "Incline Machine Press [4×10,8,8,8]",
            "Cable Crossover [4×12,12,10,10]",
            "Hanging Abs [5×max]",
            "Cable Crunch [5×15,15,12,12,12]",
        ],
    ),
    TrainingDay(
        "D2: Back + Abs",
        [
            "Pull-ups [5×12,10,10,10,8]",
            "Barbell Row [4×10,8,8,8]",
            "V-Grip Lat Pulldown [4×10,8,8,8]",
            "T-Bar Row [4×10,10,8,8]",
            "Deadlift [3×12]",
            "Abs Triset [4×(20+20+20)]",
        ],
    ),
    TrainingDay(
        "D3: Leg",
        [
            "Squat [5×12,10,10,8,8]",
            "Leg Extensions [4×10,8,8,8]",
            "Lying Leg Curl [4×8,8,6,6]",
            "Seated Leg Curl [4×10,10,8,8]",
            "Barbell Lunges [4×10]",
            "Calf Press [3×15,12,12]",
            "Seated Calf Raise [3×15,12,12]",
        ],
    ),
    TrainingDay(
        "D4: Shoulder + Abs",
        [
            "Barbell Military Press [5×12,10,10,8,8]",
            "Plate Front Raises [4×10]",
            "Machine Lateral Raises [4×10,8,8,8]",
            "Cable Rear Delts [4×10,8,8,8]",
            "Hanging Abs [5×max]",
            "Cable Crunch [5×15,15,12,12,12]",
        ],
    ),
    TrainingDay(
        "D5: Arms + Abs",
        [
            "EZ Bar Curl [4×10,8,8,8]",
            "Simultaneous DB Curl [4×10,8,8,8]",
            "Cable Curl [3×10]",
            "Reverse Curl [3×10]",
            "Parallel Bar Dips [5×12,10,8,8,8]",
            "EZ Bar Skull Crushers [3×10,8,8]",
            "Triceps Pushdown [3×10,8,8]",
            "Reverse Pushdown [3×10]",
        ],
    ),
]

DAYS_PHASE_6: list[TrainingDay] = [
    TrainingDay(
        "D1: Chest + Abs A",
        [
            "Barbell Bench Press [4×10,10,8,6+12↓]",
            "Pec Deck [3×10,10,6+12↓]",
            "Incline Machine Press [3×10,8,6+12↓]",
            "Cable Crossover [3×10,10,8+12↓]",
            "Push-ups [3×failure]",
        ],
    ),
    TrainingDay(
        "D2: Back + Abs B",
        [
            "Pull-ups [4×12,10,10,8]",
            "Barbell Row [4×10,10,8,6+12↓]",
            "V-Pulldown + V-Row [comp] [4×8+8]",
            "Deadlift [4×10,10,10,8+12↓]",
        ],
    ),
    TrainingDay(
        "D3: Leg",
        [
            "Squat [4×10,10,10,6+12↓]",
            "Leg Extensions [3×10,10,6+12↓]",
            "Lying + Seated Leg Curl [comp] [4×10+10]",
            "Barbell Lunges [3×10,10,6+12↓]",
            "Calf Press + Seated [comp] [4×12+12]",
        ],
    ),
    TrainingDay(
        "D4: Shoulder + Abs A",
        [
            "Barbell Military Press [4×10,8,8,6+12↓]",
            "Plate Front Raises [3×10,8+12↓,8+12↓]",
            "Machine Lateral Raises [3×10,8+12↓,8+12↓]",
            "Cable Rear Delts [3×10,8+12↓,8+12↓]",
        ],
    ),
    TrainingDay(
        "D5: Arms + Abs B",
        [
            "EZ Bar Curl [3×10,8,8+12↓]",
            "DB Curl [3×10,8,8+12↓]",
            "Cable Curl [triple drop] [2×10+10+10]",
            "Reverse Curl [3×10,10,8+12↓]",
            "Skull Crushers + Close-Grip [comp] [4×10+10]",
            "Triceps Pushdown [3×10,8,6+12↓]",
            "Reverse Pushdown [3×10,8,8+12↓]",
        ],
    ),
]

DAYS_PHASE_7: list[TrainingDay] = [
    # Weeks 1-3: Bi-sets (same muscle group)
    TrainingDay(
        "W1-3: Chest-Biceps",
        [
            "Bi-set: Incline DB Press + Flat Machine Press [4×8+10]",
            "Bi-set: Incline Flyes + Machine Flyes [3×8+10]",
            "Bi-set: Decline Press + Push-ups [3×8+failure]",
            "Bi-set: Barbell Curl + Simultaneous DB Curl [4×8+10]",
            "Bi-set: EZ Preacher + Hammer Curl [4×8+10]",
        ],
    ),
    TrainingDay(
        "W1-3: Back-Triceps",
        [
            "Bi-set: Front + Behind-Neck Pulldown [4×8+10]",
            "Bi-set: V-Pulldown + Seated Row [3×8+10]",
            "Bi-set: Machine Row + Reverse Barbell Row [3×8+10]",
            "Bi-set: Dips + Triceps Pushdown [4×8+10]",
            "Bi-set: Barbell + DB Skull Crushers [4×8+10]",
        ],
    ),
    TrainingDay(
        "W1-3: Shoulder-Leg",
        [
            "Bi-set: DB Press + Arnold Press [4×8+10]",
            "Triset: Front + Lateral + Rear Delts [4×10+10+10]",
            "Bi-set: Leg Press + Extensions [4×10+10]",
            "Bi-set: Romanian DL + Lying Leg Curl [4×10+10]",
            "Triset: Lunges + Seated + Standing Calf [4×10+10+10]",
        ],
    ),
    # Weeks 4-6: Antagonist supersets
    TrainingDay(
        "W4-6: Chest-Back (SS)",
        [
            "SS: Bench Press + Pull-ups [4×10+10]",
            "SS: Incline DB Press + DB Row [4×10+10]",
            "SS: Machine Flyes + Machine Row [4×10+10]",
            "SS: Cable Crossover + Behind-Neck Pulldown [4×10+10]",
        ],
    ),
    TrainingDay(
        "W4-6: Shoulder-Leg (SS)",
        [
            "Bi-set: Military + Smith Press [4×10+10]",
            "Triset: Upright Row + Rear Delts + Lateral [4×10+10+10]",
            "SS: Squat + Lying Leg Curl [4×10+10]",
            "SS: Leg Press + Romanian DL [4×10+10]",
            "Triset: Standing + Seated + Press Calf [4×12+12+12]",
        ],
    ),
    TrainingDay(
        "W4-6: Arms (Antag. SS)",
        [
            "SS: EZ Curl + EZ Skull Crushers [4×10+10]",
            "SS: Barbell Curl + Triceps Pushdown [4×10+10]",
            "SS: Incline DB Curl + Triceps Kickback [4×10+10]",
        ],
    ),
]


# ─── Upper / Lower 12-week (alternative routine) ─────────────────────

UL_PHASES: list[Phase] = [
    Phase(
        1,
        "1-6",
        "Base",
        "Construye la base",
        "#00D4AA",
        "4×6-10",
        "1'30\"-2' sets",
        "Mismas cargas. RIR 2-3. Añade peso cuando el tope de repeticiones salga fácil.",
        "high",
    ),
    Phase(
        2,
        "7-12",
        "Bloque de hipertrofia",
        "Volumen + intensidad",
        "#7C5CFC",
        "4×8-12",
        "1'-1'30\" sets",
        "Última serie cerca del fallo. Añade aislamientos como remate.",
        "high",
    ),
]

UL_DAYS_FOUNDATION: list[TrainingDay] = [
    TrainingDay(
        "Upper A: Push focus",
        [
            "Barbell Bench Press",
            "Barbell Row",
            "Seated DB Press",
            "Pull-ups",
            "EZ Bar Skull Crushers",
            "Barbell Curl",
        ],
    ),
    TrainingDay(
        "Lower A: Squat focus",
        [
            "Squat",
            "Romanian Deadlift",
            "Leg Press",
            "Lying Leg Curl",
            "Standing Calf Raise",
            "Plank",
        ],
    ),
    TrainingDay(
        "Upper B: Pull focus",
        [
            "Incline DB Press",
            "Front Lat Pulldown",
            "Lateral Raises",
            "DB Row",
            "Triceps Pushdown",
            "Hammer Curl",
        ],
    ),
    TrainingDay(
        "Lower B: Deadlift focus",
        [
            "Deadlift",
            "Leg Press",
            "Leg Extensions",
            "Seated Leg Curl",
            "Seated Calf Raise",
            "Cable Crunch",
        ],
    ),
]

UL_DAYS_HYPERTROPHY: list[TrainingDay] = [
    TrainingDay(
        "Upper A: Push focus",
        [
            "Barbell Bench Press [4×8-10]",
            "Barbell Row [4×8-10]",
            "Arnold Press [3×10-12]",
            "Pull-ups [3×max]",
            "Cable Crossover [3×12]",
            "Triceps Pushdown [3×12]",
            "Cable Curl [3×12]",
        ],
    ),
    TrainingDay(
        "Lower A: Squat focus",
        [
            "Squat [4×8-10]",
            "Romanian Deadlift [4×8-10]",
            "Leg Press [3×10-12]",
            "Lying Leg Curl [3×10-12]",
            "Standing Calf Raise [4×12-15]",
            "Hanging Abs [3×max]",
        ],
    ),
    TrainingDay(
        "Upper B: Pull focus",
        [
            "Incline DB Press [4×8-10]",
            "V-Grip Lat Pulldown [4×8-10]",
            "Lateral Raises [4×12-15]",
            "DB Row [3×10-12]",
            "EZ Bar Curl [3×10-12]",
            "Skull Crushers [3×10-12]",
        ],
    ),
    TrainingDay(
        "Lower B: Deadlift focus",
        [
            "Deadlift [4×6-8]",
            "Leg Press [4×8-10]",
            "Leg Extensions [3×12-15]",
            "Seated Leg Curl [3×12-15]",
            "Seated Calf Raise [4×12-15]",
            "Cable Crunch [3×15]",
        ],
    ),
]


# ─── Push / Pull / Legs 12-week (alternative routine) ────────────────

PPL_PHASES: list[Phase] = [
    Phase(
        1,
        "1-6",
        "Base",
        "Construye la base",
        "#00D4AA",
        "4×6-10",
        "1'30\"-2' sets",
        "6 días/semana. Mismos ejercicios dos veces. RIR 2-3 hasta la última serie.",
        "high",
    ),
    Phase(
        2,
        "7-12",
        "Intensificación",
        "Volumen + intensidad",
        "#FF6B35",
        "4×8-12",
        "1'-1'30\" sets",
        "Lleva la última serie al fallo. Añade un drop set en los aislamientos.",
        "high",
    ),
]

PPL_DAYS_FOUNDATION: list[TrainingDay] = [
    TrainingDay(
        "Push Day",
        [
            "Barbell Bench Press",
            "Seated DB Press",
            "Incline DB Press",
            "Lateral Raises",
            "Cable Crossover",
            "Triceps Pushdown",
            "EZ Bar Skull Crushers",
        ],
    ),
    TrainingDay(
        "Pull Day",
        [
            "Pull-ups",
            "Barbell Row",
            "Front Lat Pulldown",
            "Seated Cable Row",
            "Cable Rear Delts",
            "EZ Bar Curl",
            "Hammer Curl",
        ],
    ),
    TrainingDay(
        "Leg Day",
        [
            "Squat",
            "Romanian Deadlift",
            "Leg Press",
            "Lying Leg Curl",
            "Leg Extensions",
            "Standing Calf Raise",
            "Plank",
        ],
    ),
]

PPL_DAYS_INTENSIFICATION: list[TrainingDay] = [
    TrainingDay(
        "Push Day",
        [
            "Barbell Bench Press [4×8-10]",
            "Barbell Military Press [4×8-10]",
            "Incline DB Press [3×10-12]",
            "Lateral Raises [4×12-15]",
            "Cable Crossover [3×12]",
            "Triceps Pushdown [3×12]",
            "Overhead Extension [3×10-12]",
        ],
    ),
    TrainingDay(
        "Pull Day",
        [
            "Pull-ups [4×max]",
            "Barbell Row [4×8-10]",
            "V-Grip Lat Pulldown [3×10-12]",
            "DB Row [3×10-12]",
            "Cable Rear Delts [4×12-15]",
            "EZ Bar Curl [3×10-12]",
            "Incline DB Curl [3×10-12]",
        ],
    ),
    TrainingDay(
        "Leg Day",
        [
            "Squat [4×8-10]",
            "Romanian Deadlift [4×8-10]",
            "Leg Press [3×10-12]",
            "Lying Leg Curl [3×10-12]",
            "Leg Extensions [3×12-15]",
            "Seated Calf Raise [4×12-15]",
            "Hanging Abs [3×max]",
        ],
    ),
]


RECOMP_PHASES: list[Phase] = [
    Phase(
        1,
        "1-2",
        "Base",
        "Fija tus pesos de trabajo",
        "#00D4AA",
        "4×5-8 / 3×8-12",
        "3' compounds / 60-90s isolation",
        "Busca una carga que deje 2-3 reps en reserva. La semana 1 fija la línea base, no récords.",
        "low",
    ),
    Phase(
        2,
        "3-5",
        "Acumulación",
        "Una serie extra en el primero",
        "#FF6B35",
        "5×5-8 / 3×8-12",
        "3' compounds / 60-90s isolation",
        "Añade 1 serie al primer ejercicio de cada sesión. Progresión doble: llega al "
        "tope del rango en todas las series y entonces suma 2,5 kg en superior / 5 kg en inferior.",
        "low",
    ),
    Phase(
        3,
        "6",
        "Descarga",
        "Mismo peso, la mitad de series",
        "#4A9EFF",
        "2×5-8 / 2×8-12",
        "3' compounds / 60-90s isolation",
        "Mismas cargas, la mitad de series, sin cardio matinal. Semana de recuperación antes del siguiente bloque.",
        "low",
    ),
]

# 5-day PPL + Upper/Lower. Frequency 2 per muscle group, legs 72 h apart.
# Mon Push 18:30 · Tue Legs A 14:30 · Wed Pull 18:30 · Thu Upper 14:30 · Fri Lower 14:30
RECOMP_DAYS_BASE: list[TrainingDay] = [
    TrainingDay(
        "Push",
        [
            "Barbell Bench Press [4×5-8]",
            "Barbell Military Press [3×6-10]",
            "Incline DB Press [3×8-12]",
            "Lateral Raises [4×12-20]",
            "Dips [3×8-12]",
            "Triceps Pushdown [3×10-15]",
        ],
    ),
    TrainingDay(
        "Legs A: quad focus",
        [
            "Squat [4×5-8]",
            "Leg Press [3×8-12]",
            "Leg Extensions [3×12-15]",
            "Lying Leg Curl [3×10-15]",
            "Standing Calf Raise [4×12-20]",
        ],
    ),
    TrainingDay(
        "Pull",
        [
            "Pull-ups [4×6-10]",
            "Barbell Row [4×6-10]",
            "Seated Cable Row [3×10-12]",
            "Face Pull [3×15-20]",
            "EZ Bar Curl [3×8-12]",
            "Hammer Curl [3×10-15]",
        ],
    ),
    TrainingDay(
        "Upper",
        [
            "Incline Barbell Bench Press [4×6-10]",
            "DB Row [4×8-12]",
            "Seated DB Press [3×8-12]",
            "Front Lat Pulldown [3×10-12]",
            "Cable Lateral Raises [3×15-20]",
            "Incline DB Curl [3×10-15]",
            "Overhead Extension [3×10-15]",
        ],
    ),
    TrainingDay(
        "Lower: hip focus",
        [
            "Romanian Deadlift [4×6-10]",
            "Hip Thrust [3×8-12]",
            "Bulgarian Split Squat [3×8-12]",
            "Seated Leg Curl [3×10-15]",
            "Seated Calf Raise [4×15-20]",
        ],
    ),
]

# Phase 2 adds one set to the opener of every session.
RECOMP_DAYS_ACCUMULATION: list[TrainingDay] = [
    TrainingDay(
        "Push",
        [
            "Barbell Bench Press [5×5-8]",
            "Barbell Military Press [3×6-10]",
            "Incline DB Press [3×8-12]",
            "Lateral Raises [4×12-20]",
            "Dips [3×8-12]",
            "Triceps Pushdown [3×10-15]",
        ],
    ),
    TrainingDay(
        "Legs A: quad focus",
        [
            "Squat [5×5-8]",
            "Leg Press [3×8-12]",
            "Leg Extensions [3×12-15]",
            "Lying Leg Curl [3×10-15]",
            "Standing Calf Raise [4×12-20]",
        ],
    ),
    TrainingDay(
        "Pull",
        [
            "Pull-ups [5×6-10]",
            "Barbell Row [4×6-10]",
            "Seated Cable Row [3×10-12]",
            "Face Pull [3×15-20]",
            "EZ Bar Curl [3×8-12]",
            "Hammer Curl [3×10-15]",
        ],
    ),
    TrainingDay(
        "Upper",
        [
            "Incline Barbell Bench Press [5×6-10]",
            "DB Row [4×8-12]",
            "Seated DB Press [3×8-12]",
            "Front Lat Pulldown [3×10-12]",
            "Cable Lateral Raises [3×15-20]",
            "Incline DB Curl [3×10-15]",
            "Overhead Extension [3×10-15]",
        ],
    ),
    TrainingDay(
        "Lower: hip focus",
        [
            "Romanian Deadlift [5×6-10]",
            "Hip Thrust [3×8-12]",
            "Bulgarian Split Squat [3×8-12]",
            "Seated Leg Curl [3×10-15]",
            "Seated Calf Raise [4×15-20]",
        ],
    ),
]

# Deload: same loads, half the sets.
RECOMP_DAYS_DELOAD: list[TrainingDay] = [
    TrainingDay(
        "Push",
        [
            "Barbell Bench Press [2×5-8]",
            "Barbell Military Press [2×6-10]",
            "Incline DB Press [2×8-12]",
            "Lateral Raises [2×12-20]",
            "Dips [2×8-12]",
        ],
    ),
    TrainingDay(
        "Legs A: quad focus",
        [
            "Squat [2×5-8]",
            "Leg Press [2×8-12]",
            "Lying Leg Curl [2×10-15]",
            "Standing Calf Raise [2×12-20]",
        ],
    ),
    TrainingDay(
        "Pull",
        [
            "Pull-ups [2×6-10]",
            "Barbell Row [2×6-10]",
            "Face Pull [2×15-20]",
            "EZ Bar Curl [2×8-12]",
        ],
    ),
    TrainingDay(
        "Upper",
        [
            "Incline Barbell Bench Press [2×6-10]",
            "DB Row [2×8-12]",
            "Seated DB Press [2×8-12]",
            "Cable Lateral Raises [2×15-20]",
        ],
    ),
    TrainingDay(
        "Lower: hip focus",
        [
            "Romanian Deadlift [2×6-10]",
            "Hip Thrust [2×8-12]",
            "Seated Leg Curl [2×10-15]",
            "Seated Calf Raise [2×15-20]",
        ],
    ),
]


@dataclass
class Routine:
    id: str
    name: str
    description: str
    phases: list[Phase]
    days_by_phase: dict[int, list[TrainingDay]]
    week_rotation: list[list[str]] | None = None  # only for high-freq routines

    def days_for_phase(self, phase_id: int) -> list[TrainingDay]:
        return self.days_by_phase.get(phase_id, [])


# Weekly rotation for CambiaTuFísico phases 1-3 (high-frequency)
WEEK_ROTATION: list[list[str]] = [
    ["Chest-Biceps", "Back-Triceps + Abs", "Rest", "Shoulder-Leg", "Chest-Biceps + Abs"],
    ["Back-Triceps", "Shoulder-Leg + Abs", "Rest", "Chest-Biceps", "Back-Triceps + Abs"],
    ["Shoulder-Leg", "Chest-Biceps + Abs", "Rest", "Back-Triceps", "Shoulder-Leg + Abs"],
]


ROUTINES: list[Routine] = [
    Routine(
        id="cambiatufisico",
        name="CambiaTuFísico",
        description="Periodized routine · 24 weeks · 7 phases",
        phases=PHASES,
        days_by_phase={
            1: DAYS_PHASE_1_3,
            2: DAYS_PHASE_1_3,
            3: DAYS_PHASE_1_3,
            4: DAYS_PHASE_4,
            5: DAYS_PHASE_5,
            6: DAYS_PHASE_6,
            7: DAYS_PHASE_7,
        },
        week_rotation=WEEK_ROTATION,
    ),
    Routine(
        id="upper-lower",
        name="Upper / Lower",
        description="4-day split · 12 weeks · 2 phases",
        phases=UL_PHASES,
        days_by_phase={1: UL_DAYS_FOUNDATION, 2: UL_DAYS_HYPERTROPHY},
        week_rotation=None,
    ),
    Routine(
        id="push-pull-legs",
        name="Push / Pull / Legs",
        description="6-day split · 12 weeks · 2 phases",
        phases=PPL_PHASES,
        days_by_phase={1: PPL_DAYS_FOUNDATION, 2: PPL_DAYS_INTENSIFICATION},
        week_rotation=None,
    ),
    Routine(
        id="recomp-ppl-ul",
        name="Recomp — PPL + Upper/Lower",
        description="5 days · 6 weeks · lean bulk",
        phases=RECOMP_PHASES,
        days_by_phase={
            1: RECOMP_DAYS_BASE,
            2: RECOMP_DAYS_ACCUMULATION,
            3: RECOMP_DAYS_DELOAD,
        },
        week_rotation=None,
    ),
]


_active_routine_id = "cambiatufisico"


def set_active_routine(rid: str) -> None:
    global _active_routine_id
    if any(r.id == rid for r in ROUTINES):
        _active_routine_id = rid


def active_routine() -> Routine:
    for r in ROUTINES:
        if r.id == _active_routine_id:
            return r
    return ROUTINES[0]


def get_days_for_phase(phase_id: int) -> list[TrainingDay]:
    """Backward-compat wrapper around the active routine."""
    return active_routine().days_for_phase(phase_id)


# Exercise catalog by muscle group (for the logger / free entry)
EXERCISE_CATALOG: dict[str, list[str]] = {
    "Chest": [
        "Barbell Bench Press",
        "Smith Bench Press",
        "Incline DB Press",
        "Incline Machine Press",
        "Decline Press",
        "Close-Grip Bench Press",
        "Incline DB Flyes",
        "Pec Deck",
        "Cable Crossover",
        "Push-ups",
    ],
    "Back": [
        "Front Lat Pulldown",
        "Behind-Neck Lat Pulldown",
        "V-Grip Lat Pulldown",
        "Pull-ups",
        "Barbell Row",
        "DB Row",
        "Seated Cable Row",
        "T-Bar Row",
        "Machine Row",
        "Deadlift",
        "Romanian Deadlift",
    ],
    "Shoulder": [
        "Barbell Military Press",
        "Seated DB Press",
        "Arnold Press",
        "Lateral Raises",
        "Machine Lateral Raises",
        "Plate Front Raises",
        "DB Rear Delts",
        "Cable Rear Delts",
        "Upright Row",
    ],
    "Biceps": [
        "Straight Bar Curl",
        "EZ Bar Curl",
        "EZ Bar Preacher Curl",
        "Alternate DB Curl",
        "Simultaneous DB Curl",
        "Hammer Curl",
        "Cable Curl",
        "Incline DB Curl",
        "Reverse Curl",
    ],
    "Triceps": [
        "EZ Bar Skull Crushers",
        "Close-Grip Bench Press",
        "Rope Pushdown",
        "Triceps Pushdown",
        "Reverse Pushdown",
        "Parallel Bar Dips",
        "Overhead Extension",
        "Triceps Kickback",
    ],
    "Leg": [
        "Squat",
        "Leg Press",
        "Leg Extensions",
        "Lying Leg Curl",
        "Seated Leg Curl",
        "Lunges",
        "Standing Calf Raise",
        "Seated Calf Raise",
        "Calf Press",
    ],
    "Abs": [
        "Cable Crunch",
        "Hanging Abs",
        "Floor Crunch",
        "Floor Obliques",
        "Plank",
        "Leg Raises",
        "Hyperextensions",
    ],
    "Cardio": [
        "Treadmill",
        "Bike",
        "Elliptical",
        "HIIT Intervals",
    ],
}

MUSCLE_GROUPS = list(EXERCISE_CATALOG.keys())
