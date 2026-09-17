"""El cuerpo 3D: que el modelo trae lo que la app va a pedirle.

Lo que aquí se prueba no es que se vea bonito —eso solo lo dice una captura del
móvil— sino las cosas que se rompen en silencio:

* que las quince mallas del `.glb` se llamen **exactamente** como las claves que
  devuelve `analytics.sets_per_muscle_group`, porque el color se aplica por
  nombre y un nombre que no cuadra deja el músculo gris sin decir nada;
* que los colores salgan de la misma escala que el mapa plano;
* que el visor siga siendo un extra: en Linux tiene que decir que no y la
  pantalla quedarse con el mapa de siempre.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import cuerpo as geo
import cuerpo3d


def _mallas_del_glb(ruta: Path) -> list[str]:
    """Los nombres de los nodos del `.glb`, leyendo el trozo JSON a mano.

    Sin dependencias: un GLB es una cabecera de doce bytes y luego trozos con
    longitud y tipo. El primero de tipo `JSON` es la escena.
    """
    b = ruta.read_bytes()
    assert b[:4] == b"glTF", "no es un glb"
    off = 12
    while off < len(b):
        largo, tipo = struct.unpack_from("<II", b, off)
        if tipo == 0x4E4F534A:  # 'JSON'
            escena = json.loads(b[off + 8 : off + 8 + largo])
            return [n.get("name", "") for n in escena.get("nodes", [])]
        off += 8 + largo
    raise AssertionError("el glb no trae trozo JSON")


def test_el_modelo_viaja_con_la_app():
    assert cuerpo3d.instalado(), (
        "falta anatomia/: sin ella la pantalla cae al mapa plano y nadie se entera"
    )


def test_cada_musculo_de_la_app_tiene_su_malla():
    """La unión entre los dos mundos, y la que se rompe callada.

    El color se aplica con `malla.name === clave`. Si la forja renombra algo o
    la app añade un músculo, el músculo se queda del color del escenario y la
    pantalla sigue pareciendo correcta.
    """
    nombres = set(_mallas_del_glb(cuerpo3d.CARPETA / "cuerpo.glb"))
    faltan = [m.clave for m in geo.MUSCULOS if m.clave not in nombres]
    assert not faltan, f"sin malla en el modelo 3D: {faltan}"


def test_el_modelo_no_trae_mallas_de_mas():
    """Quince y no más: los catorce músculos y el escenario.

    Una malla suelta sería una llamada de dibujo por fotograma que no colorea
    nada, y el motivo por el que se funden en la forja.
    """
    nombres = _mallas_del_glb(cuerpo3d.CARPETA / "cuerpo.glb")
    esperados = {m.clave for m in geo.MUSCULOS} | {"resto"}
    assert set(nombres) == esperados
    assert len(nombres) == len(esperados), f"nombres repetidos: {nombres}"


def test_la_paleta_usa_la_escala_del_mapa_plano():
    from components.mapa_muscular import color_de
    from theme import C

    volumen = {"chest": 12.0, "biceps": 3.0}
    p = cuerpo3d.paleta(volumen, C)

    assert p["colores"]["chest"] == color_de(1.0, 12.0)
    assert p["colores"]["biceps"] == color_de(3.0 / 12.0, 3.0)
    # Un músculo sin tocar existe igual: si faltara la clave, la página se
    # quedaría con el color anterior en vez de apagarse.
    assert "glutes" in p["colores"]


def test_la_paleta_cubre_todos_los_musculos():
    from theme import C

    p = cuerpo3d.paleta({}, C)
    assert set(p["colores"]) == {m.clave for m in geo.MUSCULOS}


def test_una_semana_vacia_no_divide_entre_cero():
    from theme import C

    p = cuerpo3d.paleta({}, C)
    apagado = set(p["colores"].values())
    assert len(apagado) == 1, "sin series entrenadas todos tienen que estar igual de apagados"


@pytest.mark.parametrize(
    ("mensaje", "espera"),
    [
        ("IRON:musculo=chest", "chest"),
        ("IRON:musculo=middle back", "middle back"),
        ("IRON:musculo=", ""),
        ("IRON:listo=15", None),
        ("IRON:error=lo que sea", None),
        ("cualquier cosa que escupa el webview", None),
        ("", None),
    ],
)
def test_solo_los_toques_se_leen_como_toques(mensaje, espera):
    """El WebView deja caer sus propios avisos por el mismo canal.

    `console.log` es el único camino de vuelta, así que por ahí pasa también lo
    que escriba Chromium. Confundir uno de esos con un músculo seleccionaría
    algo que nadie tocó.
    """
    assert cuerpo3d.musculo_del_mensaje(mensaje) == espera


def test_las_ordenes_van_por_json():
    """Un nombre con espacio dentro de una llamada a JavaScript.

    `middle back` interpolado a pelo sale como `selecciona(middle back)`, que
    es un error de sintaxis y deja la página muerta desde ese momento sin
    ninguna señal.
    """
    orden = cuerpo3d.orden("selecciona", "middle back")
    assert '"middle back"' in orden
    assert orden.startswith("window.iron")


def test_la_orden_de_pintar_lleva_los_colores():
    from theme import C

    p = cuerpo3d.paleta({"chest": 5.0}, C)
    orden = cuerpo3d.orden("pinta", p)
    assert "pinta(" in orden
    assert p["colores"]["chest"] in orden


def test_un_musculo_sin_tocar_sigue_pareciendo_carne():
    """Apagado, no ausente.

    El mapa plano pinta lo no tocado casi negro y ahí funciona, porque el hueco
    queda dentro de una silueta dibujada. En 3D no hay silueta y ese mismo
    negro se lee como un agujero en el cuerpo: el abdomen sin tocar salía como
    si al muñeco le faltara el vientre.
    """
    from components.mapa_muscular import color_de
    from theme import C

    p = cuerpo3d.paleta({"chest": 10.0}, C)
    apagado = p["colores"]["abdominals"]

    assert apagado != color_de(0.0, 0.0), "sigue siendo el negro del mapa plano"
    assert apagado != p["fondo"], "se confundiría con el fondo de la tarjeta"
    assert apagado != p["resto"], "no se distinguiría de un hueso"

    # Más oscuro que el escenario: apagado tiene que leerse como apagado.
    def luz(h):
        h = h.lstrip("#")
        return sum(int(h[i : i + 2], 16) for i in (0, 2, 4))

    assert luz(apagado) < luz(p["resto"])


def test_el_escenario_no_se_confunde_con_el_fondo():
    """El cuerpo que no es músculo tiene que verse.

    La primera versión lo pintaba de `bg_sunken` a secas, que en el tema oscuro
    es casi negro: la cabeza y las manos salían como una silueta negra flotando
    entre músculos de colores.
    """
    from components.mapa_muscular import mezcla
    from theme import C

    p = cuerpo3d.paleta({}, C)
    assert p["resto"] != C.bg_sunken
    assert p["resto"] != p["fondo"]
    # Y no es un hex escrito a mano: sale de la paleta (trampa 5).
    assert p["resto"] == mezcla(C.bg_sunken, C.text_muted, 0.55)


def test_fuera_del_movil_el_visor_dice_que_no():
    """En Linux —y por tanto en los tests— tiene que caer al mapa plano.

    `ft.WebView` solo existe en móvil: sus métodos lanzan en el escritorio. Si
    esto dijera que sí, la pantalla de histórico reventaría en el PC.
    """
    import flet as ft

    from components import visor3d

    class PaginaFalsa:
        platform = ft.PagePlatform.LINUX

    assert visor3d.disponible(PaginaFalsa()) is False


def test_una_pagina_sin_plataforma_no_revienta():
    from components import visor3d

    class Rota:
        @property
        def platform(self):
            raise RuntimeError("sin plataforma")

    assert visor3d.disponible(Rota()) is False


def test_el_visor_hace_cola_hasta_que_la_pagina_carga():
    """Pintar antes de que el modelo esté dentro no puede perderse.

    El color se calcula al construir la pantalla y el `.glb` tarda unos cientos
    de milisegundos. Sin la cola, el cuerpo saldría gris hasta que algo lo
    tocara.
    """
    from components import visor3d

    visor = visor3d.Visor.__new__(visor3d.Visor)
    visor._listo = False
    visor._cola = {}
    visor.al_tocar = None
    enviados = []
    visor._enviar = lambda nombre, *a: enviados.append((nombre, a))

    visor.pinta({"colores": {"chest": "#ff0000"}})
    visor.selecciona("lats")
    visor.vista("espalda")
    assert enviados == [], "todavía no hay página a la que hablar"

    visor._mensaje(type("E", (), {"message": "IRON:listo=15"})())
    assert enviados == [
        ("pinta", ({"colores": {"chest": "#ff0000"}},)),
        ("selecciona", ("lats",)),
        ("vista", ("espalda",)),
    ]


def test_la_cola_se_queda_con_la_ultima_orden_de_cada_tipo():
    """Dos `pinta` seguidas antes de cargar solo tienen un resultado correcto.

    La pantalla se construye y se reconstruye más rápido de lo que carga el
    modelo. Guardar las dos y mandarlas en orden pintaría el color viejo y
    luego el nuevo —un parpadeo—, y guardarlas todas haría crecer la cola sin
    límite si la página nunca llega a cargar.
    """
    from components import visor3d

    visor = visor3d.Visor.__new__(visor3d.Visor)
    visor._listo = False
    visor._cola = {}
    visor.al_tocar = None
    enviados = []
    visor._enviar = lambda nombre, *a: enviados.append((nombre, a))

    visor.pinta({"colores": {"chest": "#111111"}})
    visor.pinta({"colores": {"chest": "#222222"}})
    visor._mensaje(type("E", (), {"message": "IRON:listo=15"})())

    assert enviados == [("pinta", ({"colores": {"chest": "#222222"}},))]


def test_el_visor_avisa_de_lo_que_se_toca():
    from components import visor3d

    visor = visor3d.Visor.__new__(visor3d.Visor)
    visor._listo = True
    visor._cola = {}
    tocados = []
    visor.al_tocar = tocados.append

    visor._mensaje(type("E", (), {"message": "IRON:musculo=lats"})())
    visor._mensaje(type("E", (), {"message": "IRON:musculo="})())
    visor._mensaje(type("E", (), {"message": "algo del navegador"})())

    assert tocados == ["lats", ""]


def test_el_visor_pide_los_ficheros_que_existen():
    """Cada `src` y cada `import` de la página tiene que estar en la carpeta.

    Un módulo que falta no da 404 visible: el navegador dice «Failed to fetch
    dynamically imported module» y la pantalla se queda en negro. Pasó con
    `BufferGeometryUtils.js`, que `GLTFLoader.js` importa desde otra carpeta.
    """
    import re

    carpeta = cuerpo3d.CARPETA
    pendientes = [carpeta / "visor.html"]
    vistos: set[Path] = set()
    while pendientes:
        f = pendientes.pop()
        if f in vistos or f.suffix not in (".html", ".js"):
            continue
        vistos.add(f)
        texto = f.read_text(encoding="utf-8", errors="replace")
        rutas = re.findall(r"""['"](\./[^'"]+\.(?:js|glb))['"]""", texto)
        rutas += re.findall(r"""from\s+['"](\.[^'"]+\.js)['"]""", texto)
        for r in rutas:
            destino = (f.parent / r).resolve()
            assert destino.is_file(), f"{f.name} pide {r} y no está"
            pendientes.append(destino)

    # El decodificador Draco se pide por carpeta, no por fichero.
    assert (carpeta / "lib" / "draco" / "draco_decoder.wasm").is_file()
    assert (carpeta / "lib" / "draco" / "draco_wasm_wrapper.js").is_file()


def test_la_pagina_habla_el_mismo_idioma_que_python():
    """Los nombres de `window.iron` y los que manda `cuerpo3d.orden`.

    Son dos ficheros en dos lenguajes distintos: nada los ata salvo esto.
    """
    pagina = (cuerpo3d.CARPETA / "visor.html").read_text(encoding="utf-8")
    for metodo in ("pinta", "vista", "selecciona", "gira"):
        assert f"  {metodo}(" in pagina, f"window.iron no expone {metodo}"


def test_el_servidor_no_sale_del_bucle_local():
    """Atado a 127.0.0.1 y a nada más.

    Sirve el almacenamiento de la app: en una wifi de gimnasio, escuchar en
    0.0.0.0 sería repartir el modelo —y cualquier ruta que se colara— a quien
    esté en la misma red.
    """
    direccion = cuerpo3d.url()
    if not direccion:
        pytest.skip("sin carpeta de modelo en este árbol")
    assert direccion.startswith("http://127.0.0.1:")
    assert cuerpo3d.url() == direccion, "el servidor tiene que arrancar una sola vez"


def test_el_servidor_sirve_el_modelo_y_los_modulos():
    import urllib.request

    base = cuerpo3d.url()
    if not base:
        pytest.skip("sin carpeta de modelo en este árbol")
    raiz = base.rsplit("/", 1)[0]

    with urllib.request.urlopen(f"{raiz}/cuerpo.glb", timeout=10) as r:
        assert r.status == 200
        assert r.read(4) == b"glTF"

    # Sin `text/javascript` el navegador se niega a ejecutar un módulo ES, y
    # sin `application/wasm` el decodificador Draco no arranca.
    with urllib.request.urlopen(f"{raiz}/lib/three.module.js", timeout=10) as r:
        assert r.headers.get_content_type() == "text/javascript"
    with urllib.request.urlopen(f"{raiz}/lib/draco/draco_decoder.wasm", timeout=10) as r:
        assert r.headers.get_content_type() == "application/wasm"


def test_el_visor_es_javascript_valido():
    """Que el módulo de la página al menos **compile**.

    Un error de sintaxis en `visor.html` no da error en ninguna parte que se
    vea: el navegador no ejecuta el módulo, la página se queda con el «cargando
    el cuerpo…» del HTML, y el único síntoma es una caja negra en el móvil.

    Comprueba la sintaxis y nada más. Lo que esto **no** puede pillar es llamar
    a un método que no existe —pasó con `Color.manhattanDistanceTo`, que es de
    `Vector3`— y eso solo lo dice abrir la página.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        pytest.skip("sin node en este equipo")

    pagina = (cuerpo3d.CARPETA / "visor.html").read_text(encoding="utf-8")
    modulos = re.findall(r'<script type="module">(.*?)</script>', pagina, re.S)
    assert modulos, "visor.html ya no trae un <script type=module>"

    for i, codigo in enumerate(modulos):
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
            f.write(codigo)
            ruta = f.name
        try:
            r = subprocess.run([node, "--check", ruta], capture_output=True, text=True)
            assert r.returncode == 0, f"script {i} de visor.html no compila:\n{r.stderr}"
        finally:
            Path(ruta).unlink(missing_ok=True)
