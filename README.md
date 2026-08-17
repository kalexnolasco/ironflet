# IronFlet — tu app de entrenos y comidas

<div align="center">

![Proyecto](https://img.shields.io/badge/Proyecto-IronFlet-blue?style=for-the-badge)
![Servicio](https://img.shields.io/badge/servicio-ironflet--web-FCC624?style=for-the-badge&logo=linux&logoColor=black)
![Acceso](https://img.shields.io/badge/127.0.0.1%3A8550-solo%20este%20PC-lightgrey?style=for-the-badge)
![Flet](https://img.shields.io/badge/Flet-0.28.3-7F52FF?style=for-the-badge)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Android](https://img.shields.io/badge/APK-73%20MB%20·%20SQLite-3DDC84?style=for-the-badge&logo=android&logoColor=white)
![Tests](https://img.shields.io/badge/tests-538-2f9e44?style=for-the-badge)

**Donde apuntas lo que levantas y lo que comes. En el PC comparte base con el entrenador de Telegram: lo que escribes aquí lo ve él al instante, y al revés. Y ahora también se compila como APK, con su propia base en el móvil y el PC apagado.**

</div>

---

## ⚠️ LEE ESTO ANTES DE NADA: systemd no recarga el código solo

**Si tocas cualquier fichero `.py`, la app sigue ejecutando la versión vieja hasta que reinicies el servicio.**

El proceso cargó el código en memoria cuando arrancó y ahí se queda. Guardar el fichero no cambia nada. Recargar el navegador no cambia nada. Cerrar la pestaña no cambia nada. El programa que se está ejecutando es el de hace horas.

Esto ya costó **23 horas** de mirar una versión antigua creyendo que el trabajo no se había hecho. El trabajo estaba hecho. El servicio no lo había cargado.

Después de cambiar código, siempre:

```bash
systemctl --user restart ironflet-web
```

Y confirma que ha arrancado de verdad, mirando la hora del último arranque:

```bash
systemctl --user show ironflet-web -p ActiveEnterTimestamp
```

Si esa hora no es de hace unos segundos, no se ha reiniciado y sigues viendo lo viejo.

Vale lo mismo para las otras dos piezas: `entrenador-bot` y `entrenador-panel`. Si has tocado algo que comparten (una tabla de la base de datos, por ejemplo), reinicia las tres en el orden seguro con un solo comando:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && make deploy
```

---

## Qué es IronFlet

Una app que se abre en el navegador del PC y sirve para tres cosas:

1. **Entrenar** — eliges la rutina, la fase y el día, y vas apuntando cada serie: peso, repeticiones y RIR. Con temporizador de descanso automático entre series.
2. **Comer** — un diario de comidas con catálogo de alimentos, raciones ("1 plátano mediano" en vez de pesar) y objetivos de macros.
3. **Mirar atrás** — récords personales, progresión de cada ejercicio, series por grupo muscular, racha de semanas y evolución del peso corporal.

Está **en inglés**. No hay selector de idioma ni traducción: la app se escribe en inglés y ya está. (La documentación —esto— está en castellano.)

El tema es **claro**, fijo. Hay una paleta oscura escrita en el código, pero no hay ningún botón para cambiarla.

### Cómo encaja con el resto

Son tres programas sobre **una sola base de datos** PostgreSQL:

| Pieza | Qué hace | Dónde vive |
|---|---|---|
| **IronFlet** (esto) | Apuntas entrenos y comidas con el teclado | `ironflet/` · servicio `ironflet-web` · puerto 8550 |
| **Entrenador de Telegram** | Te avisa, te pregunta y apunta por ti desde el móvil | `agente/` · servicio `entrenador-bot` |
| **Panel de administración** | Corregir y borrar datos a mano | `agente/panel/` · servicio `entrenador-panel` · puerto 8551 |

No hay sincronización ni copias: es literalmente la misma base. Si apuntas un press banca por Telegram, aparece en el historial de la app en cuanto refresques.

```mermaid
graph TD
    TU["📱 Tú"]
    APP["📱 IronFlet · 8550<br/>entrenar · comer · mirar atrás"]
    BOT["🤖 Entrenador de Telegram<br/>te avisa y apunta por ti"]
    PAN["🔐 Panel · 8551<br/>corregir y borrar"]
    PG[("🐘 PostgreSQL 17<br/>docker · solo 127.0.0.1<br/>18 tablas")]

    TU -->|"navegador de este PC"| APP
    TU -->|"Telegram, desde el móvil"| BOT
    TU -.->|"cuando algo hay que corregir"| PAN
    APP <-->|"entrenos · peso · comidas · rutinas"| PG
    BOT <-->|"las mismas tablas"| PG
    PAN <--> PG
    BOT -.->|"importa métricas y nutrición"| APP

    style TU fill:#fff4e6,stroke:#e8590c,stroke-width:2px
    style APP fill:#b2f2bb,stroke:#2f9e44,stroke-width:3px
    style BOT fill:#f3d9fa,stroke:#9c36b5,stroke-width:2px
    style PAN fill:#f8f0fc,stroke:#9c36b5,stroke-width:2px
    style PG fill:#fff3bf,stroke:#f08c00,stroke-width:3px
```

Esa última flecha de puntos es fácil de olvidar y muerde: el bot **no reimplementa** la nutrición ni las métricas, importa los ficheros `nutrition.py` y `analytics.py` de esta carpeta. Si los tocas, hay que reiniciar **también el bot**.

---

## Cómo abrirla

En el navegador de este PC:

```
http://127.0.0.1:8550
```

Si no carga, mira primero si el servicio está vivo (más abajo, "Arrancar, parar y mirar").

### Abrirla desde el móvil

Hay **dos caminos distintos**, y conviene no confundirlos porque los datos no van al mismo sitio:

| | **La APK** (app instalada) | **El navegador del móvil** (modo web) |
|---|---|---|
| ¿Necesita el PC encendido? | **No** | Sí, y estar en la misma wifi |
| ¿Dónde viven los datos? | En el propio móvil, en SQLite | En PostgreSQL del PC |
| ¿Los ve el bot de Telegram? | **No**, son una isla | Sí, es la misma base |
| Para qué sirve | Entrenar en el gimnasio sin cobertura | Usarla desde el sofá |

Lo que pediste —una app que funcione con el PC apagado— es **la APK**. Está explicada justo debajo. El modo web por wifi sigue existiendo y se explica después.

---

## 📱 La APK: IronFlet en el móvil, sin PC

### Cómo funciona por dentro

En el móvil no hay PostgreSQL ni lo puede haber, así que la app usa **SQLite**: un único fichero, `ironflet.db`, en el almacenamiento privado de la app. No hay servidor, no hay red, no hay contenedor. Se abre el fichero y ya.

La app decide sola qué base usar, en este orden (**el primero que exista gana**):

1. La URL que se le pase por código.
2. La variable `DATABASE_URL`.
3. **SQLite**, si detecta que está corriendo en Android.
4. PostgreSQL (lo de siempre, en el PC).

Que `DATABASE_URL` mande **por encima** de la detección de Android es deliberado: el servicio `ironflet-web` la trae escrita en su fichero de systemd, así que **este PC nunca se va a pasar a SQLite por accidente** y nunca se va a desconectar en silencio de la base que comparte con el bot.

Android se detecta preguntándole al propio intérprete de Python si fue compilado para Android, no mirando variables de entorno. Eso importa porque hay una variable (`FLET_APP_STORAGE_DATA`) que *parece* la señal buena y **no lo es**: Flet también la exporta en escritorio, así que usarla habría pasado tu PC a un SQLite vacío la primera vez que lanzaras `flet run`, sin ningún error, solo con el historial en blanco.

### Cómo pasas los datos de un lado a otro

**No hay sincronización.** El móvil y el PC son dos bases separadas y nadie las mezcla solo. Lo que hay es un **backup en un fichero JSON** que exporta y se importa a mano. Ese fichero lleva las **12 tablas**: entrenos, pesos, perfil, preferencias, las cuatro de comida y las cuatro de rutinas.

El viaje típico, del PC al móvil nuevo:

1. En el PC, exportar → sale un `.json`.
2. Pasarlo al móvil como quieras (cable, Drive, Telegram, correo).
3. En el móvil, importar y confirmar.

Dos cosas que conviene tener claras antes de tocar el botón:

- **Importar con "borrar" puesto vacía las 12 tablas** y deja solo lo del fichero. En un móvil recién estrenado da igual (no hay nada que perder), pero en uno con datos sí.
- **Las imágenes de los ejercicios no viajan en el backup.** Son ~9 MB que se descargan aparte, desde la propia app, cuando tengas wifi. Es a propósito: meterlas en la APK la engordaría para algo que se baja una vez.

> **⚠️ Ojo, esto todavía no está terminado.** El motor de backup de 12 tablas (`backup.py`) está hecho y probado, y la pantalla que lo usa (`views/data_view.py`) también. Pero **esa pantalla aún no está enganchada al menú**: `main.py` no la registra. Mientras tanto, el único backup al que se llega desde la app es el viejo de **Settings → Backup**, que exporta **4 tablas de 12** y **se deja la comida y tus rutinas sin avisar de nada**. Hasta que se enganche, para una copia completa usa `pg_dump` (más abajo).

### Qué necesitas para compilar la APK

**Buenas noticias: en este PC ya está todo, y la APK ya se ha construido de verdad.** No hace falta que instales nada.

`flet build apk` **se instala solo lo que le falta** la primera vez. En este ordenador se descargó y dejó puesto:

| Qué | Dónde quedó | Cuánto ocupa (medido) |
|---|---|---|
| Flutter 3.29.2 | `~/flutter/3.29.2` | 1,6 GB |
| JDK 17.0.13 | `~/java/17.0.13+11` | 316 MB |
| Android SDK (platform-tools, platforms 31/33/34/35, build-tools 34, NDK 25, CMake) | `~/Android/sdk` | 2,7 GB |
| Paquetes de Dart/Flutter | `~/.pub-cache` | 704 MB |
| Caché de Gradle | `~/.gradle` | 3,9 GB |

**Unos 9,1 GB en total**, todo fuera del repositorio. Si algún día necesitas el disco, se puede borrar entero y se vuelve a descargar solo en la siguiente compilación.

No hace falta Android Studio. `flutter doctor` se queja de que falta el *Linux toolchain* (clang, cmake, ninja, pkg-config), pero **eso solo afecta a compilar para escritorio Linux**, no a la APK. La APK se construyó con esa queja presente.

### El comando

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && .venv/bin/flet build apk
```

Si ese comando falla con *"no se ha encontrado el fichero requerido"*, no es cosa de Flet: es que los lanzadores del entorno virtual siguen apuntando a la ruta antigua del proyecto (ver "Cuando algo va mal"). Rodeo mientras tanto:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && .venv/bin/python -c "from flet.cli import main; main()" build apk
```

Tarda unos **7 minutos** la primera vez (se baja NDK y CMake) y ~2 las siguientes. La APK sale en:

```
build/apk/app-release.apk
```

Pesa **73 MB**. Se instala copiándola al móvil y abriéndola; Android pedirá permiso para instalar de orígenes desconocidos porque no viene de la Play Store.

### Dos cosas que hubo que arreglar para que la APK saliera

Merece la pena que estén escritas, porque si alguien las deshace la APK deja de compilar y el error no dice por qué.

**1. `psycopg` y `flet[all]` ya no son dependencias fijas.** `flet build apk` lee la lista de dependencias del `pyproject.toml` y **se las instala al móvil**. Ahí había tres cosas que en Android no existen:

- `psycopg[binary]` — el driver de PostgreSQL, que es un binario compilado. No hay versión para Android.
- `flet[all]` → arrastra `watchdog`, que tampoco tiene versión para Android. **Este era el que rompía la compilación**, con el mensaje `No matching distribution found for watchdog`.
- `flet[all]` → arrastra además `uvicorn[standard]` (`uvloop`, `httptools`, `watchfiles`), tres binarios más del servidor web que el móvil no usa.

Ahora la lista fija es solo `flet` y `sqlalchemy`, y lo demás vive en dos extras (`web` y `postgres`) que el PC sí instala. Quitar `psycopg` del móvil es seguro porque SQLAlchemy solo carga el driver **cuando la URL lo pide**, y en el móvil la URL es de SQLite. El `sqlite3` va dentro del propio Python, así que el móvil no necesita driver ninguno.

**2. La APK se estaba llevando el entorno virtual entero.** Flet empaqueta *toda la carpeta del proyecto*, y lo único que excluye por su cuenta es `build/`. Resultado: la primera APK que salió pesaba **237 MB**, de los cuales **154 MB eran el `.venv` de este PC** — con `psycopg`, `libpq`, `watchdog`, `uvloop` y un montón de binarios `x86_64` que un móvil ARM ni siquiera puede cargar. También se colaba el `.git` entero.

Se arregló con una lista de exclusiones en `pyproject.toml`. El resultado, medido:

| | Antes | Ahora |
|---|---|---|
| APK | 237 MB | **73 MB** |
| Código Python empaquetado | 174,6 MB | **0,8 MB** |
| Ficheros dentro | 10.252 | **47** |

Esa lista compara **rutas exactas, no comodines**. Por eso están escritos uno a uno los `__pycache__` de cada carpeta: poner solo `__pycache__` excluiría el de la raíz y colaría los otros cuatro. **Si añades una carpeta de código nueva, hay que añadir su `__pycache__` a mano.**

Lo que queda de los 73 MB es Flutter y el Python embebido para **tres arquitecturas** (`arm64-v8a`, `armeabi-v7a`, `x86_64`). Si algún día molesta el tamaño, `flet build apk --split-per-abi` saca una APK por arquitectura y la de tu móvil bajaría a la mitad larga.

---

### Abrirla desde el móvil por wifi (modo web, con el PC encendido)

Esto es lo otro: usar la app del PC desde el navegador del móvil. **Por defecto no se puede, y es a propósito.** La app escucha solo en `127.0.0.1`, o sea, solo acepta conexiones desde este mismo ordenador. Desde el móvil no llegas ni estando en tu wifi.

Se puede cambiar, pero conviene que sepas exactamente qué estás aceptando.

Edita el fichero del servicio:

```bash
systemctl --user edit --full ironflet-web
```

Añade esta línea junto a las otras `Environment=`:

```ini
Environment=IRONFLET_HOST=0.0.0.0
```

Recarga y reinicia:

```bash
systemctl --user daemon-reload && systemctl --user restart ironflet-web
```

Averigua la IP de este PC en tu red:

```bash
hostname -I | awk '{print $1}'
```

Y desde el móvil abre `http://ESA_IP:8550`.

**El compromiso, sin adornos:** con `0.0.0.0` la app queda accesible para **cualquier aparato de tu red local** — tu móvil, sí, pero también el portátil de quien esté en casa, la tele, un invitado con la contraseña del wifi, cualquier cosa conectada. **La app no pide contraseña**: quien llegue a esa dirección ve tu peso, tus medidas, tus entrenos y lo que comes, y puede borrarlo. No hay usuarios ni login que valga.

Si aun así lo quieres, dos cosas que reducen el riesgo:

- Ponlo solo cuando lo vayas a usar y quítalo después (borra la línea, `daemon-reload`, `restart`).
- Ojo con las redes wifi compartidas. En tu casa con tu gente es una cosa; en un piso compartido o un coworking es otra.

La base de datos, en cambio, **sigue en loopback pase lo que pase**: el contenedor de PostgreSQL solo publica `127.0.0.1:5432`, y eso no lo toca `IRONFLET_HOST`.

---

## Qué hay en cada pantalla

Abajo hay una barra con **cinco pestañas**:

| Pestaña | Qué es |
|---|---|
| **Home** | El resumen del día: racha 🔥, sesiones/series/volumen de los últimos 7 días, lo que llevas comido hoy y lo que has entrenado hoy |
| **Plan** | La rutina activa por fases y días, con los esquemas de series |
| **Train** | Entrenar: eliges fase y día, y vas apuntando serie a serie |
| **Food** | El diario de comidas del día |
| **History** | Historial y progreso: récords, gráficas de progresión, series por músculo |

Hay **tres pantallas más** que no tienen pestaña propia y se abren desde dentro:

- **Exercises** (el catálogo de ejercicios con imágenes y explicación) → botón "Exercises" en Home, al lado de "Start Routine".
- **Settings** (perfil, peso, copias de seguridad, borrar datos) → el icono del engranaje ⚙️ arriba a la derecha en Home.
- **Routines** (el editor de rutinas) → desde Plan, editando o duplicando una rutina.

Vienen **4 rutinas ya hechas**: CambiaTuFísico (7 fases, la de por defecto), Upper/Lower, Push/Pull/Legs y Recomp PPL+UL (la que sigue el entrenador de Telegram). Hay **68 ejercicios con ficha** explicada y **86 con imagen**.

> Antes eran ocho: las cuatro `Women` se quitaron en la 0.2.0 porque esta app la usas solo tú. Los cuatro ejercicios que ya no prescribe ninguna rutina (`HIIT Intervals`, `Hyperextensions`, `Leg Raises` y `Triceps Kickback`) siguen en el catálogo, así que los tienes disponibles en Browse y en el editor de rutinas.

---

## Lo nuevo

### 🍽 Comida (pestaña "Food")

Un diario de lo que comes, dividido en cinco momentos del día: desayuno, media mañana, comida, merienda y cena.

- **Catálogo de alimentos** con los macros por 100 g, más raciones con nombre ("1 plátano mediano" = 120 g) para no tener que pesarlo todo.
- **Favoritos y frecuentes**: los que más usas salen arriba para meterlos de un toque.
- **Copiar el día anterior**: si comes parecido, un botón y ya.
- **Objetivos con versiones**: cuando cambias los objetivos de macros, **no se reescribe el pasado**. El plan dice que si la cintura sube 1 cm hay que quitar 150 kcal — cuando lo hagas, los días de antes se siguen juzgando con el objetivo que tenían entonces, no con el nuevo. Tu adherencia de hace un mes no cambia porque hoy hayas movido un número.
- **Lo apuntado se congela**: cada línea del diario guarda las calorías y macros de esa ración, no un enlace al alimento. Si el mes que viene corriges la ficha del pollo, la comida del martes pasado sigue con los números con los que la apuntaste. Un diario es un registro de lo que pasó.

Los macros del catálogo siguen la convención de etiqueta **europea**: los hidratos van *sin* la fibra, que va aparte. (Las tablas americanas los suman; si copias un número de ahí sin restar la fibra, te salen los hidratos como un 10 % altos.)

El resumen de lo que llevas hoy también aparece en Home, y el bot de Telegram lee y escribe este mismo diario.

### 🏗 Editor de rutinas (pantalla "Routines")

Ya no estás atado a las 4 rutinas que vienen de fábrica. Puedes:

- Crear una rutina desde cero.
- **Duplicar una de las de fábrica** y tocarla a tu gusto (la original no se toca nunca).
- Añadir y quitar fases, días y ejercicios; moverlos de orden.
- Elegir ejercicios de un buscador sobre el catálogo, para que los nombres cuadren con los del historial.

Las rutinas que te hagas se guardan en la base de datos, así que sobreviven a reinicios y las ve también el bot.

### 📊 Métricas (pestaña "History")

- **Récords personales** por ejercicio, de tres tipos: mejor 1RM estimado (fórmula de Epley), peso máximo levantado y mejor volumen en una sesión. Cuando haces uno nuevo, la app te lo dice al terminar el ejercicio.
- **Progresión** del 1RM estimado a lo largo del tiempo.
- **Series semanales por grupo muscular**, para ver desequilibrios (y qué grupos llevas tiempo sin tocar).
- **Media móvil del peso corporal**, que es lo que hay que mirar: el peso de un día suelto no dice nada.

Dos cambios importantes en cómo se cuentan las cosas:

- **La racha 🔥 ahora cuenta SEMANAS, no días.** Antes contaba días seguidos entrenando, lo cual es absurdo en un plan que tiene días de descanso: la racha se rompía cada fin de semana por diseño. Ahora una semana cuenta si has entrenado los días que pide la rutina, y la semana en curso (aún sin terminar) no se penaliza.
- **"Sessions" cuenta días entrenados, no ejercicios.** Antes una sesión de seis ejercicios salía como "6 Sessions".

### 🏷 Tipos de serie y descanso automático

Cada serie que apuntas puede ser de cuatro tipos, y se cambia **tocando la etiqueta de la serie** (va rotando):

| | Tipo | Cuenta como trabajo |
|---|---|---|
| **N** | Working set (normal) | Sí |
| **W** | Warm-up (calentamiento) | **No** |
| **D** | Drop set | Sí |
| **F** | To failure (al fallo) | Sí |

El calentamiento es el único que se descuenta: no infla el volumen y **no puede robarte un récord**. Antes, un calentamiento pesado podía marcarse como PR.

El **descanso** se pone solo al terminar cada serie, según el ejercicio y el tipo de serie:

- **180 s en los básicos** — press banca, press militar, press inclinado, prensa, remo con barra, hip thrust, sentadilla, peso muerto (y rumano), fondos y dominadas.
- **90 s en el resto.**
- **60 s después de un calentamiento**, que no es la serie de la que hay que recuperarse.

Si la fase de la rutina trae su propio descanso escrito, manda ese. Y son los mismos números que te dice el bot en el móvil: hay un test que carga la lista del bot y la compara con la de la app, así que el día que alguien cambie uno salta el test en vez de que la app y el bot te den descansos distintos.

---

## Arrancar, parar y mirar el estado

Las tres piezas son servicios de usuario de systemd. Todos los comandos llevan `--user`.

**Ver si está viva:**

```bash
systemctl --user status ironflet-web
```

**Las tres de un vistazo:**

```bash
systemctl --user status ironflet-web entrenador-bot entrenador-panel --no-pager
```

**Solo si están activas o no (respuesta corta):**

```bash
systemctl --user is-active ironflet-web entrenador-bot entrenador-panel
```

**Arrancar:**

```bash
systemctl --user start ironflet-web
```

**Parar:**

```bash
systemctl --user stop ironflet-web
```

**Reiniciar (lo que necesitas tras tocar código):**

```bash
systemctl --user restart ironflet-web
```

**Reiniciar las tres en el orden seguro** (para bot y panel, reinicia la app, los vuelve a levantar y te enseña el arranque):

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && make deploy
```

Ese orden importa: el bot y el panel mantienen conexiones abiertas contra la base de datos, y si cambia el esquema mientras están conectados se quedan bloqueados.

---

## Ver los logs

Aquí es donde se ve por qué algo no funciona.

**Seguir los mensajes en vivo** (déjalo abierto y reproduce el fallo; se sale con `Ctrl+C`):

```bash
journalctl --user -u ironflet-web -f
```

**Las últimas 50 líneas:**

```bash
journalctl --user -u ironflet-web -n 50 --no-pager
```

**Solo lo de hoy:**

```bash
journalctl --user -u ironflet-web --since today --no-pager
```

**Solo errores:**

```bash
journalctl --user -u ironflet-web -p err --no-pager
```

**Las tres piezas mezcladas por orden de hora** — muy útil cuando no sabes cuál falla:

```bash
journalctl --user -u ironflet-web -u entrenador-bot -u entrenador-panel -f
```

**Y los de la base de datos**, que es un contenedor y no va por journalctl:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion && docker compose logs -f postgres
```

---

## La base de datos

PostgreSQL 17 en Docker, escuchando **solo** en `127.0.0.1:5432`. La define `docker-compose.yml` en la carpeta padre.

**Ver si está en marcha:**

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion && docker compose ps
```

**Levantarla** (si está caída, la app no arranca: sin base no hay nada que enseñar):

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion && docker compose up -d
```

Dentro hay **18 tablas**. Las que te importan:

| Tabla | Qué guarda |
|---|---|
| `entrenos` | Una fila por ejercicio y día, con todas sus series (peso, reps, RIR, tipo) |
| `pesos` | Tu peso corporal, una fila por día |
| `perfil` | Nombre, fecha de nacimiento, altura, sexo, nivel de actividad |
| `preferencias` | Ajustes sueltos (hoy solo: cuál es tu rutina activa) |
| `foods`, `servings` | El catálogo de alimentos y sus raciones con nombre |
| `food_log` | El diario de comidas |
| `nutrition_targets` | Los objetivos de macros, uno por cada vez que los cambias |
| `user_routines` y sus 3 tablas hijas | Las rutinas que te hayas construido tú |
| `recordatorios`, `medidas`, `adherencia`, `sesiones`, `checkins`, `conversacion` | Cosas del bot: avisos, medidas de cinta, si cumpliste la dieta, check-ins semanales y el historial de la conversación |

Las tablas de entreno, nutrición y rutinas **las comparten la app y el bot**. Las últimas seis son solo del bot.

**Ver qué hay, sin tocar nada:**

```bash
docker exec entrenador-postgres psql -U entrenador -d entrenador -c "\dt"
```

**Contar tus entrenos:**

```bash
docker exec entrenador-postgres psql -U entrenador -d entrenador -c "SELECT count(*) FROM entrenos;"
```

---

## Copia de seguridad

### La copia completa (la que importa)

Un fichero con **toda** la base de datos, fechado:

```bash
docker exec entrenador-postgres pg_dump -U entrenador entrenador > ~/copias/entrenador-$(date +%Y%m%d).sql
```

Crea la carpeta la primera vez:

```bash
mkdir -p ~/copias
```

Comprueba que la copia no está vacía (debería pesar decenas de KB o más, nunca 0):

```bash
ls -lh ~/copias/
```

**Guarda ese fichero fuera de este ordenador.** Una copia que vive en el mismo disco que los datos no es una copia de seguridad.

### Restaurar

Con las tres piezas paradas, porque restaurar sobre una base en uso no sale bien:

```bash
systemctl --user stop ironflet-web entrenador-bot entrenador-panel
```

```bash
cat ~/copias/entrenador-20260814.sql | docker exec -i entrenador-postgres psql -U entrenador -d entrenador
```

```bash
systemctl --user start ironflet-web entrenador-bot entrenador-panel
```

### La copia desde dentro de la app

Aquí hay que distinguir **lo que ya funciona** de **lo que todavía no se puede tocar**, porque ahora mismo conviven dos backups distintos y el que está a la vista es el malo.

**Lo que ves hoy en Settings → Backup** saca un JSON con perfil, preferencias, entrenos y pesos: **4 tablas de 12**. Se deja fuera, sin decírtelo:

- el catálogo de alimentos y sus raciones,
- **el diario de comidas entero**,
- los objetivos de macros,
- **las rutinas que te hayas construido tú**.

Comprobado midiéndolo sobre una base de prueba: ese backup exporta `workouts`, `weights`, `profile` y `prefs`, y nada más. Si haces esa copia y la restauras encima, la comida y tus rutinas **desaparecen sin un aviso**.

**Lo que ya está escrito y probado pero aún no se puede usar**: `backup.py` hace el export/import de las **12 tablas** (formato versión 3, y sigue leyendo los ficheros viejos de la versión 2), y `views/data_view.py` es la pantalla que lo maneja, con vista previa y doble confirmación antes de borrar nada. Falta un paso: **registrar esa pantalla en `main.py`** para que se pueda llegar a ella.

He verificado el motor de punta a punta: llené una base SQLite con las 12 tablas (119 filas), exporté a fichero, importé en una base vacía y comparé **tabla por tabla y columna por columna**. No se pierde ni cambia nada, y el documento reexportado sale idéntico al original.

**Mientras tanto: para una copia completa, usa `pg_dump`** (arriba). No uses el botón de Settings creyendo que te lo lleva todo.

---

## Cuando algo va mal

**La página no carga en 127.0.0.1:8550**

```bash
systemctl --user status ironflet-web
```

Si sale `inactive` o `failed`, mira por qué:

```bash
journalctl --user -u ironflet-web -n 40 --no-pager
```

**Casi siempre es la base de datos.** Si el contenedor está caído, la app no arranca:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion && docker compose up -d
```

**Ves una versión antigua de la app.** Ya sabes: reinicia. Y comprueba la hora de arranque.

```bash
systemctl --user restart ironflet-web && systemctl --user show ironflet-web -p ActiveEnterTimestamp
```

**Falta algo que apuntaste por Telegram.** Es la misma base, así que o no se guardó o no has refrescado. Cambia de pestaña y vuelve, que cada pantalla relee al mostrarse. Si sigue sin estar, mira los logs del bot:

```bash
journalctl --user -u entrenador-bot -n 60 --no-pager
```

**El servicio se reinicia solo una y otra vez.** Está puesto para reintentar cada 10 s, así que un fallo de arranque se ve como un bucle. Los logs te dicen el error de verdad:

```bash
journalctl --user -u ironflet-web --since "10 min ago" --no-pager | grep -i error
```

**`.venv/bin/flet` (o `pytest`, o `ruff`) dice "no se ha encontrado el fichero requerido".** El fichero está ahí, no te has vuelto loco. Lo que pasa es que el proyecto se movió de sitio y esos lanzadores llevan escrita **la ruta vieja** en la primera línea:

```bash
head -1 .venv/bin/flet
# #!/home/wdna/git/ironflet-final/.venv/bin/python   <- ya no existe
```

Son **14 ficheros** de `.venv/bin/` los que están así. El rodeo, que funciona siempre, es llamar al módulo en vez del lanzador:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -c "from flet.cli import main; main()" build apk
```

Y el arreglo de verdad es rehacer el entorno:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && rm -rf .venv && make deps
```

Acuérdate de que `make deps` hace las dos cosas en el orden que importa (`uv sync` y *después* CanvasKit); si haces solo `uv sync`, la app se queda sin las imágenes de CanvasKit y se las pide a Google, que en un gimnasio sin cobertura falla.

---

## Comprobar que todo sigue en pie

Antes de dar por buena cualquier cosa que hayas tocado:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && make test
```

Son **538 pruebas** y tardan unos 20 segundos. Comprueban las métricas, la nutrición, el editor de rutinas, los tipos de serie, el contraste de los colores, el backup completo de las 12 tablas, que la app funciona igual sobre SQLite que sobre PostgreSQL, y que la clave con la que se guardan los ejercicios sigue coincidiendo con la que usa el bot.

**Cuidado con una cosa:** una buena parte necesita la base de datos y, si tu terminal no tiene `DATABASE_URL`, se **saltan en silencio** — verás un montón de `skipped` y parecerá que todo va bien sin haber probado nada de nutrición. Juzga la ejecución por el número de saltos, no por el de aprobados. Para ejecutarlas todas de verdad:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && export $(grep '^DATABASE_URL=' ../agente/.env | xargs) && make test
```

Tiene que decir **`538 passed`**. Esas pruebas trabajan contra una base aparte (`entrenador_test`), nunca contra tus datos.

**No lances dos veces las pruebas a la vez.** Todas comparten la misma base `entrenador_test` y se pisan entre ellas: verás fallos raros e inconstantes en nutrición y rutinas que no tienen nada que ver con tu cambio. Si necesitas una ejecución aislada, dale su propia base:

```bash
docker exec entrenador-postgres psql -U entrenador -d postgres -c "CREATE DATABASE ironflet_scratch OWNER entrenador;"
TEST_DATABASE_URL="postgresql+psycopg://entrenador:LA_CONTRASEÑA@127.0.0.1:5432/ironflet_scratch" .venv/bin/python -m pytest -q
```

Todo a la vez (formato del código + pruebas), que es lo mismo que se ejecuta en CI:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && make check
```

Y las del bot, que incluyen la prueba que compara los dos esquemas de base de datos:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/agente && .venv/bin/python -m pytest -q
```

Son **82** en ese lado.

---

## Chuleta

```bash
# Está viva?
systemctl --user is-active ironflet-web entrenador-bot entrenador-panel
```

```bash
# He tocado código -> reiniciar (SIEMPRE)
systemctl --user restart ironflet-web
```

```bash
# Qué está pasando
journalctl --user -u ironflet-web -f
```

```bash
# Copia de seguridad
docker exec entrenador-postgres pg_dump -U entrenador entrenador > ~/copias/entrenador-$(date +%Y%m%d).sql
```

```bash
# Abrir la app
xdg-open http://127.0.0.1:8550
```

---

<div align="center">

**Plan de Recomposición** · IronFlet · El entrenador vive en [`../agente/`](../agente/README.md)

&copy; 2026 Alex Nolasco

</div>
