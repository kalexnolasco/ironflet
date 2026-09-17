"""El `ft.WebView` que enseña el cuerpo en 3D, y las trampas de montarlo.

`cuerpo3d.py` sabe dónde está el modelo y de qué color va cada músculo; este
módulo es lo único que toca Flet. Se mantiene aparte porque el visor tiene un
ciclo de vida propio —se carga una vez y luego se le habla— y meterlo en la
vista mezclaría ese ciclo con el «reconstruir todo» del resto de la pantalla.

## Las tres trampas de `ft.WebView` en Flet 0.28

1. **El control no existe en el Dart de serie.** `ft.WebView` está en el Python
   pero el cliente Flutter no lo conoce, y la pantalla dice `Unknown control:
   webview`. Lo aporta `flet-webview` desde `[project] dependencies`.
2. **JavaScript viene apagado**, y el lado Dart no lee el atributo al montar:
   solo se puede encender por método, y el método no existe hasta que el
   control está montado. De ahí `_encender()` con retraso; sin él no llega ni
   un `console.log` y parece que la página no carga.
3. **Fuera del móvil revienta.** `run_javascript` y compañía llaman a
   `_check_mobile_or_mac_platform`, que lanza en Linux y en Windows. En el PC
   —y en los tests— este módulo dice que no está disponible y la pantalla se
   queda con el mapa plano, que funciona en todas partes.
"""

from __future__ import annotations

import contextlib
import threading

import flet as ft

import cuerpo3d

#: Cuánto se espera antes de encender JavaScript. Es el tiempo que tarda el
#: lado Flutter en montar el control y suscribir sus métodos; pedirlo antes se
#: pierde en el vacío sin error. Medio segundo sobra en el emulador, que es más
#: lento que cualquier móvil.
_ESPERA_JS = 0.6


def disponible(page: ft.Page) -> bool:
    """¿Se puede enseñar el cuerpo en 3D en este aparato?

    Móvil, con la carpeta del modelo dentro y con un puerto libre. Cualquier
    «no» aquí devuelve el mapa plano, que es una respuesta peor pero nunca es
    una pantalla rota.
    """
    try:
        movil = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
    except Exception:  # noqa: BLE001
        return False
    return bool(movil and cuerpo3d.url())


class Visor:
    """El cuerpo 3D montado, con lo que hace falta para hablarle.

    Se construye **una vez por redibujado de la pantalla**, no una vez por
    sesión: volver a meter la misma instancia de `ft.WebView` en un árbol recién
    construido deja una caja negra sin ningún error. Ver `_cuerpo_en_3d` en
    `views/history.py`.
    """

    def __init__(self, al_tocar) -> None:
        #: Público: la pantalla lo vuelve a atar cuando cambia el volumen que
        #: el visor está mirando.
        self.al_tocar = al_tocar
        self._listo = False
        #: Las órdenes dadas antes de que la página estuviera lista, por nombre.
        #:
        #: Todo lo que la pantalla quiere decirle al cuerpo —el color de la
        #: semana, qué músculo estaba elegido, de qué lado se estaba mirando—
        #: se calcula al construir la vista, y el modelo tarda unos cientos de
        #: milisegundos en cargar. Sin esta cola, todo eso se pierde: el cuerpo
        #: aparecería gris, de frente y sin nada seleccionado, y solo se
        #: arreglaría al tocar algo. Es por nombre y no una lista porque
        #: repetir dos veces `pinta` con colores distintos solo tiene un
        #: resultado correcto, que es el último.
        self._cola: dict[str, tuple] = {}

        # Arranca en blanco **a propósito**. Si el control naciera apuntando al
        # visor, la página cargaría con JavaScript apagado —que es como viene—
        # y encenderlo después no vuelve a ejecutar el `<script type=module>`:
        # se ve el «cargando el cuerpo…» del HTML para siempre y ni un error en
        # ninguna parte. El orden correcto es encender y luego navegar.
        self.control = ft.WebView(
            url="about:blank",
            expand=True,
            bgcolor="#00000000",
            on_console_message=self._mensaje,
        )
        threading.Timer(_ESPERA_JS, self._arranca).start()

    # ── de la página hacia aquí ──────────────────────────────
    def _mensaje(self, e) -> None:
        texto = getattr(e, "message", "") or ""
        if texto.startswith("IRON:listo="):
            self._listo = True
            cola, self._cola = self._cola, {}
            for nombre, args in cola.items():
                self._enviar(nombre, *args)
            return
        clave = cuerpo3d.musculo_del_mensaje(texto)
        if clave is not None and self.al_tocar is not None:
            # Cadena vacía = tocó el aire o el escenario. Llega igual, porque
            # soltar lo seleccionado también es una respuesta.
            self.al_tocar(clave)

    # ── de aquí hacia la página ──────────────────────────────
    def _enviar(self, nombre: str, *args) -> None:
        # Un visor mudo es una pena; una pantalla que revienta al tocar un
        # músculo es un problema.
        with contextlib.suppress(Exception):
            self.control.run_javascript(cuerpo3d.orden(nombre, *args))

    def _pide(self, nombre: str, *args) -> None:
        if self._listo:
            self._enviar(nombre, *args)
        else:
            self._cola[nombre] = args

    def _arranca(self) -> None:
        """Enciende JavaScript y solo entonces navega al visor."""
        with contextlib.suppress(Exception):
            self.control.enable_javascript = True
            self.control.load_request(cuerpo3d.url())

    def pinta(self, datos: dict) -> None:
        """Colorea el cuerpo con la semana que se está mirando."""
        self._pide("pinta", datos)

    def selecciona(self, clave: str) -> None:
        """Marca un músculo, o ninguno con cadena vacía."""
        self._pide("selecciona", clave or "")

    def vista(self, nombre: str) -> None:
        """Gira hasta ver la cara (`frente`) o la espalda (`espalda`)."""
        self._pide("vista", nombre)
