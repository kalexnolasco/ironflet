# IronFlet — tu app de entrenos y comidas

<div align="center">

![Proyecto](https://img.shields.io/badge/Proyecto-IronFlet-blue?style=for-the-badge)
![Servicio](https://img.shields.io/badge/servicio-ironflet--web-FCC624?style=for-the-badge&logo=linux&logoColor=black)
![Acceso](https://img.shields.io/badge/127.0.0.1%3A8550-solo%20este%20PC-lightgrey?style=for-the-badge)
![Flet](https://img.shields.io/badge/Flet-0.28.3-7F52FF?style=for-the-badge)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/tests-340-2f9e44?style=for-the-badge)

**Donde apuntas lo que levantas y lo que comes. La misma base de datos que usa el entrenador de Telegram: lo que escribes aquí lo ve él al instante, y al revés.**

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

**Hoy no se puede, y es a propósito.** La app escucha solo en `127.0.0.1`, o sea, solo acepta conexiones desde este mismo ordenador. Desde el móvil no llegas ni estando en tu wifi.

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

Vienen **8 rutinas ya hechas**: CambiaTuFísico (7 fases, la de por defecto), Upper/Lower, Push/Pull/Legs, Recomp PPL+UL (la que sigue el entrenador de Telegram) y cuatro de Women. Hay **68 ejercicios con ficha** explicada y **86 con imagen**.

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

Ya no estás atado a las 8 rutinas que vienen de fábrica. Puedes:

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

En **Settings → Backup** hay un "Export backup" que saca un JSON con perfil, preferencias, entrenos y pesos. Sirve para llevarte el historial de entrenamiento, pero **no incluye la comida, ni las rutinas que te hayas hecho, ni nada del bot**. Para tenerlo todo, usa `pg_dump`.

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

---

## Comprobar que todo sigue en pie

Antes de dar por buena cualquier cosa que hayas tocado:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && make test
```

Son **340 pruebas** y tardan unos segundos. Comprueban las métricas, la nutrición, el editor de rutinas, los tipos de serie, el contraste de los colores y que la clave con la que se guardan los ejercicios sigue coincidiendo con la que usa el bot.

**Cuidado con una cosa:** unas 100 de esas pruebas necesitan la base de datos y, si tu terminal no tiene `DATABASE_URL`, se **saltan en silencio** — verás `238 passed, 102 skipped` y parecerá que todo va bien sin haber probado nada de nutrición. Para ejecutarlas todas de verdad:

```bash
cd /home/wdna/Documents/Personal/plan-recomposicion/ironflet && export $(grep '^DATABASE_URL=' ../agente/.env | xargs) && make test
```

Tiene que decir **`340 passed`**. Esas pruebas trabajan contra una base aparte (`entrenador_test`), nunca contra tus datos.

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
