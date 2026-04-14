"""Runtime downloader for exercise images.

Images are NOT bundled in the APK — they're fetched once from the
Free Exercise DB (Unlicense / public domain) and cached locally in
the platform's app-storage directory.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Callable

import httpx

from exercise_images import EXERCISE_IMAGE


RAW_BASE = ("https://raw.githubusercontent.com/yuhonas/"
            "free-exercise-db/main/exercises")
VERSION_FILE = ".installed-v1"


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


def _jobs() -> list[tuple[str, Path]]:
    """(url, target_path) for every required image file."""
    out: list[tuple[str, Path]] = []
    slugs = {s for s in EXERCISE_IMAGE.values() if s}
    for slug in sorted(slugs):
        for i in range(2):
            url = f"{RAW_BASE}/{slug}/{i}.jpg"
            target = _data_dir() / slug / f"{i}.jpg"
            out.append((url, target))
    return out


def total_file_count() -> int:
    return len(_jobs())


async def download_all(
    progress_cb: Callable[[int, int], None] | None = None,
    concurrency: int = 6,
) -> tuple[int, int]:
    """Download every missing frame. Returns (downloaded, failed)."""
    jobs = _jobs()
    total = len(jobs)
    data_dir()  # ensure root exists
    done = {"n": 0, "ok": 0, "err": 0}
    sem = asyncio.Semaphore(concurrency)

    async def fetch(client: httpx.AsyncClient, url: str, target: Path):
        async with sem:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and target.stat().st_size > 0:
                    done["ok"] += 1
                else:
                    r = await client.get(url)
                    r.raise_for_status()
                    target.write_bytes(r.content)
                    done["ok"] += 1
            except Exception:
                done["err"] += 1
            done["n"] += 1
            if progress_cb:
                try:
                    progress_cb(done["n"], total)
                except Exception:
                    pass

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        await asyncio.gather(*[fetch(client, u, t) for u, t in jobs])

    # Mark installed only if at least half succeeded.
    if done["ok"] >= total // 2:
        (_data_dir() / VERSION_FILE).write_text("ok")
    return done["ok"], done["err"]


def clear_cache() -> None:
    """Delete all cached image files and the install marker."""
    import shutil
    d = _data_dir()
    if d.exists():
        shutil.rmtree(d)
