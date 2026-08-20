"""The backup is the only bridge between the phone and the desktop.

`Storage.export_all()` covers four of the fourteen tables, so a restore used to
land with the food diary and every user-written routine missing — silently, and
reported as a success. `backup.py` is the complete one; this suite is what says
so.

Everything here runs against **SQLite** (a file under pytest's `tmp_path`), not
the shared PostgreSQL test database. Two reasons, both deliberate:

* SQLite is what the Android build actually uses, so these tests exercise the
  engine the backup exists to feed;
* they need no `DATABASE_URL` and no container, so they run everywhere,
  including CI without services. A backup test that skips is a backup test that
  never caught anything.

The five cases the design has to survive are, in order:
`test_round_trip_loses_nothing`, `test_version_2_backup_still_imports`,
`test_merge_into_a_database_that_already_has_routines`,
`test_truncated_file_fails_cleanly` and
`test_failure_midway_rolls_back_the_wipe`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import backup
import data
from backup import BACKUP_VERSION, BackupError, export_all, import_all, summary_line
from nutrition import Food, FoodLogEntry, NutritionTarget, Serving
from routine_builder import (
    DraftDay,
    DraftExercise,
    DraftPhase,
    DraftRoutine,
    UserRoutine,
    UserRoutineDay,
    UserRoutineExercise,
    UserRoutinePhase,
    list_user_drafts,
    save_draft,
    user_routine_id,
)
from storage import (
    MAX_SESSION_SECONDS,
    NOTE_MAX_LEN,
    DuracionSesion,
    Entreno,
    NotaSesion,
    Perfil,
    Peso,
    Storage,
    WorkoutEntry,
)

# Whole seconds on purpose: a float timestamp survives `fromtimestamp` exactly
# only if it has no sub-microsecond tail, and the round-trip test compares two
# documents field by field.
T0 = datetime(2026, 3, 2, 7, 30, 0).astimezone()
DAY = date(2026, 3, 2)


# ── fixtures ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def keep_global_routines():
    """Undo what `sync_user_routines()` splices into `data.ROUTINES`.

    Importing a backup refreshes the stored half of that module-level list (and
    re-selects the active routine). Without restoring it, the routines invented
    here would leak into every later suite that reads `data.ROUTINES`.
    """
    snapshot = list(data.ROUTINES)
    active = data.active_routine().id
    yield
    data.ROUTINES[:] = snapshot
    data.set_active_routine(active)


def _store(tmp_path, name: str) -> Storage:
    return Storage(db_url=f"sqlite:///{tmp_path / name}.db")


@pytest.fixture
def store(tmp_path):
    """The source device."""
    return _store(tmp_path, "source")


@pytest.fixture
def other(tmp_path):
    """The target device — a second, independent database."""
    return _store(tmp_path, "target")


def _session(store: Storage):
    return sessionmaker(bind=store._engine, expire_on_commit=False)()


# ── fixture data ─────────────────────────────────────────────


def add_food(store: Storage, slug: str, name: str, *, kcal=100.0, servings=()) -> int:
    with _session(store) as s:
        food = Food(
            slug=slug,
            name=name,
            kcal=kcal,
            protein=10.0,
            fat=2.0,
            carbs=5.0,
            fiber=None,
            is_favourite=False,
            source="test",
            created=T0,
        )
        s.add(food)
        s.flush()
        for sv_name, grams in servings:
            s.add(Serving(food_id=food.id, name=sv_name, grams=grams, is_default=False))
        s.commit()
        return food.id


def add_log(store: Storage, day: date, meal: str, food_id: int | None, food_name: str, grams=100.0):
    with _session(store) as s:
        s.add(
            FoodLogEntry(
                log_date=day,
                meal=meal,
                food_id=food_id,
                food_name=food_name,
                grams=grams,
                kcal=150.0,
                protein=12.0,
                fat=3.0,
                carbs=8.0,
                fiber=1.0,
                created=T0,
            )
        )
        s.commit()


def add_target(store: Storage, starts_on: date, kcal=2400.0):
    with _session(store) as s:
        s.add(
            NutritionTarget(
                starts_on=starts_on,
                kcal=kcal,
                protein=180.0,
                fat=70.0,
                carbs=230.0,
                note="cut",
                created=T0,
            )
        )
        s.commit()


def add_weight(store: Storage, day: date, kg: float):
    with _session(store) as s:
        s.add(Peso(fecha=day, kg=kg, creado=T0))
        s.commit()


def add_routine(store: Storage, name: str, *, exercises=("Squat", "Barbell Bench Press")) -> int:
    """A two-phase routine, so the parent/child remap has something to get wrong."""
    draft = DraftRoutine(
        name=name,
        description=f"{name} description",
        phases=[
            DraftPhase(
                name="Base",
                subtitle="Volume",
                weeks="1-4",
                scheme="4×8",
                days=[
                    DraftDay(
                        name="Day 1",
                        exercises=[DraftExercise(name=e, sets=4, reps="8") for e in exercises],
                    ),
                    DraftDay(name="Day 2", exercises=[DraftExercise(name="Deadlift", sets=3)]),
                ],
            ),
            DraftPhase(
                name="Peak",
                subtitle="Intensity",
                weeks="5-8",
                scheme="5×5",
                days=[DraftDay(name="Heavy", exercises=[DraftExercise(name="Squat", sets=5)])],
            ),
        ],
    )
    return save_draft(store, draft)


def populate(store: Storage) -> dict:
    """Fill all fourteen tables. Returns the handful of ids a test may need."""
    store.set_profile("Alex", "1990-05-01", 178.0, "male", "moderate")

    store.save_workout(
        WorkoutEntry(
            date=DAY.isoformat(),
            exercise="Squat",
            muscle_group="Legs",
            phase=2,
            sets=[{"weight": 100.0, "reps": 8}, {"weight": 20.0, "reps": 10, "type": "warmup"}],
            timestamp=T0.timestamp(),
            note="Hole 4 on the backrest.",
        )
    )
    store.save_workout(
        WorkoutEntry(
            date=(DAY - timedelta(days=2)).isoformat(),
            exercise="Barbell Bench Press",
            muscle_group="Chest",
            phase=2,
            sets=[{"weight": 80.0, "reps": 5, "rir": 2}],
            timestamp=(T0 - timedelta(days=2)).timestamp(),
            # No note, like every row written before the column existed and
            # everything the Telegram coach writes.
        )
    )
    store.set_session_note("Slept 5 h, dropped the weights on purpose.", DAY)
    # One duration, for the day — not one per exercise row. The session two
    # days earlier is deliberately left untimed, which is what every row
    # logged before this existed looks like.
    store.set_session_duration(4320, DAY)

    add_weight(store, DAY, 82.4)
    add_weight(store, DAY - timedelta(days=7), 83.1)

    chicken = add_food(store, "chicken", "Chicken breast", servings=(("1 fillet", 150.0),))
    egg = add_food(store, "egg", "Egg", kcal=143.0, servings=(("1 unit", 60.0),))
    add_log(store, DAY, "lunch", chicken, "Chicken breast", grams=180.0)
    add_log(store, DAY, "breakfast", egg, "Egg", grams=120.0)
    # A row whose catalogue entry is gone: food_id NULL, name and macros frozen.
    add_log(store, DAY, "dinner", None, "Leftover paella", grams=250.0)
    add_target(store, date(2026, 1, 1))
    add_target(store, date(2026, 2, 15), kcal=2250.0)

    pk = add_routine(store, "My PPL")

    # Written last: it points at the routine above, which is the pointer the
    # import has to remap.
    store.set_pref("routine", user_routine_id(pk))
    store.set_pref("units", "kg")
    return {"routine_pk": pk, "chicken": chicken, "egg": egg}


# ── helpers ──────────────────────────────────────────────────

_METADATA = ("exported_at", "exported_at_iso", "app_version", "engine")


def comparable(doc: dict) -> dict:
    """A document stripped of everything that legitimately differs.

    Provenance metadata changes per export, and `routines[].id` is the one
    primary key in the file — it *must* change when the rows land in another
    database. What is left is the data itself.
    """

    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if k not in _METADATA}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, float):
            # Timestamps make the round trip through a float; a microsecond of
            # rounding is not data loss.
            return round(value, 3)
        return value

    out = scrub(doc)
    for routine in out.get("routines", []):
        routine.pop("id", None)
    return out


def counts_of(store: Storage) -> dict[str, int]:
    """Row counts straight off the fourteen tables, bypassing every facade."""
    models = {
        "workouts": Entreno,
        "weights": Peso,
        "session_notes": NotaSesion,
        "session_durations": DuracionSesion,
        "profile": Perfil,
        "foods": Food,
        "servings": Serving,
        "food_log": FoodLogEntry,
        "nutrition_targets": NutritionTarget,
        "routines": UserRoutine,
        "routine_phases": UserRoutinePhase,
        "routine_days": UserRoutineDay,
        "routine_exercises": UserRoutineExercise,
    }
    with _session(store) as s:
        return {name: len(list(s.scalars(select(model)))) for name, model in models.items()}


# ── 1. the round trip ────────────────────────────────────────


def test_round_trip_loses_nothing(store, other):
    """Export from a full database, import into an empty one, export again.

    The two documents must be identical once provenance and the routine pk are
    removed. This is the whole contract in one assertion: anything a table
    holds that the exporter forgets, or the importer drops, shows up as a diff.
    """
    populate(store)
    doc = export_all(store)

    import_all(other, doc)

    assert comparable(export_all(other)) == comparable(doc)


def test_round_trip_covers_all_thirteen_tables(store, other):
    """The bug this module exists for: v2 moved 4 tables and claimed success."""
    populate(store)
    import_all(other, export_all(store))

    before, after = counts_of(store), counts_of(other)
    assert before == after
    # And none of them was empty to begin with, or the equality above proves
    # nothing about the eight tables v2 forgot.
    assert all(n > 0 for n in before.values()), before


def test_counts_report_every_table(store, other):
    populate(store)
    counts = import_all(other, export_all(store))

    assert set(counts) == set(backup.TABLES)
    assert counts["workouts"] == 2
    assert counts["weights"] == 2
    assert counts["session_notes"] == 1
    assert counts["session_durations"] == 1
    assert counts["profile"] == 1
    assert counts["prefs"] == 2
    assert counts["foods"] == 2
    assert counts["servings"] == 2
    assert counts["food_log"] == 3
    assert counts["nutrition_targets"] == 2
    assert counts["routines"] == 1
    assert counts["routine_phases"] == 2
    assert counts["routine_days"] == 3
    assert counts["routine_exercises"] == 4


def test_summary_line_is_showable(store, other):
    populate(store)
    counts = import_all(other, export_all(store))

    assert summary_line(counts) == (
        "2 workouts, 2 weigh-ins, 1 session note, 1 session time, "
        "3 food entries, 2 foods, 1 routine"
    )
    assert summary_line({}) == "nothing"
    assert summary_line({"workouts": 1}) == "1 workout"
    assert summary_line({"session_notes": 4}) == "4 session notes"
    assert summary_line({"session_durations": 1}) == "1 session time"
    assert summary_line({"session_durations": 9}) == "9 session times"


def test_export_carries_provenance(store):
    populate(store)
    doc = export_all(store)

    assert doc["app"] == "ironflet"
    assert doc["version"] == BACKUP_VERSION == 5
    assert doc["engine"] == "sqlite"
    assert doc["exported_at"] > 0
    assert doc["exported_at_iso"].startswith("20")
    assert doc["app_version"]


def test_frozen_macros_and_optional_set_keys_survive(store, other):
    """Two invariants this module could quietly break on the way through."""
    populate(store)
    import_all(other, export_all(store))

    with _session(other) as s:
        entry = s.scalar(select(FoodLogEntry).where(FoodLogEntry.food_name == "Leftover paella"))
        # Frozen at insert time, and its catalogue row never existed.
        assert entry.food_id is None
        assert entry.kcal == 150.0

        squat = s.scalar(select(Entreno).where(Entreno.ejercicio == "Squat"))
        assert squat.series == [
            {"weight": 100.0, "reps": 8},
            {"weight": 20.0, "reps": 10, "type": "warmup"},
        ]
        bench = s.scalar(select(Entreno).where(Entreno.ejercicio == "Barbell Bench Press"))
        # "rir" is optional and absent on everything the bot writes; a set dict
        # must arrive exactly as it left, extra keys included.
        assert bench.series == [{"weight": 80.0, "reps": 5, "rir": 2}]

        # None means "not on the label", 0.0 means "none". Do not flatten.
        assert s.scalar(select(Food).where(Food.slug == "chicken")).fiber is None


def test_file_round_trip(store, other, tmp_path):
    populate(store)
    path = backup.export_to_file(store, tmp_path / "out" / backup.default_filename(T0.timestamp()))

    assert path.name == "ironflet-backup-20260302-0730.json"
    backup.import_from_file(other, path)

    assert counts_of(other) == counts_of(store)


# ── 2. backwards and forwards compatibility ──────────────────


def test_version_2_backup_still_imports(store, other):
    """Today's four-table format must keep working — minus what it never had."""
    populate(store)
    old_doc = store.export_all()  # the real v2 exporter, untouched
    assert old_doc["version"] == 2

    counts = import_all(other, old_doc)

    assert counts["workouts"] == 2
    assert counts["weights"] == 2
    assert counts["profile"] == 1
    # A v2 file simply has no nutrition, routines or notes. Absent, not zeroed
    # out — and absent must parse, not raise.
    assert counts["foods"] == 0
    assert counts["food_log"] == 0
    assert counts["routines"] == 0
    assert counts["session_notes"] == 0
    assert counts["session_durations"] == 0

    after = counts_of(other)
    assert after["workouts"] == 2
    assert after["foods"] == 0
    assert after["routine_exercises"] == 0
    assert other.get_profile()["name"] == "Alex"


def test_version_2_import_drops_a_dangling_routine_pref(store, other):
    """`routine = "user:9"` with no routines in the file points at nothing.

    Keeping it would silently resolve to whatever routine owns pk 9 on *this*
    device — someone else's plan on the home screen.
    """
    populate(store)
    old_doc = store.export_all()
    assert old_doc["prefs"]["routine"].startswith("user:")

    import_all(other, old_doc)

    assert other.get_pref("routine") is None
    assert other.get_pref("units") == "kg"


def test_a_version_3_file_still_imports(store, other):
    """The format before notes existed. Old files must keep working, forever.

    Built by hand rather than by an old exporter, because there is no longer one
    to call: a v3 document is exactly today's minus `session_notes`, minus
    `session_durations` and minus `workouts[].note`, and the importer must read
    it as "no notes and nothing timed", not refuse it and not raise on the
    missing keys.
    """
    populate(store)
    doc = export_all(store)
    doc["version"] = 3
    doc.pop("session_notes")
    doc.pop("session_durations")
    for workout in doc["workouts"]:
        workout.pop("note")

    counts = import_all(other, doc)

    assert counts["workouts"] == 2
    assert counts["session_notes"] == 0
    assert counts["session_durations"] == 0
    assert other.get_session_note(DAY) is None
    assert other.get_exercise_note("Squat", DAY) is None
    assert other.get_session_duration(DAY) is None
    # …and everything a v3 file did carry arrived untouched.
    assert counts_of(other)["food_log"] == 3


def test_a_version_4_file_still_imports(store, other):
    """The format before durations existed — every backup Alex has taken so far.

    A v4 document is today's minus `session_durations`. Absent parses to
    "nothing was timed", which is the truth about every one of those sessions,
    and the notes v4 *did* carry have to arrive untouched alongside.
    """
    populate(store)
    doc = export_all(store)
    doc["version"] = 4
    doc.pop("session_durations")

    counts = import_all(other, doc)

    assert counts["workouts"] == 2
    assert counts["session_notes"] == 1
    assert counts["session_durations"] == 0
    assert other.get_session_duration(DAY) is None
    assert other.get_session_note(DAY) == "Slept 5 h, dropped the weights on purpose."
    assert other.get_exercise_note("Squat", DAY) == "Hole 4 on the backrest."


def test_current_format_is_refused_by_the_old_importer(store, other):
    """An old app must refuse a newer file outright, not import half of it.

    `Storage.import_all()` is the four-table version shipped today. Pointed at a
    document from this module it has to raise on the version check — *before* its
    wipe, which it commits in a transaction of its own and could not undo.
    """
    assert BACKUP_VERSION > Storage.BACKUP_VERSION

    populate(store)
    populate(other)
    before = counts_of(other)

    with pytest.raises(ValueError, match="newer than supported"):
        other.import_all(export_all(store))

    assert counts_of(other) == before


def test_future_version_is_refused_with_a_clear_message(store):
    doc = export_all(store)
    doc["version"] = BACKUP_VERSION + 1

    with pytest.raises(BackupError, match="newer than this app supports"):
        import_all(store, doc)


def test_a_foreign_document_is_refused(store):
    with pytest.raises(BackupError, match="Not an IronFlet backup"):
        import_all(store, {"app": "strava", "version": 3})
    with pytest.raises(BackupError, match="no version number"):
        import_all(store, {"app": "ironflet"})
    with pytest.raises(BackupError, match="Not an IronFlet backup"):
        import_all(store, ["not", "an", "object"])


# ── 3. importing over a database that already has data ───────


def test_merge_into_a_database_that_already_has_routines(store, other):
    """The id-collision case, end to end.

    `other` already owns three routines, so its phase/day/exercise ids are well
    past the source's. If a single foreign key travelled in the document,
    exercises would attach to a local day and two people's plans would be
    interleaved with nothing raising.
    """
    theirs = [add_routine(other, name) for name in ("Their A", "Their B", "Their C")]
    before = {d.name: d for d in list_user_drafts(other)}
    assert len(before) == 3

    populate(store)
    import_all(other, export_all(store), wipe=False)

    after = {d.name: d for d in list_user_drafts(other)}
    assert set(after) == {"Their A", "Their B", "Their C", "My PPL"}

    # The three that were already here are byte-for-byte what they were.
    for name, original in before.items():
        assert after[name] == original
    # …and they kept their primary keys, so anything pointing at them still does.
    assert [after[n].pk for n in ("Their A", "Their B", "Their C")] == theirs

    # The imported one is a new row with a new pk and its tree intact.
    mine = after["My PPL"]
    assert mine.pk not in theirs
    assert [p.name for p in mine.phases] == ["Base", "Peak"]
    assert [d.name for d in mine.phases[0].days] == ["Day 1", "Day 2"]
    assert [e.name for e in mine.phases[0].days[0].exercises] == ["Squat", "Barbell Bench Press"]
    assert [e.name for e in mine.phases[1].days[0].exercises] == ["Squat"]


def test_merge_reattaches_children_to_the_right_parents(store, other):
    """No orphans and no cross-links, checked against the raw foreign keys."""
    for name in ("Their A", "Their B"):
        add_routine(other, name)
    populate(store)
    import_all(other, export_all(store), wipe=False)

    with _session(other) as s:
        routine_ids = set(s.scalars(select(UserRoutine.id)))
        phases = list(s.scalars(select(UserRoutinePhase)))
        days = list(s.scalars(select(UserRoutineDay)))
        exercises = list(s.scalars(select(UserRoutineExercise)))

    assert len(routine_ids) == 3
    assert {p.routine_id for p in phases} <= routine_ids
    assert {d.phase_id for d in days} <= {p.id for p in phases}
    assert {e.day_id for e in exercises} <= {d.id for d in days}
    # Three routines × (2 phases, 3 days, 4 exercises): nothing lost, nothing
    # doubled, nothing re-parented.
    assert (len(phases), len(days), len(exercises)) == (6, 9, 12)


def test_merge_maps_the_active_routine_pref_to_its_new_pk(store, other):
    add_routine(other, "Their A")
    add_routine(other, "Their B")
    populate(store)
    source_pref = store.get_pref("routine")

    import_all(other, export_all(store), wipe=False)

    pref = other.get_pref("routine")
    assert pref != source_pref  # the pk moved…
    mine = next(d for d in list_user_drafts(other) if d.name == "My PPL")
    assert pref == user_routine_id(mine.pk)  # …and points at the right routine


def test_merge_resolves_foods_by_slug_not_by_id(store, other):
    """`food_log.food_id` is remapped through the slug, the natural key.

    `other` has three foods, so its ids run ahead of the source's. A log row
    that arrived carrying its old numeric id would point at the wrong food and
    the diary would quietly show someone else's dinner.
    """
    add_food(other, "oats", "Oats")
    add_food(other, "rice", "Rice")
    theirs_chicken = add_food(other, "chicken", "Chicken breast (their edit)", kcal=999.0)

    populate(store)
    import_all(other, export_all(store), wipe=False)

    with _session(other) as s:
        by_slug = {f.slug: f for f in s.scalars(select(Food))}
        assert set(by_slug) == {"oats", "rice", "chicken", "egg"}
        # Existing slug: kept as it was. A merge fills gaps, it never rewrites
        # a row the user may have corrected by hand.
        assert by_slug["chicken"].id == theirs_chicken
        assert by_slug["chicken"].kcal == 999.0

        entries = {e.food_name: e for e in s.scalars(select(FoodLogEntry))}
        assert entries["Chicken breast"].food_id == theirs_chicken
        assert entries["Egg"].food_id == by_slug["egg"].id
        assert entries["Leftover paella"].food_id is None


def test_merge_twice_does_not_double_the_history(store, other):
    """Importing the same file again is a mistake, not a data-doubling event."""
    populate(store)
    doc = export_all(store)

    import_all(other, doc, wipe=False)
    first = counts_of(other)
    second_counts = import_all(other, doc, wipe=False)

    after = counts_of(other)
    assert after["workouts"] == first["workouts"]
    assert after["food_log"] == first["food_log"]
    assert after["weights"] == first["weights"]
    assert second_counts["workouts"] == 0
    assert second_counts["food_log"] == 0
    # Routines have no natural key — two routines called "My PPL" really are
    # two routines — so those are the one thing that does duplicate.
    assert after["routines"] == first["routines"] + 1


def test_merge_keeps_local_rows_that_share_a_key(store, other):
    other.set_profile("Someone Else", "1980-01-01", 165.0, "female", "high")
    other.set_pref("units", "lb")
    add_weight(other, DAY, 70.0)
    add_target(other, date(2026, 1, 1), kcal=1800.0)

    populate(store)
    import_all(other, export_all(store), wipe=False)

    assert other.get_profile()["name"] == "Someone Else"
    assert other.get_pref("units") == "lb"
    with _session(other) as s:
        assert s.get(Peso, DAY).kg == 70.0
        assert s.get(NutritionTarget, date(2026, 1, 1)).kcal == 1800.0
        # The dates that were free did get filled.
        assert s.get(Peso, DAY - timedelta(days=7)).kg == 83.1
        assert s.get(NutritionTarget, date(2026, 2, 15)) is not None


def test_wipe_replaces_everything(store, other):
    add_routine(other, "Their A")
    add_food(other, "oats", "Oats")
    other.set_pref("units", "lb")

    populate(store)
    import_all(other, export_all(store), wipe=True)

    assert counts_of(other) == counts_of(store)
    assert [d.name for d in list_user_drafts(other)] == ["My PPL"]
    with _session(other) as s:
        assert set(s.scalars(select(Food.slug))) == {"chicken", "egg"}
    assert other.get_pref("units") == "kg"


# ── 4. corrupt input, and the transaction ────────────────────


def test_truncated_file_fails_cleanly(store, tmp_path):
    """Half a JSON file must not cost the user the half of a database.

    `wipe=True` is the dangerous path — the one that deletes first — so that is
    the one this asserts against.
    """
    populate(store)
    before = counts_of(store)

    good = backup.export_to_file(store, tmp_path / "full.json")
    truncated = tmp_path / "truncated.json"
    truncated.write_text(good.read_text(encoding="utf-8")[: len(good.read_text()) // 2])

    with pytest.raises(BackupError, match="not valid JSON"):
        backup.import_from_file(store, truncated, wipe=True)

    assert counts_of(store) == before


def test_missing_file_fails_cleanly(store, tmp_path):
    populate(store)
    with pytest.raises(BackupError, match="Cannot read the backup file"):
        backup.import_from_file(store, tmp_path / "nope.json")
    assert counts_of(store)["workouts"] == 2


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["workouts"][0].update(date="not-a-date"), "ISO date"),
        (lambda d: d["workouts"][0].update(sets="lots"), "expected a list"),
        (lambda d: d["weights"][0].update(kg="heavy"), "not a number"),
        (lambda d: d["nutrition"]["foods"][0].update(kcal="many"), "not a number"),
        (lambda d: d["nutrition"]["foods"][0].update(slug=""), "no slug"),
        (lambda d: d["nutrition"]["food_log"][0].update(meal="brunch"), "is not one of"),
        (lambda d: d.update(workouts={"not": "a list"}), "expected a list"),
        (lambda d: d.update(routines=[{"phases": "none"}]), "expected a list"),
        (lambda d: d["nutrition"]["food_log"][0].update(created=1e30), "usable timestamp"),
    ],
)
def test_a_corrupt_document_is_refused_before_any_write(store, other, mutate, message):
    """Validation happens with no database open, so nothing can be half-done."""
    populate(store)
    populate(other)
    before = counts_of(other)

    doc = export_all(store)
    mutate(doc)

    with pytest.raises(BackupError, match=message):
        import_all(other, doc, wipe=True)

    assert counts_of(other) == before


def test_duplicate_food_slug_is_caught_by_name(store, other):
    """`foods.slug` is UNIQUE: a duplicate would abort the flush with a database
    error nobody can act on. Catch it in the parse phase instead."""
    populate(store)
    doc = export_all(store)
    doc["nutrition"]["foods"].append(dict(doc["nutrition"]["foods"][0]))

    with pytest.raises(BackupError, match="appears twice"):
        import_all(other, doc)
    assert counts_of(other)["foods"] == 0


def test_failure_midway_rolls_back_the_wipe(store, monkeypatch):
    """The reason the wipe lives inside the transaction.

    `Storage.import_all()` commits its wipe separately, so an exception after it
    leaves an empty database and no way back. Here the delete and every insert
    share one transaction: whatever goes wrong, the user still has what they
    started with.
    """
    populate(store)
    before = counts_of(store)
    profile_before = store.get_profile()

    def boom(*args, **kwargs):
        raise RuntimeError("battery died mid-restore")

    # Fails late: routines, nutrition, workouts and weights are all written by
    # the time this raises, and the wipe happened before any of them.
    monkeypatch.setattr(backup, "_write_prefs", boom)

    with pytest.raises(RuntimeError, match="battery died"):
        import_all(store, export_all(store), wipe=True)

    assert counts_of(store) == before
    assert store.get_profile() == profile_before
    assert [d.name for d in list_user_drafts(store)] == ["My PPL"]


# ── 5. the exercise-key contract ─────────────────────────────


def test_import_canonicalises_workout_exercise_names(store):
    """An import cannot introduce a key the app and the bot will never match."""
    doc = {
        "app": "ironflet",
        "version": 3,
        "workouts": [
            {
                "date": DAY.isoformat(),
                "exercise": "Squat [5×12,10,8,8,8]",
                "muscle_group": "Legs",
                "phase": 1,
                "sets": [{"weight": 100.0, "reps": 8}],
                "timestamp": T0.timestamp(),
            },
            # Bracket *and* trailing star: `exercise_key` only strips brackets at
            # the very end, so this needs the fixed point `canonical_name` takes.
            {
                "date": DAY.isoformat(),
                "exercise": "Barbell Bench Press [4×8]*",
                "muscle_group": "Chest",
                "phase": 1,
                "sets": [],
                "timestamp": T0.timestamp(),
            },
        ],
    }

    import_all(store, doc)

    with _session(store) as s:
        assert sorted(s.scalars(select(Entreno.ejercicio))) == ["Barbell Bench Press", "Squat"]


def test_import_canonicalises_routine_exercise_names(store):
    doc = {
        "app": "ironflet",
        "version": 3,
        "routines": [
            {
                "id": 1,
                "name": "Imported",
                "phases": [
                    {
                        "position": 0,
                        "name": "Base",
                        "days": [
                            {
                                "position": 0,
                                "name": "Day 1",
                                "exercises": [
                                    {"position": 0, "name": "Squat [5×5]*", "sets": 5, "reps": "5"},
                                    {"position": 1, "name": "   ", "sets": 3, "reps": "10"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    counts = import_all(store, doc)

    assert counts["routine_exercises"] == 1  # the blank name was dropped
    draft = list_user_drafts(store)[0]
    assert [e.name for e in draft.phases[0].days[0].exercises] == ["Squat"]
    # And it renders back into exactly the shape data.py writes.
    assert draft.phases[0].days[0].exercises[0].display() == "Squat [5×5]"


def test_imported_routine_is_spliced_into_data_routines(store):
    """After a restore the app must see the routines it just imported."""
    builtin_ids = [r.id for r in data.ROUTINES]
    populate(store)
    doc = export_all(store)

    other_ids = [r.id for r in data.ROUTINES]
    assert len(other_ids) == len(builtin_ids) + 1  # populate() saved one

    import_all(store, doc, wipe=True)

    ids = [r.id for r in data.ROUTINES]
    assert len(ids) == len(builtin_ids) + 1
    # The pref came back with it, so the app reopens on the routine that was
    # active when the backup was taken.
    assert data.active_routine().id == store.get_pref("routine")


# ── 6. notes ─────────────────────────────────────────────────


def test_both_notes_survive_the_round_trip(store, other):
    """The point of v4. A note that does not travel is a note lost on the phone.

    Six months into a 24-week plan, "hole 4 on the backrest" is not recoverable
    from anywhere else — no metric implies it and nobody remembers it.
    """
    populate(store)
    import_all(other, export_all(store))

    assert other.get_exercise_note("Squat", DAY) == "Hole 4 on the backrest."
    assert other.get_session_note(DAY) == "Slept 5 h, dropped the weights on purpose."
    # The exercise note rides on its own row, so the workout without one still
    # has none — absence has to survive as faithfully as presence.
    assert other.get_exercise_note("Barbell Bench Press", DAY - timedelta(days=2)) is None
    assert other.get_session_note(DAY - timedelta(days=2)) is None


def test_a_session_note_travels_without_any_workout(store, other):
    """It hangs off the day, not off an exercise — including a day with none."""
    store.set_session_note("Gym closed, walked instead.", date(2026, 4, 1))

    counts = import_all(other, export_all(store))

    assert counts["session_notes"] == 1
    assert counts["workouts"] == 0
    assert other.get_session_note(date(2026, 4, 1)) == "Gym closed, walked instead."


def test_merge_keeps_the_session_note_already_on_this_device(store, other):
    """Gap-filling, same rule as weights: what is here was written here."""
    other.set_session_note("Mine, typed on this phone.", DAY)
    populate(store)

    import_all(other, export_all(store), wipe=False)

    assert other.get_session_note(DAY) == "Mine, typed on this phone."
    # A day the target had nothing for is filled in.
    store.set_session_note("Free day.", date(2026, 4, 2))
    import_all(other, export_all(store), wipe=False)
    assert other.get_session_note(date(2026, 4, 2)) == "Free day."


def test_wipe_replaces_the_session_note(store, other):
    other.set_session_note("Stale, from the old database.", DAY)
    populate(store)

    import_all(other, export_all(store), wipe=True)

    assert other.get_session_note(DAY) == "Slept 5 h, dropped the weights on purpose."


def test_an_overlong_note_in_a_document_is_truncated_not_refused(store):
    """A hand-edited file cannot smuggle in a note longer than the app writes.

    Truncating is the same thing `Storage` does on the way in, and it has to
    happen here too: `Text` has no width on either engine, so without this the
    document decides the column length.
    """
    doc = {
        "app": "ironflet",
        "version": 4,
        "workouts": [
            {
                "date": DAY.isoformat(),
                "exercise": "Squat",
                "sets": [],
                "timestamp": T0.timestamp(),
                "note": "x" * (NOTE_MAX_LEN + 500),
            }
        ],
        "session_notes": [{"date": DAY.isoformat(), "note": "y" * (NOTE_MAX_LEN + 500)}],
    }

    import_all(store, doc)

    assert store.get_exercise_note("Squat", DAY) == "x" * NOTE_MAX_LEN
    assert store.get_session_note(DAY) == "y" * NOTE_MAX_LEN


def test_blank_and_duplicate_notes_do_not_reach_the_database(store):
    """`notas_sesion.nota` is NOT NULL and its date is the primary key.

    A blank note is no note; two entries for one day would abort the whole
    transaction with a constraint error instead of importing the file.
    """
    doc = {
        "app": "ironflet",
        "version": 4,
        "session_notes": [
            {"date": DAY.isoformat(), "note": "   "},
            {"date": "2026-03-03", "note": "first"},
            {"date": "2026-03-03", "note": "second"},
            {"date": "2026-03-04", "note": None},
        ],
    }

    counts = import_all(store, doc)

    assert counts["session_notes"] == 1
    assert store.get_session_note(DAY) is None
    assert store.get_session_note(date(2026, 3, 3)) == "second"
    assert store.get_session_note(date(2026, 3, 4)) is None


def test_a_malformed_note_section_fails_before_any_write(store):
    populate(store)
    before = counts_of(store)
    doc = export_all(store)
    doc["session_notes"] = [{"date": "not-a-date", "note": "whatever"}]

    with pytest.raises(BackupError, match="session_notes\\[0\\].date"):
        import_all(store, doc, wipe=True)

    assert counts_of(store) == before


# ── 7. session durations ─────────────────────────────────────


def test_the_duration_survives_the_round_trip(store, other):
    """The point of v5. A duration that does not travel is lost on the phone.

    Unlike a weight or a volume there is nothing to re-derive it from: the
    session is over and the clock is not going to run again.
    """
    populate(store)
    import_all(other, export_all(store))

    assert other.get_session_duration(DAY) == 4320
    # A day that was never timed must arrive untimed, not zeroed.
    assert other.get_session_duration(DAY - timedelta(days=2)) is None
    assert other.get_duration_map() == {DAY.isoformat(): 4320}


def test_a_duration_travels_without_any_workout(store, other):
    """Keyed by the day, like a session note — including a day with no rows."""
    store.set_session_duration(2700, date(2026, 4, 1))

    counts = import_all(other, export_all(store))

    assert counts["session_durations"] == 1
    assert counts["workouts"] == 0
    assert other.get_session_duration(date(2026, 4, 1)) == 2700


def test_one_duration_per_day_not_one_per_exercise(store, other):
    """Two exercises on one date export one entry, and import one row.

    With the date now chosen per exercise this is the case that matters: the
    rows of a session arrive separately, but they share a `fecha` and therefore
    share the one span that was actually measured.
    """
    for name in ("Squat", "Barbell Bench Press", "Barbell Row"):
        store.save_workout(
            WorkoutEntry(
                date=DAY.isoformat(),
                exercise=name,
                muscle_group="Test",
                phase=1,
                sets=[{"weight": 100.0, "reps": 5}],
                timestamp=T0.timestamp(),
            )
        )
    store.set_session_duration(4500, DAY)

    doc = export_all(store)
    assert len(doc["workouts"]) == 3
    assert doc["session_durations"] == [
        {
            "date": DAY.isoformat(),
            "seconds": 4500,
            "timestamp": pytest.approx(doc["exported_at"], abs=60),
        }
    ]

    counts = import_all(other, doc)
    assert counts["workouts"] == 3
    assert counts["session_durations"] == 1


def test_merge_keeps_the_duration_already_on_this_device(store, other):
    """Gap-filling, same rule as notes and weights: this one was timed here."""
    other.set_session_duration(1800, DAY)
    populate(store)

    import_all(other, export_all(store), wipe=False)

    assert other.get_session_duration(DAY) == 1800
    # A day the target had nothing for is filled in.
    store.set_session_duration(3300, date(2026, 4, 2))
    import_all(other, export_all(store), wipe=False)
    assert other.get_session_duration(date(2026, 4, 2)) == 3300


def test_wipe_replaces_the_duration(store, other):
    other.set_session_duration(60, DAY)
    populate(store)

    import_all(other, export_all(store), wipe=True)

    assert other.get_session_duration(DAY) == 4320


def test_an_impossible_duration_in_a_document_is_refused(store):
    """Not clamped. A hand-edited file claiming a three-day session is corrupt.

    Importing it capped at 8 h would put a number nobody measured into the
    history wearing the face of a measurement — the same argument
    `clean_duration` makes, enforced at the file boundary too.
    """
    populate(store)
    before = counts_of(store)
    doc = export_all(store)
    doc["session_durations"] = [{"date": DAY.isoformat(), "seconds": 3 * 24 * 3600}]

    with pytest.raises(BackupError, match=r"session_durations\[0\].seconds"):
        import_all(store, doc, wipe=True)

    assert counts_of(store) == before
    assert store.get_session_duration(DAY) == 4320


def test_the_cap_itself_imports(store):
    doc = {
        "app": "ironflet",
        "version": BACKUP_VERSION,
        "session_durations": [{"date": DAY.isoformat(), "seconds": MAX_SESSION_SECONDS}],
    }
    assert import_all(store, doc)["session_durations"] == 1
    assert store.get_session_duration(DAY) == MAX_SESSION_SECONDS


def test_blank_and_duplicate_durations_do_not_reach_the_database(store):
    """`duraciones_sesion.segundos` is NOT NULL and its date is the primary key.

    Zero is no duration; two entries for one day would abort the whole
    transaction with a constraint error instead of importing the file.
    """
    doc = {
        "app": "ironflet",
        "version": BACKUP_VERSION,
        "session_durations": [
            {"date": DAY.isoformat(), "seconds": 0},
            {"date": "2026-03-03", "seconds": 1800},
            {"date": "2026-03-03", "seconds": 2400},
            {"date": "2026-03-04", "seconds": None},
        ],
    }

    counts = import_all(store, doc)

    assert counts["session_durations"] == 1
    assert store.get_session_duration(DAY) is None
    assert store.get_session_duration(date(2026, 3, 3)) == 2400
    assert store.get_session_duration(date(2026, 3, 4)) is None


def test_a_malformed_duration_section_fails_before_any_write(store):
    populate(store)
    before = counts_of(store)
    doc = export_all(store)
    doc["session_durations"] = [{"date": "not-a-date", "seconds": 1800}]

    with pytest.raises(BackupError, match=r"session_durations\[0\].date"):
        import_all(store, doc, wipe=True)

    assert counts_of(store) == before


def test_the_v2_exporter_still_ignores_durations(store):
    """`Storage.export_all()` is the frozen four-table format. Leave it frozen."""
    populate(store)
    doc = store.export_all()

    assert "session_durations" not in doc
    assert doc["version"] == 2
