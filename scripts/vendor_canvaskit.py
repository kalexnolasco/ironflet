"""Descarga CanvasKit para servirlo desde el propio servidor.

The `flet-web` wheel ships no CanvasKit assets, so Flutter fetches them from
www.gstatic.com on every cold start. That makes the app unusable without
internet access — awkward for something served on a LAN and opened in a gym.

This copies the exact engine revision the bundled client expects into
`flet_web/web/canvaskit/`, where Flutter looks before falling back to the CDN.

Re-run after reinstalling flet, since it patches the installed package:

    .venv/bin/python scripts/vendor_canvaskit.py
"""

from __future__ import annotations

import re
import sys
import sysconfig
from pathlib import Path
from urllib.request import urlopen

FICHEROS = ("canvaskit.js", "canvaskit.wasm", "chromium/canvaskit.js", "chromium/canvaskit.wasm")

# Downloading the files is not enough: the bootstrap hands Flutter a `config`
# object, and without canvasKitBaseUrl the engine keeps using the CDN.
MARCA = "/* ironflet: canvaskit local */"
ORIGINAL = """    config: {
        renderer: webRenderer
    },"""
PARCHE = f"""    config: {{
        renderer: webRenderer,
        canvasKitBaseUrl: "/canvaskit/"  {MARCA}
    }},"""


def cliente_web() -> Path:
    raiz = Path(sysconfig.get_paths()["purelib"]) / "flet_web" / "web"
    if not raiz.is_dir():
        sys.exit(f"No encuentro el cliente web de Flet en {raiz}")
    return raiz


def revision(web: Path) -> str:
    bootstrap = (web / "flutter_bootstrap.js").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'"engineRevision"\s*:\s*"([a-f0-9]+)"', bootstrap)
    if not m:
        sys.exit("No pude leer engineRevision de flutter_bootstrap.js")
    return m.group(1)


def main() -> int:
    web = cliente_web()
    rev = revision(web)
    base = f"https://www.gstatic.com/flutter-canvaskit/{rev}"
    destino = web / "canvaskit"
    print(f"Engine revision: {rev}\nDestino: {destino}\n")

    total = 0
    for nombre in FICHEROS:
        salida = destino / nombre
        salida.parent.mkdir(parents=True, exist_ok=True)
        url = f"{base}/{nombre}"
        try:
            with urlopen(url, timeout=120) as resp:
                datos = resp.read()
        except Exception as exc:
            # chromium/* solo existe en algunas revisiones: no es fatal.
            print(f"  ⚠️  {nombre}: {exc}")
            continue
        salida.write_bytes(datos)
        total += len(datos)
        print(f"  ✅ {nombre} — {len(datos) / 1024:.0f} KB")

    bootstrap = web / "flutter_bootstrap.js"
    js = bootstrap.read_text(encoding="utf-8")
    if MARCA in js:
        print("\n  ℹ️  flutter_bootstrap.js ya apunta a /canvaskit/")
    elif ORIGINAL in js:
        bootstrap.write_text(js.replace(ORIGINAL, PARCHE, 1), encoding="utf-8")
        print("\n  ✅ flutter_bootstrap.js apunta ahora a /canvaskit/")
    else:
        print("\n  ⚠️  No reconozco el bloque config de flutter_bootstrap.js:")
        print("      la app seguirá bajando CanvasKit del CDN de Google.")
        return 1

    # Limpia el intento anterior por window.flutterConfiguration, si quedó.
    indice = web / "index.html"
    html = indice.read_text(encoding="utf-8")
    if "window.flutterConfiguration" in html:
        limpio = re.sub(r"<!-- ironflet: canvaskit local -->.*?</script>\s*", "", html, flags=re.S)
        indice.write_text(limpio, encoding="utf-8")
        print("  🧹 index.html limpiado")

    print(f"\n{total / 1024 / 1024:.1f} MB servidos ahora en local.")
    print("Reinicia el servicio: systemctl --user restart ironflet-web")
    return 0


if __name__ == "__main__":
    sys.exit(main())
