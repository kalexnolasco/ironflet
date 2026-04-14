# Contribuir a IronFlet

Gracias por el interés. Este proyecto es pequeño y personal, pero las
aportaciones son bienvenidas.

## Setup

```bash
git clone git@github.com:kalexnolasco/ironflet.git
cd ironflet
uv sync --group dev
uv run pre-commit install        # instala hook de lint + formato
```

## Flujo de trabajo

1. Abre un issue antes de cambios grandes para discutir el enfoque.
2. Crea una rama descriptiva: `feat/nombre-corto` o `fix/bug-x`.
3. Confirma que pasa el linter y los tests:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest
   ```
4. Abre el PR contra `main` con una descripción clara del cambio.

## Estilo

- Código formateado con `ruff format` (línea 100).
- `ruff check` con las reglas por defecto + `I` (imports), `UP` (upgrades),
  `B` (bugbear), `C4` (comprehensions), `SIM` (simplify).
- Prefiere funciones/helpers cortos y sin estado global. Para estado de
  UI, usa variables en la clase `View` y `page.data["refresh_current"]()`.
- Todo el texto visible al usuario pasa por `i18n.t()` o `t_exercise()`.

## Añadir una rutina nueva

En `data.py`:

1. Crea las listas `XX_PHASES: list[Phase]` y `XX_DAYS: list[TrainingDay]`.
2. Añade una entrada más a `ROUTINES` con un `id` estable.
3. Añade al diccionario `i18n.ES` las traducciones del nombre, descripción,
   nombres de fases, subtítulos, días y cualquier frase nueva.
4. Comprueba que todos los nombres de ejercicios existen en
   `EXERCISE_IMAGE` (`exercise_images.py`) si quieres que muestren imagen
   e instrucciones.

## Añadir un ejercicio con imagen

1. Encuentra el slug en
   [Free Exercise DB](https://github.com/yuhonas/free-exercise-db/blob/main/dist/exercises.json).
2. Añade la entrada a `EXERCISE_IMAGE` en `exercise_images.py`.
3. Genera `exercise_details.py` de nuevo con las traducciones actualizadas
   (script de extracción en el historial de git).
4. Escribe la versión española en `exercise_details_es.py`
   (2–7 pasos breves, tono `tú`, terminología de gym).
5. Rehaz el tarball de Releases y publica una nueva versión (el constante
   `RELEASE_VERSION` en `asset_manager.py` debe apuntar a ese tag).

## Reportar un bug

Usa la plantilla de Bug report en la pestaña Issues. Incluye plataforma
(APK/desktop/web), versión (`VERSION` file) y pasos para reproducir.

## Licencia de tus aportaciones

Al abrir un PR aceptas que tu contribución se licencie bajo MIT, igual
que el resto del proyecto.
