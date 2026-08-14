# Contribuir a IronFlet

Gracias por el interés. Este proyecto es pequeño y personal, pero las
aportaciones son bienvenidas.

## Qué es esta app hoy

Tres cosas que condicionan casi todo lo demás:

- **Solo inglés.** No hay capa de traducción. `i18n.py` se eliminó y con él
  `t()`, `t_exercise()`, `t_muscle()`, el diccionario `ES` y el selector de
  idioma. Todo el texto visible es un literal en inglés escrito en la vista.
- **Tema claro, fijo.** `theme.LIGHT` es el que se aplica. `DARK` existe en el
  código y también cumple AA, pero no hay ningún botón para cambiarlo.
- **Necesita base de datos.** El almacenamiento es PostgreSQL 17 con SQLAlchemy
  2.x, no SQLite, y la base **se comparte** con el bot de Telegram de
  `../agente/`. Sin el contenedor levantado la app no arranca.

## Setup

```bash
git clone https://github.com/kalexnolasco/ironflet
cd ironflet
make deps                        # uv sync --group dev + vendor de CanvasKit
uv run pre-commit install        # instala hook de lint + formato
```

Usa `make deps`, no `uv sync` a secas: **el orden importa**. Los ~12 MB de
CanvasKit no son un paquete de Python — los baja `scripts/vendor_canvaskit.py`
dentro del `flet_web` ya instalado y parchea `flutter_bootstrap.js`. Cualquier
reinstalación de `flet_web` borra las dos cosas y la app vuelve, en silencio, a
descargar CanvasKit de Google.

Levanta la base antes de ejecutar o testear nada:

```bash
cd .. && docker compose up -d
```

Para arrancar la app en modo web (que es como se usa de verdad):

```bash
make run                         # IRONFLET_WEB=1, escucha en 127.0.0.1:8550
```

## Flujo de trabajo

1. Abre un issue antes de cambios grandes para discutir el enfoque.
2. Crea una rama descriptiva: `feat/nombre-corto` o `fix/bug-x`.
3. Confirma que pasa el linter y los tests:
   ```bash
   make check                    # exactamente lo que ejecuta CI
   ```
4. Abre el PR contra `main` con una descripción clara del cambio.

### Cuidado: hay tests que se saltan solos

La suite son **340 pruebas**, pero 102 de ellas necesitan una base de datos y,
si no la encuentran, se **saltan en silencio**. Sin nada en el entorno verás:

```
238 passed, 102 skipped
```

Eso parece verde y no ha probado nada de nutrición, almacenamiento ni editor de
rutinas. **Mira siempre el número de `skipped`, no el de `passed`.**

Las pruebas buscan primero `TEST_DATABASE_URL`; si no está, derivan la base de
`DATABASE_URL` cambiándole el nombre a `entrenador_test`. En ninguno de los dos
casos tocan datos reales. Levanta el contenedor y pásales una de las dos:

```bash
cd .. && docker compose up -d && cd ironflet
export $(grep '^DATABASE_URL=' ../agente/.env | xargs) && make test
```

No des por bueno un cambio hasta que el `skipped` sea 0.

Si tocas cualquier tabla compartida, ejecuta también la suite del bot, que
incluye `test_modelos_espejo.py`, la comparación de los dos esquemas:

```bash
cd ../agente && .venv/bin/python -m pytest -q
```

## Estilo

- Código formateado con `ruff format` (línea 100).
- `ruff check` con `E`/`F`/`W` más `I` (imports), `UP` (upgrades), `B`
  (bugbear), `C4` (comprehensions), `SIM` (simplify).
- Prefiere funciones y helpers cortos, sin estado global. Para estado de UI,
  usa variables en la clase `View` y `page.data["refresh_current"]()`.

## Las cuatro reglas que se rompen en silencio

Ninguna de estas lanza una excepción cuando la incumples. Por eso están aquí.

**1. Todo el texto visible al usuario es un literal en inglés en la vista.**
No hay función de traducción que llamar ni diccionario al que añadir nada.

**2. Ningún color hex en una vista.** Todo color sale de `from theme import C`,
que resuelve contra la paleta activa en el momento del acceso al atributo. Eso
incluye los colores de fase: `exercises.phase_color(id)` indexa `C.phase`, así
que la fase es el *índice* y el tema decide el tono. Un hex escrito a mano —o
una constante de color a nivel de módulo, que queda congelada en el import— se
salta la paleta. `tests/test_theme.py` recalcula el contraste WCAG de cada par
en las dos paletas.

**3. Todo nombre de ejercicio que llegue a la base pasa por `exercise_key()`**
(`exercises.py`). Convierte `"Squat [5×12,10,8,8,8]"` en `"Squat"`, y ese nombre
pelado **es** la clave con la que se guarda cada serie en `entrenos.ejercicio`.
El bot de Telegram escribe esa misma columna con su propio `a_canonico()`. Si la
normalización cambia, no salta nada: las filas simplemente dejan de cuadrar, la
app escribe una clave y el bot otra, y el historial del que depende todo el plan
se parte en dos. Congelado en `tests/test_exercise_key.py` (282 cadenas de
rutina colapsan en exactamente 104 claves). Un fallo ahí es un incidente de
integridad de datos, no una nota de formato.

**4. Un cambio de esquema se hace a la vez aquí y en
`../agente/entrenador/modelos.py`.** Los modelos SQLAlchemy están duplicados a
mano. Nadie ejecuta migraciones: cada programa llama a `create_all()` al
arrancar y crea la tabla el que llegue primero. Si las dos declaraciones
difieren, `create_all` ni lo detecta ni lo repara — se queda callado y el otro
proceso muere más tarde con un `UndefinedColumn` a mitad de consulta. Los dos
ficheros, en el mismo commit. Lo vigila
`../agente/tests/test_modelos_espejo.py`, que compara columnas, tipos,
nullability, defaults, claves primarias y ajenas, constraints e índices.

Y una consecuencia de compartir base que conviene tener presente: las filas que
escribe el bot no llevan las claves opcionales `"rir"` ni `"type"` en sus
series. Léelas siempre con `.get()`, y trata una serie sin `"type"` como
**normal** — nunca como calentamiento, porque eso reescribiría el tonelaje.

## Añadir una rutina nueva

En `data.py`:

1. Crea las listas `XX_PHASES: list[Phase]` y `XX_DAYS: list[TrainingDay]`.
2. Añade una entrada más a `ROUTINES` con un `id` estable.
3. Escribe los nombres de ejercicio **exactamente igual** que los que ya
   existen. Un nombre que difiera en una tilde o un guion es un ejercicio
   distinto en el historial, y no hay nada que avise.
4. Comprueba que todos esos nombres existen en `EXERCISE_IMAGE`
   (`exercise_images.py`) si quieres que muestren imagen e instrucciones.
5. Añadir ejercicios cambia las cuentas congeladas en
   `tests/test_exercise_key.py` (`CADENAS_ESPERADAS`, `CLAVES_ESPERADAS`).
   Actualízalas a conciencia, nunca sólo para que un test rojo se ponga verde.

## Añadir un ejercicio con imagen

1. Encuentra el slug en
   [Free Exercise DB](https://github.com/yuhonas/free-exercise-db/blob/main/dist/exercises.json).
2. Añade la entrada a `EXERCISE_IMAGE` en `exercise_images.py`.
3. Comprueba que ese slug existe también en `exercise_details.py`, que está
   autogenerado (el script de extracción está en el historial de git).
   `EXERCISE_IMAGE` es la clave para las dos cosas: cambiar un slug mueve la
   foto **y** los datos musculares, y un slug que la tabla de detalles no tenga
   deja el ejercicio fuera de `sets_per_muscle_group` sin decir nada.
4. Rehaz el tarball de Releases y publica una versión nueva (la constante
   `RELEASE_VERSION` en `asset_manager.py` debe apuntar a ese tag).

Los nombres compuestos y las superseries (con `+`, o con prefijo `Bi-set:`,
`SS:` o `Triset:`) no llevan imagen a propósito.

## Subir la versión

Edita **a la vez** el campo `version` de `pyproject.toml` y el fichero
`VERSION`, y añade la entrada correspondiente en `CHANGELOG.md`.

## Reportar un bug

Usa la plantilla de Bug report en la pestaña Issues. Incluye cómo la estás
ejecutando (web en `127.0.0.1:8550`, o escritorio), la versión (fichero
`VERSION`) y los pasos para reproducir. Si es un fallo de arranque, el log
importa más que la descripción:

```bash
journalctl --user -u ironflet-web -n 50 --no-pager
```

## Créditos y licencias de terceros

- **Imágenes e instrucciones base de ejercicios**:
  [Free Exercise DB](https://github.com/yuhonas/free-exercise-db) — Unlicense /
  dominio público. No se redistribuyen con el código: `asset_manager.py` las
  descarga en runtime desde una release de este repositorio.
- **Estructura de categorías de rutinas** inspirada en la clasificación pública
  de [cambiatufisico.com](https://www.cambiatufisico.com). Cada rutina está
  modelada como datos (series × reps + ejercicios); los textos explicativos y
  los tips in-app son originales.

## Licencia de tus aportaciones

Al abrir un PR aceptas que tu contribución se licencie bajo MIT, igual
que el resto del proyecto.
