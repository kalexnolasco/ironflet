"""The exercise bundle shipped two slugs short, and nothing said so.

`EXERCISE_IMAGE` needs 70 images. The tarball published with the release holds
68: `Barbell_Hip_Thrust` and `Full_Range-Of-Motion_Lat_Pulldown` were added to
the catalog *after* it was cut, and copied by hand into the developer's
`assets/` directory. On the PC they were there. On the phone — which installs
from the tarball and nothing else — `image_for()` returned None and two
exercises rendered as blank space. That is the "some images fail" report.

Three separate things let it stay invisible, and each one is pinned below:

- completeness was measured as "did the tarball extract", not "does the catalog
  have its images", so a bundle two slugs short reported itself installed;
- the progress denominator was `slugs * 2 = 140` while the tarball only ever
  held 136 files, so a *successful* download always ended in "4 err" and the
  number stopped meaning anything;
- there was no second source, so a stale release could never be repaired.

The coverage test reads `scripts/exercise_sources.json` — a manifest recorded
from the real release and the real upstream catalog by
`scripts/build_exercise_bundle.py --refresh-manifest`. It is deliberately
offline: a test that hits the network to prove images exist goes red on gym
Wi-Fi, on a plane and in CI, and a flaky guard gets deleted instead of fixed.
The network checks at the bottom are opt-in via IRONFLET_NETWORK_TESTS=1.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

import asset_manager as am
from exercise_images import EXERCISE_IMAGE, required_slugs

MANIFIESTO = Path(__file__).resolve().parent.parent / "scripts" / "exercise_sources.json"

# The two that went missing. Named, not counted, so the test says which.
LOS_QUE_FALTARON = ("Barbell_Hip_Thrust", "Full_Range-Of-Motion_Lat_Pulldown")

SOLO_CON_RED = pytest.mark.skipif(
    not os.environ.get("IRONFLET_NETWORK_TESTS"),
    reason="network test; set IRONFLET_NETWORK_TESTS=1 to run",
)


@pytest.fixture
def almacen(tmp_path, monkeypatch) -> Path:
    """Point the asset manager at an empty directory for this test only."""
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    return tmp_path / "assets" / "exercises"


def instalar(raiz: Path, slug: str, frames=(0, 1)) -> None:
    """Drop a minimal but genuinely JPEG-headed file, as a download would."""
    for f in frames:
        p = raiz / slug / f"{f}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xff\xd8\xff" + b"0" * 32)


@pytest.fixture(scope="module")
def fuentes() -> dict:
    if not MANIFIESTO.exists():
        pytest.fail(
            f"{MANIFIESTO} is missing. Regenerate it with:\n"
            "  .venv/bin/python scripts/build_exercise_bundle.py --refresh-manifest"
        )
    return json.loads(MANIFIESTO.read_text())


# ── every slug must be obtainable from somewhere ─────────────


def test_todo_slug_del_catalogo_tiene_una_fuente(fuentes):
    """The regression guard: no slug may be needed and unavailable.

    A slug that is in neither the published tarball nor the upstream catalog
    is an image that can never appear, on any device — exactly the state the
    two names above were in on the phone, only permanent.
    """
    disponibles = set(fuentes["release_tarball_slugs"]) | set(fuentes["upstream_slugs"])
    huerfanos = sorted(set(required_slugs()) - disponibles)
    assert not huerfanos, (
        f"{len(huerfanos)} slug(s) cannot be obtained from any source: {huerfanos}. "
        "Either fix the slug spelling in exercise_images.py or, if it is genuinely "
        "new upstream, refresh the manifest: "
        "scripts/build_exercise_bundle.py --refresh-manifest"
    )


def test_los_dos_que_faltaban_siguen_cubiertos_por_upstream(fuentes):
    """Pins the incident itself: absent from the release, present upstream."""
    release = set(fuentes["release_tarball_slugs"])
    upstream = set(fuentes["upstream_slugs"])
    for slug in LOS_QUE_FALTARON:
        assert slug in required_slugs(), f"{slug} disappeared from EXERCISE_IMAGE"
        assert slug in upstream, f"{slug} is no longer obtainable upstream"
        if slug in release:
            # Only reachable once a rebuilt bundle is published. Not a failure —
            # it is the fix — but the repair path must not be dropped because of
            # it: the next slug added will be in the same position.
            pytest.skip(f"{slug} is now in the published release too")


def test_el_manifiesto_describe_el_release_que_la_app_descarga(fuentes):
    assert fuentes["release"] == am.RELEASE_VERSION, (
        "the manifest was recorded for a different release than asset_manager "
        "downloads; run scripts/build_exercise_bundle.py --refresh-manifest"
    )
    assert set(fuentes["release_tarball_slugs"]) <= set(fuentes["upstream_slugs"])


def test_hay_una_ruta_de_reparacion_por_fichero():
    """Without a per-file source, a stale release is unfixable at runtime."""
    assert am.UPSTREAM_BASE.startswith("https://")
    assert "free-exercise-db" in am.UPSTREAM_BASE


# ── counting what is installed ───────────────────────────────


def test_el_denominador_cuenta_slugs_no_frames():
    """The 140-vs-136 bug: a complete download used to report 4 failures."""
    assert am.total_file_count() == len(required_slugs())
    assert am.total_slug_count() == len(required_slugs())
    assert len({s for s in EXERCISE_IMAGE.values() if s}) == am.total_slug_count()


def test_status_dice_cuantas_y_cuales_faltan(almacen):
    todos = required_slugs()
    for slug in todos[:-2]:
        instalar(almacen, slug)

    st = am.status()
    assert st.total == len(todos)
    assert st.missing == 2
    assert st.present == len(todos) - 2
    assert st.missing_slugs == todos[-2:]
    assert not st.complete
    assert am.missing_summary() == f"2 of {len(todos)} exercise images missing"


def test_instalacion_completa_no_reporta_nada(almacen):
    for slug in required_slugs():
        instalar(almacen, slug)
    assert am.is_installed()
    assert am.missing_summary() is None
    assert am.status().missing_slugs == ()


def test_la_marca_del_tarball_no_basta_para_decir_instalado(almacen):
    """The exact bug. The marker meant "extraction happened", never "complete".

    Two slugs short, marker written, `is_installed()` said True — so the app
    never retried and the hole was permanent until someone cleared the cache.
    """
    for slug in required_slugs()[:-2]:
        instalar(almacen, slug)
    almacen.mkdir(parents=True, exist_ok=True)
    (almacen / am.TARBALL_MARKER).write_text(am.RELEASE_VERSION)

    assert not am.is_installed()
    assert am.status().missing == 2


def test_un_fichero_de_cero_bytes_no_cuenta_como_instalado(almacen):
    """What an interrupted write left behind; `exists()` alone called it done."""
    slug = required_slugs()[0]
    p = almacen / slug / "0.jpg"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    assert slug in am.missing_slugs()


def test_sin_directorio_falta_todo(almacen):
    st = am.status()
    assert st.missing == st.total
    assert not am.is_installed()


# ── writing safely ───────────────────────────────────────────


def test_escritura_atomica_no_deja_restos(tmp_path):
    destino = tmp_path / "slug" / "0.jpg"
    am._atomic_write(destino, b"\xff\xd8\xffdatos")
    assert destino.read_bytes() == b"\xff\xd8\xffdatos"
    assert not list(tmp_path.glob("**/*.part"))


def test_html_no_pasa_por_jpeg():
    assert am._looks_like_jpeg(b"\xff\xd8\xff\xe0" + b"x" * 20)
    assert not am._looks_like_jpeg(b"<!DOCTYPE html><title>Gym WiFi login</title>")
    assert not am._looks_like_jpeg(b"")


# ── the repair path, without touching the network ────────────


_AsyncClient = httpx.AsyncClient  # captured before any test patches the name


def _cliente(handler) -> httpx.AsyncClient:
    return _AsyncClient(transport=httpx.MockTransport(handler))


async def _sin_esperar(_segundos: float) -> None:
    """Stand-in for the retry backoff, so tests do not pay for it in real time."""


async def test_reparar_baja_los_dos_frames(almacen):
    slug = "Barbell_Hip_Thrust"
    pedidas: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        pedidas.append(str(req.url))
        return httpx.Response(200, content=b"\xff\xd8\xff" + b"jpeg")

    async with _cliente(handler) as c:
        assert await am._repair_slug(c, slug)

    assert (almacen / slug / "0.jpg").exists()
    assert (almacen / slug / "1.jpg").exists()
    assert pedidas == [
        f"{am.UPSTREAM_BASE}/{slug}/0.jpg",
        f"{am.UPSTREAM_BASE}/{slug}/1.jpg",
    ]


async def test_un_portal_cautivo_no_se_guarda_como_imagen(almacen):
    """A gym hotspot answers 200 with a login page. Saving it is worse than
    failing: the file exists, so every later check considers it installed."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<html>Sign in to use this network</html>")

    async with _cliente(handler) as c:
        assert not await am._repair_slug(c, "Plank")

    assert not (almacen / "Plank" / "0.jpg").exists()
    assert "Plank" in am.missing_slugs()


async def test_el_segundo_frame_es_opcional(almacen):
    """A slug with only frame 0 is a still image, not a missing exercise."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("1.jpg"):
            return httpx.Response(404)
        return httpx.Response(200, content=b"\xff\xd8\xff" + b"jpeg")

    async with _cliente(handler) as c:
        assert await am._repair_slug(c, "Plank")

    assert (almacen / "Plank" / "0.jpg").exists()
    assert not (almacen / "Plank" / "1.jpg").exists()
    assert "Plank" not in am.missing_slugs()


async def test_reintenta_un_corte_de_conexion(almacen):
    """Gym Wi-Fi drops one request and serves the next. One failure is not a
    verdict, so the retry loop must ride over it."""
    intentos = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("0.jpg"):
            intentos["n"] += 1
            if intentos["n"] == 1:
                raise httpx.ConnectError("connection reset")
        return httpx.Response(200, content=b"\xff\xd8\xff" + b"jpeg")

    async with _cliente(handler) as c:
        assert await am._repair_slug(c, "Plank")

    assert intentos["n"] == 2
    assert (almacen / "Plank" / "0.jpg").exists()


async def test_download_all_no_toca_la_red_si_ya_esta_todo(almacen, monkeypatch):
    """Reopening Profile must not re-download 9 MB to confirm it is done."""
    for slug in required_slugs():
        instalar(almacen, slug)

    def prohibido(*a, **k):
        raise AssertionError("download_all hit the network with nothing missing")

    monkeypatch.setattr(am.httpx, "AsyncClient", prohibido)
    ok, faltan = await am.download_all()

    assert (ok, faltan) == (len(required_slugs()), 0)


async def test_una_instalacion_antigua_no_se_baja_el_tarball_otra_vez(almacen, monkeypatch):
    """The upgrade case: images already on disk, but from the previous version,
    which wrote a differently-named marker. Only two slugs are actually
    missing, and re-fetching 9 MB of tarball to recover them would be the
    worst possible thing to do on gym Wi-Fi."""
    for slug in required_slugs()[:-2]:
        instalar(almacen, slug)
    (almacen / ".installed-v0.1.0").write_text("ok")  # the old marker name

    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        return httpx.Response(200, content=b"\xff\xd8\xff" + b"jpeg")

    monkeypatch.setattr(am.httpx, "AsyncClient", lambda **k: _cliente(handler))
    ok, faltan = await am.download_all()

    assert (ok, faltan) == (len(required_slugs()), 0)
    assert not any(u == am.TARBALL_URL for u in urls), "re-downloaded the whole bundle"
    assert all(u.startswith(am.UPSTREAM_BASE) for u in urls)


async def test_se_rinde_pronto_cuando_no_hay_red(almacen, monkeypatch):
    """A dead connection must not mean minutes of frozen progress bar.

    Every failed slug costs three attempts with backoff, so without a circuit
    breaker an offline retry walks all 70 before reporting anything.
    """
    intentos = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        raise httpx.ConnectError("network is unreachable")

    monkeypatch.setattr(am.httpx, "AsyncClient", lambda **k: _cliente(handler))
    # The retry backoff is real time; without this the test sleeps for ~8 s.
    monkeypatch.setattr(am.asyncio, "sleep", _sin_esperar)
    # Few enough missing that phase 1 is skipped: this exercises the repair loop.
    for slug in required_slugs()[am._BULK_THRESHOLD :]:
        instalar(almacen, slug)

    ok, faltan = await am.download_all()

    assert faltan == am._BULK_THRESHOLD, "nothing should have been installed"
    assert intentos["n"] <= am._REPAIR_GIVE_UP * am._ATTEMPTS, (
        f"kept trying after the network was clearly down ({intentos['n']} requests)"
    )


async def test_download_all_informa_el_progreso_en_slugs(almacen):
    for slug in required_slugs():
        instalar(almacen, slug)
    pasos: list[tuple[int, int]] = []
    await am.download_all(progress_cb=lambda d, t: pasos.append((d, t)))
    assert pasos[-1] == (len(required_slugs()), len(required_slugs()))


def test_un_progress_cb_que_revienta_no_tumba_la_descarga(almacen):
    """The view can be rebuilt or navigated away from mid-download. Progress is
    cosmetic and must never take the install with it."""
    for slug in required_slugs():
        instalar(almacen, slug)

    def explota(done, total):
        raise RuntimeError("the view is gone")

    ok, faltan = asyncio.run(am.download_all(progress_cb=explota))
    assert faltan == 0


# ── opt-in: the sources really answer ────────────────────────


@SOLO_CON_RED
def test_las_urls_de_upstream_responden_de_verdad():
    """Proves the manifest is not fiction. Off by default so the suite stays
    green without a network."""
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        fallan = [
            slug
            for slug in required_slugs()
            if c.head(f"{am.UPSTREAM_BASE}/{slug}/0.jpg").status_code >= 400
        ]
    assert not fallan, f"upstream no longer serves: {fallan}"
