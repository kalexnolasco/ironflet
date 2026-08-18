"""Auto-generated. Maps canonical English exercise name → Free Exercise DB slug.

Images live in assets/exercises/<slug>/0.jpg.
Source: github.com/yuhonas/free-exercise-db (Unlicense / public domain).
"""

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
