"""Runtime downloader for exercise images.

Images are NOT bundled in the APK. They are fetched on demand into the
platform's app-storage directory and cached there.

There are **two** sources, tried in this order:

1. **The release tarball** — one request, ~8.5 MB, every slug at once. Fast,
   and the only sane way to move 140 files over a phone connection.
2. **The upstream Free Exercise DB** (github.com/yuhonas/free-exercise-db,
   Unlicense / public domain) — one file at a time, used to repair whatever
   the tarball did not deliver.

The second source is the whole point of this module's design. The tarball is a
*snapshot*: it was built once, from the catalog as it stood that day. Any slug
added to `EXERCISE_IMAGE` afterwards simply does not exist in it. That is
exactly what happened — `Barbell_Hip_Thrust` and `Full_Range-Of-Motion_Lat_Pulldown`
were added to the catalog and hand-copied into the developer's `assets/`
directory, so they rendered fine on the PC and were *missing on the phone*,
which downloads the tarball and nothing else. The failure was silent:
`image_for()` returned None and the screen showed a hole.

So: completeness is now measured against `EXERCISE_IMAGE`, never against "did
the tarball arrive". Anything the tarball is short of is fetched individually.

Hostile-network notes (this app is used on gym Wi-Fi):

- The tarball download **resumes** via HTTP Range instead of restarting the
  8.5 MB from zero when the connection drops mid-file.
- Every payload is checked against its magic bytes. A captive portal answers
  `200 OK` with an HTML login page, and the old code would happily save that
  as `0.jpg` — an unopenable file that *exists*, which is worse than a missing
  one because every later check considers it installed.
- Files are written to a temporary name and `os.replace`d into place, so a
  process killed mid-write never leaves a truncated JPEG behind.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import httpx

from exercise_images import required_slugs

RELEASE_VERSION = "v0.1.0"
TARBALL_URL = (
    f"https://github.com/kalexnolasco/ironflet/releases/download/{RELEASE_VERSION}/exercises.tar.gz"
)

# Marks "the tarball for this release was already extracted here". It does NOT
# mean "the install is complete" — that question is answered by looking at the
# files on disk, because the tarball can be (and is) short of the catalog.
TARBALL_MARKER = ".tarball-" + RELEASE_VERSION

# Upstream, per-file. Same public-domain source the tarball was built from.
UPSTREAM_BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises"

_JPEG_MAGIC = b"\xff\xd8\xff"
_GZIP_MAGIC = b"\x1f\x8b"

# Above this many missing slugs the tarball is worth its 9 MB; below it,
# fetching the stragglers one by one costs a few hundred KB instead.
#
# This is what spares an upgrading phone a pointless 9 MB. Its images were
# installed by the previous version, which used a differently-named marker
# file, so "was this release's tarball extracted here?" answers no even though
# 68 of the 70 images are already sitting on disk. Deciding by *what is
# actually missing* rather than by a marker gets that case right without
# knowing anything about the old file's name.
_BULK_THRESHOLD = 8

# Consecutive per-file failures that mean "the network is gone" rather than
# "this one file is unavailable". See the circuit breaker in `download_all`.
_REPAIR_GIVE_UP = 5

# Retries per individual file. Three is enough to ride out a lift-shaft dropout
# without making a genuinely dead network take a minute to admit it.
_ATTEMPTS = 3

# Short read timeout on purpose: a stalled gym connection should fail and be
# retried, not hang for two minutes behind a progress bar that never moves.
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)


# ── locations ────────────────────────────────────────────────


def _data_dir() -> Path:
    """Where the downloaded frames live: inside `assets/`, always.

    They used to land next to the source and be referenced as `file://` URLs.
    That works on desktop and dies in web mode, which is how this app is
    actually used: the browser refuses with "Not allowed to load local
    resource" and every exercise renders blank. Under `assets/` Flet serves
    them over HTTP from the same origin as the page, and the desktop build
    resolves the same relative path locally.
    """
    base = os.environ.get("FLET_APP_STORAGE_DATA") or os.getcwd()
    return Path(base) / "assets" / "exercises"


def data_dir() -> Path:
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _work_dir() -> Path:
    """Scratch space for partial downloads.

    Dot-prefixed and inside the data dir so `clear_cache()` takes it with
    everything else, and so it can never be mistaken for a slug directory.
    """
    d = _data_dir() / ".partial"
    d.mkdir(parents=True, exist_ok=True)
    return d


def image_path(slug: str, frame: int = 0) -> Path | None:
    if not slug:
        return None
    p = _data_dir() / slug / f"{frame}.jpg"
    return p if p.exists() else None


# ── what is installed ────────────────────────────────────────


class AssetStatus(NamedTuple):
    """A count Profile can render without recomputing anything.

    `missing_slugs` is the list, not just the number, because "2 of 70
    missing" is only actionable if you can also say *which* two.
    """

    total: int
    present: int
    missing: int
    missing_slugs: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.missing == 0


def _has_slug(slug: str) -> bool:
    """A slug counts as installed when frame 0 is on disk and non-empty.

    Size matters: a zero-byte file is what an interrupted write used to leave,
    and `Path.exists()` alone called that installed.
    """
    p = _data_dir() / slug / "0.jpg"
    try:
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def missing_slugs() -> tuple[str, ...]:
    """Required slugs with no usable frame 0 on disk."""
    return tuple(s for s in required_slugs() if not _has_slug(s))


def status() -> AssetStatus:
    faltan = missing_slugs()
    total = len(required_slugs())
    return AssetStatus(
        total=total,
        present=total - len(faltan),
        missing=len(faltan),
        missing_slugs=faltan,
    )


def is_installed() -> bool:
    """True only when every slug the catalog needs is actually on disk.

    This used to be `marker_file.exists()`, which is why the bug survived: the
    marker was written as soon as *anything* extracted, so a bundle two slugs
    short reported itself installed forever and never retried.
    """
    return status().complete


def missing_summary() -> str | None:
    """One line for the UI, or None when there is nothing to report."""
    st = status()
    if st.complete:
        return None
    return f"{st.missing} of {st.total} exercise images missing"


def total_slug_count() -> int:
    """Number of distinct images the catalog needs — the progress denominator."""
    return len(required_slugs())


def total_file_count() -> int:
    """Legacy name kept for the views; same number as `total_slug_count()`.

    It used to return `slugs * 2` and count frames, which never matched what
    actually arrived: the tarball holds 136 files, the catalog claimed 140, so
    a *fully successful* download reported "136 ok / 4 err" every single time.
    Progress is counted in slugs now — one exercise, one step.
    """
    return total_slug_count()


# ── writing ──────────────────────────────────────────────────


def _atomic_write(target: Path, payload: bytes) -> None:
    """Write via a temp file + rename, so readers never see a partial file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(payload)
    os.replace(tmp, target)


def _looks_like_jpeg(payload: bytes) -> bool:
    """Reject captive-portal HTML served with a 200 and an image URL."""
    return payload.startswith(_JPEG_MAGIC)


# ── downloading ──────────────────────────────────────────────


async def _fetch_frame(client: httpx.AsyncClient, slug: str, frame: int) -> bool:
    """Fetch one frame from upstream. False = not available (and that is fine).

    A 404 is a legitimate answer (some slugs could ship a single frame), so it
    returns False rather than raising. Anything else is retried.
    """
    url = f"{UPSTREAM_BASE}/{slug}/{frame}.jpg"
    for intento in range(1, _ATTEMPTS + 1):
        try:
            r = await client.get(url)
            if r.status_code == 404:
                return False
            r.raise_for_status()
            payload = r.content
            if not _looks_like_jpeg(payload):
                # Not a transport error, so httpx will not retry it for us.
                raise ValueError(f"{url} did not return a JPEG (captive portal?)")
            _atomic_write(_data_dir() / slug / f"{frame}.jpg", payload)
            return True
        except Exception:
            if intento == _ATTEMPTS:
                return False
            await asyncio.sleep(0.5 * intento)
    return False


async def _repair_slug(client: httpx.AsyncClient, slug: str) -> bool:
    """Fetch a single missing exercise from upstream. True if frame 0 landed.

    Frame 1 is best-effort: `image_frames()` falls back to showing frame 0
    twice, so a missing second frame costs the animation, not the image.
    """
    ok = await _fetch_frame(client, slug, 0)
    if ok:
        await _fetch_frame(client, slug, 1)
    return ok


async def _download_tarball(client: httpx.AsyncClient) -> Path | None:
    """Stream the release tarball to disk, resuming a previous partial file.

    Streamed to a file rather than to memory: 8.5 MB of gzip plus the extracted
    copy is a lot to hold on a phone, and a file is what makes Range resume
    possible at all.
    """
    part = _work_dir() / "exercises.tar.gz.part"
    ya = part.stat().st_size if part.exists() else 0

    headers = {"Range": f"bytes={ya}-"} if ya else {}
    try:
        async with client.stream("GET", TARBALL_URL, headers=headers) as r:
            if ya and r.status_code == 200:
                # Server ignored the Range header: it is sending the whole file
                # again, so the bytes we already have must not be kept.
                ya = 0
            elif r.status_code not in (200, 206):
                r.raise_for_status()
            modo = "ab" if ya else "wb"
            with part.open(modo) as fh:
                async for chunk in r.aiter_bytes(chunk_size=64 * 1024):
                    fh.write(chunk)
    except Exception:
        # Keep the partial file: the next attempt resumes from where it died.
        return None

    if part.stat().st_size < 4 or part.open("rb").read(2) != _GZIP_MAGIC:
        # A resumed-onto-garbage or captive-portal body. Start clean next time.
        part.unlink(missing_ok=True)
        return None
    return part


def _extract_tarball(archive: Path) -> int:
    """Extract `exercises/<slug>/<n>.jpg` into the data dir. Returns file count."""
    root = data_dir()
    extraidos = 0
    with tarfile.open(archive, mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            # Sanitize: only relative paths, no escape via ..
            name = m.name
            if name.startswith("/") or ".." in Path(name).parts:
                continue
            rel = name
            if rel.startswith("exercises/"):
                rel = rel[len("exercises/") :]
            f = tar.extractfile(m)
            if f is None:
                continue
            _atomic_write(root / rel, f.read())
            extraidos += 1
    return extraidos


async def download_all(
    progress_cb: Callable[[int, int], None] | None = None,
    *,
    force: bool = False,
) -> tuple[int, int]:
    """Install every image the catalog needs. Returns (installed, missing).

    Progress is reported in **slugs**, not files: `(done, total)` where total
    is `total_slug_count()`. `missing` is what is still absent when this
    returns, so `missing == 0` is the only definition of success — the caller
    no longer has to guess from a byte count.
    """
    data_dir()
    total = total_slug_count()

    def report(hechos: int) -> None:
        if progress_cb:
            with contextlib.suppress(Exception):
                progress_cb(min(hechos, total), total)

    st = status()
    if st.complete and not force:
        report(total)
        return st.present, 0

    report(st.present)
    marca = _data_dir() / TARBALL_MARKER

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        # Phase 1 — bulk. Skipped when this release's tarball already landed,
        # or when so little is missing that per-file repair is the cheaper
        # request: retrying after a partial install must not re-fetch 9 MB to
        # recover two files.
        if force or (not marca.exists() and st.missing > _BULK_THRESHOLD):
            archive = await _download_tarball(client)
            if archive is not None:
                try:
                    if _extract_tarball(archive) > 0:
                        marca.write_text(RELEASE_VERSION)
                        archive.unlink(missing_ok=True)
                except tarfile.TarError:
                    # Corrupt archive: drop it so the next run re-downloads
                    # instead of resuming onto broken bytes forever.
                    archive.unlink(missing_ok=True)
            report(status().present)

        # Phase 2 — repair. Whatever the tarball did not cover is fetched one
        # file at a time. This is what stops a stale release from becoming a
        # hole on the screen.
        pendientes = missing_slugs()
        hechos = total - len(pendientes)
        seguidos_mal = 0
        for slug in pendientes:
            if await _repair_slug(client, slug):
                hechos += 1
                seguidos_mal = 0
            else:
                seguidos_mal += 1
                # Circuit breaker. Each failed slug costs three attempts with
                # backoff, so grinding through 70 of them on a dead connection
                # leaves the user staring at a frozen progress bar for minutes.
                # A run of consecutive failures means the network, not the
                # files: stop and report, the caller can retry.
                if seguidos_mal >= _REPAIR_GIVE_UP:
                    break
            report(hechos)

    final = status()
    return final.present, final.missing


def clear_cache() -> None:
    import shutil

    d = _data_dir()
    if d.exists():
        shutil.rmtree(d)
