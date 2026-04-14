"""Runtime downloader for exercise images.

Images are NOT bundled in the APK. On first use the app downloads a single
tarball attached to a GitHub Release of this repository, extracts it into
the platform's app-storage directory, and caches it there.

Upstream content comes from the Free Exercise DB (Unlicense / public
domain); we redistribute a subset matching our exercise catalog.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path
from typing import Callable

import httpx

from exercise_images import EXERCISE_IMAGE


RELEASE_VERSION = "v0.1.0"
TARBALL_URL = (
    "https://github.com/kalexnolasco/ironflet/releases/download/"
    f"{RELEASE_VERSION}/exercises.tar.gz"
)
VERSION_FILE = ".installed-" + RELEASE_VERSION


def _data_dir() -> Path:
    base = os.environ.get("FLET_APP_STORAGE_DATA") or os.getcwd()
    return Path(base) / "exercises"


def data_dir() -> Path:
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_installed() -> bool:
    return (_data_dir() / VERSION_FILE).exists()


def image_path(slug: str, frame: int = 0) -> Path | None:
    if not slug:
        return None
    p = _data_dir() / slug / f"{frame}.jpg"
    return p if p.exists() else None


def total_file_count() -> int:
    """Number of unique image frames the bundle contains (2 per unique slug)."""
    slugs = {s for s in EXERCISE_IMAGE.values() if s}
    return len(slugs) * 2


async def download_all(
    progress_cb: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    """Download and extract the exercise tarball. Returns (extracted, failed)."""
    root = data_dir()
    total_bytes = 0
    received = 0

    def report(done_files: int, total_files: int):
        if progress_cb:
            try:
                progress_cb(done_files, total_files)
            except Exception:
                pass

    report(0, total_file_count())

    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            buf = io.BytesIO()
            async with client.stream("GET", TARBALL_URL) as r:
                r.raise_for_status()
                total_bytes = int(r.headers.get("content-length") or 0)
                async for chunk in r.aiter_bytes(chunk_size=64 * 1024):
                    buf.write(chunk)
                    received += len(chunk)
                    if total_bytes:
                        # Map byte progress to a 0..(file_count // 2) range so
                        # users see movement even before extraction starts.
                        approx = int(
                            received / total_bytes * (total_file_count() // 2)
                        )
                        report(approx, total_file_count())
            buf.seek(0)
    except Exception:
        return 0, total_file_count()

    # Extract
    extracted = 0
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        total = len(members) or total_file_count()
        for i, m in enumerate(members, 1):
            # Sanitize: only relative paths, no escape via ..
            name = m.name
            if name.startswith("/") or ".." in Path(name).parts:
                continue
            # Strip leading "exercises/" if present (tarball may or may not have it)
            rel = name
            if rel.startswith("exercises/"):
                rel = rel[len("exercises/"):]
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            f = tar.extractfile(m)
            if f is None:
                continue
            target.write_bytes(f.read())
            extracted += 1
            report(extracted, total)

    if extracted > 0:
        (_data_dir() / VERSION_FILE).write_text("ok")
    return extracted, max(0, total_file_count() - extracted)


def clear_cache() -> None:
    import shutil
    d = _data_dir()
    if d.exists():
        shutil.rmtree(d)
