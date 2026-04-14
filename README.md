# IronLog

App móvil de seguimiento de entrenamiento (tracker de pesas) escrita en
Python con [Flet](https://flet.dev) — mismo código corre como Android APK,
escritorio nativo (Linux/Windows/macOS) y web.

Bilingüe **ES/EN**, offline-first, sin cuenta, sin telemetría.

## Características

- **7 rutinas** periodizadas incluidas: CambiaTuFísico (24 semanas),
  Upper/Lower, Push/Pull/Legs, Mujer Fitness y tres variantes femeninas
  más (Casa, Fuerza, Volumen).
- **68 ejercicios** con imagen animada (frame 0 ↔ frame 1), músculos
  primario/secundario, equipamiento, nivel, e **instrucciones paso a paso
  en español y en inglés**.
- **Flujo de entrenamiento** guiado con cronómetro de sesión, temporizador
  de descanso y swipe horizontal entre ejercicios.
- **Perfil + métricas derivadas**: edad, IMC, TMB (Mifflin-St Jeor), GEDT,
  objetivo de proteína (1.6–2.2 g/kg), hidratación (~35 ml/kg).
- **Historial de peso** con gráfico y de entrenamientos por ejercicio con
  PR y volumen por fecha.
- **Backup / restore** en JSON via portapapeles.
- **Guías** originales in-app de entrenamiento, nutrición y mujer fitness
  (7 tips por tema, EN/ES).

## Capturas

_Pendiente de añadir._

## Requisitos

- Python `>=3.10,<3.13`
- [uv](https://github.com/astral-sh/uv) (gestor de entorno y dependencias)
- Para Android APK: JDK 17+, Flutter SDK y Android SDK (el wrapper
  `flet build apk` los descarga la primera vez)

## Desarrollo

```bash
uv sync                                  # crear venv + deps
uv run python main.py                    # ventana nativa (Linux/macOS/Win)
IRONLOG_WEB=1 uv run python main.py      # modo web en http://localhost:8550
```

En Android o escritorio, la primera vez que abras los ejercicios hay que
ir a **Ajustes → Datos → Guías de ejercicios → Descargar** (~9 MB) para
traer las fotos e instrucciones desde la Free Exercise DB. Sin descargar
verás un icono de pesa de placeholder.

## Build Android (APK)

```bash
flet build apk                           # universal (todas las arquitecturas)
flet build apk --target-platform android-arm64   # arm64-only (~80 MB)
adb install -r build/apk/app-release.apk
```

## Estructura

```
main.py                    # entrypoint + navegación
storage.py                 # SQLite (workouts, profile, weight_log, prefs)
data.py                    # rutinas + fases + días de entrenamiento
health.py                  # BMI / BMR / TDEE / proteína
i18n.py                    # strings y helpers de traducción ES/EN
guides.py                  # contenido de las guías in-app
exercise_images.py         # mapping canonical name → slug Free Exercise DB
exercise_details.py        # detalles (auto-generado desde Free Exercise DB)
exercise_details_es.py     # instrucciones en español, escritas a mano
asset_manager.py           # descargador de imágenes runtime
theme.py                   # paleta y helpers visuales
components/
  timer.py                 # temporizador de descanso
  charts.py                # gráfico de barras simple
views/
  home.py, plan.py, workout.py, browse.py, history.py, profile.py
  exercise_dialog.py, guide_dialog.py
```

## Licencias y créditos

- Código de IronLog: MIT.
- Contenido de `exercise_details.py`, imágenes de ejercicios y datos base:
  [Free Exercise DB](https://github.com/yuhonas/free-exercise-db), Unlicense
  (dominio público). Se descargan en runtime — no se redistribuyen con el
  repositorio.
- Estructura inicial de la rutina "CambiaTuFísico" inspirada en la
  categorización pública de [cambiatufisico.com](https://www.cambiatufisico.com);
  cada rutina está modelada como datos (series × reps + ejercicios) en
  `data.py`. Los textos explicativos son originales.
- Las guías in-app (training / nutrition / women fitness) son contenido
  original basado en principios generales de fuerza y nutrición.
