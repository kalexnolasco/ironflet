"""Fotos de progreso: una por día, comprimidas, con las medidas al lado.

La idea de Alex, literal: "pasarle foto cada dia", "tener galeria de las
fotos... y que se pueda detectar las mejoras". La parte honesta de "detectar
mejoras" en una app local es enseñar la foto A y la foto B **con los números
medidos entre medias** (peso y cintura, que ya existen) — un juicio visual
informado, no una puntuación inventada. La otra mitad — que el coach opine —
vive en `agent.py`, que puede adjuntar estas fotos a un modelo con visión.

## Dónde viven los bytes

En `FLET_APP_STORAGE_DATA/progreso/` (Android) o `~/.local/share/ironflet/
progreso/` (PC). La base de datos guarda solo el NOMBRE del fichero
(`storage.Foto.archivo`): en Android el prefijo del almacenamiento privado
cambia entre reinstalaciones, así que una ruta absoluta guardada hoy señalaría
a la instalación anterior. La copia de seguridad JSON lleva los metadatos; los
bytes se exportan aparte con `exportar_zip()` porque un backup de texto con
meses de JPEG en base64 dejaría de caber en un chat.

## Compresión

Pillow (wheel Android en pypi.flet.dev, pin exacto en pyproject — trampa 25):
lado mayor a 1600 px, JPEG calidad 85, y `ImageOps.exif_transpose` primero
porque las fotos de móvil llegan giradas vía EXIF y una galería con la mitad
de las fotos tumbadas parece rota. ~10 MB de cámara quedan en ~200-400 KB.
"""

from __future__ import annotations

import io
import os
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

#: Lado mayor tras comprimir. 1600 px sobra para comparar en pantalla y para
#: un modelo con visión (la mayoría reescala a ~1k de todas formas).
LADO_MAX = 1600
CALIDAD_JPEG = 85


def directorio() -> Path:
    """El directorio de fotos, creado si hace falta.

    El mismo criterio que `notificaciones._destino_por_defecto()`: en Android
    manda `FLET_APP_STORAGE_DATA`; en el PC, el XDG de datos del usuario.
    """
    raiz = os.environ.get("FLET_APP_STORAGE_DATA")
    if raiz:
        ruta = Path(raiz) / "progreso"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        ruta = Path(base) / "ironflet" / "progreso"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _comprimir(origen: bytes | str | Path) -> bytes:
    """Bytes JPEG listos para guardar: orientados, reescalados, opacos.

    Acepta bytes o una ruta. `convert("RGB")` porque un PNG con alfa (una
    captura, por ejemplo) revienta el encoder JPEG con "cannot write mode
    RGBA"; aplanar a RGB es la respuesta correcta para una foto de progreso.
    """
    datos = origen if isinstance(origen, bytes) else Path(origen).read_bytes()
    with Image.open(io.BytesIO(datos)) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((LADO_MAX, LADO_MAX))
        salida = io.BytesIO()
        im.save(salida, format="JPEG", quality=CALIDAD_JPEG, optimize=True)
        return salida.getvalue()


def guardar(
    store: Any,
    origen: bytes | str | Path,
    on_date: date | str | None = None,
    nota: str | None = None,
    base: Path | None = None,
) -> dict:
    """Guarda la foto del día (por defecto hoy) y devuelve la fila.

    El fichero se llama `YYYY-MM-DD.jpg`, así que la segunda foto del mismo
    día pisa a la primera en disco igual que la fila la pisa en la base — la
    semántica de `pesos`, deliberadamente. Escritura por fichero temporal y
    `os.replace`, que una galería leyendo a medias no vea un JPEG truncado.
    """
    dia = date.fromisoformat(on_date) if isinstance(on_date, str) else (on_date or date.today())
    carpeta = base or directorio()
    nombre = f"{dia.isoformat()}.jpg"
    datos = _comprimir(origen)

    tmp = carpeta / (nombre + ".tmp")
    tmp.write_bytes(datos)
    os.replace(tmp, carpeta / nombre)

    store.save_photo(dia, nombre, nota)
    return {"date": dia.isoformat(), "file": nombre, "note": nota, "bytes": len(datos)}


def listar(store: Any, base: Path | None = None) -> list[dict]:
    """Las filas de la base, con `path` resuelto y solo si el fichero existe.

    Una fila cuyo JPEG falta (restauraste la copia JSON en un móvil nuevo y
    aún no trajiste el zip) no se descarta: vuelve con `path=None` para que
    la galería pueda decir "falta el archivo de este día" en vez de callar.
    """
    carpeta = base or directorio()
    salida = []
    for fila in store.get_photos():
        ruta = carpeta / fila["file"]
        salida.append({**fila, "path": str(ruta) if ruta.exists() else None})
    return salida


def para_fecha(store: Any, on_date: date | str, base: Path | None = None) -> dict | None:
    fila = store.get_photo(on_date)
    if fila is None:
        return None
    ruta = (base or directorio()) / fila["file"]
    return {**fila, "path": str(ruta) if ruta.exists() else None}


def borrar(store: Any, on_date: date | str, base: Path | None = None) -> bool:
    """Fila y fichero, en ese orden — la fila es la verdad, el fichero el resto."""
    fila = store.get_photo(on_date)
    if not store.delete_photo(on_date):
        return False
    if fila:
        ruta = (base or directorio()) / fila["file"]
        try:
            ruta.unlink(missing_ok=True)
        except OSError:
            pass
    return True


def medidas_para(store: Any, on_date: date | str) -> dict:
    """El peso y la cintura más cercanos a esa fecha (±14 días), con su fecha.

    Para el comparador A/B: "entre estas dos fotos, −2,1 kg y −1,0 cm" es la
    detección de mejora que unos datos locales pueden afirmar con honestidad.
    Devuelve `{}` limpio cuando no hay nada cerca — la tarjeta simplemente no
    pinta esa línea.
    """
    dia = date.fromisoformat(on_date) if isinstance(on_date, str) else on_date
    salida: dict = {}

    def _mas_cercano(filas: list[dict], campo: str) -> tuple[float, str] | None:
        mejor: tuple[int, float, str] | None = None
        for fila in filas:
            valor = fila.get(campo)
            if valor is None:
                continue
            distancia = abs((date.fromisoformat(fila["date"]) - dia).days)
            if distancia > 14:
                continue
            if mejor is None or distancia < mejor[0]:
                mejor = (distancia, float(valor), fila["date"])
        return (mejor[1], mejor[2]) if mejor else None

    try:
        peso = _mas_cercano(store.get_weights(), "kg")
        if peso:
            salida["kg"], salida["kg_date"] = peso
    except Exception:
        pass
    try:
        cintura = _mas_cercano(store.get_measurements(), "waist")
        if cintura:
            salida["waist"], salida["waist_date"] = cintura
    except Exception:
        pass
    return salida


def exportar_zip(store: Any, destino: Path | str, base: Path | None = None) -> int:
    """Todas las fotos existentes a un zip plano. Devuelve cuántas entraron.

    El complemento del backup JSON (que lleva los metadatos): este zip son los
    bytes. Sin compresión extra — un JPEG no se comprime dos veces.
    """
    carpeta = base or directorio()
    contadas = 0
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_STORED) as zf:
        for fila in store.get_photos():
            ruta = carpeta / fila["file"]
            if ruta.exists():
                zf.write(ruta, fila["file"])
                contadas += 1
    return contadas


def importar_zip(store: Any, origen: Path | str, base: Path | None = None) -> int:
    """Restaura los JPEG de un zip y re-registra cada día que aún no exista.

    Idempotente: un fichero ya presente se pisa con el del zip (los bytes del
    zip son la copia que el usuario eligió restaurar), y la fila se hace
    upsert por fecha. Nombres que no sean `YYYY-MM-DD.jpg` se ignoran — el zip
    lo escribió `exportar_zip`, y cualquier otra cosa dentro no es una foto
    de progreso.
    """
    carpeta = base or directorio()
    contadas = 0
    with zipfile.ZipFile(origen) as zf:
        for nombre in zf.namelist():
            tallo = Path(nombre).name
            if not tallo.endswith(".jpg"):
                continue
            try:
                dia = date.fromisoformat(tallo[:-4])
            except ValueError:
                continue
            (carpeta / tallo).write_bytes(zf.read(nombre))
            store.save_photo(dia, tallo)
            contadas += 1
    return contadas
