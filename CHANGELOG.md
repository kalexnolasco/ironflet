# Changelog

Todos los cambios notables de IronFlet.
El formato sigue [Keep a Changelog](https://keepachangelog.com/) y el proyecto
usa [SemVer](https://semver.org/).

## [0.9.0] — 2026-08-20

**El coach va por OpenRouter y eliges el modelo.** Una sola clave y ~350
modelos, Claude incluido, con sus precios traídos en vivo.

### Añadido

- **Desplegable de modelos** en Ajustes: una lista corta (Opus 5, Sonnet 5,
  Haiku 4.5, GPT-4.1 mini, Gemini 2.5 Flash, Llama 3.3 70B) más un botón
  **"All 350…"** con buscador sobre el catálogo completo, ordenado de más
  barato a más caro.
- **Los precios no están escritos en el código.** Se leen del catálogo de
  OpenRouter, que es público y no necesita clave — así que puedes mirar lo que
  cuesta cada cosa antes de pagar nada. Debajo de cada respuesta sale lo que
  OpenRouter dice que **cobró de verdad**, no una estimación nuestra.
- Solo aparecen los modelos que soportan herramientas (348 de 417). Los otros 69
  se verían bien en la lista y luego romperían el coach en silencio: sin
  herramientas no puede leer ni un dato tuyo, y contestaría de memoria.

### La APK adelgaza 11 MB

83,2 → **72,3 MB**, y el motivo importa más que el número: fuera el SDK de
Anthropic, y con él `pydantic-core` y `jiter`, las **dos únicas extensiones en
Rust** que quedaban. Llegaban al móvil solo porque pypi.flet.dev publica una
rueda `cp312-android_24_arm64_v8a` para cada una — una apuesta a que un tercero
siga compilando para una ABI que casi nadie usa, en una app que se instala a
mano y no se puede parchear desde el gimnasio. Ahora la lista de dependencias
de Android no lleva **nada compilado de terceros**: `httpx` y sus 8 paquetes son
Python puro.

### Lo que no cambió

Las herramientas, la tarjeta de confirmación y la garantía de que **el coach no
puede escribir en tu historial**. Solo se movió el transporte — 33 líneas de 53
funciones.

### Arreglado

- Tres pantallas seguían diciendo "Anthropic API key" y sugiriendo `sk-ant-`
  después del cambio. La app funcionaba perfectamente mientras te pedía el tipo
  de clave equivocado. Ahora hay un test que lo impide.
- Cinco tests estaban **duplicados** y el segundo tapaba al primero, así que no
  se ejecutaban. Los cazó ruff, no la suite en verde.

## [0.8.0] — 2026-08-20

**Home es tu día entero.** Al abrir la app: qué sesión toca, el botón para
empezarla, y debajo peso, cintura, comida contra objetivo y lo que el bot aún te
va a mandar hoy.

### Añadido

- **Panel "Your day"** en Home. Peso (¿te has pesado hoy? media de 7 días y
  ritmo en kg/semana) y **cintura** (valor, cuántos días tiene, y cuánto se ha
  movido). Los estados vacíos son accionables: *"never logged · tap to add"*.
- **Ajustes → Waist**: apuntar la cintura. Hacía falta porque no lo capturaba
  nada — el bot tiene la herramienta pero ni comando ni recordatorio, y la tabla
  `medidas` está vacía con el plan ya en marcha.
- **Tarjeta de avisos**: lo que el bot todavía va a enviar hoy, con los
  atrasados marcados. Solo cuando hay PostgreSQL detrás.
- `analytics.weight_trend()` y `analytics.waist_summary()`.
- Las tablas `medidas` y `recordatorios` ahora también se declaran en la app.

### La cintura no lleva veredicto, y es a propósito

El plan dice el ±1 cm **dos veces y no coinciden**: en los objetivos, "respecto a
la medición inicial"; en las reglas de ajuste, la revisión quincenal. En un
volumen limpio que funciona dan respuestas distintas. Así que se muestran las
dos, etiquetadas, y ninguna se convierte en un semáforo. Elegir una en silencio
haría de esta pantalla el primer sitio del sistema donde una regla ambigua se
vuelve un número sobre el que actúas.

Tampoco hay línea de tendencia: el ruido de la cinta métrica es ~±0,5 cm, la
mitad del umbral.

### Arreglado

- **El ritmo en kg/semana estaba implementado tres veces** — un método privado
  de la pantalla de Perfil (que Home no podía importar), una copia distinta
  dentro del coach, y Home iba a ser la tercera. Es el número por el que se guía
  todo el plan. Ahora vive una sola vez, en `analytics.py`.
- **El coach reventaba al preguntar por el peso** con dos o más pesajes:
  leía `["average"]` de una función que devuelve `{"date", "kg"}`. El test tenía
  un solo pesaje, así que la rama nunca se ejecutaba.
- **El coach etiquetaba el grupo muscular con otro vocabulario** que la pantalla
  de entreno (`Leg` frente a `Shoulder-Leg`), archivando la misma sesión de dos
  maneras.
- Borrados los dos recordatorios de prueba de producción (ya estaban inactivos,
  así que no iban a dispararse — eran suciedad en la lista).

### Sabido

- En el móvil no hay tarjeta de avisos: los escribe el bot en PostgreSQL desde
  el PC. El panel se apaga por backend, no por lista vacía, para que no salga
  una caja vacía permanente que parezca un fallo.
- La APK sigue en 83 MB porque lleva tres arquitecturas. Con una sola son
  **29,8 MB** (`flet build apk --arch arm64-v8a`), pero con dos el build sale
  roto — ver el aviso en `pyproject.toml`.

## [0.7.0] — 2026-08-20

**El entrenador vive dentro de la app.** Le hablas, te contesta sobre tus
propios datos, y te aconseja con el plan de 24 semanas delante. Corre contra la
API de Claude con tu clave, así que funciona desde el gimnasio sin depender del
PC ni de Telegram.

### Añadido

- **Pantalla Coach** (icono de bocadillo en Home). Tres cosas:
  - *Registrar hablando.* «Hice 4 series de sentadilla a 100 por 5» y te
    aparece una tarjeta con lo que ha entendido.
  - *Preguntar por tus datos.* Historial de un ejercicio, la semana, el peso
    corporal y su media de 7 días, calorías y macros contra el objetivo.
  - *Aconsejar con el plan delante.* Sabe en qué fase y semana estás, qué
    prescribe la rutina hoy y qué llevas ya registrado.
- **La clave API se escribe en Ajustes → Coach**, una vez. Se guarda en el
  almacenamiento privado de la app. Puedes elegir modelo (Opus 5 / Sonnet 5 /
  Haiku 4.5) y cuánto piensa. Debajo de cada respuesta sale el coste aproximado.
- `Storage.replace_workout()` — guarda sustituyendo la fila que ya hubiera de
  ese ejercicio ese día, en vez de añadir otra.

### El agente no puede escribir en tu historial

No es que se le pida que no lo haga: **no tiene ninguna herramienta que
escriba**. Registrar es una *propuesta* — valida lo que entendió y devuelve una
tarjeta; la fila la escribe el botón Guardar que pulsas tú. Aunque el modelo se
salte el prompt entero o entienda mal un peso, lo peor que puede hacer es poner
una tarjeta equivocada en pantalla.

Se avisó de que hablarle a una máquina de tus series es la forma más fácil de
acabar con un número que nunca levantaste en el log. Esta es la respuesta a eso,
y es estructural, no una promesa. `tests/test_agent.py` la comprueba corriendo
todas las herramientas contra una base que revienta ante cualquier escritura.

### Arreglado

- **La clave API habría viajado en cada backup.** `preferencias` es una bolsa
  clave-valor y los dos exportadores la copiaban entera; un backup es un JSON
  que te mandas a ti mismo por WhatsApp. Ahora `storage.SECRET_PREF_KEYS` la
  excluye al exportar **y** al importar, y un `wipe` la conserva — restaurar en
  un móvil nuevo es justo cuando peor viene tener que ir a buscar la clave.
- **`"press banca"` resolvía, con toda confianza, a `Leg Press`** — una palabra
  compartida. Y `"bench press"` elegía `Smith Bench Press` antes que la barra,
  por dos caracteres menos de nombre. Ambos habrían escrito el ejercicio
  equivocado sin que saltara nada. Ahora la ambigüedad se niega y ofrece las
  opciones en vez de adivinar.
- **`VERSION` decía `0.2.0`** mientras el proyecto iba por 0.6.0, así que cada
  backup se firmaba con una versión falsa.

### Sabido

- La APK pasa de 76 MB a 87 MB: es el cliente de Anthropic más `jiter` y
  `pydantic-core` compilados para ARM64.
- Se factura por mensaje a tu clave, **aparte de cualquier suscripción**.
- La conversación vive en memoria y se pierde al reiniciarse la app. Tus datos
  no: esos están en la base, puestos ahí por un botón.
- Es lo único de la app que necesita cobertura.

## [0.4.0] — 2026-08-19

Cuatro mejoras pedidas, y **un fallo de actualización que habría dejado la app
inservible en el móvil** — encontrado probando la actualización, no leyendo el
código.

### Arreglado

- **Añadir una columna rompía toda base que ya existiera.** `create_all()` crea
  las tablas que faltan e ignora en silencio las columnas que faltan, así que
  `entrenos.nota` funcionaba en toda base nueva —todos los tests, toda
  instalación limpia— y reventaba en las que ya estaban, a la primera lectura,
  con `no such column`. Eso es History, Home y la pantalla de entreno. En el PC
  se arregla con un `ALTER TABLE`; **en el móvil no hay consola**, y la única
  salida era exportar, desinstalar, reinstalar y restaurar. Ahora
  `storage.add_missing_columns()` (y su espejo `anadir_columnas_que_faltan()` en
  el bot) añade en el arranque las columnas nulables que falten. Solo AÑADE:
  nunca borra, renombra ni cambia un tipo, y una `NOT NULL` se salta en vez de
  aplicarse a medias.
- **El historial se partía en dos con una sustitución activa.** Si Android
  mataba el proceso y se restauraba la sesión, la posición sustituida volvía sin
  reconocerse como registrada y al guardar otra vez se escribía una **segunda
  fila** el mismo día, una bajo cada nombre. Sin ningún error. La restauración
  comparaba la clave *prescrita* contra la *registrada*, y con un cambio en
  curso nunca coinciden: ahora pasa por `_performed_key`, la única función que
  responde qué se escribe en `entrenos.ejercicio`.
- **Una nota a medio escribir viajaba en el backup.** `workout_notes` es estado
  de la sesión en curso y faltaba en `EPHEMERAL_PREF_KEYS`, así que media frase
  tecleada en agosto habría aterrizado en una restauración de noviembre, colgada
  de otro ejercicio.

### Añadido

- **Las series que el plan prescribe** (`session_plan.py`). Un ejercicio sin
  historial abría una fila; el plan pide 3, 4 o 5 según la fase. Sobre la rutina
  real son 635 series en lugar de 178, más **25 filas descendentes** (`6+12↓`)
  que el plan prescribe y que no existían — todas en la fase 6, que se llama
  "Drop Sets + Compound". Cuando el plan y la última sesión no coinciden manda
  el plan, y la pantalla enseña los dos números.
- **Notas** por ejercicio (`entrenos.nota`) y por sesión (tabla `notas_sesion`,
  que existe aunque ese día no se registre ningún entreno). Y lo que les da
  sentido: **la nota de la última vez aparece al volver a ese ejercicio**.
- **Sustituir un ejercicio** (`substitutions.py`) por un equivalente, solo por
  hoy o para el resto de la fase, con la regla intacta: en `entrenos.ejercicio`
  va el movimiento que se hizo de verdad.
- **El bot usa `progression.py`**, así que la app y Telegram dejan de poder
  recomendar cosas distintas el mismo día.
- El backup sube a v4 (`workouts[].note` y sección `session_notes`); un fichero
  v2 o v3 sigue importándose.

## [0.3.0] — 2026-08-18

Esta versión sale de recorrer la app en un emulador Android en vez de leerla:
tres de los cuatro fallos de abajo no los veía ningún test, y uno llevaba
meses reportado como otra cosa.

### Arreglado

- **Las fotos de los ejercicios nunca podían salir en el móvil.** Se
  descargaban bien —140 ficheros verificados en el dispositivo— y la pantalla
  las pedía por `/exercises/<slug>/0.jpg`, una ruta que dentro de la APK no
  apunta a ningún sitio: las descargas van a `FLET_APP_STORAGE_DATA` y el
  paquete de Flutter es otro sitio distinto. `ft.Image` pinta un recuadro gris
  vacío para un origen que no resuelve, así que no fallaba nada, simplemente no
  aparecía nada. Reinstalar, borrar la caché y volver a descargar dejaban la
  app idéntica, y por eso se reportó como "no se descargan las imágenes".
  Ahora `exercise_images.image_props()` decide la entrega preguntando lo único
  que la determina —¿está el fichero dentro del directorio que se está
  sirviendo?— y, cuando no, manda los bytes en base64. Verificado compilando
  una APK mínima aparte con los dos métodos lado a lado.
- **El prerrelleno leía del futuro al registrar un día anterior.**
  `get_last_sets()` devolvía la fila más reciente de la tabla, sin mirar la
  fecha de la sesión: apuntar el lunes desde el miércoles ofrecía los pesos del
  miércoles. Y como `_seed_sets` los escribe en las casillas y un toque los
  confirma, no parecía un fallo, parecía un entrenamiento.
- **La semana de descarga recomendaba subir peso.** La fase dice "Same loads,
  half the sets", y llegar al tope del rango con la mitad de las series es lo
  esperado en una descarga, no una señal para cargar más.
- **El campo "Height" del perfil salía cortado** ("Heig") con su casilla fuera
  de pantalla: dos campos en una `Row` sin repartir el ancho.
- **Las gráficas de peso corporal y de 1RM estimado escalaban desde cero**, así
  que 2,2 kg de cambio se dibujaban como 3 píxeles de 110. Ahora recortan el
  eje y lo declaran; la de volumen sigue desde cero, donde un día flojo *debe*
  verse corto.
- **Perfil se quedaba en blanco si la base no respondía.** El fallo salía de
  `build()` sin capturar. Igual que el resto de pantallas, ahora dice qué pasa
  y ofrece reintentar.
- Plurales rotos por toda la app ("1 sets", "3 warm-up", "Copied 1 items"),
  anchos fijos que recortaban texto en cinco diálogos, y jerga sin explicar
  ("est. 1RM", "🏆 vol", "12.3k", "unmapped").

### Añadido

- **Herramientas de gimnasio** (`gym_tools.py`): calculadora de discos que
  resuelve por pares y admite barras distintas (la EZ pesa 7,5 kg), series de
  calentamiento por porcentajes redondeadas siempre a un peso montable, y tabla
  de porcentajes y RMs sobre el 1RM que `analytics` ya calculaba.
- **Progresión doble** (`progression.py`): la regla que estaba escrita en prosa
  dentro de `data.py` convertida en código, con el incremento por tipo de
  ejercicio y el peso resultante montable. Calla cuando debe — sin historial no
  inventa un peso, y tras un parón largo no manda subir.
- **En la fila de la serie**: el objetivo prescrito ("5-8 @ RIR 2-3"), el
  desglose de discos de ese peso, y los dos pesos vecinos cuando el pedido no
  se puede montar. Todo como texto ya visible, nunca un diálogo: uno modal a
  mitad de serie es la peor interacción posible en un gimnasio.
- **Calentamiento de un toque**, insertado como sugerencias sin confirmar.
- **La pantalla se mantiene encendida durante la app** (`build_template/`).
  Flet 0.28.3 no lo permite desde Python — comprobado contra el paquete
  instalado, no de memoria — pero `wakelock_plus` ya viajaba dentro de la APK
  sin que nadie lo llamara. Se bifurca la plantilla de compilación para
  llamarlo. **Subir la versión de Flet obliga a rehacer la bifurcación.**
- **Interruptor de vibración** del temporizador, junto al del sonido. La
  preferencia existía, se leía y se respetaba, y nada podía cambiarla.
- **Tabla de planificación** en el detalle del ejercicio (History): los
  porcentajes del 1RM estimado — 60 a 90 % — con el peso **redondeado a algo que
  se puede montar de verdad**, sus discos y las reps aproximadas. Convierte un
  número que solo miraba hacia atrás en los pesos de la semana que viene. Ojo al
  detalle que casi se cuela: `PercentageRow` lleva dos pesos, el aritmético
  (71,75 kg) y el montable (72,5 kg), y pintar el primero al lado de los discos
  del segundo daba una tabla que se contradecía a sí misma.
- **Tendencia de peso** en Perfil: media de 7 días y ritmo semanal, usando
  `analytics.moving_average`, que llevaba desde 0.2.0 escrito y sin llamador.
  Se niega a dar el ritmo con menos de dos semanas de datos.
- `views/shared_ui.py`: `plural()`, `dialog_width()`/`dialog_height()` y
  `db_error_card()` — los tres patrones que se habían roto en más de un fichero.

### Cambiado

- El editor de rutinas, Browse y Perfil pasan a los helpers compartidos.
- La entrada de descarga se llama "Exercise photos" y dice la consecuencia
  ("Not downloaded — photos won't show") en vez del tamaño.

## [0.2.0] — 2026-08-14

Nota sobre el bloque `[0.1.0]`: se deja intacto porque describe lo que se
publicó entonces, no lo que hay hoy. Varias de sus líneas ya no son ciertas
(SQLite, la app bilingüe, el splash oscuro); lo que las corrige es esta
sección, no una edición del pasado.

### Añadido
- **Diario de comidas** (`nutrition.py`, pestaña *Food*): catálogo por 100 g,
  raciones con nombre, las 5 comidas del plan con su hora, y objetivos
  versionados por fecha de inicio — el plan recorta 150 kcal si la cintura
  sube, y eso no puede reescribir lo ya comido. Cada registro congela sus
  macros al guardarse, por el mismo motivo. Sembrado con los 18 alimentos
  del menú real.
- **Analítica** (`analytics.py`): 1RM estimado (Epley), los tres récords que
  registra Hevy (mejor 1RM, peso máximo, mejor volumen de sesión), series por
  grupo muscular y semana, y media móvil del peso corporal.
- **Editor de rutinas** (`routine_builder.py`): rutinas propias en base de
  datos, duplicando una de fábrica. Se exponen con la misma interfaz que las
  de `data.py`, así que las vistas no distinguen entre unas y otras.
- **Tipos de serie** (`set_types.py`): calentamiento, normal, drop y al fallo.
  Los calentamientos dejan de contar para volumen y récords.
- **Descanso automático**: el `RestTimer` existía y se pintaba desde el
  principio, y nadie lo arrancaba nunca. Ahora arranca al guardar una serie,
  con 180 s en básicos y 90 s en aislamiento.

### Corregido
- **La racha marcaba 0 haciendo la semana perfecta.** Contaba días naturales
  consecutivos, así que una rutina de 5 días con 2 de descanso la rompía cada
  fin de semana por diseño. Ahora cuenta semanas consecutivas que cumplen el
  mínimo de sesiones de la rutina activa.
- **"Sessions" contaba filas, no días**: un día de 6 ejercicios se leía como
  6 sesiones.
- **Las imágenes de ejercicio no se veían**, por dos motivos independientes: el
  pack nunca se descargaba, y las rutas eran `file://`, que un navegador
  rechaza. Ahora viven en `assets/exercises/` y se sirven por HTTP.
- **Un jalón ilustrado con un remo**: `Behind-Neck Lat Pulldown` apuntaba a
  `Reverse_Grip_Bent-Over_Rows`. `Hip Thrust` no estaba mapeado y ahora cuenta
  para glúteo en el volumen por músculo.
- Dos diálogos pintaban tarjeta blanca sobre tema oscuro, por importar alias
  de color ligados a la paleta clara en tiempo de import.

### Cambiado
- **PostgreSQL 17 en Docker** sustituye a SQLite. La base la comparten esta app
  y el entrenador de Telegram de `../agente/`, así que lo que se apunta en una
  lo ve la otra al instante.
- **Solo inglés**: se elimina `i18n.py` y el selector de idioma.
- **Tema claro por defecto**, con paleta tokenizada y contrastes WCAG AA
  verificados por tests. Ninguna vista escribe ya un color.
- La app escucha en **127.0.0.1** por defecto (`IRONFLET_HOST`, `IRONFLET_PORT`).
- Splash a `#F4F6F8`, acorde al tema claro.
- De 7 rutinas a **4**: entra Recomp PPL+UL y salen las cuatro de mujer
  (ver *Retirado*). 87 nombres de ejercicio con imagen y ficha.
- De 88 a **340 tests**.

### Retirado
- **Las cuatro rutinas de mujer** (`women-fitness`, `women-home`,
  `women-strength`, `women-volume`) **y la guía "Women Fitness"**. IronFlet
  nació como tracker genérico, pero tiene un solo usuario y es Alex: mantener
  ocho rutinas de las que nunca se abren cuatro sólo alarga la lista de la
  pestaña *Plan* y da cuatro sitios más donde una rutina puede quedarse
  desactualizada. La app pasa a ser suya. Quedan CambiaTuFísico, Upper/Lower,
  Push/Pull/Legs y Recomp PPL+UL, que es la que sigue de verdad y la que lee
  el entrenador de Telegram.
  - El contrato de `exercise_key()` se estrecha en consecuencia: de 282
    cadenas / 104 claves a **219 cadenas / 100 claves**. Los 28 ejercicios que
    escribe el bot siguen existiendo en las cuatro rutinas que quedan, así que
    el historial compartido no se parte.
  - Sólo cuatro ejercicios dejan de estar prescritos por rutina alguna
    (`HIIT Intervals`, `Hyperextensions`, `Leg Raises`, `Triceps Kickback`) y
    los cuatro siguen en `EXERCISE_CATALOG`: se pueden buscar en *Ejercicios*
    y meter en una rutina propia desde el editor. No se pierde nada.
- `README.en.md` y `README.es.md`: eran el par bilingüe de un selector de
  idioma que ya no existe. `README.md` (castellano, para el dueño del sistema)
  y `CLAUDE.md` (técnico) los sustituyen. Siguen en el historial de git.
- La integración con Google Sheets.

## [0.1.0] — 2026-04-14

### Añadido
- Rutinas periodizadas: 7 programas incluidos.
  - **CambiaTuFísico**: 7 fases / 24 semanas.
  - **Upper / Lower**: 2 fases / 12 semanas / 4 días.
  - **Push / Pull / Legs**: 2 fases / 12 semanas / 6 días.
  - **Mujer Fitness**: 2 fases / 12 semanas, enfoque glúteo + tonificación.
  - **Mujer — Casa**: 1 fase / 8 semanas, peso corporal + mancuernas opcionales.
  - **Mujer — Fuerza**: 2 fases / 12 semanas, básicos pesados.
  - **Mujer — Volumen**: 2 fases / 12 semanas, hipertrofia alto volumen.
- Flujo de entrenamiento guiado: selección fase → día → ejercicio.
- Swipe horizontal entre ejercicios durante la sesión.
- Cronómetro de sesión con duración final en la pantalla de "sesión completada".
- Temporizador de descanso con presets (1', 1'30", 2', 3').
- 68 ejercicios con imagen y animación frame 0 ↔ frame 1 cada 700 ms.
- Diálogo de detalle con equipamiento, nivel, músculos primario/secundario
  e instrucciones paso a paso.
- Navegador de ejercicios (pestaña Ejercicios) filtrable por grupo muscular.
- Guías originales in-app: **Entrenamiento**, **Nutrición**, **Mujer Fitness**
  (7 tips por cada una en EN/ES).
- Perfil con: nombre, fecha nacimiento, altura, sexo, nivel de actividad.
- Cálculos derivados: edad, **IMC**, **TMB** (Mifflin-St Jeor), **GEDT**,
  objetivo de proteína (1.6–2.2 g/kg), objetivo de agua (~35 ml/kg).
- Historial de peso con gráfico y eliminación por entrada.
- Historial de entrenamiento por ejercicio con PR, peso máximo y volumen
  graficados por fecha.
- Internacionalización EN/ES, con toggle persistente en el Home.
- Backup/restore en JSON via portapapeles.
- Borrado selectivo (solo entrenamientos) o total (todos los datos).
- Descarga bajo demanda de las imágenes e instrucciones de ejercicios
  desde la [Free Exercise DB](https://github.com/yuhonas/free-exercise-db)
  (Unlicense / dominio público). No se bundlean en el APK para mantener
  el tamaño ajustado.

### Técnico
- Flet `>=0.25,<0.30`, Python `>=3.10,<3.13`.
- SQLite stdlib para persistencia (workouts, prefs, profile, weight_log).
- SafeArea respetada en Android (barra de estado + gesture nav).
- Lifecycle handler fuerza re-render al volver de background.
- Splash color (`#0A0A0B`) configurado para evitar flash blanco al arrancar.
