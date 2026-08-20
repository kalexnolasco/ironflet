"""Training analytics — pure functions over stored workouts and weigh-ins.

Nothing here imports Flet, opens a database or touches the filesystem. Every
function takes plain data and returns plain data, so it unit-tests without a
running app and can be reused by the Telegram coach in ../agente/.

This module is the single implementation of every metric it defines.
`storage.py` delegates: `Storage.get_week_stats()` calls `session_count()`,
`working_sets()` and `total_volume()`, and `Storage.get_streak()` calls
`training_streak()`. Those methods only fetch rows and supply arguments — the
streak minimum, for one, which storage derives from the active routine. There
is no second copy to keep in sync; fix a metric here and the whole app,
Telegram coach included, gets the fix.

Two definitions replaced weaker ones and are worth knowing before reading on:

* `training_streak()` counts consecutive *weeks* that hit a session minimum.
  The streak used to be consecutive calendar *days*, which any routine with
  rest days breaks every weekend by design.
* `session_count()` counts distinct training *days*. It used to be a count of
  table rows, and there is one row per exercise, so a six-exercise session
  reported as six sessions.

Both are spelled out at their definitions.

Input shapes accepted everywhere:

* an *entry* is a `storage.WorkoutEntry` or the equivalent dict from
  `Storage.export_all()["workouts"]` — `date`, `exercise`, `sets`.
* a *set* is `{"weight": float, "reps": int}` plus optional `"rir"` and
  optional `"type"` (see `is_warmup`).
* a *weigh-in* is `{"date": iso, "kg": float}`, as `Storage.get_weights()`
  returns it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────
# coercion helpers
#
# Data reaches these functions from three writers (this app, the Telegram
# coach, restored backups) so nothing is assumed to be well-typed.
# ─────────────────────────────────────────────────────────────────────────


def _num(value: Any) -> float | None:
    """Best-effort float. None for anything that is not a real number.

    `bool` is rejected explicitly: it subclasses `int`, so a stray True would
    otherwise be read as 1 kg.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    """ISO string or date → date. None when unparseable."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _field(entry: Any, name: str, default: Any = None) -> Any:
    """Read `name` off a dataclass entry or a dict entry."""
    if isinstance(entry, dict):
        return entry.get(name, default)
    return getattr(entry, name, default)


def _entry_date(entry: Any) -> date | None:
    return _as_date(_field(entry, "date"))


def _entry_sets(entry: Any) -> list[dict]:
    raw = _field(entry, "sets") or []
    return [s for s in raw if isinstance(s, dict)]


def _monday(d: date) -> date:
    """Monday of the week `d` falls in. Weeks are ISO: Monday to Sunday."""
    return d - timedelta(days=d.weekday())


def week_key(d: date) -> str:
    """Sortable ISO week label, e.g. `2026-W33`.

    Built from `isocalendar()`, not from the calendar year: the Monday of a
    week straddling New Year belongs to the ISO year of the week, and using
    `d.year` there would file it under the wrong label.
    """
    iso = _monday(d).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ─────────────────────────────────────────────────────────────────────────
# set types and volume
# ─────────────────────────────────────────────────────────────────────────

#: Values of `set["type"]` that mean "this set does not count as work".
#: The set-type feature writes `"warmup"`; the spellings are here because the
#: Telegram coach and hand-edited backups are not guaranteed to agree.
WARMUP_TYPES = frozenset({"warmup", "warm_up", "warm-up", "warm up"})


def is_warmup(one_set: dict) -> bool:
    """True when a set is flagged as a warm-up.

    Only warm-ups are excluded from volume and PRs. Every other type
    (straight, drop set, failure, myo-reps…) is real work, and a set with no
    `"type"` at all — which is every set written before the set-type feature
    existed — counts as work. Anything else would silently rewrite history.
    """
    raw = one_set.get("type")
    if raw is None:
        return False
    return str(raw).strip().lower() in WARMUP_TYPES


def working_sets(sets: Iterable[dict]) -> list[dict]:
    """The sets that count: warm-ups dropped, non-dict junk dropped."""
    return [s for s in sets or [] if isinstance(s, dict) and not is_warmup(s)]


def volume(sets: Iterable[dict]) -> float:
    """Tonnage of one exercise: sum of weight × reps over working sets.

    Bodyweight sets logged at 0 kg contribute 0. That is a known limitation of
    load × reps volume, not a bug to patch here.
    """
    total = 0.0
    for s in working_sets(sets):
        w, r = _num(s.get("weight")), _num(s.get("reps"))
        if w is not None and r is not None and w > 0 and r > 0:
            total += w * r
    return round(total, 2)


def total_volume(entries: Iterable[Any]) -> float:
    """Tonnage across many entries."""
    return round(sum(volume(_entry_sets(e)) for e in entries), 2)


# ─────────────────────────────────────────────────────────────────────────
# estimated 1RM
# ─────────────────────────────────────────────────────────────────────────


def estimated_1rm(weight: Any, reps: Any) -> float | None:
    """Epley estimated one-rep max: `weight × (1 + reps / 30)`.

    Returns None below 1 rep, and for a non-positive load: a "0 kg max" is not
    a strength number, it is a bodyweight set, and letting it through would
    park a 0.0 at the top of every PR comparison.

    reps == 1 short-circuits to the weight itself. Epley does not reduce to
    `weight` at one rep — it returns 1.0333 × weight — so a genuine single
    would otherwise be reported as 3.3% heavier than what was actually
    lifted, and would beat itself as a "PR" on re-entry.

    Accuracy caveat: Epley is fitted to low rep ranges and drifts optimistic
    past ~12 reps. The value is still returned; treat high-rep estimates as
    trend material, not as a number to load on a bar.
    """
    w, r = _num(weight), _num(reps)
    if w is None or r is None or w <= 0 or r < 1:
        return None
    if r == 1:
        return round(w, 2)
    return round(w * (1 + r / 30.0), 2)


def best_e1rm(sets: Iterable[dict]) -> float | None:
    """Highest estimated 1RM among the working sets. None if there is none."""
    values = [
        e
        for s in working_sets(sets)
        if (e := estimated_1rm(s.get("weight"), s.get("reps"))) is not None
    ]
    return max(values) if values else None


def e1rm_progression(entries: Iterable[Any], exercise: str | None = None) -> list[dict]:
    """Best estimated 1RM per session date, oldest first — the trend line.

    One point per *date*, not per row: an exercise logged twice in a day
    collapses to that day's best, so the chart has no vertical pairs.
    """
    per_day: dict[date, float] = {}
    for e in entries:
        if exercise is not None and _field(e, "exercise") != exercise:
            continue
        d = _entry_date(e)
        best = best_e1rm(_entry_sets(e))
        if d is None or best is None:
            continue
        if best > per_day.get(d, 0.0):
            per_day[d] = best
    return [{"date": d.isoformat(), "e1rm": v} for d, v in sorted(per_day.items())]


# ─────────────────────────────────────────────────────────────────────────
# personal records
# ─────────────────────────────────────────────────────────────────────────


class PRKind(str, Enum):
    """The three records Hevy tracks, and the three tracked here.

    `str` mixin so the value serialises straight into JSON and prefs without
    a converter.
    """

    E1RM = "e1rm"
    MAX_WEIGHT = "max_weight"
    SESSION_VOLUME = "session_volume"


#: UI labels. Kept next to the enum so a new kind cannot be added without one.
PR_LABELS: dict[PRKind, str] = {
    PRKind.E1RM: "Estimated 1RM",
    PRKind.MAX_WEIGHT: "Heaviest weight",
    PRKind.SESSION_VOLUME: "Best session volume",
}


@dataclass(frozen=True)
class Record:
    """One record: what kind, how much, when, and the set that produced it.

    `weight`/`reps` are the set behind the number; they are None for
    SESSION_VOLUME, which is a property of a whole session rather than a set.
    """

    kind: PRKind
    exercise: str
    value: float
    date: str
    weight: float | None = None
    reps: int | None = None

    @property
    def label(self) -> str:
        return PR_LABELS[self.kind]


@dataclass(frozen=True)
class PersonalRecords:
    """The three PRs for one exercise. Any of them is None with no data."""

    exercise: str
    e1rm: Record | None = None
    max_weight: Record | None = None
    session_volume: Record | None = None

    def get(self, kind: PRKind) -> Record | None:
        return {
            PRKind.E1RM: self.e1rm,
            PRKind.MAX_WEIGHT: self.max_weight,
            PRKind.SESSION_VOLUME: self.session_volume,
        }[kind]

    def all(self) -> list[Record]:
        """The records that exist, in a stable order, for rendering."""
        return [r for r in (self.e1rm, self.max_weight, self.session_volume) if r is not None]


def personal_records(entries: Iterable[Any], exercise: str) -> PersonalRecords:
    """Best e1RM, heaviest weight and best session volume for one exercise.

    Warm-up sets are excluded from all three: a warm-up cannot set a record.

    Session volume is summed per *date*, so an exercise logged across several
    rows on the same day is one session, not several.
    """
    best_e: Record | None = None
    best_w: Record | None = None
    per_day_volume: dict[date, float] = {}

    for e in entries:
        if _field(e, "exercise") != exercise:
            continue
        d = _entry_date(e)
        if d is None:
            continue
        iso = d.isoformat()
        per_day_volume[d] = per_day_volume.get(d, 0.0) + volume(_entry_sets(e))

        for s in working_sets(_entry_sets(e)):
            w, r = _num(s.get("weight")), _num(s.get("reps"))
            est = estimated_1rm(w, r)
            if est is not None and (best_e is None or est > best_e.value):
                best_e = Record(PRKind.E1RM, exercise, est, iso, w, int(r) if r else None)
            # Heaviest weight is judged on load alone, but it still has to be
            # a set that happened: 100 kg logged with 0 reps was not lifted.
            performed = w is not None and r is not None and w > 0 and r >= 1
            if performed and (best_w is None or w > best_w.value):
                best_w = Record(PRKind.MAX_WEIGHT, exercise, w, iso, w, int(r))

    best_v: Record | None = None
    for d, vol in sorted(per_day_volume.items()):
        if vol > 0 and (best_v is None or vol > best_v.value):
            best_v = Record(PRKind.SESSION_VOLUME, exercise, round(vol, 2), d.isoformat())

    return PersonalRecords(exercise, best_e, best_w, best_v)


def all_personal_records(entries: Iterable[Any]) -> dict[str, PersonalRecords]:
    """PRs for every exercise present, keyed by exercise."""
    rows = list(entries)
    names = {n for e in rows if (n := _field(e, "exercise"))}
    return {n: personal_records(rows, n) for n in sorted(names)}


def detect_new_records(history: Iterable[Any], entry: Any) -> list[Record]:
    """Which of the three records `entry` beats, given everything before it.

    `history` must be the entries *preceding* `entry` — this does not filter
    by date, so passing a list that already contains `entry` yields nothing
    (a value never strictly beats itself).

    Ties are not records: the comparison is strictly greater. Matching a
    previous best is a good session, and calling it a PR every week is how a
    PR badge stops meaning anything.

    With empty history any real work sets all three — the first log of an
    exercise is, correctly, its own PR.

    If one session is split across several rows, merge them into one entry
    before calling: session volume is computed from `entry` alone.
    """
    exercise = _field(entry, "exercise")
    d = _entry_date(entry)
    if not exercise or d is None:
        return []

    previous = personal_records([e for e in history if _field(e, "exercise") == exercise], exercise)
    candidate = personal_records([entry], exercise)

    out: list[Record] = []
    for kind in (PRKind.E1RM, PRKind.MAX_WEIGHT, PRKind.SESSION_VOLUME):
        new, old = candidate.get(kind), previous.get(kind)
        if new is not None and (old is None or new.value > old.value):
            out.append(new)
    return out


# ─────────────────────────────────────────────────────────────────────────
# sets per muscle group
# ─────────────────────────────────────────────────────────────────────────

#: Fine-grained muscle names → the app's eight display buckets.
#: The target vocabulary mirrors `data.MUSCLE_GROUPS`; `data` is not imported
#: because it pulls the whole routine catalogue into a pure module. If that
#: list changes, this mapping has to follow.
#: `forearms` folds into Biceps because the display vocabulary has no arm
#: bucket of its own.
COARSE_MUSCLE: dict[str, str] = {
    "abdominals": "Abs",
    "biceps": "Biceps",
    "forearms": "Biceps",
    "calves": "Leg",
    "quadriceps": "Leg",
    "hamstrings": "Leg",
    "glutes": "Leg",
    "chest": "Chest",
    "lats": "Back",
    "middle back": "Back",
    "lower back": "Back",
    "traps": "Back",
    "shoulders": "Shoulder",
    "triceps": "Triceps",
}

# "Bi-set: A + B", "SS: A + B", "Triset: A + B + C" — the routine's own
# notation for paired work. See `resolve_muscles`.
_COMBO_PREFIX_RE = re.compile(r"^\s*(?:bi-?set|superset|ss|tri-?set)\s*:\s*", re.IGNORECASE)


@dataclass(frozen=True)
class MuscleResolution:
    """What muscles an exercise key maps to, and how confident that mapping is.

    `status` is one of:

    * `exact`   — the key has its own entry in the exercise database.
    * `partial` — a combination entry where only some components resolved.
                  The muscles listed are real but *incomplete*; whatever is
                  in `unresolved` is missing from the count.
    * `unknown` — nothing resolved. The key contributes no muscle data.
    """

    primary: tuple[str, ...] = ()
    secondary: tuple[str, ...] = ()
    status: str = "unknown"
    unresolved: tuple[str, ...] = ()


def _lookup_details(key: str) -> dict | None:
    from exercise_details import details_for

    return details_for(key)


def resolve_muscles(key: str, lookup=_lookup_details) -> MuscleResolution:
    """Map an exercise key to the muscles it trains.

    `details_for()` looks the key up *through* `EXERCISE_IMAGE`, so it only
    answers for exercises that ship an image. 33 of the routine's 104 keys
    have none and return None.

    Those 33 are not random gaps: almost all are combination entries — the
    routine logs a bi-set, superset or triset as a single exercise, and the
    combined string ("SS: Squat + Lying Leg Curl") is not in the database
    even though both components are. So a failed lookup is retried on the
    components, which recovers 24 of the 33.

    In a paired set every round contains every component, so each component
    that resolves earns the entry's full set count. Duplicates across
    components are intentional: a bi-set of two chest movements really is
    double chest work.

    The remaining 9 (Hip Thrust, Bulgarian Split Squat and seven combinations
    written too tersely to split, e.g. "Triset: Front + Lateral + Rear Delts")
    come back as `unknown` rather than being dropped, so the caller can show
    what is missing instead of quietly under-reporting leg and shoulder work.

    `lookup` is injectable so this is testable without the 79k-line details
    table.
    """
    direct = lookup(key)
    if direct:
        return MuscleResolution(
            tuple(direct.get("primary") or ()),
            tuple(direct.get("secondary") or ()),
            "exact",
        )

    body = _COMBO_PREFIX_RE.sub("", key or "")
    parts = [p.strip() for p in body.split("+") if p.strip()]
    if len(parts) < 2 and body.strip() == (key or "").strip():
        # Not a combination at all — a plain key the database does not know.
        return MuscleResolution(status="unknown", unresolved=(key,))

    primary: list[str] = []
    secondary: list[str] = []
    missing: list[str] = []
    for part in parts:
        d = lookup(part)
        if not d:
            missing.append(part)
            continue
        primary.extend(d.get("primary") or ())
        secondary.extend(d.get("secondary") or ())

    if not primary and not secondary:
        return MuscleResolution(status="unknown", unresolved=tuple(missing or [key]))
    status = "partial" if missing else "exact"
    return MuscleResolution(tuple(primary), tuple(secondary), status, tuple(missing))


@dataclass(frozen=True)
class MuscleVolume:
    """Weekly sets per muscle, plus an honest account of what didn't map.

    `by_week` is week label → muscle → sets, and every requested week is
    present even when empty, so a chart has no gaps to special-case.
    """

    weeks: tuple[str, ...]
    by_week: dict[str, dict[str, float]]
    totals: dict[str, float]
    #: exercise key → working sets that mapped to no muscle at all.
    unattributed: dict[str, int]
    #: exercise key → the components of a combination that failed to resolve.
    #: These weeks *are* counted, but under-counted.
    partial: dict[str, tuple[str, ...]]

    @property
    def unattributed_sets(self) -> int:
        """Total sets missing from `by_week`. Show it, don't hide it."""
        return sum(self.unattributed.values())


def sets_per_muscle_group(
    entries: Iterable[Any],
    weeks: int = 8,
    *,
    today: date | None = None,
    secondary_weight: float = 0.5,
    coarse: bool = False,
) -> MuscleVolume:
    """Working sets per muscle group per week — the volume/growth metric.

    Weeks are ISO (Monday–Sunday) and the window ends with the week `today`
    falls in, so the current, partly-finished week is always the last bucket.

    A set counts 1.0 for each primary muscle of the exercise and
    `secondary_weight` for each secondary one. Half credit for secondaries is
    the usual convention for hypertrophy bookkeeping — an incline press is
    real triceps work, but it is not a triceps set. Pass
    `secondary_weight=0.0` for strict direct-set counting.

    `coarse=True` folds the database's fine-grained names (lats, middle back,
    quadriceps…) into the app's eight display buckets via `COARSE_MUSCLE`.

    Exercises the database cannot map are reported in `unattributed` rather
    than dropped — see `resolve_muscles`.
    """
    today = today or date.today()
    if weeks < 1:
        weeks = 1
    mondays = [_monday(today) - timedelta(days=7 * i) for i in range(weeks - 1, -1, -1)]
    labels = [week_key(m) for m in mondays]
    in_window = dict(zip(mondays, labels, strict=True))

    by_week: dict[str, dict[str, float]] = {label: {} for label in labels}
    unattributed: dict[str, int] = {}
    partial: dict[str, tuple[str, ...]] = {}

    for e in entries:
        d = _entry_date(e)
        if d is None:
            continue
        label = in_window.get(_monday(d))
        if label is None:
            continue
        n = len(working_sets(_entry_sets(e)))
        if n == 0:
            continue  # an all-warm-up row is not volume, and not a gap either

        key = _field(e, "exercise") or ""
        res = resolve_muscles(key)
        if res.status == "unknown":
            unattributed[key] = unattributed.get(key, 0) + n
            continue
        if res.status == "partial":
            partial[key] = res.unresolved

        bucket = by_week[label]
        for muscles, credit in ((res.primary, float(n)), (res.secondary, n * secondary_weight)):
            if credit == 0:
                # secondary_weight=0 means "don't count these at all", so the
                # muscle must not appear as a 0.0 — an empty bar in a chart
                # and a phantom row in a legend.
                continue
            for muscle in muscles:
                name = COARSE_MUSCLE.get(muscle, muscle) if coarse else muscle
                bucket[name] = bucket.get(name, 0.0) + credit

    totals: dict[str, float] = {}
    for label in labels:
        by_week[label] = {m: round(v, 2) for m, v in sorted(by_week[label].items())}
        for m, v in by_week[label].items():
            totals[m] = round(totals.get(m, 0.0) + v, 2)

    return MuscleVolume(tuple(labels), by_week, totals, unattributed, partial)


# ─────────────────────────────────────────────────────────────────────────
# adherence
# ─────────────────────────────────────────────────────────────────────────


def session_count(entries: Iterable[Any]) -> int:
    """Number of distinct training days.

    `Storage.get_week_stats()` returns `len(rows)` for this, but `entrenos`
    holds one row per exercise, so a normal six-exercise session is reported
    on the home screen as six "Sessions". Counting distinct dates is what the
    label has always claimed to mean.
    """
    return len({d for e in entries if (d := _entry_date(e)) is not None})


def training_streak(
    dates: Iterable[Any],
    *,
    min_sessions: int = 4,
    today: date | None = None,
) -> int:
    """Consecutive weeks meeting a session minimum. **Weeks, not days.**

    This is a deliberate change of meaning from the streak this app used to
    show, which counted consecutive calendar days with any entry, walking back
    from today. That definition cannot work here:

    * every routine has rest days, so the day-streak resets every single
      weekend, by design, forever;
    * it starts the walk at today, so on any rest day — including every
      Saturday and Sunday — it returns 0. Home renders that as a big 🔥 0
      next to a perfectly adherent week.

    Weekly adherence is what a streak is actually trying to say. A week counts
    when it contains at least `min_sessions` distinct training days.

    The minimum belongs to the caller, because it depends on the routine being
    followed and this module deliberately knows nothing about routines: a
    3-day-a-week plan graded against 4 sessions can never start a streak.
    `Storage.get_streak()` derives it from the active routine (see
    `storage.weekly_session_minimum`). The default of 4 is only a fallback for
    callers that pass nothing.

    The current week is graded gently: it counts once it has already hit the
    minimum, and is otherwise *skipped* rather than treated as a failure,
    because it has not finished yet. Without this, every streak would read 0
    until Thursday and the day-based bug would simply come back weekly.

    Returns the number of consecutive qualifying weeks, ending at the most
    recent one.
    """
    today = today or date.today()
    per_week: dict[date, set[date]] = {}
    for value in dates:
        d = _as_date(value)
        if d is None or d > today:  # future-dated rows are not sessions done
            continue
        per_week.setdefault(_monday(d), set()).add(d)

    def qualifies(monday: date) -> bool:
        return len(per_week.get(monday, ())) >= min_sessions

    current = _monday(today)
    streak = 1 if qualifies(current) else 0

    monday = current - timedelta(days=7)
    while qualifies(monday):
        streak += 1
        monday -= timedelta(days=7)
    return streak


def week_stats(entries: Iterable[Any], *, days: int = 7, today: date | None = None) -> dict:
    """Sessions / sets / volume over a trailing window.

    The corrected replacement for `Storage.get_week_stats()`: sessions are
    distinct days (see `session_count`) and volume skips warm-ups.
    """
    today = today or date.today()
    since = today - timedelta(days=days)
    rows = []
    for e in entries:
        d = _entry_date(e)
        if d is not None and since <= d <= today:
            rows.append(e)
    return {
        "sessions": session_count(rows),
        "sets": sum(len(working_sets(_entry_sets(e))) for e in rows),
        "volume": total_volume(rows),
    }


# ─────────────────────────────────────────────────────────────────────────
# bodyweight trend
# ─────────────────────────────────────────────────────────────────────────


def moving_average(weights: Iterable[Any], days: int = 7) -> list[dict]:
    """Rolling bodyweight average — the line you actually read for trend.

    Day-to-day scale readings swing a kilo on water and gut content, which is
    several times the ±0.3 kg/week this plan is steering by. The average is
    what the adjustment rules in ../plan_recomposicion.md are meant to be read
    against.

    The window is `days` **calendar** days, not `days` samples: each point
    averages every weigh-in in `[d - days + 1, d]`. With irregular logging a
    sample-based window would silently average across a month and call it a
    week.

    Returns the same `{"date", "kg"}` shape as `Storage.get_weights()`, one
    point per weigh-in date, oldest first, so it can be dropped into a chart
    wherever the raw series is used today. Same-day duplicates collapse to
    their mean before averaging.
    """
    per_day: dict[date, list[float]] = {}
    for w in weights or []:
        if isinstance(w, (tuple, list)) and len(w) == 2:
            d, kg = _as_date(w[0]), _num(w[1])
        else:
            d, kg = _as_date(_field(w, "date")), _num(_field(w, "kg"))
        if d is not None and kg is not None:
            per_day.setdefault(d, []).append(kg)

    series = sorted((d, sum(v) / len(v)) for d, v in per_day.items())
    if days < 1:
        days = 1

    out: list[dict] = []
    for i, (d, _) in enumerate(series):
        floor = d - timedelta(days=days - 1)
        # Walk back from the current point: the series is short (a weigh-in a
        # day at most) so this stays cheap and needs no deque bookkeeping.
        window = [kg for other, kg in series[: i + 1] if other >= floor]
        out.append({"date": d.isoformat(), "kg": round(sum(window) / len(window), 2)})
    return out


#: A week of daily weigh-ins is not enough to read a rate through ±1 kg of
#: water noise. Two are. Below this the rate is `None` rather than a number
#: nobody should act on.
MIN_TREND_DAYS = 14


def weight_trend(
    weights: Iterable[Any], days: int = 7, min_days: int = MIN_TREND_DAYS
) -> tuple[float | None, float | None]:
    """`(rolling average now, kg per week)` — either may be `None`.

    **The number the whole plan steers by.** `../plan_recomposicion.md` targets
    +0.2 kg/week and adjusts calories at ±0.3, which is well inside the kilo the
    scale swings on water and gut content, so the rate has to be read off
    `moving_average` and never off two raw weigh-ins.

    It lives here because it was previously implemented three times: as a
    private method on `ProfileView` (unimportable from anywhere else), a second,
    divergent copy inside the in-app coach, and Home was about to be the third.
    Three answers to one question, on three screens, none of them wrong-looking.

    `None` for the rate means "not enough span to say", which is a different
    statement from "no change" and is rendered differently everywhere.
    """
    series = moving_average(weights, days=days)
    if not series:
        return None, None

    newest = series[-1]
    average = newest["kg"]

    end = _as_date(newest["date"])
    start = _as_date(series[0]["date"])
    if end is None or start is None or (end - start).days < min_days:
        return average, None

    # The averaged point nearest a week back, not the raw weigh-in that day:
    # comparing an average against a single reading puts back exactly the noise
    # the average exists to take out.
    target = end - timedelta(days=7)
    previous = min(series, key=lambda p: abs(((_as_date(p["date"]) or end) - target).days))
    span = (end - (_as_date(previous["date"]) or end)).days
    if span <= 0:
        return average, None
    return average, (average - previous["kg"]) / span * 7


#: The plan measures the tape every two weeks, on a Sunday
#: (`../plan_recomposicion.md` §5). Past this, the number on screen is stale
#: enough that its age matters more than its value.
MEASUREMENT_EVERY_DAYS = 14

#: The ceiling the plan treats as "cut 150 kcal". A one-way limit: there is no
#: documented rule for a waist that shrinks.
WAIST_LIMIT_CM = 1.0


@dataclass(frozen=True)
class WaistSummary:
    """Waist, its age, and BOTH readings of the plan's rule — never a verdict.

    ## Why there is no verdict

    `../plan_recomposicion.md` states the waist rule twice and the two do not
    agree:

    * §goal: *"cintura como freno: si sube más de ~1 cm **respecto a la medición
      inicial**"* — cumulative drift from the plan's baseline.
    * §rules: *"revisión cada 2 semanas ... o cintura +1 cm"* — the fortnightly
      window, this measurement against the one before.

    On a lean bulk that is working those give materially different answers, and
    nothing in the repo picks one. So this returns `vs_baseline` **and**
    `vs_previous`, labelled, and the screen shows both. Silently choosing would
    make this the first place in the system where an ambiguous rule became a
    number Alex acts on.

    ## Why there is no trend

    Tape noise is roughly ±0.5 cm — half the trigger. Two fortnightly points are
    a line segment, not a trend, and interpolating between them invents 13
    measurements nobody took. `count` is exposed so a caller can refuse to draw
    anything until there are three.
    """

    count: int = 0
    latest: float | None = None
    on: date | None = None
    days_ago: int | None = None
    baseline: float | None = None
    baseline_on: date | None = None
    vs_baseline: float | None = None
    previous: float | None = None
    previous_on: date | None = None
    vs_previous: float | None = None

    @property
    def known(self) -> bool:
        return self.latest is not None

    @property
    def due(self) -> bool:
        """Is a fresh measurement owed? True when there has never been one.

        Nothing in the coach nudges for measurements — `plan.AVISOS_FIJOS` seeds
        five reminders and none of them is the fortnightly tape. So whatever
        renders this is the only thing in the system that will ever say so.
        """
        return self.days_ago is None or self.days_ago >= MEASUREMENT_EVERY_DAYS

    @property
    def headroom(self) -> float | None:
        """Centimetres left before the baseline reading of the rule trips.

        Uses `vs_baseline` because that is the wording in the goal section, and
        it is the more conservative of the two. Negative means already over.
        """
        if self.vs_baseline is None:
            return None
        return WAIST_LIMIT_CM - self.vs_baseline


def waist_summary(measurements: Iterable[Any], today: date | None = None) -> WaistSummary:
    """Build a `WaistSummary` from `Storage.get_measurements()` rows.

    Rows whose waist is empty are skipped rather than counted: a check-in that
    recorded only the chest is not a waist measurement, and treating it as one
    would make the newest waist look older than it is.
    """
    today = today or date.today()

    puntos: list[tuple[date, float]] = []
    for row in measurements or []:
        valor = _num(_field(row, "waist"))
        cuando = _as_date(_field(row, "date"))
        if valor is not None and cuando is not None:
            puntos.append((cuando, valor))
    puntos.sort()

    if not puntos:
        return WaistSummary()

    on, latest = puntos[-1]
    baseline_on, baseline = puntos[0]
    resumen = {
        "count": len(puntos),
        "latest": latest,
        "on": on,
        "days_ago": (today - on).days,
        "baseline": baseline,
        "baseline_on": baseline_on,
    }
    # A single measurement IS the baseline, so the drift against it is zero by
    # construction and saying "+0.0 cm vs baseline" would dress up "we have one
    # number" as a comparison.
    if len(puntos) >= 2:
        previous_on, previous = puntos[-2]
        resumen.update(
            {
                "vs_baseline": round(latest - baseline, 1),
                "previous": previous,
                "previous_on": previous_on,
                "vs_previous": round(latest - previous, 1),
            }
        )
    return WaistSummary(**resumen)
