# Changelog

Todos los cambios notables de IronLog.
El formato sigue [Keep a Changelog](https://keepachangelog.com/) y el proyecto
usa [SemVer](https://semver.org/).

## [1.0.0] — 2026-04-14

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
