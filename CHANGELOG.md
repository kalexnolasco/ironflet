# Changelog

Todos los cambios notables de IronFlet.
El formato sigue [Keep a Changelog](https://keepachangelog.com/) y el proyecto
usa [SemVer](https://semver.org/).

## [0.0.1] — 2026-09-17

**El cuerpo, en 3D de verdad.**

### Añadido

- **Un cuerpo anatómico girable en Historial.** Sustituye al mapa plano en el
  móvil: se arrastra con el dedo para darle la vuelta, se pellizca para
  acercarse, y al tocar un músculo dice cuántas series lleva. Gira solo hasta
  que lo tocas, los colores se funden al cambiar de semana, y el músculo
  elegido late.

  Es three.js dentro de un `ft.WebView`, con un modelo anatómico real de
  quince mallas —una por grupo muscular. Los colores son **los mismos** que el
  mapa plano: `color_de` la calcula una vez y la usan los dos, para que la
  misma semana no salga naranja en una pantalla y roja en la otra.

  El mapa plano sigue ahí y no se ha tocado: el 3D necesita un WebView, que
  solo existe en Android y iOS. En el PC, en los tests y si el visor falla, la
  pantalla cae al de siempre.

- **`scripts/forja.mjs`**, que convierte el atlas anatómico original —826
  mallas, 8,2 MB— en el modelo que viaja en la APK: **0,44 MB** y quince
  mallas. No es solo tamaño: cada malla es una llamada de dibujo por fotograma,
  y fundirlas dobló los fotogramas por segundo.

### Lo que no hay

- **El cuerpo no hace los ejercicios.** El modelo es geometría estática, sin
  esqueleto ni animaciones, así que las animaciones son de cámara, de color y
  de latido. Un cuerpo que ejecuta un press de banca pediría otro modelo con
  rig y datos de movimiento por ejercicio.

### Detalles que costaron

- **`ft.WebView` no existe en el Flutter de flet 0.28.3.** El control está en el
  Python; la pantalla decía `Unknown control: webview` y logcat, nada. Lo aporta
  `flet-webview==0.1.0`.

- **JavaScript viene apagado, y encenderlo tarde no sirve.** El lado Dart no lee
  el atributo al montar y encender después de que la página cargara no vuelve a
  ejecutar el módulo: se quedaba en «cargando el cuerpo…» para siempre, sin un
  error en ninguna parte. Ahora nace en blanco, enciende, y entonces navega.

- **Desde `file://` el modelo no llega.** Android bloquea `fetch` entre ficheros
  locales y GLTFLoader lee el `.glb` con `fetch`. Se sirve desde un servidor
  http dentro de la propia app, atado a 127.0.0.1 — y con hilos, porque el
  navegador pide los módulos en paralelo y uno secuencial los mataba con un
  error que sonaba a permisos.

- **El abdomen sin entrenar parecía un agujero.** El negro del mapa plano
  funciona dentro de una silueta dibujada; en 3D, sin silueta, se lee como que
  al cuerpo le falta el vientre. Ahora lo no tocado es el escenario oscurecido.

- **Y la calavera negra.** El resto del cuerpo se pintaba de `bg_sunken` a
  secas, que en tema oscuro es casi negro: cabeza y manos flotaban en negro
  entre músculos de colores.

### Arreglado

- **Dos tests que caducaban.** `test_history_view.py` fijaba `2026-08-10` y
  comprobaba una tarjeta que mira **las últimas cuatro semanas contadas desde
  hoy**: pasaron durante treinta y seis días y se pusieron rojos solos, sin que
  nadie tocara el código. El fallo —«falta la nota de series sin contar»— no
  apunta al calendario por ningún lado. Ahora la fecha es relativa.

### Créditos

El modelo deriva de [Z-Anatomy](https://www.z-anatomy.com/) (CC BY-SA 4.0) y se
dibuja con [three.js](https://threejs.org/) (MIT). Detalle y obligaciones de la
licencia en `anatomia/CREDITOS.md`.

## [0.22.0] — 2026-09-01

**El cuerpo humano, coloreado con lo que entrenas.**

### Añadido

- **Un mapa muscular en Historial.** Un cuerpo dibujado por músculos, coloreado
  con las series de la ventana: azul lo poco trabajado, verde, ámbar, y rojo lo
  machacado. Gris lo que no has tocado. Se gira para ver la espalda y se toca
  cada músculo para ver sus series.

  Los datos llevaban ahí desde 0.4 — `sets_per_muscle_group` devuelve trece
  músculos — y lo único que se hacía con ellos era una lista de barras. Una
  lista contesta «cuántas series de dorsal»; el cuerpo contesta **qué llevas
  flojo**, que es la pregunta con la que se abre esa pantalla.

  Sin 3D: el volumen sale de un degradado radial con el foco donde daría la
  luz, y en una silueta plana eso basta. (En 0.0.1 sí lo hay, y este mapa se
  queda como el cuerpo de repuesto para cuando el WebView no está.)

### Detalles que costaron

- **Tocar el bíceps devolvía «Abdomen».** La caja de un músculo par va de un
  brazo al otro cruzando el torso entero. Ahora hay una caja por lado. En
  pantalla no se notaba nada: se pintaba bien y respondía mal.
- **15 series de pierna y 3 de tríceps salían del mismo azul.** La primera
  escala mezclaba el gris del fondo con el acento y no discriminaba: existía en
  los números y no en el ojo.
- **Los brazos salían más finos que sus músculos.** Suavizar un polígono lo
  encoge, y más donde más cerrado gira; la silueta era un único contorno de 28
  puntos y el bíceps acababa flotando al lado del brazo. Ahora es una pieza por
  parte del cuerpo.

## [0.21.0] — 2026-09-01

**Solo gimnasio.**

Alex: «quítale la nutrición, es algo complejo… solo gym». Fuera la pestaña
Comida, el diario, los 50 alimentos, las raciones, los objetivos de macros, la
compra del sábado, el plan de cocina del domingo, las calorías del widget y las
tres herramientas del coach que las leían. **Unas 3.900 líneas.**

### Qué se queda, y por qué

- **Tus datos de comida no se borran.** Las cuatro tablas siguen en la base y
  la copia de seguridad se las lleva igual — en «Copia y datos» aparecen bajo
  «Comida (función retirada)». Borrar las declaraciones habría hecho dos cosas
  calladas: que una copia nueva dejara de llevárselas, y que restaurar una
  vieja fallara al encontrar claves que ya nadie sabe leer.
- **Las métricas del perfil** —IMC, BMR, TDEE, el rango de proteína y el agua—
  siguen en Ajustes. Son aritmética sobre tu cuerpo, no un registro de lo que
  comes: nada apunta ya una comida.

### Cambiado

- **La barra tiene cuatro pestañas**: Inicio, Plan, Entreno, Historial.
- **El widget** cambia calorías y proteína por lo que llevas de semana
  (sesiones y series) y tu cintura. El hueco estaba y lo que falta en una app
  de gimnasio es eso.
- **El entrenador ya no habla de comida** y su prompt lo dice explícitamente:
  sin diario que leer, proponerte calorías sería inventar números. Si sacas el
  tema, te dice que la app ya no lo lleva en vez de fingir que lo sabe.

### Arreglado por el camino

- La sección de la copia decía «Nutrición» en una app sin nutrición, lo cual se
  lee como que la función sigue ahí y no se encuentra.
- **Los índices de vista bajaron uno.** Es justo lo que la trampa 1 dice que no
  se haga a la ligera; se hizo buscando cada literal, y quedaban cuatro sueltos
  porque `views/home.py` ya usaba constantes con nombre.
- Y una trampa se retiró con su causa: el `sys.modules.pop` de los fixtures
  existía porque `test_nutrition_view` dejaba un stub puesto. Sin ese fichero,
  sobra.

## [0.20.0] — 2026-09-01

**Medirte entero, saber cuándo llegas, y que el entrenador escriba él.**

### Añadido

- **Las cinco medidas**, no solo la cintura. `medidas` declaraba cintura,
  cadera, pecho, brazo y muslo desde que existe y la app solo pedía una, con un
  comentario que decía que las otras «son del coach» — ese coach era el de
  Telegram y se jubiló en la 0.13. Llevaban dos versiones vacías.

  Y lo que dicen **juntas**, que es lo único que justifica medir cinco cosas:
  «Cintura −1,7 cm y pecho y brazo arriba: es la recomposición, y el peso puede
  no estar diciéndolo». Calla cuando todo está dentro del ruido de la cinta
  (±0,5 cm), que es lo que pasa las primeras semanas.

- **Objetivo de peso, con fecha.** Pones 78 kg y te dice cuándo llegas al ritmo
  que llevas de verdad — de tu media móvil de 7 días, no del último pesaje. Se
  niega a dar fecha si vas en dirección contraria, si el ritmo es casi nulo o si
  queda a más de un año, y en los tres casos dice cuál de los tres es.

- **El repaso semanal**: una vez por semana el entrenador mira tus entrenos, tu
  peso y tus medidas y te deja tres frases en Inicio. Hasta ahora solo
  contestaba cuando le hablabas.

  Es **la única cosa de la app que hace una llamada de pago sin que la pidas**,
  y de ahí todo su diseño: apagado de fábrica, una por semana, y el coste
  guardado junto al texto y escrito debajo. Un gasto que nadie ve es un gasto
  que se descubre en un extracto.

### Detalles que costaron más de lo que parecen

- **La fecha del objetivo se dice con la precisión que el dato aguanta.** Un
  solo pesaje de dos kilos —lo que mueve una cena salada— desplaza la previsión
  46 días. Eso no se arregla amortiguando más el ritmo: lo que está mal es
  prometer un martes concreto de diciembre. A dos semanas se dice el día; a tres
  meses, los meses.
- **El repaso cuenta por semana ISO, no por «han pasado 7 días»**: lo segundo
  se desplaza cada vez que uno llega tarde, y en dos meses el repaso del lunes
  cae en jueves.
- **La semana se marca antes de llamar al modelo.** Si la llamada revienta a
  mitad, lo que no puede pasar es que el siguiente arranque lo intente otra vez
  y lo vuelva a pagar.

## [0.19.0] — 2026-09-01

**Los ejercicios, en español.**

### Cambiado

- **Todo lo que se lee está en español**, incluidos los nombres de los
  ejercicios: «Elliptical» es «Elíptica», «Smith Bench Press» es «Press banca
  en multipower», «Chest - Biceps» es «Pecho - Bíceps». También el widget, que
  hasta ahora los dejaba en inglés a propósito — ese argumento se dio la vuelta
  el día que Inicio empezó a traducirlos.

  **En la base siguen en inglés**, y eso no es un descuido: `entrenos.ejercicio`
  guarda el nombre inglés porque es la clave con la que se agrupa el historial.
  Traducir el dato habría partido meses de series en dos idiomas sin que nada
  fallara. La regla, en una línea: *lo que se guarda es inglés, lo que se ve es
  español, y nadie traduce al revés.*

- **El buscador entiende los dos idiomas.** «sentadilla» y «squat» encuentran
  lo mismo — enseñar un nombre y no encontrarlo al escribirlo sería el peor de
  los dos mundos, porque el inglés sigue siendo el que aparece en cualquier
  cosa leída antes.

Los ~100 ejercicios que prescriben las rutinas están traducidos a mano, porque
un entrenador español no dice «aplastadores de cráneo» sino «press francés».
Los otros 775 del catálogo se componen por reglas —el inglés ordena modificador
+ equipo + movimiento y el español al revés— y **lo que las reglas no entienden
se queda en inglés**: media traducción no se puede buscar en ninguno de los dos
idiomas y parece un fallo.

### Arreglado

- Cinco ejercicios del catálogo acababan con el mismo nombre en español, y
  cuatro de ellos son **el mismo movimiento con dos nombres en la propia base**
  («DB Shoulder Press» y «Dumbbell Shoulder Press»). Gana uno y el otro se
  queda en inglés: verlos distintos es peor que verlos traducidos y mucho mejor
  que dos filas idénticas en el buscador.
- Los chips de grupo del buscador de la sesión seguían en inglés, en la misma
  pantalla donde todo lo demás ya estaba traducido.

## [0.18.0] — 2026-09-01

**Fotos para los 875, cuatro rutinas más, y entrenar sin plan.**

### Añadido

- **Todos los ejercicios con foto.** Hasta ahora solo tenían los 70 del
  tarball: las 875 a tamaño completo son 126 MB, cuatro veces la app. La
  solución estaba en la web de Free Exercise DB, que sirve sus propias fotos
  por un CDN que las redimensiona — **10 KB en vez de 60**. Las 875 caben en
  9 MB y se bajan según se miran, sesenta por búsqueda.
- **Cuatro rutinas nuevas**, que son ocho en total: **PHUL** (fuerza +
  hipertrofia, 4 días, la que mejor encaja con una recomposición),
  **StrongLifts 5×5**, **Arnold Split** y **Full Body 3 días** para las semanas
  con poco tiempo. Transcritas con sus series y repeticiones originales.
- **«Libre»**, en Inicio: llegar al gimnasio sin plan, elegir cuatro ejercicios
  y hacerlos. Antes había que entrar por una fase y un día, o sea fingir que
  hoy tocaba pecho — y esa mentira acaba en `entrenos.grupo`, que es lo que
  agrupa Historial.
- **El catálogo de Ejercicios ahora tiene buscador** y conoce los 875, no los
  67 escritos a mano.

### Arreglado

- **Entrar en «Libre» desde una sesión de pesas dejaba 60 kg × 10 prellenados
  en el primer abdominal.** `_sets_by_ex` guarda lo tecleado por posición, y la
  posición 0 de un día es la posición 0 del siguiente. A un toque de Guardar y
  del historial. Ahora hay un solo camino entre modos y vacía ese buffer,
  guardando el borrador antes.
- Un «Libre» sin nada elegido salía con el abdomen del día y sin decir de dónde
  venía. Ahora abre el buscador.

### Cómo no se rompió el historial, otra vez

Las cuatro rutinas suben las cadenas de ejercicio de 219 a 275 y **dejan las
claves en 100**. Ni un nombre nuevo: PHUL empieza por «Bench Press» y aquí es
`Barbell Bench Press`, porque ese nombre *es* la clave con la que se guarda
cada serie. Una sentadilla hecha en PHUL cae en el mismo historial que la de
CambiaTuFísico.

## [0.17.0] — 2026-09-01

**Abdomen todos los días, que el plan ya pedía y la app no daba.**

### Añadido

- **Abdomen cada día** (`abdomen.py`), que se enciende en Ajustes. Al final de
  cada entreno, y los días de descanso en Inicio — porque «cada día» son siete
  y se entrenan cuatro o cinco.

  No era una función nueva: era **un agujero**. El calendario de la fase 1 dice
  «+ Abs» cinco veces por semana y los tres días que se entrenan de verdad no
  llevan un solo ejercicio de abdomen en su lista. El «+ Abs» vivía en el
  calendario, que es texto de distribución y no llega a la pantalla de entreno.

  Tres al día por defecto, uno de cada tipo —flexión, inferior y oblicuos—, que
  rotan solos y no repiten del día anterior. Barajar los 93 ejercicios de
  abdomen del catálogo habría dado días con tres crunches.

### Arreglado

- **La lista de días prometía siete ejercicios y entregaba diez.** Contaba los
  de la rutina y no los de la sesión; la diferencia no se veía hasta estar
  dentro. Ahora dice «7 ejercicios + 3 de abdomen».
- **El chip «Atrás» de la cabecera llevaba a los días de una fase que no se
  estaba entrenando.** Su docstring prometía «lo mismo que el botón físico» y
  había dejado de cumplirlo: repetía las tres líneas de `handle_back` en vez de
  llamarlo, y no se enteró de que había una sesión de solo abdomen de la que
  salir. Ahora delega.
- Un nombre inventado en el pool de abdomen —`Hanging Leg Raise`, que no existe
  en el catálogo— habría abierto un historial paralelo. Lo cazó su test antes
  de llegar a ninguna parte.
- Un fixture nuevo recargaba `views.workout` sin necesitarlo y rompía
  `test_workout_exercise_date`, un test que nadie había tocado. Solo fallaba en
  la suite entera. Trampa 33.

## [0.16.0] — 2026-09-01

**875 ejercicios y poder añadir uno a mitad de sesión.**

### Añadido

- **«+ Ejercicio», junto a Terminar sesión.** La máquina está ocupada, o
  acabas la última serie con ganas de meter algo más. Hasta ahora la única
  salida era editar la rutina: cambiar el plan de 24 semanas para arreglar un
  martes. Un extra **vale solo para hoy** — mañana el plan vuelve a ser el que
  era sin que nadie deshaga nada.
- **El catálogo pasa de 67 ejercicios a 875.** Y la sorpresa fue que ya
  estaban: la app lleva desde 0.6 bajando fotos de Free Exercise DB (dominio
  público), 876 movimientos con músculo, equipo, nivel y foto. No faltaba la
  fuente, faltaba que la app los conociera. Viajan 174 KB de datos dentro del
  APK; las fotos no —serían 126 MB, cuatro veces la app— y se bajan de una en
  una la primera vez que hacen falta.
- El buscador arranca **filtrado por lo que se entrena hoy**, y si ese filtro
  deja cero resultados busca sin él y lo dice.

### Arreglado

- **Un extra podía perder las series recién tecleadas.** `fit_to_routine`
  descarta toda fila cuya clave no esté en la rutina —es lo que impide que los
  pesos del press acaben bajo una sentadilla— y un extra nunca lo está, por
  definición. Al reabrir la app desaparecían, en silencio y con toda la lógica
  haciendo lo que promete. Trampa 32.
- **Buscar «crunch» un día de pecho decía «Nada con ese nombre»** teniendo 21
  respuestas en abdomen. Salió del emulador, no de leer el código.
- En el mismo sitio: el teclado dejaba la lista en dos filas (fuera el
  autofocus, el camino corto casi nunca es escribir) y los chips de grupo
  ocupaban dos filas, que era un resultado menos.

### Cómo no se rompió el historial

Los nombres de la base no son los de la app —ella dice `Barbell Bench Press` y
la base `Barbell Bench Press - Medium Grip`; de 114 nombres, 13 coinciden— y el
nombre **es** la clave con la que se guarda cada serie. Ofrecer los dos habría
abierto dos historias del mismo movimiento sin que nada fallara. Manda el de
casa: `EXERCISE_IMAGE` se lee al revés y es la única tabla que sabe qué
movimiento de la base es el mismo que uno nuestro.

## [0.15.0] — 2026-08-22

**El finde resuelto, y un entrenador que se acuerda de quién eres.**

### Añadido

- **La compra del sábado y la cocina del domingo** (`finde.py`), dentro de
  Comida. Los datos ya estaban —`nutrition.TEMPLATE_DAY` lleva el menú del plan
  con sus gramos—; faltaba multiplicarlos por siete, agruparlos por alimento y
  decirlos en unidades de supermercado.

  La lista va **ordenada por el recorrido de la tienda**, y esas secciones están
  escritas a mano a propósito: se puede deducir el macro dominante y agrupar por
  ahí, sin mantenimiento, y saldría mal — el plátano y el arroz son los dos
  hidratos y están en pasillos distintos. Una lista de la compra se ordena por
  dónde están las cosas, que es un hecho del mundo y no de la tabla nutricional.

  Se ajusta a tus calorías **sin tocar la proteína**, que es lo que dice el
  plan («el aceite de la cena, nunca la proteína»); el recorte recae entero
  sobre los hidratos y las grasas. Y tiene suelo: por debajo de la mitad ya no
  escala, avisa. Sin él, un objetivo de 900 kcal mandaba comprar 63 g de manzana
  para la semana — aritméticamente correcto y completamente inútil.

  El domingo, qué cocinar y en qué orden: primero lo que más tarda, porque el
  horno trabaja solo. Los minutos son de reloj, no la suma de los pasos. Cada
  receta lleva **los días que aguanta en la nevera**, y ese número es el que
  hace honesto el plan: sin él, la primera versión mandaba cocinar el domingo un
  salmón que se comía el sábado siguiente.

  El coach lo relata en vez de recalcularlo (`weekend_plan`). Darle el menú y
  los objetivos y dejar que multiplique es un error que se descubre en la caja
  del súper.
- **El entrenador se acuerda de quién eres** (`memoria.py`). Hechos, no
  conversación: a qué hora entrenas, qué no comes, qué rodilla te molesta.
  Guardar el chat sería un blob creciendo sin límite y un mes de charla
  re-facturado en cada pregunta; lo que cambia el producto son veinte líneas.

  Van en el **prompt de sistema** y no detrás de una herramienta, que es la
  única excepción deliberada a un prompt escrito para ser idéntico byte a byte:
  se paga en caché invalidada al editar uno —unas pocas veces en la vida del
  producto— y a cambio el coach nunca puede *no* saberlos.

  Él **propone**, tú guardas, como todo lo demás. Es la tarjeta donde más obvio
  resulta por qué: un modelo que escribe en su propia memoria acaba recordando
  cosas que nadie le dijo, y nadie sabría cuáles hasta leerlas en Ajustes.
  Se editan en **Ajustes → Lo que recuerda de ti**, con una papelera por línea,
  y la primera vez el chat ofrece una entrevista corta en vez de adivinar.
- `tests/test_finde.py` (34), `test_finde_view.py` (20) y `test_memoria.py`
  (47).

### Arreglado

- **La leche salía en kilos.** «Leche semidesnatada 1,81 kg» es correcto y no lo
  dice nadie en una tienda: la tabla nutricional está en gramos porque las
  etiquetas europeas lo están. La lista deshace esa conversión — leche y aceite
  en litros.
- **La misma nota de congelar, cuatro veces** en el plan del domingo. Ocupaba
  media pantalla y se dejaba de leer, incluida la única distinta —la del
  salmón—, que es justo la que cambia lo que haces. Ahora lo que le toca a la
  mayoría se dice una vez arriba y en la tarjeta solo queda la excepción.
- **Añadir un hecho te devolvía al principio de Ajustes.** `refresh_current()`
  reconstruye la pantalla entera, así que tras cada uno había que volver a bajar
  cinco pantallas. La memoria se mudó a un diálogo, que se redibuja solo a sí
  mismo. Y dentro de él, un botón que medía 350 px de alto: `expand` reparte el
  eje del padre y el de una `Column` es el vertical (trampa 31).
- **El guard que garantiza que ninguna herramienta del coach escribe** decía
  «every tool» y probaba **seis de quince**. Su lista estaba escrita a mano y
  nadie la actualizó al añadir fotos, calendario, avisos ni objetivos: la
  invariante que sostiene toda la seguridad de esa función se comprobaba sobre
  un subconjunto que ya no representaba nada. Ahora recorre los registros, y un
  test hermano se pone rojo si una herramienta nueva se queda sin argumentos de
  prueba. Con eso saltó `propose_calendar_event`, que se rechazaba a sí misma
  antes de tocar nada y pasaba por no haberse ejecutado.

## [0.14.0] — 2026-08-21

**Un widget en la pantalla de inicio y gráficas de verdad.**

### Añadido

- **Widget de la pantalla de inicio.** Lo de hoy sin abrir la app: qué toca
  entrenar —con un ✓ cuando la sesión ya está hecha—, tu peso, y cómo vas de
  calorías y proteína. Cuatro líneas y nada más: un widget se mira de refilón,
  y lo único que lo justifica frente a abrir la app es contestar «¿qué me
  toca?» y «¿cómo voy?» sin un solo toque.

  Mismo puente de fichero que los avisos: `widget.py` escribe `widget.json` y
  `IronFletWidget.kt` lo lee (los dos procesos comparten UID). **El JSON viaja
  ya formateado** —«82,4 kg», no `82.4`— así que Kotlin no repite ni una
  decisión de formato y todo lo que decide algo tiene tests en Python.

  Se añade desde **Ajustes → Widget**, que le pide al lanzador que lo ofrezca,
  en vez de tener que saber que existe y buscarlo en el selector.
- `tests/test_widget.py` (23) y los dos de `test_puente_dart.py` que validan
  los XML de la plantilla — un comentario XML con dos guiones seguidos tumbó
  un build entero con un error que no nombraba el fichero.

### Cambiado

- **Las gráficas las dibuja Flet, no `ft.Container` apilados.** El módulo
  presumía de no tener dependencias; no las tenía porque Flet trae `BarChart`
  y `LineChart` desde la 0.22 y esto los reimplementaba peor.
- **El peso es una línea, con su media móvil de 7 días punteada encima.** Siete
  barras sueltas escondían justo la tendencia que se mira, y el peso de un día
  se mueve un kilo con la sal — varias veces los ±0,3 kg/semana del plan.
- **Fundido de 180 ms al cambiar de pantalla**, y solo al cambiar de pantalla:
  `refresh_current()` se llama con cada serie confirmada y cada tecla del
  buscador, y fundir en esas es la pantalla parpadeando mientras entrenas.

### Arreglado

- **El icono de las notificaciones ya es la mancuerna.** El *resource shrinker*
  se lo llevaba por delante porque solo lo nombra una constante de Dart, que
  vive en el snapshot AOT y no en el DEX; `res/raw/keep.xml` lo ancla.
- «1 Sesiones» en Inicio, «178.0» en la altura y el chip «Los 350…», que
  parecía un botón al que no le cabe el texto.

## [0.13.2] — 2026-08-21

**Segunda vuelta al emulador**, con la APK reinstalada y verificando en pantalla
cada arreglo de la 0.13.1. Encontró una regresión de la propia 0.13.1 y dos
fallos que no se habían tocado nunca.

### Arreglado

- **Los avisos dejaron de entregarse, y el culpable era su icono.** En 0.13.1
  se le puso a las notificaciones un icono monocromo. El recurso llegó al
  proyecto Android generado pero **no al APK** (trampa 30), así que
  `_notifPlugin.initialize()` lanzaba — y como el `Timer.periodic` que lee el
  puente estaba **en el mismo `try`**, el temporizador no llegaba a
  registrarse. Sin poll no se programa nada: cero avisos, sin un solo error a
  la vista. El aviso recién creado se quedaba tan tranquilo en su lista.
  Ahora el temporizador vive fuera de ese `try` y el icono se degrada al del
  lanzador si no resuelve. Un icono es cosmética; el aviso es la función.
- **Exportar la copia no escribía nada en Android.** El diálogo del sistema
  devuelve un URI del Storage Access Framework (`/document/12`) que Flet pasa
  como si fuera una ruta, así que `write_bytes` fallaba y quedaba un `.json`
  de **0 bytes** en Descargas con el nombre correcto — peor que ningún fichero,
  porque parece una copia. La copia interna sí estaba completa (28 KB de JSON
  válido), pero el mensaje de error pisaba al de éxito y se leía como «te has
  quedado sin copia». Ahora nombra las tres cosas: que Android se negó, que ese
  fichero está vacío, y dónde está la copia buena.
- **La pantalla de copia contaba tres de sus tablas como cero.** `photos`,
  `session_notes` y `session_durations` van en la copia desde la v4 y el
  contador no las buscaba. Con una foto guardada y 7 minutos cronometrados, la
  pantalla decía 0.
- **Un fallo de red del entrenador ya dice cuál.** Cinco causas distintas
  caían en «Sin conexión con OpenRouter» — cierto para una y engañoso para las
  otras cuatro, que mandan a mirar la cobertura. Ahora se distinguen TLS, DNS,
  proxy, corte y desconexión, leyendo la cadena de causas (httpx envuelve el
  fallo de certificado dentro de un `ConnectError`).
- **«1 Sesiones».** La etiqueta ya concuerda con el número que tiene encima.
- **Las prescripciones se dicen en español** sin tocar el dato: Plan mostraba
  «Descanso: 1' sets / 2-3' exercises» y la lista de fases «Ascending
  Pyramid». `set_types.describir_esquema/descanso` traducen para mostrar.

### Añadido

- `tests/test_puente_dart.py` — lee `main.dart` como texto y falla si algún
  `try` vuelve a juntar el `initialize` del plugin con el temporizador del
  poll. No hay tests de Dart en este repo y esta propiedad no puede volver a
  quedar sin vigilancia.
- Trampas 29 y 30 en `CLAUDE.md`.

## [0.13.1] — 2026-08-21

**Un recorrido entero por la APK instalada**, pantalla por pantalla y con datos
de verdad dentro. Casi todo lo que salió era idioma; una cosa era un fallo
disfrazado de idioma.

### Arreglado

- **Inicio decía «Proteína 0 g» con 42 g apuntados.** El pase al español había
  renombrado la CLAVE del diccionario (`totals.get("proteína")`), y como
  `.get()` de una clave que no existe devuelve `None` en vez de fallar, la
  tarjeta pintaba un cero perfectamente creíble. `nutrition` habla en inglés
  porque es contrato de datos: la trampa 22 en su forma más silenciosa.
- **Unos 80 literales seguían en inglés**, ninguno visible sin estar en la
  pantalla exacta: el campo de fecha de los diálogos de peso y cintura, la
  categoría del IMC, el pie de la gráfica de peso, las cuatro descripciones de
  rutina, `LAST SESSION`, `Confirm all`, `Next exercise`, todos los motivos y
  avisos de `session_plan`, los nombres por defecto del editor de rutinas y el
  resumen de pesos montables.
- **`plural()` pluralizaba en inglés.** `singular + "s"` colaba de milagro con
  *serie*, *día* y *fase*, y daba «2 sesións» en cuanto la palabra acababa en
  consonante. Ahora es `-s` tras vocal, `-es` tras consonante, más una tabla
  corta para las que mueven la tilde.
- **La grasa es G, no F.** «Grasa» en la etiqueta y `F` en la línea de macros
  era la abreviatura inglesa sobreviviendo a su propia palabra. Unificado entre
  la pantalla de Comida y la tarjeta de objetivos del entrenador.
- **Un tiempo agotado no es falta de cobertura.** El entrenador decía «Sin
  conexión con OpenRouter» con la red viva y 499 ms de ida y vuelta: todas las
  excepciones caían en el mismo mensaje, y ese manda a mirar el sitio
  equivocado.
- **Cuatro cosas que solo se ven en un móvil.** El botón «Parar» del descanso
  salía cortado por el borde derecho (`wrap=True` dentro de una `Row` sin ancho
  acotado nunca envuelve); la fecha bajo las miniaturas de la galería salía
  partida por la mitad; «Nacimiento (AAAA-MM-DD)» no cabía en media fila y su
  label pisaba el campo de arriba; y el markdown del entrenador se leía con los
  asteriscos puestos.

### Añadido

- `tests/test_layout_movil.py` — los cuatro fallos de arriba, congelados. Cada
  arreglo se revirtió en su sitio para comprobar que su test se pone rojo.
- Trampas 26, 27 y 28 en `CLAUDE.md`: la clave traducida, el `wrap` sin acotar
  y el markdown crudo.

## [0.13.0] — 2026-08-21

**Solo el móvil.** Se jubilan la versión de PC, el modo web y el bot de
Telegram. Lo que queda es la APK y su fichero SQLite.

### Quitado

- **PostgreSQL, Docker y `psycopg`.** El almacenamiento es un fichero SQLite y
  `resolve_db_url()` ya no tiene rama de servidor.
- **El modo web** (`IRONFLET_WEB`, `flet[all]`, los ~12 MB de CanvasKit
  vendorizados a mano, `scripts/vendor_canvaskit.py`) y los tres servicios de
  systemd: `ironflet-web`, `entrenador-bot`, `entrenador-panel` — parados y
  deshabilitados.
- **El esquema duplicado a mano** entre este repo y el del bot, con su test de
  espejo. Una sola declaración.

### Cambiado

- **Ya no se salta ningún test.** Antes 211 pruebas —todo lo que tocaba
  almacenamiento— se saltaban en silencio sin un PostgreSQL levantado, y un
  verde con 211 saltos no había verificado nada. Ahora corren las 1716 sobre
  SQLite, sin Docker, y en la mitad de tiempo.
- `tests/conftest.py` da a cada proceso su propio fichero temporal en vez de
  crear y borrar una base por pid.
- Makefile nuevo: `make apk` y `make install` en lugar de `make deploy`.
  `make apk` borra `build/` entero, porque borrar solo `build/flutter` deja a
  flet con medio estado y falla con un error que no dice qué pasa.
- README y CONTRIBUTING reescritos: hablaban de puertos, systemd y una app en
  inglés con tema claro fijo.

### Arreglado

- **Las claves foráneas no se estaban comprobando en los tests de nutrición.**
  Su fixture construía el motor con un `create_engine()` desnudo, sin los
  PRAGMAs que sí aplica la app, y con PostgreSQL nunca se notó porque allí van
  encendidas de fábrica. Al migrar saltó: un apunte de comida seguía apuntando
  a un alimento borrado. La fixture usa ahora `create_db_engine`, como la app.

## [0.12.0] — 2026-08-21

**Fotos de progreso, el coach que las ve, Google Calendar y los permisos que faltaban.**

### Añadido

- **Google Calendar** (`gcal.py`, httpx puro): la tarjeta AGENDA en Inicio
  enseña hoy y mañana; el coach lee tu semana antes de proponer horarios y
  puede proponer eventos — tarjeta y Guardar, como todo. Conexión por
  dispositivo: «Importar del bot» en el PC, «Conectar con Google» (navegador +
  loopback) en el móvil. Las tres credenciales viven en `SECRET_PREF_KEYS` y
  jamás entran en una copia. Ojo: si la app OAuth de Google está en modo
  Testing, el token caduca a los 7 días — publícala en Cloud Console.

- **Foto de progreso diaria** con la semántica de los pesajes: una por día y
  la segunda corrige la primera. Se eligen con el selector del sistema, se
  comprimen en el móvil (Pillow con wheel Android; lado mayor 1600 px, JPEG 85,
  orientación EXIF corregida) y viven en el almacenamiento privado de la app.
- **Galería** (tarjeta FOTO en Inicio): rejilla por fechas, detalle con las
  medidas tomadas cerca de ese día, y **comparador A/B** — dos fotos lado a
  lado con la diferencia real de peso y cintura entre sus fechas. Esa resta es
  la "detección de mejoras" honesta; la opinión con ojos la da el coach.
- **El coach ve tus fotos**: botón 📷 en el chat que adjunta la última foto de
  progreso (viaja una sola vez; en el historial queda una marca, no los bytes,
  para no re-pagarla en cada turno). El desplegable marca con 📷 los ~220
  modelos de OpenRouter que aceptan imágenes, y la app rehúsa adjuntar a uno
  que no las vea. Herramienta nueva `progress_photos` (solo fechas y medidas —
  jamás bytes a demanda del modelo).
- **El coach ajusta las comidas semanales**: propone objetivos diarios nuevos
  (kcal y macros, normalmente desde el lunes) con el mismo modelo de seguridad
  de siempre — tarjeta de confirmación, y nada se escribe hasta tocar Guardar.
  Al guardar, los objetivos se versionan por fecha de inicio: los días ya
  vividos no se reescriben.
- **Copia de seguridad**: los metadatos de las fotos entran en el JSON, y los
  JPEG van en un **zip aparte** (exportar/importar en Copia y datos) — meses de
  fotos en base64 harían la copia inenviable por chat.

### Arreglado

- **"No suena" en el móvil real**: la APK ahora lleva `USE_EXACT_ALARM`
  (autoconcedido; esta app va por sideload, no por Play), pide el permiso de
  notificaciones al crear el primer aviso, abre una única vez el ajuste de
  «Alarmas y recordatorios» si sigue apagado, y **escribe el estado de ambos
  permisos** en `notif_status.json`. El diálogo de Avisos lo lee y dice
  exactamente qué interruptor del sistema falta, en vez de parecer rota.

## [0.11.0] — 2026-08-20

**Los avisos suenan en el móvil, y toda la app habla español.**

### Añadido

- **Notificaciones locales de recordatorios en la APK.** Flet no expone ninguna
  API de notificaciones a Python, así que el puente es un fichero:
  `notificaciones.py` expande cada aviso (diario o semanal, en hora de pared de
  Madrid) a 30 días de instantes UTC absolutos y escribe `notifications.json`;
  el `main.dart` de la plantilla forkeada lo relee por mtime cada 3 s y lo
  reprograma con `flutter_local_notifications` — alarmas exactas si Android lo
  permite, inexactas si no, y sobreviven al reinicio del móvil.
- **Gestión de avisos en Inicio**: crear (una vez / diario / semanal con días de
  la semana), pausar y borrar los tuyos. Los fijos del bot se ven, con su icono
  de robot, y no se pueden borrar desde aquí: los re-sembraría el bot igual.
- **Un planificador por base de datos, nunca dos.** En el PostgreSQL compartido
  entrega el bot por Telegram y `proxima` es suya; en el SQLite del móvil
  entrega Android y la app refresca `proxima` al sincronizar. La puerta vieja
  `reminders_available()` pasa a llamarse `bot_delivers_reminders()`, porque esa
  era la única pregunta que respondía de verdad.
- Tests nuevos de la aritmética del puente: subconjunto de cron, expansión en
  pared de Madrid (incluido el cambio de hora de marzo), payload, CRUD y las dos
  guardas de `sync()`.

### Cambiado

- **Todo lo que ve el usuario está en español.** Las diez pantallas, diálogos,
  tooltips, avisos, estados vacíos, el glosario de métricas, la ayuda de tipos
  de serie, las guías, los errores de copia de seguridad, las razones de la
  progresión y las pistas de discos. La letra de calentamiento pasa de W a C
  para casar con su palabra; los cubos de músculo, las comidas y las fechas
  también.
- **Lo que NO se tradujo, a propósito**, porque es contrato de datos y no
  interfaz: nombres de ejercicios y sus claves (compartidas con el bot), los
  nombres de día que se escriben en `entrenos.grupo`, las claves de tipo de
  serie, y las cadenas `scheme`/`rest` de las fases que parsean
  `parse_scheme`/`parse_prescribed_rest`.
- **Dos parsers de prosa se hicieron bilingües** para no perder funciones en el
  cambio: `parse_rir` y `parse_prescribed_step` reconocen ahora español e inglés
  (las marcas de descarga ya lo eran). Verificado contra todas las fases de
  serie: mismos objetivos, mismas descargas, la regla 5 intacta.
- **El descanso del modo zen ya no se come la pantalla del móvil**: dial de
  128 px/36 pt → 104 px/28 pt, trazo más fino, y la etiqueta DESCANSO fuera del
  anillo en vez de apretada dentro. En reposo un guion; al acabar, ¡YA!

## [0.10.0] — 2026-08-20

**Nueva piel, con el aspecto de symmetry.club.** Fondo casi negro, un solo azul,
esquinas muy redondeadas y cero sombras.

### Cambiado

- Paleta nueva por defecto, con valores **medidos del sitio real**, no a ojo:
  fondo `#121212`, superficies `#1A1A1A`, acento `#3781FA`, gris secundario
  `#9CA3AF`, bordes de 1 px a baja opacidad y ninguna sombra.
- Esquinas: tarjetas a 24 px y botones y chips en **píldora** — en el sitio,
  `9999px` era el radio más usado (32 veces) y `24px` el segundo (21).
- **Ajustes → Appearance** para cambiar de tema. Se guarda y se aplica al vuelo.

Como ninguna vista escribe un color ni un radio propio, esto reviste **las diez
pantallas de una vez**. Esa regla existía justo para esto.

### Dos desviaciones a propósito, porque el original no cumple AA

- **Blanco sobre su azul da 3,70:1** y el mínimo para una etiqueta de botón de
  14 px en negrita es 4,5. Y no hay forma de tener las dos: para leerse sobre un
  fondo `#121212` el acento necesita luminancia ≥ 0,2022 y para llevar blanco
  encima ≤ 0,1833 — los rangos no se tocan. Así que la etiqueta va en negro,
  igual que ya hacía el tema oscuro anterior.
- **Su gris de texto `#6B7280` da 3,60:1** sobre tarjeta. Se conserva, pero
  degradado a borde, y los grises de texto suben un escalón.

Peor par de la paleta nueva: 4,71:1. Los tres temas pasan el test de contraste.

### Arreglado

- **"Clear all data" se había vuelto azul.** Las filas destructivas usaban
  `C.accent_2`, que en el tema claro *era* carmesí por casualidad — el rol y el
  color nunca habían coincidido y el tono lo tapaba. Ahora usan `C.danger`, y
  hay un test que lo exige.

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
