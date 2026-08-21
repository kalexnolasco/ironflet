"""fotos.py — compresión, una-por-día, medidas cercanas y el zip.

SQLite en tmp_path y un `base=` explícito en cada llamada: el directorio real
depende de FLET_APP_STORAGE_DATA y un test que escribiera en el XDG del
usuario sería un test que ensucia la máquina.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

import fotos
import notificaciones as notif
from storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(f"sqlite:///{tmp_path / 'fotos.db'}")


@pytest.fixture
def carpeta(tmp_path):
    ruta = tmp_path / "progreso"
    ruta.mkdir()
    return ruta


def _jpeg(w=3000, h=2000, color=(120, 40, 40)) -> bytes:
    im = Image.new("RGB", (w, h), color)
    out = io.BytesIO()
    im.save(out, format="JPEG")
    return out.getvalue()


def _png_con_alfa(w=500, h=500) -> bytes:
    im = Image.new("RGBA", (w, h), (0, 100, 0, 128))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


# ── guardar: compresión y semántica una-por-día ──────────────────────────


def test_guardar_comprime_y_registra(store, carpeta):
    fila = fotos.guardar(store, _jpeg(), on_date="2026-08-21", base=carpeta)
    assert fila["file"] == "2026-08-21.jpg"
    ruta = carpeta / "2026-08-21.jpg"
    assert ruta.exists()
    with Image.open(ruta) as im:
        assert max(im.size) <= fotos.LADO_MAX
        assert im.format == "JPEG"
    assert store.get_photo("2026-08-21")["file"] == "2026-08-21.jpg"
    assert not list(carpeta.glob("*.tmp")), "la escritura no fue atómica"


def test_la_segunda_foto_del_dia_corrige_la_primera(store, carpeta):
    fotos.guardar(store, _jpeg(color=(200, 0, 0)), on_date="2026-08-21", base=carpeta)
    fotos.guardar(store, _jpeg(color=(0, 0, 200)), on_date="2026-08-21", base=carpeta)
    assert len(store.get_photos()) == 1
    with Image.open(carpeta / "2026-08-21.jpg") as im:
        r, g, b = im.getpixel((10, 10))
    assert b > r, "el fichero no fue reemplazado por la segunda foto"


def test_un_png_con_alfa_no_revienta_el_jpeg(store, carpeta):
    fila = fotos.guardar(store, _png_con_alfa(), on_date="2026-08-20", base=carpeta)
    assert (carpeta / fila["file"]).exists()


def test_una_foto_vertical_no_se_agranda(store, carpeta):
    fotos.guardar(store, _jpeg(w=800, h=1200), on_date="2026-08-19", base=carpeta)
    with Image.open(carpeta / "2026-08-19.jpg") as im:
        assert im.size == (800, 1200), "thumbnail() jamás agranda; algo lo hizo"


# ── listar / borrar ──────────────────────────────────────────────────────


def test_listar_resuelve_rutas_y_denuncia_ficheros_perdidos(store, carpeta):
    fotos.guardar(store, _jpeg(), on_date="2026-08-18", base=carpeta)
    fotos.guardar(store, _jpeg(), on_date="2026-08-21", base=carpeta)
    (carpeta / "2026-08-18.jpg").unlink()

    filas = fotos.listar(store, base=carpeta)
    assert [f["date"] for f in filas] == ["2026-08-21", "2026-08-18"]  # nueva primero
    assert filas[0]["path"] is not None
    assert filas[1]["path"] is None, "un JPEG perdido debe volver como path=None, no desaparecer"


def test_borrar_quita_fila_y_fichero(store, carpeta):
    fotos.guardar(store, _jpeg(), on_date="2026-08-21", base=carpeta)
    assert fotos.borrar(store, "2026-08-21", base=carpeta) is True
    assert store.get_photos() == []
    assert not (carpeta / "2026-08-21.jpg").exists()
    assert fotos.borrar(store, "2026-08-21", base=carpeta) is False


# ── las medidas que hacen honesto el comparador ──────────────────────────


def test_medidas_para_encuentra_lo_cercano_e_ignora_lo_lejano(store):
    store.save_weight(82.4, date_iso="2026-08-20")
    store.save_measurement(waist=83.0, on_date="2026-08-15")
    store.save_weight(90.0, date_iso="2026-05-01")  # a meses: fuera de la ventana

    m = fotos.medidas_para(store, "2026-08-21")
    assert m["kg"] == 82.4 and m["kg_date"] == "2026-08-20"
    assert m["waist"] == 83.0 and m["waist_date"] == "2026-08-15"

    lejos = fotos.medidas_para(store, "2026-01-01")
    assert lejos == {}, "una medida a meses de la foto no describe la foto"


# ── el zip de ida y vuelta ───────────────────────────────────────────────


def test_zip_ida_y_vuelta(store, carpeta, tmp_path):
    fotos.guardar(store, _jpeg(color=(10, 200, 10)), on_date="2026-08-20", base=carpeta)
    fotos.guardar(store, _jpeg(), on_date="2026-08-21", base=carpeta)
    destino = tmp_path / "fotos.zip"
    assert fotos.exportar_zip(store, destino, base=carpeta) == 2
    with zipfile.ZipFile(destino) as zf:
        assert sorted(zf.namelist()) == ["2026-08-20.jpg", "2026-08-21.jpg"]

    # Móvil nuevo: base de datos limpia y carpeta vacía.
    otro = Storage(f"sqlite:///{tmp_path / 'nuevo.db'}")
    carpeta2 = tmp_path / "progreso2"
    carpeta2.mkdir()
    assert fotos.importar_zip(otro, destino, base=carpeta2) == 2
    filas = fotos.listar(otro, base=carpeta2)
    assert len(filas) == 2 and all(f["path"] for f in filas)


def test_importar_zip_ignora_lo_que_no_es_foto(store, carpeta, tmp_path):
    malicioso = tmp_path / "raro.zip"
    with zipfile.ZipFile(malicioso, "w") as zf:
        zf.writestr("../../fuera.jpg", b"x")  # nombre con ruta: se aplana o se ignora
        zf.writestr("notas.txt", b"hola")
        zf.writestr("nofecha.jpg", b"x")
    assert fotos.importar_zip(store, malicioso, base=carpeta) == 0
    assert store.get_photos() == []
    assert not (tmp_path / "fuera.jpg").exists(), "zip-slip: escribió fuera de la carpeta"


# ── el estado de permisos que escribe Dart ───────────────────────────────


def test_estado_android_lee_el_fichero_de_dart(tmp_path):
    fichero = tmp_path / "notif_status.json"
    assert notif.estado_android(target=fichero) is None  # aún no existe
    fichero.write_text('{"granted": false, "exact": true}')
    estado = notif.estado_android(target=fichero)
    assert estado == {"granted": False, "exact": True}
    fichero.write_text("esto no es json")
    assert notif.estado_android(target=fichero) is None
