"""El cuerpo en 3D de verdad: dónde vive, quién lo sirve y cómo se colorea.

El mapa de `cuerpo.py` es plano y lo dibuja `flet.canvas`. Este es el mismo dato
—`analytics.sets_per_muscle_group`— pintado sobre un cuerpo anatómico real, que
gira, que se puede tocar músculo a músculo, y que responde al dedo.

## Por qué hay un servidor HTTP dentro de la app

Flet no trae motor 3D, pero sí un `ft.WebView`, y ese WebView es Chromium con
WebGL. Lo que no puede es leer el modelo desde `file://`: Android deja pasar un
`<script src>` pero bloquea `fetch` y `XMLHttpRequest` entre ficheros locales
(`allowFileAccessFromFileURLs` va a false desde API 16), y GLTFLoader carga el
`.glb` con `fetch`. Comprobado en el emulador: por `file://` el modelo no llega;
por `http://127.0.0.1` llega entero.

Así que la app se sirve a sí misma. Es un `ThreadingHTTPServer` en el bucle
local, atado a `127.0.0.1` y a un puerto que elige el sistema, y **con hilos**:
el navegador pide los módulos ES en paralelo y un servidor de un hilo los mata
con «Failed to fetch dynamically imported module», que suena a permisos y era
una cola. Nada de esto sale del teléfono.

Hace falta además `usesCleartextTraffic` en el manifiesto: desde Android 9 el
http en claro está prohibido por defecto **incluso contra localhost**.

## Qué viaja en la APK

`anatomia/` pesa 2,2 MB: three.js, el decodificador Draco y `cuerpo.glb`. El
modelo salió de un atlas de 826 mallas y 8,2 MB —Z-Anatomy, CC BY-SA 4.0— que
`scripts/forja.mjs` funde en **quince**: los catorce grupos que la app calcula,
más el resto del cuerpo como escenario. Fundir no es solo tamaño: cada malla es
una llamada de dibujo por fotograma, y pasar de 826 a 15 dobló los fotogramas
por segundo en el emulador.

## Un solo color para dos vistas

El color no se decide aquí: se pide a `components.mapa_muscular`, el mismo que
pinta el mapa plano. Dos vistas del mismo dato que colorean distinto son dos
respuestas a la misma pregunta, y una de las dos sobra.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

#: Todo lo que el visor necesita. Es una carpeta y no un paquete de Python: no
#: hay ningún `.py` dentro, solo el modelo y las librerías que lo dibujan.
CARPETA = Path(__file__).resolve().parent / "anatomia"

#: El servidor, una vez arrancado. `None` mientras nadie ha pedido el cuerpo.
_servidor: object | None = None
_url: str = ""
_candado = threading.Lock()


def instalado() -> bool:
    """¿Está la carpeta con el modelo y las librerías?

    En el móvil siempre, porque viaja dentro de la APK. Puede no estarlo en un
    árbol de fuentes a medio clonar, y ahí lo que toca es caer al mapa plano y
    no dejar la pantalla en blanco.
    """
    return (CARPETA / "visor.html").is_file() and (CARPETA / "cuerpo.glb").is_file()


def url() -> str:
    """La dirección del visor, arrancando el servidor la primera vez.

    Devuelve cadena vacía si no se puede: sin modelo, o sin poder abrir un
    puerto. Quien llama decide qué enseñar en su lugar.
    """
    global _servidor, _url

    if _url:
        return _url
    if not instalado():
        return ""

    with _candado:
        if _url:  # otro hilo llegó primero mientras esperábamos
            return _url
        try:
            import http.server

            carpeta = str(CARPETA)

            class Mano(http.server.SimpleHTTPRequestHandler):
                # Sin `application/wasm` el decodificador Draco no puede usar
                # `instantiateStreaming`, y sin `text/javascript` el navegador
                # se niega a ejecutar un módulo ES.
                extensions_map = {
                    **http.server.SimpleHTTPRequestHandler.extensions_map,
                    ".js": "text/javascript",
                    ".wasm": "application/wasm",
                    ".glb": "model/gltf-binary",
                }

                def __init__(self, *a, **kw):
                    super().__init__(*a, directory=carpeta, **kw)

                def log_message(self, *a):
                    """Callado. Una línea por petición llena logcat sin decir nada."""

            class Servidor(http.server.ThreadingHTTPServer):
                daemon_threads = True

                def handle_error(self, request, client_address):
                    """Callado ante una conexión cortada.

                    El navegador cancela peticiones a mitad como parte de su
                    trabajo normal —al navegar, al recargar, al dejar de
                    necesitar un fichero—, y cada una de esas deja un
                    `BrokenPipeError`. Con el manejador de serie eso son veinte
                    líneas de traza en logcat por algo que no es un fallo.
                    """

            srv = Servidor(("127.0.0.1", 0), Mano)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _servidor = srv
            _url = f"http://127.0.0.1:{srv.server_address[1]}/visor.html"
        except Exception:  # noqa: BLE001
            _url = ""
    return _url


def paleta(volumen: dict[str, float], tema) -> dict:
    """De qué color va cada músculo, con la escala del mapa plano.

    `volumen` son series por músculo, con las claves inglesas que devuelve
    `analytics.sets_per_muscle_group` —las mismas con las que la forja nombró
    las mallas del modelo, y por eso no hay traducción por medio.
    """
    import cuerpo as geo
    from components.mapa_muscular import color_de, mezcla

    claves = [m.clave for m in geo.MUSCULOS]
    tope = max([volumen.get(c, 0.0) for c in claves] + [0.0]) or 1.0

    # El escenario —huesos, cabeza, manos, cuello— tiene que leerse como cuerpo
    # sin competir con ningún músculo. `bg_sunken` a secas, que es lo que
    # parecía obvio, sale casi negro en el tema oscuro: la primera versión
    # enseñaba una calavera negra flotando sobre unos músculos de colores. Un
    # gris medio sacado de la misma paleta lo arregla y sigue sin escribir
    # ningún hex (trampa 5).
    escenario = mezcla(tema.bg_sunken, tema.text_muted, 0.55)

    # Y un músculo sin tocar **no** puede ser el mismo negro que usa el mapa
    # plano. Ahí funciona porque el hueco está dentro de una silueta dibujada,
    # así que se lee como «parte del cuerpo, apagada». En 3D no hay silueta: el
    # negro se lee como un agujero, y el abdomen sin tocar salía como si al
    # cuerpo le faltara el vientre. Un escenario oscurecido dice lo mismo —está
    # ahí y no lo has trabajado— sin abrir un boquete.
    apagado = mezcla(escenario, tema.bg_sunken, 0.6)

    colores = {}
    for c in claves:
        series = volumen.get(c, 0.0)
        colores[c] = color_de(series / tope, series) if series > 0 else apagado

    return {"colores": colores, "resto": escenario, "fondo": tema.bg_surface}


def orden(nombre: str, *args) -> str:
    """Una llamada a `window.iron` lista para `run_javascript`.

    Los argumentos van por JSON y no interpolados a mano: un nombre de músculo
    lleva espacios (`middle back`) y una comilla mal puesta rompe la página
    entera sin decir dónde.
    """
    dentro = ", ".join(json.dumps(a) for a in args)
    return f"window.iron && window.iron.{nombre}({dentro});"


def musculo_del_mensaje(mensaje: str) -> str | None:
    """Lo que la página cuenta por `console.log`, si es un músculo tocado.

    El visor habla con líneas `IRON:clave=valor`. Devuelve `None` para todo lo
    demás —arranques, errores— porque el WebView también deja caer por ahí sus
    propios avisos y ninguno es un toque.
    """
    if not mensaje or not mensaje.startswith("IRON:"):
        return None
    clave, _, valor = mensaje[5:].partition("=")
    if clave != "musculo":
        return None
    return valor.strip()
