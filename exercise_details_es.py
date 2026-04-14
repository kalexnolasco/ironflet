"""Instrucciones en español para cada ejercicio (concisas, propias).

Keyed por el slug de Free Exercise DB. Se usan cuando el idioma activo es
español; si un slug no tiene entrada, la UI cae al inglés original.
"""

from __future__ import annotations


INSTRUCTIONS_ES: dict[str, list[str]] = {
    # ── Chest / Pecho ─────────────────────────────────────────
    "Barbell_Bench_Press_-_Medium_Grip": [
        "Túmbate en el banco con los pies firmes y escápulas retraídas.",
        "Agarra la barra con un agarre medio (manos ligeramente más anchas que los hombros).",
        "Baja controlado hasta rozar el pecho, inspirando.",
        "Empuja hacia arriba hasta extender los codos, espirando.",
        "Mantén los glúteos pegados al banco durante todo el movimiento.",
    ],
    "Smith_Machine_Bench_Press": [
        "Coloca un banco plano bajo la barra del multipower.",
        "Túmbate con los ojos justo debajo de la barra y agarra con manos separadas al ancho de hombros + 2 dedos.",
        "Desbloquea y baja la barra controlada hasta tocar el pecho.",
        "Empuja hacia arriba hasta casi bloquear los codos.",
        "Al terminar, gira las muñecas para bloquear la barra en los ganchos.",
    ],
    "Incline_Dumbbell_Press": [
        "Ajusta el banco a 30-45°; siéntate con una mancuerna en cada mano sobre los muslos.",
        "Súbelas a los hombros con impulso de rodilla y colócalas con las palmas hacia delante.",
        "Baja las mancuernas hacia los laterales del pecho, codos a ~45°.",
        "Empuja hacia arriba juntándolas ligeramente sin chocar.",
        "Repite; para terminar, deja caer las mancuernas a los muslos.",
    ],
    "Smith_Machine_Incline_Bench_Press": [
        "Ajusta el banco inclinado a 30-45° bajo la barra del multipower.",
        "Agarra la barra con agarre medio y desbloquéala.",
        "Baja controlado hasta la parte alta del pecho.",
        "Empuja hacia arriba hasta casi bloquear.",
        "Bloquea la barra en los ganchos antes de bajar del banco.",
    ],
    "Machine_Bench_Press": [
        "Ajusta el asiento para que las asas queden a la altura del pecho.",
        "Siéntate con espalda firme contra el respaldo.",
        "Agarra las asas con las palmas hacia delante.",
        "Empuja hacia delante extendiendo los brazos sin bloquear.",
        "Vuelve lento al punto de partida sintiendo la elongación del pecho.",
    ],
    "Decline_Dumbbell_Bench_Press": [
        "Siéntate en un banco declinado y fija los pies.",
        "Coloca las mancuernas a los lados del pecho.",
        "Túmbate y alinea las mancuernas al exterior del pecho.",
        "Empuja hacia arriba juntándolas ligeramente arriba.",
        "Baja controlado manteniendo tensión en el pecho.",
        "Termina devolviendo las mancuernas a los muslos con cuidado.",
    ],
    "Close-Grip_Barbell_Bench_Press": [
        "Túmbate en un banco plano con los pies firmes.",
        "Agarra la barra con las manos a la anchura de los hombros (no pegadas).",
        "Baja la barra controlada hacia la parte baja del pecho con los codos cerca del torso.",
        "Empuja hacia arriba activando el tríceps.",
        "No sacrifiques el rango por cerrar más el agarre.",
    ],
    "Incline_Dumbbell_Flyes": [
        "Ajusta el banco a 30° y siéntate con una mancuerna en cada mano.",
        "Túmbate y súbelas con las palmas enfrentadas y ligera flexión de codos.",
        "Abre los brazos en arco hasta sentir el estiramiento del pecho.",
        "Sube juntando las mancuernas en arco sin cambiar el ángulo del codo.",
        "Aprieta el pecho arriba un segundo.",
        "El codo NO se bloquea ni cambia su flexión durante la serie.",
    ],
    "Butterfly": [
        "Ajusta el asiento para que las asas queden a la altura del hombro.",
        "Siéntate con espalda pegada y agarra las asas con codos ligeramente flexionados.",
        "Cierra los brazos al frente hasta juntar las asas apretando el pecho.",
        "Vuelve lento sintiendo la elongación sin perder tensión.",
        "Mantén los codos a la misma altura que los hombros todo el tiempo.",
    ],
    "Cable_Crossover": [
        "Coloca ambas poleas en alto y agarra un agarre en cada mano.",
        "Da un paso al frente con un pie adelantado y torso ligeramente inclinado.",
        "Con los codos ligeramente flexionados, junta las manos al frente abajo cruzándolas.",
        "Aprieta el pecho abajo un segundo.",
        "Vuelve lento dejando que los brazos se abran en arco.",
    ],
    "Pushups": [
        "Apóyate en el suelo con manos a la anchura de los hombros y cuerpo en línea recta.",
        "Baja controlado hasta casi rozar el pecho con el suelo, codos a ~45°.",
        "Empuja hacia arriba sin bloquear los codos ni perder la línea del cuerpo.",
        "Si es muy duro, apoya las rodillas; si es muy fácil, eleva los pies.",
    ],

    # ── Back / Espalda ────────────────────────────────────────
    "Wide-Grip_Lat_Pulldown": [
        "Siéntate con los muslos bajo el apoyo y agarra la barra con agarre ancho en pronación.",
        "Inclina ligeramente el torso hacia atrás (~15°) y saca pecho.",
        "Tira de la barra hacia la parte alta del pecho juntando los omóplatos.",
        "Sube lento permitiendo que los dorsales se elonguen sin encoger hombros.",
        "No balancees el torso para tirar más peso.",
        "Mantén los codos hacia abajo, no hacia atrás.",
    ],
    "Reverse_Grip_Bent-Over_Rows": [
        "Agarra la barra con las palmas hacia arriba, manos a la anchura de los hombros.",
        "Inclina el torso hacia delante a ~45° con rodillas ligeramente flexionadas.",
        "Tira de la barra hacia el ombligo apretando la espalda.",
        "Baja controlado hasta casi extender los brazos.",
        "Mantén la espalda neutra durante toda la serie.",
    ],
    "V-Bar_Pulldown": [
        "Engancha un agarre en V a la polea alta.",
        "Siéntate con muslos fijados y agarra con palmas enfrentadas.",
        "Tira del agarre hacia la parte alta del pecho manteniendo el torso firme.",
        "Aprieta los dorsales en la parte baja.",
        "Sube lento controlando el peso.",
        "Codos cerca del torso durante toda la trayectoria.",
    ],
    "Pullups": [
        "Cuélgate de la barra con agarre prono a la anchura de los hombros o un poco más.",
        "Sube tirando con la espalda hasta que la barbilla supere la barra.",
        "Baja lento hasta extender casi por completo los brazos.",
        "No balancees el cuerpo para ganar impulso.",
        "Si es muy duro, usa banda elástica o máquina asistida.",
    ],
    "Bent_Over_Barbell_Row": [
        "Coge la barra con agarre prono ligeramente más ancho que los hombros.",
        "Inclina el torso a ~45°, rodillas un poco flexionadas y espalda neutra.",
        "Tira de la barra hacia el bajo abdomen apretando los omóplatos.",
        "Baja lento hasta casi extender los brazos.",
        "No curves la espalda en ningún momento.",
    ],
    "One-Arm_Dumbbell_Row": [
        "Coloca una rodilla y la mano del mismo lado sobre un banco, espalda plana.",
        "Con el otro brazo agarra una mancuerna a brazo extendido.",
        "Tira de la mancuerna hacia la cadera llevando el codo hacia atrás.",
        "Aprieta arriba, bajo control.",
        "Baja lento extendiendo el brazo sin perder la postura.",
        "Repite las reps y cambia de lado.",
        "No gires el torso para ayudarte.",
    ],
    "Bent_Over_Two-Dumbbell_Row": [
        "Agarra una mancuerna en cada mano con palmas enfrentadas.",
        "Inclina el torso a ~45° con rodillas algo flexionadas y espalda neutra.",
        "Tira de ambas mancuernas hacia las caderas apretando la espalda.",
        "Baja lento extendiendo los brazos sin perder la postura del torso.",
    ],
    "Seated_Cable_Rows": [
        "Siéntate con los pies en los apoyos y agarra el agarre en V.",
        "Saca pecho y mantén espalda neutra con una ligera inclinación hacia atrás.",
        "Tira del agarre hacia el abdomen llevando los codos atrás.",
        "Aprieta los omóplatos al final del movimiento.",
        "Vuelve lento sin encoger la espalda.",
    ],
    "T-Bar_Row_with_Handle": [
        "Colócate a horcajadas sobre la barra con rodillas flexionadas y torso a ~45°.",
        "Engancha el agarre bajo la barra.",
        "Tira de la barra hacia el pecho apretando los dorsales.",
        "Baja lento hasta casi extender los brazos.",
        "Mantén la espalda plana durante toda la serie.",
    ],
    "Face_Pull": [
        "Ajusta la polea a la altura de la cara con cuerda. Tira de la cuerda hacia la cara abriendo los codos y juntando los omóplatos; baja lento.",
    ],
    "Reverse_Flyes": [
        "Siéntate en el borde de un banco con torso inclinado a ~45°.",
        "Agarra una mancuerna en cada mano con palmas enfrentadas.",
        "Abre los brazos en arco hacia los lados hasta sentir los deltoides posteriores.",
        "Aprieta arriba con codos ligeramente flexionados.",
        "Baja lento sin balancearte.",
        "Evita usar el trapecio para subir.",
    ],
    "Barbell_Deadlift": [
        "Colócate con los pies a la anchura de las caderas y la barra sobre el medio pie.",
        "Flexiona caderas y rodillas; agarra la barra justo fuera de las piernas.",
        "Saca pecho, espalda neutra y tensa el core.",
        "Levanta la barra extendiendo caderas y rodillas a la vez.",
        "Baja controlado guiando la barra cerca de las piernas.",
    ],
    "Romanian_Deadlift": [
        "De pie con la barra al frente y rodillas ligeramente flexionadas.",
        "Agarra con manos a la anchura de los hombros y espalda neutra.",
        "Baja la barra empujando las caderas hacia atrás hasta sentir el femoral.",
        "La barra debe rozar las piernas durante todo el descenso.",
        "Sube extendiendo caderas sin arquear la zona lumbar.",
    ],

    # ── Shoulder / Hombro ─────────────────────────────────────
    "Standing_Military_Press": [
        "De pie con la barra apoyada en la parte superior del pecho.",
        "Pies a la anchura de las caderas, core y glúteos firmes.",
        "Empuja la barra hacia arriba hasta extender los brazos sobre la cabeza.",
        "Mueve ligeramente la cabeza hacia atrás al principio y vuelve a alineación arriba.",
        "Baja controlado al punto inicial.",
        "Evita arquear la zona lumbar.",
    ],
    "Smith_Machine_Overhead_Shoulder_Press": [
        "Siéntate en un banco con respaldo vertical bajo la barra del multipower.",
        "Agarra la barra con manos un poco más anchas que los hombros.",
        "Desbloquea y baja controlada hasta la parte alta del pecho.",
        "Empuja hacia arriba sin bloquear los codos.",
        "Bloquea la barra en los ganchos al terminar.",
    ],
    "Seated_Dumbbell_Press": [
        "Siéntate en un banco con respaldo vertical, mancuerna en cada mano.",
        "Súbelas a la altura de los hombros con las palmas hacia delante.",
        "Empuja hacia arriba hasta casi juntar las mancuernas sin bloquear codos.",
        "Baja controlado a la altura de los hombros.",
        "Mantén el torso firme contra el respaldo.",
        "Evita que los codos caigan muy por detrás del cuerpo.",
    ],
    "Arnold_Dumbbell_Press": [
        "Siéntate con respaldo vertical y mancuernas frente a los hombros, palmas hacia ti.",
        "Empieza a empujar y, a medio recorrido, gira las muñecas hasta palmas hacia delante arriba.",
        "Extiende arriba sin bloquear codos.",
        "Invierte el giro al bajar para volver a la posición inicial.",
        "Mantén movimiento controlado en todo momento.",
    ],
    "Side_Lateral_Raise": [
        "De pie o sentado, una mancuerna en cada mano a los lados.",
        "Con los codos ligeramente flexionados, abre los brazos en arco hasta la altura de los hombros.",
        "Mantén un segundo arriba sin encoger el trapecio.",
        "Baja lento controlando la bajada.",
    ],
    "Front_Plate_Raise": [
        "De pie, sujeta un disco con ambas manos delante de los muslos.",
        "Con los brazos extendidos y codos sin bloquear, levanta el disco al frente hasta la altura de los ojos.",
        "Aprieta el deltoides anterior un segundo arriba.",
        "Baja controlado a la posición inicial.",
    ],
    "Upright_Barbell_Row": [
        "De pie con la barra delante, agarre estrecho (palmas hacia ti).",
        "Tira de la barra hacia la barbilla llevando los codos arriba y hacia afuera.",
        "Los codos siempre por encima de las manos durante la subida.",
        "Baja controlado sin dejar caer la barra.",
    ],

    # ── Biceps / Bíceps ───────────────────────────────────────
    "Barbell_Curl": [
        "De pie con la barra en agarre supino, manos a la anchura de los hombros.",
        "Codos pegados al torso fijos.",
        "Flexiona los codos subiendo la barra hasta casi tocar los hombros.",
        "Aprieta el bíceps arriba un segundo.",
        "Baja lento extendiendo los brazos sin rebote.",
    ],
    "EZ-Bar_Curl": [
        "De pie con la barra Z en agarre supino en el codo interior de la Z.",
        "Codos pegados al torso y fijos.",
        "Sube la barra hasta casi tocar los hombros flexionando solo los codos.",
        "Baja lento con control sin bloquear los codos.",
        "Evita balancear el torso para ayudar.",
    ],
    "Preacher_Curl": [
        "Siéntate en el banco Scott con los brazos apoyados sobre el cojín.",
        "Agarra la barra Z en agarre supino con las axilas contra el cojín.",
        "Sube la barra flexionando los codos hasta que antebrazos queden casi verticales.",
        "Baja lento extendiendo los brazos pero sin bloquear del todo.",
        "No levantes los codos del cojín en ningún momento.",
    ],
    "Dumbbell_Bicep_Curl": [
        "De pie con una mancuerna en cada mano, palmas enfrentadas.",
        "Manteniendo los codos pegados, sube ambas mancuernas girando las palmas hacia arriba a medio recorrido.",
        "Aprieta el bíceps arriba; baja lento invirtiendo el giro.",
        "Evita balancear el torso.",
    ],
    "Alternate_Incline_Dumbbell_Curl": [
        "Siéntate en un banco inclinado a ~45° con mancuernas colgando, palmas enfrentadas.",
        "Sube una mancuerna girando la palma hacia arriba, el otro brazo estático.",
        "Aprieta arriba un segundo y baja lento.",
        "Repite con el otro brazo; cada ciclo es una repetición.",
        "Mantén el codo pegado al torso; solo se mueve el antebrazo.",
    ],
    "Hammer_Curls": [
        "De pie con una mancuerna en cada mano y palmas enfrentadas (agarre neutro).",
        "Codos pegados al torso fijos durante todo el movimiento.",
        "Sube las mancuernas hacia los hombros sin rotar las palmas.",
        "Aprieta arriba un segundo.",
        "Baja lento controlando la bajada.",
    ],
    "Incline_Dumbbell_Curl": [
        "Siéntate en un banco inclinado a 45° con mancuernas colgando, palmas enfrentadas.",
        "Sube las mancuernas girando las palmas hacia arriba durante la subida.",
        "Aprieta arriba sin levantar los codos del respaldo.",
        "Baja lento y controlado invirtiendo el giro.",
    ],
    "Standing_Biceps_Cable_Curl": [
        "De pie frente a una polea baja con una barra recta enganchada.",
        "Agárrala con agarre supino, codos pegados al torso.",
        "Sube la barra flexionando los codos hasta casi tocar los hombros.",
        "Baja lento sin dejar caer el peso.",
    ],
    "Reverse_Barbell_Curl": [
        "De pie con la barra en agarre prono (palmas hacia abajo), manos al ancho de los hombros.",
        "Codos pegados al torso y fijos.",
        "Sube la barra flexionando solo los codos.",
        "Baja lento controlando el peso.",
    ],

    # ── Triceps / Tríceps ─────────────────────────────────────
    "EZ-Bar_Skullcrusher": [
        "Túmbate en un banco plano con barra Z en agarre cerrado supino.",
        "Extiende los brazos al frente con la barra sobre el pecho.",
        "Baja la barra hacia la frente flexionando solo los codos; codos fijos apuntando arriba.",
        "Extiende hacia arriba activando el tríceps sin mover los codos.",
    ],
    "Lying_Triceps_Press": [
        "Túmbate en un banco plano con una mancuerna en cada mano.",
        "Extiende los brazos al frente con las palmas enfrentadas.",
        "Baja las mancuernas hacia los lados de la cabeza flexionando solo los codos.",
        "Mantén los codos apuntando arriba (no se abren).",
        "Extiende hacia arriba apretando el tríceps.",
    ],
    "Triceps_Pushdown": [
        "De pie frente a una polea alta con cuerda o barra.",
        "Codos pegados al torso y fijos.",
        "Empuja hacia abajo extendiendo solo los antebrazos.",
        "Aprieta abajo un segundo con los codos bloqueados.",
        "Sube lento controlando el peso sin levantar los codos.",
    ],
    "Reverse_Grip_Triceps_Pushdown": [
        "De pie frente a una polea alta con barra recta.",
        "Agárrala en supino (palmas arriba) con manos al ancho de los hombros.",
        "Codos pegados al torso y fijos.",
        "Empuja hacia abajo extendiendo los antebrazos.",
        "Sube lento controlando sin encoger los hombros.",
    ],
    "Dips_-_Triceps_Version": [
        "Sujétate en paralelas con los brazos extendidos y torso vertical.",
        "Baja flexionando los codos hasta ~90°, codos cerca del cuerpo.",
        "Empuja hacia arriba extendiendo los codos.",
        "Mantén el torso lo más vertical posible (inclinación mínima) para aislar el tríceps.",
    ],
    "Standing_Dumbbell_Triceps_Extension": [
        "De pie, agarra una mancuerna con ambas manos por el extremo superior.",
        "Súbela por encima de la cabeza con los brazos extendidos.",
        "Baja la mancuerna tras la nuca flexionando solo los codos; codos apuntan al techo.",
        "Extiende hacia arriba apretando el tríceps.",
        "Mantén los codos cerca de la cabeza durante todo el rango.",
    ],
    "Tricep_Dumbbell_Kickback": [
        "Apoya una mano y una rodilla en un banco, espalda paralela al suelo.",
        "Con la otra mano agarra una mancuerna, brazo pegado al torso y codo flexionado a 90°.",
        "Extiende el codo hacia atrás hasta que el brazo quede recto.",
        "Vuelve lento a 90° sin mover el hombro.",
    ],

    # ── Leg / Pierna ──────────────────────────────────────────
    "Barbell_Squat": [
        "Apoya la barra sobre los trapecios (o más baja sobre las posteriores del hombro).",
        "Pies a la anchura de los hombros o un poco más, puntas ligeramente hacia fuera.",
        "Saca pecho y tensa el core.",
        "Baja flexionando caderas y rodillas hasta que los muslos queden paralelos al suelo o por debajo.",
        "Sube empujando a través de los talones sin colapsar las rodillas hacia dentro.",
        "Mantén la mirada al frente y la espalda neutra.",
    ],
    "Leg_Press": [
        "Siéntate en la máquina con la espalda firme contra el respaldo.",
        "Pies a la anchura de los hombros en la plataforma.",
        "Desbloquea y baja lento flexionando rodillas hacia el pecho.",
        "Empuja con los talones hasta casi extender sin bloquear las rodillas.",
        "Mantén las lumbares pegadas al respaldo durante toda la serie.",
    ],
    "Leg_Extensions": [
        "Siéntate en la máquina con las espinillas detrás del rodillo.",
        "Ajusta el respaldo para que las rodillas queden alineadas con el eje.",
        "Extiende las rodillas hasta casi bloquear apretando los cuádriceps.",
        "Baja lento controlando el peso.",
    ],
    "Lying_Leg_Curls": [
        "Túmbate boca abajo con las espinillas bajo el rodillo.",
        "Ajusta para que el rodillo quede a la altura de los tobillos.",
        "Flexiona las rodillas llevando los talones hacia los glúteos.",
        "Baja lento hasta casi extender.",
    ],
    "Seated_Leg_Curl": [
        "Siéntate con las piernas extendidas sobre el rodillo inferior.",
        "Ajusta el apoyo superior sobre los muslos.",
        "Flexiona las rodillas empujando el rodillo hacia abajo.",
        "Aprieta el femoral un segundo abajo.",
        "Sube lento controlando el peso.",
    ],
    "Bodyweight_Walking_Lunge": [
        "De pie con los pies a la anchura de las caderas, manos en las caderas.",
        "Da un paso largo al frente y baja hasta que la rodilla trasera casi roce el suelo.",
        "Empuja con el talón del pie delantero para levantarte y avanzar el pie trasero.",
        "Alterna piernas de forma continua.",
    ],
    "Dumbbell_Lunges": [
        "De pie con una mancuerna en cada mano a los lados.",
        "Da un paso largo al frente y baja la rodilla trasera hacia el suelo.",
        "Empuja con el talón delantero para volver a la posición inicial.",
        "Alterna piernas; mantén el torso erguido.",
    ],
    "Barbell_Walking_Lunge": [
        "Coloca la barra sobre los trapecios como en la sentadilla.",
        "Da un paso largo al frente y baja la rodilla trasera hacia el suelo.",
        "Empuja con el talón delantero para levantarte y avanzar el pie trasero.",
        "Mantén el torso erguido y la espalda neutra.",
    ],
    "Standing_Barbell_Calf_Raise": [
        "Coloca la barra sobre los trapecios como en la sentadilla.",
        "Apoya la parte delantera de los pies en una plataforma con los talones libres.",
        "Baja los talones lentamente estirando los gemelos.",
        "Sube a puntillas lo máximo posible apretando los gemelos.",
        "Aguanta arriba un segundo.",
        "Mantén las rodillas prácticamente bloqueadas.",
    ],
    "Seated_Calf_Raise": [
        "Siéntate en la máquina con los muslos bajo el rodillo.",
        "Apoya la parte delantera de los pies en la plataforma.",
        "Deja caer los talones despacio para estirar.",
        "Sube a puntillas apretando los gemelos.",
        "Aguanta arriba; baja lento.",
        "Usa el rango completo en cada repetición.",
    ],
    "Calf_Press": [
        "Siéntate en la prensa y apoya los pies en la parte baja de la plataforma con los talones por fuera.",
        "Desbloquea y deja que los tobillos se flexionen lentamente bajando los talones.",
        "Empuja con las puntas hasta flexionar por completo los tobillos.",
        "Rango completo en cada repetición.",
    ],

    # ── Abs / Abdomen ─────────────────────────────────────────
    "Crunches": [
        "Túmbate boca arriba con rodillas flexionadas y pies apoyados.",
        "Coloca las manos detrás de las orejas o cruzadas al pecho.",
        "Despega solo los hombros del suelo flexionando el abdomen.",
        "Aprieta arriba un segundo sin tirar del cuello.",
        "Baja lento manteniendo tensión en el abdomen.",
        "Mantén la zona lumbar apoyada todo el tiempo.",
    ],
    "Cable_Crunch": [
        "Arrodíllate frente a una polea alta con cuerda.",
        "Agarra la cuerda a ambos lados de la cabeza.",
        "Con las caderas fijas, flexiona el tronco hacia delante acercando los codos a los muslos.",
        "Aprieta el abdomen abajo.",
        "Sube lento manteniendo tensión en el abdomen.",
        "No uses el peso del cuerpo; el movimiento sale del abdomen.",
    ],
    "Hanging_Leg_Raise": [
        "Cuélgate de una barra con agarre prono.",
        "Con las piernas juntas, elévalas al frente flexionando las caderas hasta que queden paralelas al suelo o más arriba.",
        "Baja lento sin balancearte.",
        "Mantén el core tenso durante todo el recorrido.",
    ],
    "Oblique_Crunches": [
        "Túmbate de lado con las rodillas flexionadas.",
        "Coloca la mano del lado apoyado en el suelo y la otra detrás de la oreja.",
        "Despega el hombro superior del suelo acercando el codo a la cadera.",
        "Aprieta el oblicuo arriba.",
        "Baja lento sin tirar del cuello.",
        "Termina las reps y cambia de lado.",
        "Movimiento pequeño pero con alta contracción.",
    ],
    "Plank": [
        "Apóyate en los antebrazos y puntas de los pies con el cuerpo alineado.",
        "Aprieta glúteos y abdomen; mantén la posición el tiempo objetivo sin hundir la cadera.",
    ],
    "Hyperextensions_Back_Extensions": [
        "Ajusta el banco romano para que las caderas queden justo fuera del apoyo.",
        "Fija los tobillos bajo los rodillos.",
        "Cruza los brazos al pecho y mantén espalda neutra.",
        "Baja el torso flexionando las caderas hasta ~90°.",
        "Sube extendiendo las caderas hasta alinear el cuerpo.",
        "No hiperextiendas la zona lumbar arriba.",
    ],

    # ── Cardio ────────────────────────────────────────────────
    "Jogging_Treadmill": [
        "Selecciona una velocidad de trote cómoda; calienta 2-3 min andando.",
        "Trota manteniendo pisada natural y respiración controlada.",
    ],
    "Bicycling_Stationary": [
        "Ajusta el sillín para que al pedalear la rodilla quede ligeramente flexionada abajo.",
        "Pedalea a cadencia estable; sube la resistencia cuando se haga cómodo.",
    ],
    "Elliptical_Trainer": [
        "Colócate con los pies sobre los pedales y las manos en las asas.",
        "Pedalea con movimiento fluido; cambia el sentido a la mitad para variar.",
    ],
    "Air_Bike": [
        "Túmbate con la zona lumbar pegada al suelo y manos detrás de las orejas.",
        "Eleva los hombros en crunch y sube las rodillas a 90°.",
        "Pedalea alternando: lleva el codo derecho a la rodilla izquierda.",
        "Cambia de lado: codo izquierdo a rodilla derecha.",
        "No tires del cuello; el movimiento sale del abdomen.",
        "Mantén ritmo controlado hasta completar todas las reps.",
    ],
}


def instructions_es(slug: str) -> list[str] | None:
    return INSTRUCTIONS_ES.get(slug)
