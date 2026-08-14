# Changelog

Todos los cambios notables de IronFlet.
El formato sigue [Keep a Changelog](https://keepachangelog.com/) y el proyecto
usa [SemVer](https://semver.org/).

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
- 8 rutinas (antes 7) y 87 nombres de ejercicio con imagen y ficha.
- De 88 a **340 tests**.

### Retirado
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
