"""Auto-generated. Maps canonical English exercise name → Free Exercise DB slug.

Images live in assets/exercises/<slug>/0.jpg.
Source: github.com/yuhonas/free-exercise-db (Unlicense / public domain).

## Why there are two delivery paths — read this before touching `image_props`

An assets-relative URL (`/exercises/<slug>/0.jpg`) only renders if the file
sits inside the directory Flet is *serving*. That is true in web mode (Flet
serves `assets/` over HTTP) and on desktop (the client resolves the path
locally). **On Android it is false**, and the failure is silent and total:

    the frames download to  FLET_APP_STORAGE_DATA/assets/exercises/<slug>/
    the APK's asset bundle is a different place entirely
    -> the Image control finds nothing and paints an empty grey box

That is the whole of "the images don't download on my phone". They downloaded
perfectly — 140 files, verified on the device — and then nothing could ever
show them. Re-downloading, clearing the cache and reinstalling all leave it
exactly as broken, which is why it read as a download bug.

So `image_props()` picks the delivery by asking the one question that actually
decides it: **is the file inside the directory being served?** If yes, hand
over the URL, which is cheap and streams. If no, read the bytes and send them
inline as base64. No platform sniffing — the rule is the mechanism.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

EXERCISE_IMAGE: dict[str, str] = {
    "Barbell Bench Press": "Barbell_Bench_Press_-_Medium_Grip",
    "Smith Bench Press": "Smith_Machine_Bench_Press",
    "Incline DB Press": "Incline_Dumbbell_Press",
    "Incline Machine Press": "Smith_Machine_Incline_Bench_Press",
    "Decline Press": "Decline_Dumbbell_Bench_Press",
    "Close-Grip Bench Press": "Close-Grip_Barbell_Bench_Press",
    "Smith Close-Grip Press": "Close-Grip_Barbell_Bench_Press",
    "Flat Machine Press": "Machine_Bench_Press",
    "Incline DB Flyes": "Incline_Dumbbell_Flyes",
    "Incline Flyes": "Incline_Dumbbell_Flyes",
    "Machine Flyes": "Butterfly",
    "Pec Deck": "Butterfly",
    "Cable Crossover": "Cable_Crossover",
    "Push-ups": "Pushups",
    "Front Lat Pulldown": "Wide-Grip_Lat_Pulldown",
    "Behind-Neck Lat Pulldown": "Full_Range-Of-Motion_Lat_Pulldown",
    "V-Grip Lat Pulldown": "V-Bar_Pulldown",
    "Pull-ups": "Pullups",
    "Barbell Row": "Bent_Over_Barbell_Row",
    "DB Row": "One-Arm_Dumbbell_Row",
    "Seated Cable Row": "Seated_Cable_Rows",
    "T-Bar Row": "T-Bar_Row_with_Handle",
    "Machine Row": "Bent_Over_Two-Dumbbell_Row",
    "Reverse Barbell Row": "Reverse_Grip_Bent-Over_Rows",
    "Deadlift": "Barbell_Deadlift",
    "Romanian Deadlift": "Romanian_Deadlift",
    "Hip Thrust": "Barbell_Hip_Thrust",
    "Barbell Military Press": "Standing_Military_Press",
    "Smith Military Press": "Smith_Machine_Overhead_Shoulder_Press",
    "Seated DB Press": "Seated_Dumbbell_Press",
    "DB Shoulder Press": "Seated_Dumbbell_Press",
    "Arnold Press": "Arnold_Dumbbell_Press",
    "Lateral Raises": "Side_Lateral_Raise",
    "Machine Lateral Raises": "Side_Lateral_Raise",
    "Plate Front Raises": "Front_Plate_Raise",
    "Standing Rear Delts": "Reverse_Flyes",
    "DB Rear Delts": "Reverse_Flyes",
    "Cable Rear Delts": "Face_Pull",
    "Upright Row": "Upright_Barbell_Row",
    "Straight Bar Curl": "Barbell_Curl",
    "Barbell Curl": "Barbell_Curl",
    "EZ Bar Curl": "EZ-Bar_Curl",
    "EZ Bar Preacher Curl": "Preacher_Curl",
    "Alternate DB Curl": "Alternate_Incline_Dumbbell_Curl",
    "Simultaneous DB Curl": "Dumbbell_Bicep_Curl",
    "Hammer Curl": "Hammer_Curls",
    "Alternate Hammer Curl": "Hammer_Curls",
    "Cable Curl": "Standing_Biceps_Cable_Curl",
    "Incline DB Curl": "Incline_Dumbbell_Curl",
    "Reverse Curl": "Reverse_Barbell_Curl",
    "DB Curl": "Dumbbell_Bicep_Curl",
    "EZ Bar Skull Crushers": "EZ-Bar_Skullcrusher",
    "Skull Crushers": "EZ-Bar_Skullcrusher",
    "DB Skull Crushers": "Lying_Triceps_Press",
    "Rope Pushdown": "Triceps_Pushdown",
    "Triceps Pushdown": "Triceps_Pushdown",
    "Reverse Pushdown": "Reverse_Grip_Triceps_Pushdown",
    "Parallel Bar Dips": "Dips_-_Triceps_Version",
    "Overhead Extension": "Standing_Dumbbell_Triceps_Extension",
    "Triceps Kickback": "Tricep_Dumbbell_Kickback",
    "Squat": "Barbell_Squat",
    "Leg Press": "Leg_Press",
    "Leg Extensions": "Leg_Extensions",
    "Lying Leg Curl": "Lying_Leg_Curls",
    "Seated Leg Curl": "Seated_Leg_Curl",
    "Lunges": "Bodyweight_Walking_Lunge",
    "DB Lunges": "Dumbbell_Lunges",
    "Barbell Lunges": "Barbell_Walking_Lunge",
    "Standing Calf Raise": "Standing_Barbell_Calf_Raise",
    "Seated Calf Raise": "Seated_Calf_Raise",
    # Recomp routine. Slugs reused from the existing bundle so no new assets
    # are needed, except Barbell_Hip_Thrust and Full_Range-Of-Motion_Lat_Pulldown
    # (mapped above), which postdate the release tarball and are fetched
    # per-file from upstream by `asset_manager`. Bulgarian Split Squat has no
    # match at all in the source catalogue and deliberately renders without an
    # image — a photo of a different movement would be worse than none.
    "Dips": "Dips_-_Triceps_Version",
    "Face Pull": "Face_Pull",
    "Cable Lateral Raises": "Side_Lateral_Raise",
    "Incline Barbell Bench Press": "Smith_Machine_Incline_Bench_Press",
    "Calf Press": "Calf_Press",
    "Cable Crunch": "Cable_Crunch",
    "Hanging Abs": "Hanging_Leg_Raise",
    "Floor Crunch": "Crunches",
    "Floor Obliques": "Oblique_Crunches",
    "Plank": "Plank",
    "Leg Raises": "Hanging_Leg_Raise",
    "Hyperextensions": "Hyperextensions_Back_Extensions",
    "Abs Triset": "Crunches",
    "Treadmill": "Jogging_Treadmill",
    "Bike": "Bicycling_Stationary",
    "Elliptical": "Elliptical_Trainer",
    "HIIT Intervals": "Air_Bike",
}


def required_slugs() -> tuple[str, ...]:
    """Every distinct slug the catalog needs, sorted.

    Single source of truth for "what must be installed". `asset_manager`, the
    bundle-building script and the tests all ask this instead of each keeping
    their own set comprehension over `EXERCISE_IMAGE.values()` — three copies
    of that is how a slug ends up required by one and unknown to another.
    """
    return tuple(sorted({s for s in EXERCISE_IMAGE.values() if s}))


def image_for(key: str) -> str | None:
    """Return an assets-relative path to the first frame, or None.

    Assets-relative — `/exercises/<slug>/0.jpg` — and not `file://`: Flet
    serves `assets/` over HTTP in web mode, and a `file://` URL is rejected
    outright by the browser ("Not allowed to load local resource").
    """
    slug = EXERCISE_IMAGE.get(key)
    if not slug:
        return None
    from asset_manager import image_path

    return f"/exercises/{slug}/0.jpg" if image_path(slug, 0) else None


def image_frames(key: str) -> tuple[str, str] | None:
    """Return (frame0, frame1) assets-relative paths for animation, or None."""
    slug = EXERCISE_IMAGE.get(key)
    if not slug:
        return None
    from asset_manager import image_path

    if not image_path(slug, 0):
        return None
    # Frame 1 is optional: it can be absent when a slug was repaired from
    # upstream and only the first frame came through. Falling back to frame 0
    # shows a still instead of a hole.
    segundo = 1 if image_path(slug, 1) else 0
    return f"/exercises/{slug}/0.jpg", f"/exercises/{slug}/{segundo}.jpg"


# ── delivery: URL where it works, inline bytes where it does not ──────────


def url_is_served() -> bool:
    """True when an `/exercises/...` URL can actually resolve to the frames.

    It can when the download directory lives under the `assets/` folder Flet
    was handed (`ft.app(assets_dir="assets")`), which is the case whenever the
    process runs from the project directory: web mode and desktop. A packaged
    APK sets `FLET_APP_STORAGE_DATA` to private app storage, far away from the
    bundle, and then the URL resolves to nothing at all.

    Deliberately derived from the paths rather than from `page.platform`: the
    thing that breaks is the path relationship, so that is what gets asked.
    """
    from asset_manager import _data_dir

    try:
        return _data_dir().resolve().is_relative_to((Path.cwd() / "assets").resolve())
    except (OSError, ValueError):  # pragma: no cover - unresolvable path
        return False


#: Bounded on purpose. Browse paints a grid of ~100 thumbnails, and holding
#: every frame's base64 would be ~9 MB of strings pinned for the life of the
#: process on the device with the least memory to spare. 48 entries covers the
#: longest training day several times over and costs about 2 MB.
@lru_cache(maxsize=48)
def _inline(path_text: str) -> str | None:
    """A frame as base64, or None if it cannot be read.

    Cached by path text rather than `Path` so equal paths hit the same entry.
    Returns None instead of raising: a corrupt or half-written frame must cost
    one blank photo, never the whole training screen.
    """
    try:
        return base64.b64encode(Path(path_text).read_bytes()).decode("ascii")
    except OSError:
        return None


def _slug_de(key: str) -> str:
    """El slug de un ejercicio: primero la tabla de casa, luego el catálogo.

    `EXERCISE_IMAGE` sigue mandando — es la que decide qué foto le corresponde
    a cada nombre de la app. El respaldo existe para los movimientos que solo
    conoce `catalogo.py`, que son los que Alex puede añadir a mitad de sesión y
    que esta tabla nunca va a nombrar: son 875 y ella tiene 87.
    """
    directo = EXERCISE_IMAGE.get(key)
    if directo:
        return directo
    try:
        import catalogo

        e = catalogo.por_nombre(key)
        return e.slug if e else ""
    except Exception:
        return ""


def image_props(key: str, frame: int = 0) -> dict:
    """Kwargs for `ft.Image` that render `key` on every platform.

    Returns `{}` when there is no image, so callers branch on truthiness:

        props = image_props(name)
        if props:
            ft.Image(**props, fit=ft.ImageFit.COVER, ...)

    Never returns a `src` the platform cannot load — that was the old bug, and
    it was invisible because `ft.Image` renders an empty box rather than
    complaining.
    """
    slug = _slug_de(key)
    if not slug:
        return {}
    from asset_manager import image_path

    path = image_path(slug, frame) or image_path(slug, 0)
    if path is None:
        return {}
    if url_is_served():
        return {"src": f"/exercises/{slug}/{path.stem}.jpg"}
    data = _inline(str(path))
    return {"src_base64": data} if data else {}


def image_frames_props(key: str) -> tuple[dict, dict] | None:
    """`(frame0, frame1)` as `ft.Image` kwargs, or None when there is no image.

    The animated counterpart of `image_props`. Frame 1 is optional — a slug
    repaired from upstream can arrive with only frame 0 — and then both entries
    are the same frame, so the caller animates a still instead of blinking to a
    hole every 700 ms.
    """
    first = image_props(key, 0)
    if not first:
        return None
    return first, (image_props(key, 1) or first)


def apply_image_props(image, props: dict) -> None:
    """Point an existing `ft.Image` at a different frame.

    Both delivery keys are written every time, one of them to None. The
    alternative — setting only the key in use — leaves the previous frame's
    `src_base64` sitting on the control underneath the new `src`, and Flet then
    renders whichever it happens to prefer. That would look like an animation
    that plays once and freezes, which is a far harder bug to read than a
    missing photo.
    """
    image.src = props.get("src")
    image.src_base64 = props.get("src_base64")


def clear_inline_cache() -> None:
    """Drop the base64 cache — call after a download replaces frames on disk."""
    _inline.cache_clear()
