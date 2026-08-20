"""The frames have to reach the screen, not just the disk.

These tests exist because of a bug that every previous test missed by asking
the wrong question. `tests/test_exercise_images.py` checks that `image_for()`
returns a sane assets-relative path and never a `file://` URL — and it passed
throughout, because the path *was* sane. It just pointed somewhere the phone
could not read:

    downloaded to  <app storage>/assets/exercises/<slug>/0.jpg   (140 files, verified)
    asked for      /exercises/<slug>/0.jpg                       (the APK bundle)

Nothing raised. `ft.Image` renders an empty grey box for a source it cannot
resolve, so the training screen looked like a layout gap, the download dialog
reported "Installed", and the user reported it as "the images don't download".
They downloaded fine. They could never have been shown.

So these tests assert on the *delivery*: what a caller can actually hand to
`ft.Image`, under both path layouts. Testing `image_for()` harder would not
have caught it — the string was always correct.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

import asset_manager
import exercise_images
from exercise_images import EXERCISE_IMAGE, clear_inline_cache, image_props, url_is_served

SLUG = "Barbell_Bench_Press_-_Medium_Grip"
NOMBRE = "Barbell Bench Press"

# A one-pixel JPEG. Real bytes rather than b"x" so anything that ever decides
# to sniff the magic number keeps working.
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAA"
    "AQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    "MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpT"
    "VFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5"
    "usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/APn+iiigD//Z"
)


@pytest.fixture
def frames(tmp_path, monkeypatch):
    """Put real frames on disk in a directory that is *not* under cwd/assets."""
    storage = tmp_path / "app_storage"
    carpeta = storage / "assets" / "exercises" / SLUG
    carpeta.mkdir(parents=True)
    (carpeta / "0.jpg").write_bytes(JPEG)
    (carpeta / "1.jpg").write_bytes(JPEG)
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(storage))
    clear_inline_cache()
    yield carpeta
    clear_inline_cache()


# ── which delivery gets picked ───────────────────────────────────────────


def test_almacenamiento_privado_no_se_sirve_por_url(frames, monkeypatch, tmp_path):
    """The Android layout: frames outside cwd/assets, so no URL can work."""
    monkeypatch.chdir(tmp_path)
    assert url_is_served() is False


def test_el_directorio_del_proyecto_si_se_sirve(tmp_path, monkeypatch):
    """The web/desktop layout: frames under the assets dir Flet is serving."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    (tmp_path / "assets" / "exercises").mkdir(parents=True)
    assert url_is_served() is True


# ── what the caller can hand to ft.Image ─────────────────────────────────


def test_en_el_movil_devuelve_bytes_no_una_url(frames, monkeypatch, tmp_path):
    """THE REGRESSION. A `src` here is unrenderable on the device."""
    monkeypatch.chdir(tmp_path)
    props = image_props(NOMBRE)

    assert props, "no props at all means the exercise renders with no photo"
    assert "src" not in props, (
        "an assets-relative URL cannot resolve on Android — this is the bug "
        "that made every image on the phone a silent grey box"
    )
    assert base64.b64decode(props["src_base64"]) == JPEG


def test_en_web_devuelve_una_url_no_bytes(tmp_path, monkeypatch):
    """Inlining ~9 MB into a Browse grid the browser could stream is a waste."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    carpeta = tmp_path / "assets" / "exercises" / SLUG
    carpeta.mkdir(parents=True)
    (carpeta / "0.jpg").write_bytes(JPEG)
    clear_inline_cache()

    props = image_props(NOMBRE)
    assert props == {"src": f"/exercises/{SLUG}/0.jpg"}


def test_el_segundo_fotograma_tambien_llega(frames, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert base64.b64decode(image_props(NOMBRE, 1)["src_base64"]) == JPEG


def test_sin_segundo_fotograma_cae_al_primero(frames, monkeypatch, tmp_path):
    """A slug repaired from upstream can arrive with frame 0 only."""
    monkeypatch.chdir(tmp_path)
    (frames / "1.jpg").unlink()
    clear_inline_cache()
    assert image_props(NOMBRE, 1).get("src_base64")


# ── failing without taking the screen down ───────────────────────────────


def test_ejercicio_sin_imagen_devuelve_vacio():
    """Bulgarian Split Squat has no slug on purpose; `{}` is falsy, not a crash."""
    assert image_props("Bulgarian Split Squat") == {}
    assert image_props("Not An Exercise") == {}


def test_fichero_ilegible_no_revienta(frames, monkeypatch, tmp_path):
    """A half-written frame costs one photo, never the training screen."""
    monkeypatch.chdir(tmp_path)

    def explota(self, *a, **k):
        raise OSError("disk went away mid-set")

    monkeypatch.setattr(Path, "read_bytes", explota)
    clear_inline_cache()
    assert image_props(NOMBRE) == {}


# ── the cache must not outlive the files ─────────────────────────────────


def test_borrar_la_cache_deja_de_servir_lo_borrado(frames, monkeypatch, tmp_path):
    """Otherwise "Clear cache" looks like it did nothing at all."""
    monkeypatch.chdir(tmp_path)
    assert image_props(NOMBRE).get("src_base64")

    asset_manager.clear_cache()
    exercise_images.clear_inline_cache()
    assert image_props(NOMBRE) == {}


def test_la_cache_esta_acotada():
    """~100 thumbnails of base64 pinned forever is real memory on a phone."""
    assert exercise_images._inline.cache_info().maxsize is not None


# ── the whole catalogue, not just one lucky slug ─────────────────────────


def test_todo_lo_instalado_se_puede_entregar(monkeypatch):
    """Every exercise with a file on disk must produce usable props.

    Runs against whatever this machine actually has installed. It is the check
    that would have failed loudly on the device: 70 of 70 present on disk, 0 of
    70 deliverable.
    """
    if not asset_manager.status().present:
        pytest.skip("no images installed on this machine")

    entregables = 0
    for nombre, slug in EXERCISE_IMAGE.items():
        if slug and asset_manager.image_path(slug, 0):
            props = image_props(nombre)
            assert props, f"{nombre}: file on disk but nothing to render"
            assert ("src" in props) == url_is_served()
            entregables += 1
    assert entregables > 0


def test_url_is_served_coincide_con_el_entorno_real():
    """Sanity: on this machine the two layouts must not both claim to apply."""
    servido = url_is_served()
    en_almacenamiento_privado = bool(os.environ.get("FLET_APP_STORAGE_DATA"))
    if en_almacenamiento_privado:
        assert servido == (
            asset_manager._data_dir().resolve().is_relative_to((Path.cwd() / "assets").resolve())
        )
