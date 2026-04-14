"""Simple in-process i18n. Code uses English literals; ES dict translates."""

from __future__ import annotations

_lang = "en"

# Spanish translations. Keys are the English strings used in source.
ES: dict[str, str] = {
    # ── Navigation ──────────────────────────────────────────
    "Home": "Inicio",
    "Plan": "Plan",
    "Train": "Entrena",
    "Browse": "Ejercicios",
    "History": "Historial",
    "All": "Todos",
    "Tap an exercise for details": "Toca un ejercicio para ver detalles",
    "Guides": "Guías",
    "Training": "Entrenamiento",
    "Nutrition": "Nutrición",

    # ── Profile ─────────────────────────────────────────────
    "Profile": "Perfil",
    "Settings": "Ajustes",
    "Data": "Datos",
    "Clear workout history": "Borrar historial de entrenamientos",
    "Clear all data": "Borrar todos los datos",
    "This will permanently delete all logged workouts. "
    "Profile and weight log stay.":
        "Esto borrará todos los entrenamientos registrados. "
        "El perfil y el historial de peso se mantienen.",
    "This will erase profile, weight log, workouts and preferences. "
    "Cannot be undone.":
        "Esto borrará el perfil, historial de peso, entrenamientos y preferencias. "
        "No se puede deshacer.",
    "Delete": "Borrar",
    "Erase all": "Borrar todo",
    "Exercise guides": "Guías de ejercicios",
    "Installed": "Instaladas",
    "Not installed": "No instaladas",
    "Downloading…": "Descargando…",
    "Partial": "Parcial",
    "Download": "Descargar",
    "Clear cache": "Limpiar caché",
    "Exercise photos and instructions are downloaded "
    "from a public fitness database (Unlicense). "
    "Approx. 9 MB over Wi-Fi is recommended.":
        "Las fotos e instrucciones se descargan de una base de "
        "datos pública (Unlicense). ~9 MB, mejor por Wi-Fi.",
    "Your data": "Tus datos",
    "Derived metrics": "Métricas derivadas",
    "Weight": "Peso",
    "Name": "Nombre",
    "Birthdate (YYYY-MM-DD)": "Fecha nacimiento (AAAA-MM-DD)",
    "Height (cm)": "Altura (cm)",
    "Sex": "Sexo",
    "Activity level": "Nivel de actividad",
    "Male": "Hombre",
    "Female": "Mujer",
    "Prefer not to say": "Prefiero no decir",
    "Save profile": "Guardar perfil",
    "sedentary": "sedentario",
    "light": "ligero",
    "moderate": "moderado",
    "active": "activo",
    "very_active": "muy activo",
    "Age": "Edad",
    "BMI": "IMC",
    "BMR": "TMB",
    "TDEE": "GEDT",
    "Protein": "Proteína",
    "Water": "Agua",
    "underweight": "bajo peso",
    "normal": "normal",
    "overweight": "sobrepeso",
    "obese": "obesidad",
    "Current weight": "Peso actual",
    "Log weight": "Registrar peso",
    "History": "Historial",
    "No weight logged yet": "Sin registros de peso aún",
    "Weight (kg)": "Peso (kg)",
    "Date (YYYY-MM-DD)": "Fecha (AAAA-MM-DD)",
    "Enter a valid weight": "Introduce un peso válido",
    "Invalid date format": "Formato de fecha inválido",
    "Cancel": "Cancelar",
    "Save": "Guardar",

    # ── Backup ──────────────────────────────────────────────
    "Backup": "Respaldo",
    "Export backup": "Exportar respaldo",
    "Import backup": "Importar respaldo",
    "Export": "Exportar",
    "Import": "Importar",
    "Copy to clipboard": "Copiar al portapapeles",
    "Paste from clipboard": "Pegar del portapapeles",
    "Copied!": "¡Copiado!",
    "Backup imported": "Respaldo importado",
    "Workouts": "Entrenamientos",
    "Weight entries": "Registros de peso",
    "Preferences": "Preferencias",
    "Size": "Tamaño",
    "Invalid backup JSON": "JSON de respaldo inválido",
    "Paste backup JSON below": "Pega aquí el JSON del respaldo",
    "This will replace all current data.":
        "Esto reemplazará todos los datos actuales.",
    "Keep current data / merge prefs only":
        "Mantener datos actuales / solo combinar prefs",
    "Replace all": "Reemplazar todo",

    # ── Home ────────────────────────────────────────────────
    "Sessions": "Sesiones",
    "Sets": "Series",
    "Vol (kg)": "Vol (kg)",
    "Start Routine": "Empezar Rutina",
    "Today": "Hoy",
    "No records": "Sin registros",
    "days": "días",

    # ── Plan ────────────────────────────────────────────────
    "Training Plan": "Plan de Entrenamiento",
    "Periodized routine · 24 weeks · 7 phases":
        "Rutina periodizada · 24 semanas · 7 fases",
    "PHASE": "FASE",
    "WK": "SEM",
    "High freq.": "Alta freq.",
    "Low freq.": "Baja freq.",
    "Exercises": "Ejercicios",
    "Distribution": "Distribución",
    "Phases": "Fases",
    "Sets:": "Series:",
    "Rest:": "Descanso:",
    "Wk": "Sem",

    # ── Workout ─────────────────────────────────────────────
    "Choose your current phase": "Elige tu fase actual",
    "exercises": "ejercicios",
    "Back": "Volver",
    "EXERCISE": "EJERCICIO",
    "LAST SESSION": "ÚLTIMA SESIÓN",
    "First time - no history": "Primera vez - sin historial",
    "SET": "SET",
    "KG": "KG",
    "REPS": "REPS",
    "+ Set": "+ Serie",
    "Skip": "Saltar",
    "Save → Next": "Guardar → Siguiente",
    "Save → Finish": "Guardar → Finalizar",
    "Session Complete!": "¡Sesión Completada!",
    "exercises logged": "ejercicios registrados",
    "Back to Home": "Volver al Inicio",
    "Duration": "Duración",

    # ── History ─────────────────────────────────────────────
    "History & Progress": "Historial y Progresión",
    "Tap an exercise to see your progress":
        "Toca un ejercicio para ver tu evolución",
    "Start training to see your progress":
        "Empieza a entrenar para ver tu progresión",
    "sessions": "sesiones",
    "max kg": "kg máx",
    "Max weight": "Peso máximo",
    "Total volume": "Volumen total",
    "Session detail": "Detalle por sesión",
    "PR": "PR",

    # ── Routines ────────────────────────────────────────────
    "Routine": "Rutina",
    "CambiaTuFísico": "CambiaTuFísico",
    "Upper / Lower": "Torso / Pierna",
    "Push / Pull / Legs": "Empuje / Tirón / Pierna",
    "Women Fitness": "Mujer Fitness",
    "Women — Home": "Mujer — Casa",
    "Women — Strength": "Mujer — Fuerza",
    "Women — Volume": "Mujer — Volumen",
    "Periodized routine · 24 weeks · 7 phases":
        "Rutina periodizada · 24 semanas · 7 fases",
    "4-day split · 12 weeks · 2 phases":
        "Rutina 4 días · 12 semanas · 2 fases",
    "6-day split · 12 weeks · 2 phases":
        "Rutina 6 días · 12 semanas · 2 fases",
    "Glute + tone focus · 12 weeks · 2 phases":
        "Enfoque glúteo + tonificación · 12 semanas · 2 fases",
    "At home · 3 days · 8 weeks · 1 phase":
        "En casa · 3 días · 8 semanas · 1 fase",
    "Barbell strength · 4 days · 12 weeks · 2 phases":
        "Fuerza con barra · 4 días · 12 semanas · 2 fases",
    "High volume hypertrophy · 4 days · 12 weeks · 2 phases":
        "Hipertrofia alto volumen · 4 días · 12 semanas · 2 fases",

    # ── Phase names ─────────────────────────────────────────
    "Conditioning": "Acondicionamiento",
    "Total Hypertrophy": "Hipertrofia Total",
    "Functional Hypertrophy": "Hipertrofia Funcional",
    "Deload": "Descarga",
    "Weider Hypertrophy": "Hipertrofia Weider",
    "High Intensity": "Alta Intensidad",
    "Fat Loss": "Pérdida de Grasa",
    "Foundation": "Base",
    "Hypertrophy Block": "Bloque de Hipertrofia",
    "Intensification": "Intensificación",
    "Tone & Build": "Tonificar y Construir",
    "Shape & Burn": "Moldear y Quemar",
    "Home Foundation": "Base en Casa",
    "Bodyweight + DBs": "Peso corporal + Mancuernas",
    "Technique Base": "Base Técnica",
    "Submax 5×5": "Submáximo 5×5",
    "Strength Block": "Bloque de Fuerza",
    "Heavy 5×3-5": "Pesado 5×3-5",
    "Volume Base": "Base de Volumen",
    "Build volume": "Construir volumen",
    "Metabolic Peak": "Pico Metabólico",
    "Pump + burn": "Bombeo + quema",

    # ── Phase subtitles ─────────────────────────────────────
    "Hypertrophy": "Hipertrofia",
    "Muscle Failure": "Fallo muscular",
    "Strength + Hypertrophy": "Fuerza + Hipertrofia",
    "Recovery": "Recuperación",
    "High Volume": "Alto volumen",
    "Drop Sets + Compound": "Descendentes + Compuestas",
    "Bi-sets / Supersets": "Biseries / Superseries",
    "Build base": "Construir base",
    "Volume + Intensity": "Volumen + Intensidad",

    # ── Sets schemes (free-form) ────────────────────────────
    "Ascending Pyramid": "Pirámide ascendente",
    "Drop sets (e.g.: 10,8,6+12↓)": "Descendentes (ej: 10,8,6+12↓)",

    # ── Rest notations ──────────────────────────────────────
    "1' sets / 2-3' exercises": "1' series / 2-3' ejercicios",
    "1'30\" sets (max 2')": "1'30\" series (máx 2')",
    "2-2'30\" / 3' ex. / 1' on *": "2-2'30\" / 3' ejerc. / 1' en *",
    "1' sets / 2' exercises": "1' series / 2' ejercicios",
    "1'30\" sets / 3' exercises": "1'30\" series / 3' ejercicios",
    "1' sets / 3' exercises": "1' series / 3' ejercicios",
    "Min. between blocks, 1-1'30\"": "Mín. entre bloques, 1-1'30\"",
    "1'30\"-2' sets": "1'30\"-2' series",
    "1'-1'30\" sets": "1'-1'30\" series",
    "1' sets": "1' series",
    "45s sets": "45s series",
    "45s-1' sets": "45s-1' series",
    "2-3' sets": "2-3' series",
    "3-5' sets": "3-5' series",
    "60-90s sets": "60-90s series",
    "45-60s sets": "45-60s series",
    "5×5 @ RPE 6-7": "5×5 @ RPE 6-7",
    "5×3-5 @ RPE 8": "5×3-5 @ RPE 8",
    "4×10-12": "4×10-12",
    "4×12-15 + drop set": "4×12-15 + descendente",
    "3×10-15": "3×10-15",

    # ── Phase notes ─────────────────────────────────────────
    "No absolute failure. 20' continuous cardio post-weights. Abs 2 days/week.":
        "Sin fallo absoluto. Cardio 20' continuo post-pesas. Abs 2 días/semana.",
    "Failure on last set. Same exercises. 20' cardio. More intense abs.":
        "Fallo en última serie. Mismos ejercicios. Cardio 20'. Abs más intensidad.",
    "Increase loads. *= 3×8 to failure. 20' cardio. Abs 5×8-12.":
        "Subir kilajes. *= 3×8 fallo. Cardio 20'. Abs 5×8-12.",
    "Low intensity, no failure. 3 days full body.":
        "Baja intensidad, sin fallo. 3 días full body.",
    "5 days, 1 muscle/day. Failure on all sets except first.":
        "5 días, 1 músculo/día. Fallo en todas menos 1ª serie.",
    "Drop sets on last set. 5' treadmill pre-weights.":
        "Series descendentes en última serie. 5' cinta pre-pesas.",
    "Weeks 1-3: bi-sets. Weeks 4-6: antagonist supersets.":
        "Sem 1-3: biseries. Sem 4-6: superseries antagonistas.",
    "Same loads. RIR 2-3. Add weight when top reps are easy.":
        "Mismas cargas. RIR 2-3. Sube peso cuando las top reps vayan fáciles.",
    "Last set close to failure. Add isolation finishers.":
        "Última serie cerca del fallo. Añade aislamientos de remate.",
    "6 days/week. Same exercises twice. RIR 2-3 until last set.":
        "6 días/semana. Mismos ejercicios dos veces. RIR 2-3 hasta la última serie.",
    "Push last set to failure. Add drop set on isolation moves.":
        "Última serie al fallo. Añade descendentes en los aislamientos.",
    "3 days/week. Glute focus + upper body balance. 20' cardio after.":
        "3 días/semana. Enfoque glúteo + equilibrio superior. 20' de cardio al final.",
    "4 days/week. Supersets and HIIT finishers. Keep intensity up.":
        "4 días/semana. Superseries y remates HIIT. Mantén la intensidad alta.",
    "3 days/week at home. Start bodyweight, add DBs when top reps feel easy.":
        "3 días/semana en casa. Empieza con peso corporal; añade mancuernas cuando las top reps vayan fáciles.",
    "Submaximal loads. Add weight when 3 sessions at the same load feel easy.":
        "Cargas submáximas. Sube peso cuando 3 sesiones al mismo kilaje te resulten cómodas.",
    "Top set RPE 8. Back-off sets 10-15% lighter for volume.":
        "Serie top a RPE 8. Back-off sets 10-15% más ligeras para sumar volumen.",
    "Moderate loads, higher volume. Mind-muscle focus over loads.":
        "Cargas moderadas, mayor volumen. Prioriza conexión músculo-mente antes que kilaje.",
    "Last set each exercise ends with a drop set for extra intensity.":
        "La última serie de cada ejercicio acaba con una descendente para sumar intensidad.",

    # ── Day names (phases 1-3 high-freq) ────────────────────
    "Chest - Biceps": "Pecho - Bíceps",
    "Back - Triceps": "Espalda - Tríceps",
    "Shoulder - Leg": "Hombro - Pierna",

    # ── Day names (phase 4 deload) ──────────────────────────
    "Day 1 Full Body": "Día 1 Full Body",
    "Day 2 Full Body": "Día 2 Full Body",
    "Day 3 Full Body": "Día 3 Full Body",

    # ── Day names (phase 5 Weider) ──────────────────────────
    "D1: Chest + Abs": "D1: Pecho + Abs",
    "D2: Back + Abs": "D2: Espalda + Abs",
    "D3: Leg": "D3: Pierna",
    "D4: Shoulder + Abs": "D4: Hombro + Abs",
    "D5: Arms + Abs": "D5: Brazos + Abs",

    # ── Day names (phase 6 high intensity) ──────────────────
    "D1: Chest + Abs A": "D1: Pecho + Abs A",
    "D2: Back + Abs B": "D2: Espalda + Abs B",
    "D4: Shoulder + Abs A": "D4: Hombro + Abs A",
    "D5: Arms + Abs B": "D5: Brazos + Abs B",

    # ── Day names (phase 7 fat loss) ────────────────────────
    "W1-3: Chest-Biceps": "S1-3: Pecho-Bíceps",
    "W1-3: Back-Triceps": "S1-3: Espalda-Tríceps",
    "W1-3: Shoulder-Leg": "S1-3: Hombro-Pierna",
    "W4-6: Chest-Back (SS)": "S4-6: Pecho-Espalda (SS)",
    "W4-6: Shoulder-Leg (SS)": "S4-6: Hombro-Pierna (SS)",
    "W4-6: Arms (Antag. SS)": "S4-6: Brazos (SS Antag.)",

    # ── Day names (Upper / Lower routine) ───────────────────
    "Upper A: Push focus": "Torso A: Empuje",
    "Upper B: Pull focus": "Torso B: Tirón",
    "Lower A: Squat focus": "Pierna A: Sentadilla",
    "Lower B: Deadlift focus": "Pierna B: Peso Muerto",

    # ── Day names (Push / Pull / Legs routine) ──────────────
    "Push Day": "Día Empuje",
    "Pull Day": "Día Tirón",
    "Leg Day": "Día Pierna",

    # ── Day names (Women Fitness routine) ───────────────────
    "Glutes + Lower": "Glúteos + Pierna",
    "Upper Body": "Tren Superior",
    "Core + Cardio": "Core + Cardio",
    "Lower A: Glute focus": "Pierna A: Glúteo",
    "Upper + HIIT": "Superior + HIIT",
    "Lower B: Quad focus": "Pierna B: Cuádriceps",
    "Full Body + Core": "Full Body + Core",

    # ── Day names (Women — Home routine) ────────────────────
    "Upper at Home": "Superior en Casa",
    "Lower at Home": "Inferior en Casa",
    "Full Body Flow": "Full Body",

    # ── Day names (Women — Strength routine) ────────────────
    "Squat Day": "Día Sentadilla",
    "Bench Day": "Día Press Banca",
    "Deadlift Day": "Día Peso Muerto",
    "Press Day": "Día Press Militar",

    # ── Day names (Women — Volume routine) ──────────────────
    "Lower A: Quads": "Inferior A: Cuádriceps",
    "Upper A: Push": "Superior A: Empuje",
    "Lower B: Posterior": "Inferior B: Posterior",
    "Upper B: Pull": "Superior B: Tirón",

    # ── Muscle groups (catalog keys) ────────────────────────
    "Chest": "Pecho",
    "Back": "Espalda",
    "Shoulder": "Hombro",
    "Biceps": "Bíceps",
    "Triceps": "Tríceps",
    "Leg": "Pierna",
    "Abs": "Abdomen",
    "Cardio": "Cardio",

    # ── Exercises (canonical English → Spanish) ─────────────
    # Chest
    "Barbell Bench Press": "Press Banca Barra",
    "Smith Bench Press": "Press Banca Multipower",
    "Incline DB Press": "Press Inclinado Manc.",
    "Incline Machine Press": "Press Inclinado Máq.",
    "Decline Press": "Press Declinado",
    "Close-Grip Bench Press": "Press Banca Cerrado",
    "Smith Close-Grip Press": "Press Banca Cerrado Multi.",
    "Flat Machine Press": "Press Plano Máq.",
    "Incline DB Flyes": "Aperturas Inclinado Manc.",
    "Incline Flyes": "Aperturas Inclinado",
    "Machine Flyes": "Aperturas Máq.",
    "Pec Deck": "Contractora",
    "Cable Crossover": "Cruces en Polea",
    "Push-ups": "Flexiones",
    # Back
    "Front Lat Pulldown": "Jalones Frontales",
    "Behind-Neck Lat Pulldown": "Jalones Tras Nuca",
    "V-Grip Lat Pulldown": "Jalones Agarre V",
    "Pull-ups": "Dominadas",
    "Barbell Row": "Remo Barra",
    "DB Row": "Remo Manc.",
    "Seated Cable Row": "Remo Polea Sentado",
    "T-Bar Row": "Remo Barra T",
    "Machine Row": "Remo Máq.",
    "Reverse Barbell Row": "Remo Barra Invertido",
    "Deadlift": "Peso Muerto",
    "Romanian Deadlift": "Peso Muerto Rumano",
    # Shoulder
    "Barbell Military Press": "Press Militar Barra",
    "Smith Military Press": "Press Militar Multi.",
    "Seated DB Press": "Press Manc. Sentado",
    "DB Shoulder Press": "Press Hombros Manc.",
    "Arnold Press": "Press Arnold",
    "Lateral Raises": "Elevaciones Laterales",
    "Machine Lateral Raises": "Elev. Laterales Máq.",
    "Plate Front Raises": "Elev. Frontales Disco",
    "Standing Rear Delts": "Pájaros de Pie",
    "DB Rear Delts": "Pájaros Manc.",
    "Cable Rear Delts": "Pájaros Polea",
    "Upright Row": "Remo al Mentón",
    # Biceps
    "Straight Bar Curl": "Curl Barra Recta",
    "Barbell Curl": "Curl Barra",
    "EZ Bar Curl": "Curl Barra Z",
    "EZ Bar Preacher Curl": "Curl Scott Barra Z",
    "Alternate DB Curl": "Curl Manc. Alterno",
    "Simultaneous DB Curl": "Curl Manc. Simultáneo",
    "DB Curl": "Curl Manc.",
    "Hammer Curl": "Curl Martillo",
    "Alternate Hammer Curl": "Curl Martillo Alterno",
    "Cable Curl": "Curl Polea",
    "Incline DB Curl": "Curl Inclinado Manc.",
    "Reverse Curl": "Curl Invertido",
    # Triceps
    "EZ Bar Skull Crushers": "Press Francés Barra Z",
    "Skull Crushers": "Press Francés",
    "DB Skull Crushers": "Press Francés Manc.",
    "Rope Pushdown": "Jalones Cuerda",
    "Triceps Pushdown": "Jalones Tríceps",
    "Reverse Pushdown": "Jalones Inverso",
    "Parallel Bar Dips": "Fondos Paralelas",
    "Overhead Extension": "Extensión sobre Cabeza",
    "Triceps Kickback": "Patadas Tríceps",
    # Leg
    "Squat": "Sentadilla",
    "Leg Press": "Prensa Inclinada",
    "Leg Extensions": "Extensiones Máq.",
    "Lying Leg Curl": "Femoral Tumbado",
    "Seated Leg Curl": "Femoral Sentado",
    "Lunges": "Zancadas",
    "DB Lunges": "Splits Manc.",
    "Barbell Lunges": "Splits Barra",
    "Standing Calf Raise": "Gemelo de Pie",
    "Seated Calf Raise": "Gemelo Sentado",
    "Calf Press": "Gemelo Prensa",
    # Abs
    "Cable Crunch": "Crunch Polea",
    "Hanging Abs": "Abs Colgado",
    "Floor Crunch": "Encogimientos Suelo",
    "Floor Obliques": "Oblicuos Suelo",
    "Plank": "Plancha",
    "Leg Raises": "Elevación Piernas",
    "Hyperextensions": "Hiperextensiones",
    "Abs Triset": "Triserie Abs",
    # Cardio
    "Treadmill": "Cinta de Correr",
    "Bike": "Bicicleta",
    "Elliptical": "Elíptica",
    "HIIT Intervals": "HIIT Intervalos",

    # ── Day-of-week / month abbrev (shown via helpers) ──────
    # (handled by DAYS_OF_WEEK / MONTHS below)

    # ── Week rotation strings (plan.py distribution view) ───
    "Chest-Biceps": "Pecho-Bíceps",
    "Back-Triceps": "Espalda-Tríceps",
    "Shoulder-Leg": "Hombro-Pierna",
    "Chest-Biceps + Abs": "Pecho-Bíceps + Abs",
    "Back-Triceps + Abs": "Espalda-Tríceps + Abs",
    "Shoulder-Leg + Abs": "Hombro-Pierna + Abs",
    "Rest": "Descanso",

    # ── Composite / Phase-6 compound exercises ──────────────
    "V-Pulldown + V-Row": "Jalones V + Remo V",
    "Lying + Seated Leg Curl": "Femoral Tumb. + Sent.",
    "Calf Press + Seated": "Gemelo Prensa + Sent.",
    "Skull Crushers + Close-Grip": "Press Francés + Cerrado",

    # ── Phase-7 bi-sets / supersets / trisets ───────────────
    # W1-3 Chest-Biceps
    "Bi-set: Incline DB Press + Flat Machine Press":
        "BI: Press Inc. Manc. + Press Plano Máq.",
    "Bi-set: Incline Flyes + Machine Flyes":
        "BI: Aperturas Inc. + Aperturas Máq.",
    "Bi-set: Decline Press + Push-ups":
        "BI: Press Declinado + Flexiones",
    "Bi-set: Barbell Curl + Simultaneous DB Curl":
        "BI: Curl Barra + Curl Manc. Sim.",
    "Bi-set: EZ Preacher + Hammer Curl":
        "BI: Curl Scott Z + Curl Martillo",
    # W1-3 Back-Triceps
    "Bi-set: Front + Behind-Neck Pulldown":
        "BI: Jalones Front. + Tras Nuca",
    "Bi-set: V-Pulldown + Seated Row":
        "BI: Jalones V + Remo Sentado",
    "Bi-set: Machine Row + Reverse Barbell Row":
        "BI: Remo Máq. + Remo Barra Inv.",
    "Bi-set: Dips + Triceps Pushdown":
        "BI: Fondos + Jalones Tríceps",
    "Bi-set: Barbell + DB Skull Crushers":
        "BI: Press Francés Barra + Manc.",
    # W1-3 Shoulder-Leg
    "Bi-set: DB Press + Arnold Press":
        "BI: Press Manc. + Press Arnold",
    "Triset: Front + Lateral + Rear Delts":
        "TRI: Elev. Front. + Lat. + Pájaros",
    "Bi-set: Leg Press + Extensions":
        "BI: Prensa + Extensiones",
    "Bi-set: Romanian DL + Lying Leg Curl":
        "BI: PM Rumano + Femoral Tumb.",
    "Triset: Lunges + Seated + Standing Calf":
        "TRI: Splits + Gem. Sent. + Gem. Pie",
    # W4-6 Chest-Back SS
    "SS: Bench Press + Pull-ups":
        "SS: Press Banca + Dominadas",
    "SS: Incline DB Press + DB Row":
        "SS: Press Inc. Manc. + Remo Manc.",
    "SS: Machine Flyes + Machine Row":
        "SS: Aperturas Máq. + Remo Máq.",
    "SS: Cable Crossover + Behind-Neck Pulldown":
        "SS: Cruces Polea + Jalones Nuca",
    # W4-6 Shoulder-Leg SS
    "Bi-set: Military + Smith Press":
        "BI: Press Militar + Press Multi.",
    "Triset: Upright Row + Rear Delts + Lateral":
        "TRI: Remo Mentón + Pájaros + Lat.",
    "SS: Squat + Lying Leg Curl":
        "SS: Sentadilla + Femoral Tumb.",
    "SS: Leg Press + Romanian DL":
        "SS: Prensa + PM Rumano",
    "Triset: Standing + Seated + Press Calf":
        "TRI: Gemelo Pie + Sent. + Prensa",
    # W4-6 Arms antag. SS
    "SS: EZ Curl + EZ Skull Crushers":
        "SS: Curl Barra Z + Press Francés Z",
    "SS: Barbell Curl + Triceps Pushdown":
        "SS: Curl Barra + Jalones Tríceps",
    "SS: Incline DB Curl + Triceps Kickback":
        "SS: Curl Inc. Manc. + Patadas Tríc.",

    # ── Exercise detail dialog ──────────────────────────────
    "Primary": "Primario",
    "Secondary": "Secundario",
    "Equipment": "Equipo",
    "Level": "Nivel",
    "Type": "Tipo",
    "How to do it": "Cómo se hace",
    "Instructions in English": "Instrucciones en inglés",
    "Close": "Cerrar",
    "No details available": "Sin detalles disponibles",

    # Equipment values
    "barbell": "barra",
    "dumbbell": "mancuerna",
    "cable": "polea",
    "machine": "máquina",
    "body only": "peso corporal",
    "e-z curl bar": "barra Z",
    "bands": "bandas",
    "kettlebells": "kettlebells",
    "exercise ball": "pelota",
    "medicine ball": "balón medicinal",
    "other": "otro",
    "foam roll": "foam roll",
    "none": "ninguno",

    # Level
    "beginner": "principiante",
    "intermediate": "intermedio",
    "expert": "experto",

    # Mechanic
    "compound": "compuesto",
    "isolation": "aislamiento",

    # Muscles
    "chest": "pecho",
    "shoulders": "hombros",
    "triceps": "tríceps",
    "biceps": "bíceps",
    "forearms": "antebrazos",
    "lats": "dorsales",
    "middle back": "espalda media",
    "lower back": "lumbares",
    "traps": "trapecios",
    "neck": "cuello",
    "quadriceps": "cuádriceps",
    "hamstrings": "femoral",
    "glutes": "glúteos",
    "calves": "gemelos",
    "adductors": "aductores",
    "abductors": "abductores",
    "abdominals": "abdominales",

    # ── Misc tokens used by t_exercise ──────────────────────
    "to failure": "al fallo",
    "max": "máx",
}


DAYS_OF_WEEK = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "es": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"],
}

MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "es": ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
           "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"],
}

WEEKDAY_LABELS = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "es": ["Lun", "Mar", "Mié", "Jue", "Vie"],
}


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in ("en", "es") else "en"


def get_language() -> str:
    return _lang


def t(text: str) -> str:
    """Translate text to active language. Returns input unchanged if unknown."""
    if not text or _lang == "en":
        return text
    return ES.get(text, text)


import re as _re

# Tokens that appear inside scheme/modifier brackets.
_BRACKET_EN_TO_ES = [
    ("max", "máx"),
    ("failure", "fallo"),
    ("triple drop", "triple desc"),
    ("comp", "comp"),  # identical; listed for discoverability
]
_EXERCISE_BRACKETS_RE = _re.compile(r"^(.*?)((?:\s*\[[^\]]*\])*)\s*$")


def exercise_key(s: str) -> str:
    """Canonical DB key: strips trailing [..] brackets and trailing `*`."""
    m = _EXERCISE_BRACKETS_RE.match(s)
    name = m.group(1).rstrip() if m else s
    if name.endswith("*"):
        name = name[:-1].rstrip()
    return name


def t_exercise(s: str) -> str:
    """Translate an exercise entry, preserving trailing `[..]` brackets and `*`.

    Handles formats like:
      - "Barbell Row"
      - "Pec Deck *"
      - "Squat [5×12,10,8,8,8]"
      - "Hanging Abs [5×max]"
      - "V-Pulldown + V-Row [comp] [4×8+8]"
      - "Cable Curl [triple drop] [2×10+10+10]"
    """
    m = _EXERCISE_BRACKETS_RE.match(s)
    if not m:
        return s
    name = m.group(1).rstrip()
    brackets = m.group(2).strip()
    star = ""
    if name.endswith("*"):
        name = name[:-1].rstrip()
        star = " *"
    if _lang != "en":
        for en, es in _BRACKET_EN_TO_ES:
            brackets = brackets.replace(en, es)
    return t(name) + star + (f" {brackets}" if brackets else "")


def day_name(idx: int) -> str:
    return DAYS_OF_WEEK[_lang][idx]


def month_name(idx: int) -> str:
    return MONTHS[_lang][idx]


def weekday_label(idx: int) -> str:
    return WEEKDAY_LABELS[_lang][idx]
