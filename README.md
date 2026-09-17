# IronFlet — tu app de entrenos

<div align="center">

![Proyecto](https://img.shields.io/badge/Proyecto-IronFlet-blue?style=for-the-badge)
![Android](https://img.shields.io/badge/APK-85%20MB%20·%20SQLite-3DDC84?style=for-the-badge&logo=android&logoColor=white)
![Flet](https://img.shields.io/badge/Flet-0.28.3-7F52FF?style=for-the-badge)
![Idioma](https://img.shields.io/badge/interfaz-español-E4312b?style=for-the-badge)
![Tests](https://img.shields.io/badge/tests-2084-2f9e44?style=for-the-badge)

**Donde apuntas lo que levantas, con un entrenador dentro que mira tus fotos y
te escribe cada semana. Solo gimnasio: sin diario de comida, sin contar nada
que no sean series. Una app de móvil y nada más — sin servidor, sin cuenta, sin
nube. Tus datos viven en tu teléfono.**

</div>

---

## Solo el móvil (desde 0.13)

Esto **era** tres programas sobre una base PostgreSQL compartida: la app en el
PC, un entrenador de Telegram y un panel de administración. En 0.13 se
jubilaron los tres y quedó lo que de verdad se usa: **la APK**.

- **No hay que arrancar nada.** Ni `docker compose`, ni `systemctl`, ni un
  puerto que recordar. Instalas el APK y funciona con el PC apagado.
- **Tus datos son un fichero** SQLite en el almacenamiento privado de la app.
  Sobrevive a las actualizaciones; se va si desinstalas — por eso existe la
  copia de seguridad, y por eso conviene hacerla de vez en cuando.
- **Las fotos** viven en su carpeta al lado y viajan en su propio zip: la copia
  JSON solo guarda las fechas, porque meses de fotos en base64 harían un
  fichero imposible de mandar por un chat.

El código del bot sigue en `../agente/` por si algún día se rescata, pero nada
de esta app depende ya de él.

## Qué hace

1. **Ocho rutinas** — la tuya de CambiaTuFísico y siete más: Upper/Lower,
   Push/Pull/Legs, Recomp, PHUL, StrongLifts 5×5, Arnold Split y Full Body de
   3 días. Se cambian en Plan, y cualquiera se clona para hacerla tuya.
2. **Entrenar** — eliges rutina, fase y día, y apuntas cada serie: peso,
   repeticiones y RIR. Temporizador de descanso automático y modo zen (solo la
   serie que estás haciendo, sin nada más en pantalla). Si la máquina está
   ocupada o te sobran ganas, **«+ Ejercicio» añade uno más a la sesión de
   hoy** — de entre 875, con su foto, buscables por nombre y filtrados por lo
   que toca hoy — sin tocar el plan de las 24 semanas. Y si llegas sin plan,
   **«Libre»**: eliges tú los ejercicios y ya está.
3. **Abdomen cada día** — se enciende en Ajustes y aparece al final de cada
   entreno; los días de descanso, en Inicio. Tres ejercicios que rotan solos,
   uno de flexión, uno de inferior y uno de oblicuos, sin repetir del día
   anterior. Tu plan ya lo pedía —«+ Abs» cinco veces por semana— y la app no
   te lo daba.
4. **Verte por dentro** — un cuerpo humano **en 3D** en Historial, coloreado
   con lo que has entrenado: azul lo poco trabajado, rojo lo machacado, apagado
   lo que no has tocado. Se arrastra con el dedo para darle la vuelta, se
   pellizca para acercarse, y al tocar un músculo dice cuántas series lleva.
   Contesta de un vistazo lo que una lista de barras no: qué llevas flojo.
5. **Mirar atrás** — récords, progresión por ejercicio, series por músculo,
   racha de semanas y evolución del peso. Con un objetivo puesto, te dice
   cuándo llegas al ritmo que llevas de verdad.
6. **Medirte entero** — cintura, pecho, brazo, muslo y cadera. Para una
   recomposición son la métrica que importa: el peso puede no moverse en un mes
   mientras la cintura baja y el brazo sube, y eso la báscula no lo dice.
7. **Verte cambiar** — una foto al día, galería y comparador A/B con la
   diferencia real de peso y cintura entre las dos fechas.
8. **Verlo sin abrir la app** — un widget en la pantalla de inicio con lo de
   hoy: qué toca entrenar (con un ✓ cuando la sesión ya está), tu peso, lo que
   llevas de semana y tu cintura. Se añade desde Ajustes → Widget.
9. **Que te entrenen** — un coach dentro de la app que lee tu historial, mira
   tus fotos y **propone**: registrar una sesión, ajustar los objetivos de la
   semana, crear un aviso, bloquear un hueco en tu Google Calendar. Nada se
   guarda hasta que tocas Guardar.
10. **Que te conozca** — le cuentas una vez a qué hora entrenas, qué no comes o
   qué rodilla te molesta, y deja de preguntarlo.
11. **Que te escriba él** — una vez por semana mira tus datos y te deja un
   repaso en Inicio. Se enciende en Ajustes: es lo único de la app que hace una
   llamada de pago sin que la pidas, y lo que cuesta sale escrito debajo. Son hechos, no la
   conversación entera: veinte líneas que viajan en cada pregunta. Los propone
   él según hablas y los editas en Ajustes → «Lo que recuerda de ti».

Todo en español, **también los nombres de los ejercicios**. En la base siguen
guardándose en inglés —son la clave del historial y traducirla lo partiría en
dos— pero lo que se lee está traducido, y el buscador entiende los dos idiomas:
«sentadilla» y «squat» encuentran lo mismo.

## Compilar e instalar

```bash
make deps      # dependencias de desarrollo
make check     # lint + los 2084 tests (sin Docker, sin saltarse nada)
make apk       # el APK, con las tres ABIs
make install   # adb install al móvil o al emulador conectado
```

El APK sale en `build/apk/app-release.apk` (~85 MB: lleva CPython, las tres
arquitecturas y el cuerpo 3D). Se instala encima de la anterior sin perder datos.

Para desarrollar en el escritorio, `make run` abre la app contra un SQLite
local — sirve para ver pantallas, no para usarla en serio.

## La primera vez, en el móvil

1. **Permite las notificaciones** cuando te lo pida al abrir: sin eso los
   avisos no suenan. Si lo denegaste, Ajustes → Avisos te dice qué interruptor
   del sistema falta.
2. **Pega tu clave de OpenRouter** en Ajustes → Entrenador y elige modelo. Los
   marcados con 📷 pueden mirar tus fotos.
3. **Cuéntale quién eres.** Abre el chat y toca «Que me conozcas»: pregunta de
   una en una y te ofrece guardar cada respuesta. O escríbelo a mano en
   Ajustes → «Lo que recuerda de ti». Cuatro o cinco líneas bastan, y a partir
   de ahí no vuelve a preguntarlas.
4. **Conecta el calendario** (opcional): Ajustes → Calendario de Google →
   Conectar. En un PC con el token del bot todavía a mano, «Importar del bot»
   se lo salta todo.

## Copia de seguridad

Ajustes → Copia y datos:

- **Exportar** escribe un JSON con todo (entrenos, peso, medidas, rutinas,
  notas, fechas de fotos) y te deja elegir dónde copiarlo.
- **Exportar fotos (zip)** son los JPEG, aparte.
- **Importar** enseña qué trae el fichero y qué reemplaza **antes** de tocar
  nada.

Tu clave de OpenRouter y las credenciales de Google **nunca** entran en la
copia (`storage.SECRET_PREF_KEYS`): un backup es un fichero que uno se manda
por chat, y una clave dentro es una clave filtrada. En un móvil nuevo se
vuelven a poner a mano; todo lo demás vuelve del fichero — **incluido lo que el
entrenador sabe de ti**, que es justo lo que uno no quiere volver a contar.

## Si algo va mal

| Síntoma | Qué mirar |
|---|---|
| Los avisos no suenan | Ajustes → Avisos: dice qué permiso del sistema falta. Y quítale a la app la optimización de batería. |
| El coach responde con un error de clave | Ajustes → Entrenador: la clave o el crédito de OpenRouter. |
| «El calendario no está conectado» | Ajustes → Calendario. Si la app OAuth de Google está en modo Testing, el permiso caduca a los 7 días: publícala en Cloud Console. |
| Las fotos de ejercicios salen en gris | Ajustes → Datos → Fotos de ejercicios: se bajan una vez, con wifi. |
| La app se abre en morado con texto de error | Es un traceback de Python en pantalla. Hazle captura: `adb logcat` no lo recoge. |

## Cómo está hecho

Python + [Flet](https://flet.dev) (que dibuja con Flutter), empaquetado con
`flet build apk`. La lógica de negocio — métricas, progresión,
programación, gimnasio — son módulos puros sin Flet, y por eso se pueden probar sin abrir una
ventana. `CLAUDE.md` cuenta la arquitectura y, sobre todo, las **trampas**: las
cosas que se rompen en silencio si no las sabes.

La plantilla de compilación está forkeada en `build_template/` para añadir tres
cosas que Flet no trae: mantener la pantalla encendida durante el entreno, las
notificaciones locales, y el puente de ficheros por el que Python le habla al
lado Android.

El cuerpo 3D es [three.js](https://threejs.org/) dentro de un `ft.WebView`,
dibujando un modelo anatómico de quince mallas —una por grupo muscular— que
`scripts/forja.mjs` fabrica a partir de un atlas de 826. La página se sirve
desde un servidor http que corre dentro de la propia app y no sale del bucle
local; el porqué, y las cuatro trampas que costó, están en `CLAUDE.md`. El
modelo deriva de [Z-Anatomy](https://www.z-anatomy.com/) (CC BY-SA 4.0):
atribución y obligaciones en `anatomia/CREDITOS.md`.
