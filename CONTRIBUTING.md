# Contribuir a IronFlet

Gracias por el interés. Este proyecto es pequeño y personal, pero las
aportaciones son bienvenidas.

## Qué es esta app hoy

Tres cosas que condicionan casi todo lo demás:

- **Todo en español.** No hay capa de traducción: cada texto visible es un
  literal español escrito en la vista. Lo que NO se traduce, porque es
  contrato de datos y no interfaz: nombres de ejercicios y sus claves, los
  nombres de día que van a `entrenos.grupo`, las claves de tipo de serie y las
  cadenas `scheme`/`rest` de las fases.
- **Tres temas**, elegibles en Ajustes → Apariencia. Ninguna vista escribe un
  color: todo pasa por el proxy `C`, y por eso cambiar de tema reviste las
  once pantallas de golpe.
- **No necesita nada levantado.** El almacenamiento es un fichero SQLite y los
  tests crean el suyo en el temporal. Hasta 0.12 esto pedía PostgreSQL en
  Docker y compartía base con el bot de Telegram; en 0.13 se jubilaron los dos.
- **El coach no escribe nada.** Lee, propone, y lo que se guarda lo guarda
  Alex tocando un botón. Es la regla 5 de la lista de abajo y condiciona cómo
  se añade cualquier función suya, incluida su propia memoria.

## Setup

```bash
git clone https://github.com/kalexnolasco/ironflet
cd ironflet
make deps                        # uv sync --group dev
uv run pre-commit install        # hook de lint + formato
```

Y ya está: no hay contenedor que levantar ni assets que vendorizar.

```bash
make check     # lint + los 1961 tests
make run       # la app en el escritorio, contra un SQLite local
make apk       # el APK (las tres ABIs)
make install   # adb install al dispositivo conectado
```

`make run` en el escritorio sirve para mirar pantallas mientras desarrollas.
La app de verdad es la APK.

## Flujo de trabajo

1. Abre un issue antes de cambios grandes para discutir el enfoque.
2. Crea una rama descriptiva: `feat/nombre-corto` o `fix/bug-x`.
3. Confirma que pasa el linter y los tests:
   ```bash
   make check                    # exactamente lo que ejecuta CI
   ```
4. Abre el PR contra `main` con una descripción clara del cambio.

### La suite no se salta nada

Son **1961 pruebas** y corren todas con `make test`, sin Docker y sin
variables de entorno. `tests/conftest.py` le da a cada proceso su propio
fichero SQLite en el temporal.

Hasta 0.12 esta sección avisaba de lo contrario: 102 pruebas —y luego 211—
necesitaban PostgreSQL y **se saltaban en silencio** si no lo encontraban, así
que un `238 passed, 102 skipped` parecía verde sin haber probado nada de
almacenamiento. Ese riesgo se fue con el servidor. La única que sigue
saltándose es un test de red en `test_asset_manager.py`, y hay que pedirlo:

```bash
IRONFLET_NETWORK_TESTS=1 make test
```

## Estilo

- Código formateado con `ruff format` (línea 100).
- `ruff check` con `E`/`F`/`W` más `I` (imports), `UP` (upgrades), `B`
  (bugbear), `C4` (comprehensions), `SIM` (simplify).
- Prefiere funciones y helpers cortos, sin estado global. Para estado de UI,
  usa variables en la clase `View` y `page.data["refresh_current"]()`.

## Las cinco reglas que se rompen en silencio

Ninguna de estas lanza una excepción cuando la incumples. Por eso están aquí.

**1. Todo el texto visible al usuario es un literal en español en la vista.**
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
Si la normalización cambia, no salta nada: las filas simplemente dejan de
cuadrar con las ya guardadas y el historial del que depende todo el plan se
parte en dos. Congelado en `tests/test_exercise_key.py` (219 cadenas de rutina
colapsan en exactamente 100 claves). Un fallo ahí es un incidente de
integridad de datos, no una nota de formato.

**4. `create_all()` no añade columnas a una tabla que ya existe.** Nadie
ejecuta migraciones: `Storage()` llama a `create_all()` al arrancar, que crea
las tablas que faltan y **no toca** las que están. Una columna nueva funciona
en todo lo nuevo — cada test, cada instalación limpia — y revienta en el móvil
de Alex, que es el único sitio donde hay una base vieja y no hay consola. Por
eso `storage.add_missing_columns()` corre justo después: solo **añade**, nunca
borra ni renombra, y se salta las columnas `NOT NULL` en vez de aplicarlas a
medias. Una columna `NOT NULL` nueva sigue necesitando migración escrita a
mano.

Hasta 0.12 esta regla era más dura: el esquema estaba declarado **dos veces**,
aquí y en el bot, y cambiarlo en un lado tumbaba al otro a mitad de consulta.
Jubilado el bot, queda una sola declaración.

Y una herencia de aquella época: las filas que escribió el bot no llevan las
claves opcionales `"rir"` ni `"type"` en sus series. Léelas siempre con
`.get()`, y trata una serie sin `"type"` como **normal** — nunca como
calentamiento, porque eso reescribiría el tonelaje.

**5. Ninguna herramienta del coach escribe en la base.** Toda la historia de
seguridad de esa función es esa: el modelo *propone*, la vista pinta una
tarjeta y el toque de Alex en Guardar es lo único que escribe. `commit_proposal`
es la única función que escribe y ninguna herramienta llega a ella, así que la
garantía es estructural y no una frase en el prompt que un modelo pueda
ignorar. Una herramienta servicial que guarde directamente la borra, y nada
falla.

Se protege con `test_ninguna_herramienta_escribe`, que las corre todas contra
una tienda que revienta ante cualquier escritura. Dos cosas que aprender de la
vez que ese guard mintió: decía «every tool» y probaba **seis de quince**
porque su lista estaba escrita a mano, así que ahora recorre los registros y un
test hermano se pone rojo si una herramienta nueva no tiene argumentos en
`ARGUMENTOS_DE_PRUEBA`. Y esos argumentos tienen que hacer que la herramienta
**haga algo**: una que se rechaza a sí misma en la segunda línea nunca llega a
donde escribiría, y pasa el guard por no haberse ejecutado.

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
