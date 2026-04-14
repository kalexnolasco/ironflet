"""
CambiaTuFísico routine data.
7 phases, 24 weeks of periodized training.

All strings are canonical English. i18n.t()/t_exercise() translate to ES.
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
        "Conditioning",
        "Hypertrophy",
        "#00D4AA",
        "3×12",
        "1' sets / 2-3' exercises",
        "No absolute failure. 20' continuous cardio post-weights. Abs 2 days/week.",
        "high",
    ),
    Phase(
        2,
        "4-6",
        "Total Hypertrophy",
        "Muscle Failure",
        "#FF6B35",
        "3×8-10",
        "1'30\" sets (max 2')",
        "Failure on last set. Same exercises. 20' cardio. More intense abs.",
        "high",
    ),
    Phase(
        3,
        "7-9",
        "Functional Hypertrophy",
        "Strength + Hypertrophy",
        "#7C5CFC",
        "4×5-6 (*=3×8)",
        "2-2'30\" / 3' ex. / 1' on *",
        "Increase loads. *= 3×8 to failure. 20' cardio. Abs 5×8-12.",
        "high",
    ),
    Phase(
        4,
        "10",
        "Deload",
        "Recovery",
        "#FFD93D",
        "3-4×12",
        "1' sets / 2' exercises",
        "Low intensity, no failure. 3 days full body.",
        "low",
    ),
    Phase(
        5,
        "11-14",
        "Weider Hypertrophy",
        "High Volume",
        "#FF3366",
        "Ascending Pyramid",
        "1'30\" sets / 3' exercises",
        "5 days, 1 muscle/day. Failure on all sets except first.",
        "low",
    ),
    Phase(
        6,
        "15-18",
        "High Intensity",
        "Drop Sets + Compound",
        "#FF8A5C",
        "Drop sets (e.g.: 10,8,6+12↓)",
        "1' sets / 3' exercises",
        "Drop sets on last set. 5' treadmill pre-weights.",
        "low",
    ),
    Phase(
        7,
        "19-24",
        "Fat Loss",
        "Bi-sets / Supersets",
        "#4ECDC4",
        "BI 4×8+10 / SS 4×10+10",
        "Min. between blocks, 1-1'30\"",
        "Weeks 1-3: bi-sets. Weeks 4-6: antagonist supersets.",
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
        "Foundation",
        "Build base",
        "#00D4AA",
        "4×6-10",
        "1'30\"-2' sets",
        "Same loads. RIR 2-3. Add weight when top reps are easy.",
        "high",
    ),
    Phase(
        2,
        "7-12",
        "Hypertrophy Block",
        "Volume + Intensity",
        "#7C5CFC",
        "4×8-12",
        "1'-1'30\" sets",
        "Last set close to failure. Add isolation finishers.",
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


# ─── Women Fitness 12-week (glute + tone focus) ──────────────────────

WF_PHASES: list[Phase] = [
    Phase(
        1,
        "1-6",
        "Tone & Build",
        "Foundation",
        "#FF3366",
        "3×12-15",
        "1' sets",
        "3 days/week. Glute focus + upper body balance. 20' cardio after.",
        "high",
    ),
    Phase(
        2,
        "7-12",
        "Shape & Burn",
        "Fat Loss",
        "#FF6B35",
        "4×12-15 + HIIT",
        "45s sets",
        "4 days/week. Supersets and HIIT finishers. Keep intensity up.",
        "high",
    ),
]

WF_DAYS_TONE: list[TrainingDay] = [
    TrainingDay(
        "Glutes + Lower",
        [
            "Squat",
            "Romanian Deadlift",
            "Leg Press",
            "Lying Leg Curl",
            "Barbell Lunges",
            "Standing Calf Raise",
        ],
    ),
    TrainingDay(
        "Upper Body",
        [
            "Incline DB Press",
            "Front Lat Pulldown",
            "Seated Cable Row",
            "Lateral Raises",
            "Cable Curl",
            "Triceps Pushdown",
        ],
    ),
    TrainingDay(
        "Core + Cardio",
        [
            "Cable Crunch",
            "Hanging Abs",
            "Plank",
            "Leg Raises",
            "Hyperextensions",
            "HIIT Intervals",
        ],
    ),
]

WF_DAYS_SHAPE: list[TrainingDay] = [
    TrainingDay(
        "Lower A: Glute focus",
        [
            "Squat [4×12]",
            "Romanian Deadlift [4×12]",
            "Leg Press [3×15]",
            "Lying Leg Curl [3×15]",
            "Standing Calf Raise [3×15]",
        ],
    ),
    TrainingDay(
        "Upper + HIIT",
        [
            "Incline DB Press [3×12]",
            "Front Lat Pulldown [3×12]",
            "Seated Cable Row [3×12]",
            "Lateral Raises [3×15]",
            "Cable Curl [3×12]",
            "HIIT Intervals [15 min]",
        ],
    ),
    TrainingDay(
        "Lower B: Quad focus",
        [
            "Barbell Lunges [4×12]",
            "Leg Extensions [3×15]",
            "Seated Leg Curl [3×15]",
            "Leg Press [3×15]",
            "Seated Calf Raise [3×15]",
        ],
    ),
    TrainingDay(
        "Full Body + Core",
        [
            "DB Row [3×12]",
            "Push-ups [3×max]",
            "Arnold Press [3×12]",
            "Cable Crunch [3×15]",
            "Plank [3×max]",
            "Leg Raises [3×15]",
        ],
    ),
]


# ─── Women — Home (3 days, 8 weeks, bodyweight + optional DBs) ───────

WH_PHASES: list[Phase] = [
    Phase(
        1,
        "1-8",
        "Home Foundation",
        "Bodyweight + DBs",
        "#FF3366",
        "3×10-15",
        "45s-1' sets",
        "3 days/week at home. Start bodyweight, add DBs when top reps feel easy.",
        "high",
    ),
]

WH_DAYS: list[TrainingDay] = [
    TrainingDay(
        "Upper at Home",
        [
            "Push-ups",
            "Incline DB Press",
            "DB Row",
            "Lateral Raises",
            "Hammer Curl",
            "Triceps Kickback",
        ],
    ),
    TrainingDay(
        "Lower at Home",
        [
            "Squat",
            "Lunges",
            "Romanian Deadlift",
            "Standing Calf Raise",
            "Plank",
            "Leg Raises",
        ],
    ),
    TrainingDay(
        "Full Body Flow",
        [
            "Squat",
            "Push-ups",
            "DB Row",
            "Lunges",
            "Lateral Raises",
            "Plank",
        ],
    ),
]


# ─── Women — Strength (4 days, 12 weeks, barbell compounds) ──────────

WS_PHASES: list[Phase] = [
    Phase(
        1,
        "1-6",
        "Technique Base",
        "Submax 5×5",
        "#00D4AA",
        "5×5 @ RPE 6-7",
        "2-3' sets",
        "Submaximal loads. Add weight when 3 sessions at the same load feel easy.",
        "high",
    ),
    Phase(
        2,
        "7-12",
        "Strength Block",
        "Heavy 5×3-5",
        "#FF6B35",
        "5×3-5 @ RPE 8",
        "3-5' sets",
        "Top set RPE 8. Back-off sets 10-15% lighter for volume.",
        "high",
    ),
]

WS_DAYS_BASE: list[TrainingDay] = [
    TrainingDay(
        "Squat Day",
        [
            "Squat",
            "Romanian Deadlift",
            "Leg Extensions",
            "Lying Leg Curl",
            "Plank",
        ],
    ),
    TrainingDay(
        "Bench Day",
        [
            "Barbell Bench Press",
            "Incline DB Press",
            "Seated DB Press",
            "Triceps Pushdown",
            "Cable Curl",
        ],
    ),
    TrainingDay(
        "Deadlift Day",
        [
            "Deadlift",
            "Barbell Row",
            "Pull-ups",
            "Lateral Raises",
            "Hyperextensions",
        ],
    ),
    TrainingDay(
        "Press Day",
        [
            "Barbell Military Press",
            "Front Lat Pulldown",
            "DB Row",
            "EZ Bar Curl",
            "Skull Crushers",
        ],
    ),
]

WS_DAYS_HEAVY: list[TrainingDay] = [
    TrainingDay(
        "Squat Day",
        [
            "Squat [5×3]",
            "Romanian Deadlift [4×5]",
            "Leg Press [3×8-10]",
            "Lying Leg Curl [3×10]",
            "Plank [3×max]",
        ],
    ),
    TrainingDay(
        "Bench Day",
        [
            "Barbell Bench Press [5×3]",
            "Incline DB Press [4×5-6]",
            "Seated DB Press [3×8]",
            "Triceps Pushdown [3×10]",
            "Cable Curl [3×10]",
        ],
    ),
    TrainingDay(
        "Deadlift Day",
        [
            "Deadlift [5×3]",
            "Barbell Row [4×5]",
            "Pull-ups [4×max]",
            "Lateral Raises [3×12]",
            "Hyperextensions [3×12]",
        ],
    ),
    TrainingDay(
        "Press Day",
        [
            "Barbell Military Press [5×3]",
            "Front Lat Pulldown [4×6-8]",
            "DB Row [3×8]",
            "EZ Bar Curl [3×8]",
            "Skull Crushers [3×10]",
        ],
    ),
]


# ─── Women — Volume (4 days, 12 weeks, high-volume hypertrophy) ──────

WV_PHASES: list[Phase] = [
    Phase(
        1,
        "1-6",
        "Volume Base",
        "Build volume",
        "#7C5CFC",
        "4×10-12",
        "60-90s sets",
        "Moderate loads, higher volume. Mind-muscle focus over loads.",
        "high",
    ),
    Phase(
        2,
        "7-12",
        "Metabolic Peak",
        "Pump + burn",
        "#FF8A5C",
        "4×12-15 + drop set",
        "45-60s sets",
        "Last set each exercise ends with a drop set for extra intensity.",
        "high",
    ),
]

WV_DAYS_BASE: list[TrainingDay] = [
    TrainingDay(
        "Lower A: Quads",
        [
            "Squat",
            "Leg Press",
            "Leg Extensions",
            "Barbell Lunges",
            "Standing Calf Raise",
        ],
    ),
    TrainingDay(
        "Upper A: Push",
        [
            "Incline DB Press",
            "Barbell Bench Press",
            "Arnold Press",
            "Lateral Raises",
            "Cable Crossover",
            "Triceps Pushdown",
        ],
    ),
    TrainingDay(
        "Lower B: Posterior",
        [
            "Romanian Deadlift",
            "Lying Leg Curl",
            "Seated Leg Curl",
            "DB Lunges",
            "Seated Calf Raise",
        ],
    ),
    TrainingDay(
        "Upper B: Pull",
        [
            "Pull-ups",
            "Seated Cable Row",
            "Front Lat Pulldown",
            "Cable Rear Delts",
            "EZ Bar Curl",
            "Hammer Curl",
        ],
    ),
]

WV_DAYS_PEAK: list[TrainingDay] = [
    TrainingDay(
        "Lower A: Quads",
        [
            "Squat [4×12]",
            "Leg Press [4×12+drop]",
            "Leg Extensions [3×15+drop]",
            "Barbell Lunges [3×12]",
            "Standing Calf Raise [4×15]",
        ],
    ),
    TrainingDay(
        "Upper A: Push",
        [
            "Incline DB Press [4×12]",
            "Barbell Bench Press [4×12]",
            "Arnold Press [3×12+drop]",
            "Lateral Raises [4×15+drop]",
            "Cable Crossover [3×15]",
            "Triceps Pushdown [3×15+drop]",
        ],
    ),
    TrainingDay(
        "Lower B: Posterior",
        [
            "Romanian Deadlift [4×12]",
            "Lying Leg Curl [4×12+drop]",
            "Seated Leg Curl [3×15]",
            "DB Lunges [3×12]",
            "Seated Calf Raise [4×15+drop]",
        ],
    ),
    TrainingDay(
        "Upper B: Pull",
        [
            "Pull-ups [4×max]",
            "Seated Cable Row [4×12]",
            "Front Lat Pulldown [4×12+drop]",
            "Cable Rear Delts [4×15]",
            "EZ Bar Curl [3×12+drop]",
            "Hammer Curl [3×12]",
        ],
    ),
]


# ─── Push / Pull / Legs 12-week (alternative routine) ────────────────

PPL_PHASES: list[Phase] = [
    Phase(
        1,
        "1-6",
        "Foundation",
        "Build base",
        "#00D4AA",
        "4×6-10",
        "1'30\"-2' sets",
        "6 days/week. Same exercises twice. RIR 2-3 until last set.",
        "high",
    ),
    Phase(
        2,
        "7-12",
        "Intensification",
        "Volume + Intensity",
        "#FF6B35",
        "4×8-12",
        "1'-1'30\" sets",
        "Push last set to failure. Add drop set on isolation moves.",
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
        id="women-fitness",
        name="Women Fitness",
        description="Glute + tone focus · 12 weeks · 2 phases",
        phases=WF_PHASES,
        days_by_phase={1: WF_DAYS_TONE, 2: WF_DAYS_SHAPE},
        week_rotation=None,
    ),
    Routine(
        id="women-home",
        name="Women — Home",
        description="At home · 3 days · 8 weeks · 1 phase",
        phases=WH_PHASES,
        days_by_phase={1: WH_DAYS},
        week_rotation=None,
    ),
    Routine(
        id="women-strength",
        name="Women — Strength",
        description="Barbell strength · 4 days · 12 weeks · 2 phases",
        phases=WS_PHASES,
        days_by_phase={1: WS_DAYS_BASE, 2: WS_DAYS_HEAVY},
        week_rotation=None,
    ),
    Routine(
        id="women-volume",
        name="Women — Volume",
        description="High volume hypertrophy · 4 days · 12 weeks · 2 phases",
        phases=WV_PHASES,
        days_by_phase={1: WV_DAYS_BASE, 2: WV_DAYS_PEAK},
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
