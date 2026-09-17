#!/usr/bin/env python3
"""Rebuild `exercises.tar.gz` — the exercise-image bundle attached to a release.

Why this exists
---------------
The bundle is a snapshot of `exercise_images.EXERCISE_IMAGE`. It was built once
by hand, and then the catalog grew: `Barbell_Hip_Thrust` and
`Full_Range-Of-Motion_Lat_Pulldown` were added, copied straight into the
developer's `assets/` directory, and never made it into the published tarball.
On the PC they were there; on the phone — which installs from the tarball and
nothing else — two exercises rendered as blank space.

`asset_manager` now repairs that at runtime by fetching stragglers one by one
from upstream, so nothing is silently missing any more. But 70 individual
requests over gym Wi-Fi is not how the bundle *should* be delivered. Running
this script and publishing the result puts every image back in the one-request
fast path.

Usage
-----
    # build the bundle from the current catalog (network: only for what is
    # not already in ./assets/exercises or the cache)
    .venv/bin/python scripts/build_exercise_bundle.py

    # verify the catalog is fully obtainable, build nothing
    .venv/bin/python scripts/build_exercise_bundle.py --check

    # re-record which slugs the published release and upstream hold
    # (this is what keeps tests/test_asset_manager.py honest)
    .venv/bin/python scripts/build_exercise_bundle.py --refresh-manifest

Then publish it, and bump `asset_manager.RELEASE_VERSION` to match:

    gh release create v0.2.0 build/exercises.tar.gz \
        --repo kalexnolasco/ironflet --title v0.2.0 --notes "Exercise images"
    .venv/bin/python scripts/build_exercise_bundle.py --refresh-manifest

Bumping `RELEASE_VERSION` matters: it is baked into the marker file that says
"this release's tarball was already extracted here", so phones on the old
bundle will fetch the new one instead of assuming they are done.

Content is Free Exercise DB (github.com/yuhonas/free-exercise-db), Unlicense /
public domain, redistributed as the subset this app maps.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from exercise_images import required_slugs  # noqa: E402

UPSTREAM_RAW = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main"
UPSTREAM_IMAGES = f"{UPSTREAM_RAW}/exercises"
UPSTREAM_CATALOG = f"{UPSTREAM_RAW}/dist/exercises.json"

MANIFEST = REPO / "scripts" / "exercise_sources.json"
DEFAULT_OUT = REPO / "build" / "exercises.tar.gz"
DEFAULT_CACHE = REPO / "build" / "exercise-cache"

FRAMES = (0, 1)
JPEG_MAGIC = b"\xff\xd8\xff"


def _get(client: httpx.Client, url: str) -> bytes | None:
    """GET with the retries a flaky link needs. None means "not available"."""
    for intento in range(3):
        try:
            r = client.get(url)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except httpx.HTTPError:
            if intento == 2:
                raise
    return None


def _frame_bytes(client: httpx.Client, cache: Path, slug: str, frame: int) -> bytes | None:
    """One frame, from the cache, then the local assets dir, then upstream.

    The local `assets/exercises` copy is preferred over the network so a
    rebuild on a machine that already installed the images is offline and
    instant — but only if the file is a real JPEG, never a zero-byte stub left
    by an interrupted download.
    """
    for candidato in (
        cache / slug / f"{frame}.jpg",
        REPO / "assets" / "exercises" / slug / f"{frame}.jpg",
    ):
        if candidato.is_file() and candidato.stat().st_size > 0:
            datos = candidato.read_bytes()
            if datos.startswith(JPEG_MAGIC):
                return datos

    datos = _get(client, f"{UPSTREAM_IMAGES}/{slug}/{frame}.jpg")
    if datos is None:
        return None
    if not datos.startswith(JPEG_MAGIC):
        # A captive portal or a moved path. Saving it would poison the bundle
        # with a file that exists and cannot be decoded.
        raise SystemExit(f"{slug}/{frame}.jpg did not come back as a JPEG")
    destino = cache / slug / f"{frame}.jpg"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return datos


def gather(client: httpx.Client, cache: Path) -> tuple[dict[str, dict[int, bytes]], list[str]]:
    """Collect every frame for every required slug. Returns (frames, missing)."""
    recogido: dict[str, dict[int, bytes]] = {}
    faltan: list[str] = []
    slugs = required_slugs()
    for i, slug in enumerate(slugs, 1):
        marcos = {}
        for frame in FRAMES:
            datos = _frame_bytes(client, cache, slug, frame)
            if datos is not None:
                marcos[frame] = datos
        if 0 not in marcos:
            # Frame 0 is the image; without it the exercise has nothing to show.
            faltan.append(slug)
            print(f"  [{i:>3}/{len(slugs)}] MISSING  {slug}")
            continue
        recogido[slug] = marcos
        print(f"  [{i:>3}/{len(slugs)}] ok ({len(marcos)} frames)  {slug}")
    return recogido, faltan


def write_tarball(frames: dict[str, dict[int, bytes]], out: Path) -> None:
    """Write `exercises/<slug>/<n>.jpg`, the layout `asset_manager` extracts."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    with tarfile.open(tmp, "w:gz") as tar:
        for slug in sorted(frames):
            for frame in sorted(frames[slug]):
                datos = frames[slug][frame]
                with tempfile.NamedTemporaryFile() as fh:
                    fh.write(datos)
                    fh.flush()
                    tar.add(fh.name, arcname=f"exercises/{slug}/{frame}.jpg")
    tmp.replace(out)


def verify(out: Path) -> None:
    """Re-open what was written and check it against the catalog.

    Building and trusting the build is how the two missing slugs shipped in the
    first place.
    """
    with tarfile.open(out, "r:gz") as tar:
        dentro = {
            Path(m.name).parent.name
            for m in tar.getmembers()
            if m.isfile() and m.name.endswith(".jpg")
        }
    faltan = set(required_slugs()) - dentro
    if faltan:
        raise SystemExit(f"bundle is short of {len(faltan)} slugs: {sorted(faltan)}")
    print(f"verified: {len(dentro)} slugs, {out.stat().st_size / 1e6:.1f} MB → {out}")


def refresh_manifest() -> None:
    """Re-record what upstream and the published release actually contain.

    `tests/test_asset_manager.py` reads this file to assert, without touching
    the network, that every slug in the catalog is obtainable from somewhere.
    A manifest nobody regenerates would eventually assert nothing, so this is
    the command to run whenever a slug is added or a release is published.
    """
    import asset_manager

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        catalogo = json.loads(_get(client, UPSTREAM_CATALOG) or b"[]")
        upstream = sorted({e["id"] for e in catalogo if e.get("id")})

        release: list[str] = []
        try:
            datos = _get(client, asset_manager.TARBALL_URL)
        except httpx.HTTPError as exc:
            print(f"warning: could not read the published release ({exc}); keeping previous list")
            if MANIFEST.exists():
                release = json.loads(MANIFEST.read_text()).get("release_tarball_slugs", [])
            datos = None
        if datos:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz") as fh:
                fh.write(datos)
                fh.flush()
                with tarfile.open(fh.name, "r:gz") as tar:
                    release = sorted(
                        {
                            Path(m.name).parent.name
                            for m in tar.getmembers()
                            if m.isfile() and m.name.endswith(".jpg")
                        }
                    )

    MANIFEST.write_text(
        json.dumps(
            {
                "_comment": (
                    "Generated by scripts/build_exercise_bundle.py --refresh-manifest. "
                    "Read by tests/test_asset_manager.py so 'every slug is obtainable' "
                    "can be asserted without network access."
                ),
                "release": asset_manager.RELEASE_VERSION,
                "release_tarball_url": asset_manager.TARBALL_URL,
                "upstream_catalog_url": UPSTREAM_CATALOG,
                "release_tarball_slugs": release,
                "upstream_slugs": upstream,
            },
            indent=1,
        )
        + "\n"
    )
    print(
        f"manifest: {len(release)} slugs in {asset_manager.RELEASE_VERSION}, {len(upstream)} upstream"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help=f"tarball path (default {DEFAULT_OUT})"
    )
    p.add_argument(
        "--cache", type=Path, default=DEFAULT_CACHE, help="where downloaded frames are kept"
    )
    p.add_argument("--check", action="store_true", help="report coverage, write nothing")
    p.add_argument("--refresh-manifest", action="store_true", help="re-record the source manifest")
    p.add_argument("--clean", action="store_true", help="drop the frame cache first")
    args = p.parse_args(argv)

    if args.refresh_manifest:
        refresh_manifest()
        return 0

    if args.clean and args.cache.exists():
        shutil.rmtree(args.cache)
    args.cache.mkdir(parents=True, exist_ok=True)

    print(f"catalog: {len(required_slugs())} slugs")
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        frames, faltan = gather(client, args.cache)

    if faltan:
        print(f"\n{len(faltan)} slug(s) could not be obtained: {faltan}", file=sys.stderr)
        return 1
    if args.check:
        print(f"\nall {len(frames)} slugs are obtainable")
        return 0

    write_tarball(frames, args.out)
    verify(args.out)
    print("\nNext: upload it and bump asset_manager.RELEASE_VERSION, then")
    print("      scripts/build_exercise_bundle.py --refresh-manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
