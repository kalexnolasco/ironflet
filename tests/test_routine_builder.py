"""User routines: they must be indistinguishable from the ones in data.py.

The test that matters is `test_exercise_saved_by_the_editor_matches_data_py`:
an exercise added through the editor has to land on exactly the same key as the
same exercise written by hand in data.py, because that key is what the Telegram
coach in ../agente/ writes its history under. Get it wrong and one exercise
becomes two, silently, with half the progression under each.

The rest guards the seam: a stored routine has to *be* a `data.Routine`, land in
`data.ROUTINES` without evicting the built-ins, and survive a save/load round
trip with its days in order.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import make_url

from data import EXERCISE_CATALOG, ROUTINES, Routine, active_routine, set_active_routine
from exercises import exercise_key
from routine_builder import (
    DraftDay,
    DraftExercise,
    DraftPhase,
    DraftRoutine,
    UserRoutine,
    UserRoutineDay,
    UserRoutineExercise,
    UserRoutinePhase,
    builtin_routines,
    canonical_name,
    delete_routine,
    draft_from_builtin,
    duplicate_builtin,
    duplicate_user_routine,
    ensure_tables,
    format_exercise,
    is_user_routine,
    list_user_routines,
    load_draft,
    move,
    new_draft,
    parse_exercise,
    routine_pk,
    save_draft,
    sync_user_routines,
    user_routine_id,
)
from storage import Storage
from views.routine_editor import RoutineEditorView

BUILTIN_IDS = [r.id for r in ROUTINES if not is_user_routine(r.id)]


@pytest.fixture
def store():
    """Storage against `entrenador_test`, with the routine tables emptied.

    Same resolution as tests/test_smoke.py. Rows are deleted rather than tables
    dropped: other suites run against this database too, and dropping would take
    their fixtures with it.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ.get("DATABASE_URL")
        if not base:
            pytest.skip("sin DATABASE_URL: no hay base de datos contra la que probar")
        # render_as_string, no str(): str() enmascara la contraseña.
        url = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)

    if make_url(url).database == "entrenador":
        pytest.skip("apunta a la base de producción: no se toca")

    almacen = Storage(url)
    ensure_tables(almacen)
    from sqlalchemy import delete as sa_delete
    from sqlalchemy.orm import sessionmaker

    with sessionmaker(bind=almacen._engine)() as s:
        for modelo in (UserRoutineExercise, UserRoutineDay, UserRoutinePhase, UserRoutine):
            s.execute(sa_delete(modelo))
        s.commit()
    sync_user_routines(almacen)
    yield almacen
    # data.ROUTINES is a module global: leaving stored routines in it would leak
    # into every other test in the session.
    ROUTINES[:] = [r for r in ROUTINES if not is_user_routine(r.id)]
    set_active_routine("cambiatufisico")


@pytest.fixture
def page_mock():
    page = MagicMock()
    page.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "set_routine": lambda r: None,
    }
    return page


def _all_builtin_exercise_strings() -> list[tuple[str, str]]:
    """(raw string, phase scheme) for every exercise line in data.py."""
    out = []
    for r in builtin_routines():
        for p in r.phases:
            for d in r.days_for_phase(p.id):
                for ex in d.exercises:
                    out.append((ex, p.scheme))
    return out


# ── the rule of this repo ────────────────────────────────────


def test_format_round_trips_through_exercise_key():
    """`format_exercise` must be the exact inverse of `exercise_key`."""
    for names in EXERCISE_CATALOG.values():
        for name in names:
            for sets, reps in ((3, "10"), (5, "12,10,8,8,8"), (4, "8-10"), (5, "max")):
                assert exercise_key(format_exercise(name, sets, reps)) == name


def test_exercise_saved_by_the_editor_matches_data_py(store, page_mock):
    """The headline: editor key == data.py key, for the same exercise.

    Picked through the catalogue exactly as the picker dialog does it, then
    written and read back through the database.
    """
    page_mock.data["store"] = store
    # Exercises that exist both in the catalogue and in a data.py routine.
    data_keys = {exercise_key(raw) for raw, _ in _all_builtin_exercise_strings()}
    shared = [n for names in EXERCISE_CATALOG.values() for n in names if n in data_keys]
    assert len(shared) > 20, "catalogue and routines barely overlap — check the fixture"

    view = RoutineEditorView(page_mock, store)
    view.on_show()
    view._open_new()
    view.draft.name = "Key check"
    for name in shared:
        view._add_exercise(0, name)
    view._save()

    stored = [r for r in ROUTINES if is_user_routine(r.id)]
    assert len(stored) == 1
    saved = [ex for d in stored[0].days_for_phase(1) for ex in d.exercises]
    assert len(saved) == len(shared)

    for rendered, name in zip(saved, shared, strict=True):
        assert exercise_key(rendered) == name
        # And the same exercise as data.py writes it collapses to the same key.
        same_in_data = next(
            raw for raw, _ in _all_builtin_exercise_strings() if exercise_key(raw) == name
        )
        assert exercise_key(rendered) == exercise_key(same_in_data)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("Squat", "Squat"),
        ("  Squat  ", "Squat"),
        ("Squat [5×5]", "Squat"),
        ("Squat* [5×5]", "Squat"),
        ("Pec Deck *", "Pec Deck"),
        # exercise_key() alone leaves "Squat [5×5]" here: its regex only strips
        # brackets at the very end, and the star sits behind them.
        ("Squat [5×5]*", "Squat"),
        ("Squat [4×8] [comp]", "Squat"),
    ],
)
def test_canonical_name_reaches_a_fixed_point(typed, expected):
    assert canonical_name(typed) == expected
    assert canonical_name(canonical_name(typed)) == expected


def test_canonical_name_agrees_with_exercise_key_on_data_py():
    """The extra pass may not change a single one of data.py's own strings."""
    for raw, _ in _all_builtin_exercise_strings():
        assert canonical_name(raw) == exercise_key(raw)


def test_typed_scheme_in_the_name_does_not_create_a_second_exercise(store):
    """Someone types "Squat [5×5]*" into a name. It must still store "Squat"."""
    draft = new_draft("Typed")
    draft.phases[0].days[0].exercises = [
        DraftExercise(name="Squat [5×5]*", sets=5, reps="5"),
        DraftExercise(name="  Deadlift  ", sets=1, reps="5"),
    ]
    pk = save_draft(store, draft)
    reloaded = load_draft(store, pk)
    assert [e.name for e in reloaded.phases[0].days[0].exercises] == ["Squat", "Deadlift"]


def test_every_builtin_exercise_survives_duplication(store):
    """Duplicating a routine may not change a single exercise key."""
    for rid in BUILTIN_IDS:
        src = next(r for r in ROUTINES if r.id == rid)
        pk = duplicate_builtin(store, rid)
        copy = next(r for r in ROUTINES if r.id == user_routine_id(pk))

        assert len(copy.phases) == len(src.phases)
        for idx, phase in enumerate(src.phases, start=1):
            src_days = src.days_for_phase(phase.id)
            copy_days = copy.days_for_phase(idx)
            assert [d.name for d in copy_days] == [d.name for d in src_days]
            for sd, cd in zip(src_days, copy_days, strict=True):
                assert [exercise_key(e) for e in cd.exercises] == [
                    exercise_key(e) for e in sd.exercises
                ]


def test_scheme_brackets_survive_duplication():
    """A copy should still read like the original, brackets included."""
    draft = draft_from_builtin("recomp-ppl-ul")
    src = next(r for r in ROUTINES if r.id == "recomp-ppl-ul")
    for phase_idx, phase in enumerate(src.phases):
        for day_idx, day in enumerate(src.days_for_phase(phase.id)):
            for ex_idx, raw in enumerate(day.exercises):
                copied = draft.phases[phase_idx].days[day_idx].exercises[ex_idx].display()
                assert copied == raw, f"{raw} came back as {copied}"


# ── scheme parsing ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "phase_scheme", "expected"),
    [
        ("Squat [5×12,10,8,8,8]", "3×12", ("Squat", 5, "12,10,8,8,8")),
        ("Barbell Bench Press [4×8-10]", "3×12", ("Barbell Bench Press", 4, "8-10")),
        ("Hanging Abs [5×max]", "3×12", ("Hanging Abs", 5, "max")),
        ("Abs Triset [4×(20+20+20)]", "3×12", ("Abs Triset", 4, "(20+20+20)")),
        # No bracket: inherits the phase scheme.
        ("Pec Deck", "3×12", ("Pec Deck", 3, "12")),
        # Starred with no bracket: takes the alternate the phase declares.
        ("Leg Extensions *", "4×5-6 (*=3×8)", ("Leg Extensions", 3, "8")),
        # Starred but the phase has no alternate: plain phase scheme.
        ("Pec Deck *", "3×12", ("Pec Deck", 3, "12")),
        # A tag bracket carries no scheme and must not be mistaken for one.
        ("Deadlift [comp]", "4×6-10", ("Deadlift", 4, "6-10")),
        # Unparseable phase scheme: fall back to the defaults, do not crash.
        ("Lunges", "Ascending Pyramid", ("Lunges", 3, "10")),
        # ASCII x, as a human would type it.
        ("Squat [3x8]", "", ("Squat", 3, "8")),
    ],
)
def test_parse_exercise(raw, phase_scheme, expected):
    ex = parse_exercise(raw, phase_scheme)
    assert (ex.name, ex.sets, ex.reps) == expected


def test_move_swaps_and_refuses_out_of_range():
    items = ["a", "b", "c"]
    assert move(items, 0, 1) and items == ["b", "a", "c"]
    assert move(items, 2, -1) and items == ["b", "c", "a"]
    assert not move(items, 0, -1)
    assert not move(items, 2, 1)
    assert items == ["b", "c", "a"]


# ── the compatibility layer ──────────────────────────────────


def test_stored_routine_is_a_data_routine(store):
    pk = duplicate_builtin(store, "upper-lower", "Mine")
    routine = next(r for r in ROUTINES if r.id == user_routine_id(pk))

    assert isinstance(routine, Routine)  # not a lookalike: the real dataclass
    assert routine.name == "Mine"
    assert routine.week_rotation is None
    assert routine.phases and routine.days_for_phase(routine.phases[0].id)
    for p in routine.phases:
        # Every field the views read has to be there and be a string.
        for attr in ("weeks", "name", "subtitle", "color", "scheme", "rest", "notes", "freq"):
            assert isinstance(getattr(p, attr), str)
        assert p.color.startswith("#")  # from the palette, never a literal


def test_active_routine_can_be_a_stored_one(store):
    pk = duplicate_builtin(store, "push-pull-legs", "PPL mine")
    rid = user_routine_id(pk)
    set_active_routine(rid)
    assert active_routine().id == rid
    assert active_routine().days_for_phase(1)  # what every view calls


def test_the_existing_views_render_a_stored_routine(store, page_mock):
    """The whole point: no view knows the difference.

    Same walk as tests/test_smoke.py, but with a database routine active instead
    of a constant — including the Plan phase detail, which is the screen that
    reads the most fields off `Phase`.
    """
    from views.history import HistoryView
    from views.home import HomeView
    from views.plan import PlanView
    from views.profile import ProfileView
    from views.workout import WorkoutView

    page_mock.data["store"] = store
    pk = duplicate_builtin(store, "recomp-ppl-ul", "Alex's PPL")
    set_active_routine(user_routine_id(pk))
    routine = active_routine()
    assert routine.name == "Alex's PPL"

    for cls in (HomeView, PlanView, WorkoutView, HistoryView, ProfileView):
        view = cls(page_mock, store)
        view.on_show()
        view.build()

    plan = PlanView(page_mock, store)
    for idx, phase in enumerate(routine.phases):
        plan.selected_phase_idx = idx
        plan._expanded_days = {d.name for d in routine.days_for_phase(phase.id)}
        plan.build()

    workout = WorkoutView(page_mock, store)
    workout.phase_id = routine.phases[0].id
    workout.day_idx = 0
    workout.build()
    assert workout._current_exercise_raw() != ""


def test_sync_is_idempotent_and_keeps_the_builtins(store):
    before = [r.id for r in ROUTINES]
    # Was `women-home` (1 phase / 3 days) before that routine was removed. This
    # test only needs *some* built-in to duplicate, so it takes the cheapest
    # survivor: `push-pull-legs`, 2 phases of 3 days, the smallest still shipped.
    duplicate_builtin(store, "push-pull-legs")
    for _ in range(3):
        sync_user_routines(store)
    after = [r.id for r in ROUTINES]
    assert after[: len(before)] == before  # built-ins untouched, still first
    assert len([r for r in after if is_user_routine(r)]) == 1


def test_deleting_the_active_routine_falls_back(store):
    # Was `women-strength`. `upper-lower` is its exact structural twin — 2 phases
    # of 4 days each — so the copy being deleted is the same size and shape as
    # before. It must also not be ROUTINES[0], since the fallback asserted below
    # is precisely "the active routine reverts to ROUTINES[0]"; it is not.
    pk = duplicate_builtin(store, "upper-lower")
    rid = user_routine_id(pk)
    set_active_routine(rid)
    assert active_routine().id == rid

    assert delete_routine(store, pk) is True
    assert not any(is_user_routine(r.id) for r in ROUTINES)
    assert active_routine().id == ROUTINES[0].id
    assert store.get_pref("routine") == ROUTINES[0].id
    assert delete_routine(store, pk) is False  # second delete is a no-op


def test_routine_pk_round_trip():
    assert routine_pk(user_routine_id(7)) == 7
    assert routine_pk("cambiatufisico") is None
    assert routine_pk("user:not-a-number") is None


# ── persistence ──────────────────────────────────────────────


def test_save_load_round_trip_keeps_order(store):
    draft = DraftRoutine(
        name="Ordered",
        description="three days",
        phases=[
            DraftPhase(
                name="Block A",
                weeks="1-4",
                scheme="4×8",
                rest="90s",
                days=[
                    DraftDay(name="Pull", exercises=[DraftExercise("Deadlift", 5, "5")]),
                    DraftDay(name="Push", exercises=[DraftExercise("Barbell Bench Press", 4, "8")]),
                    DraftDay(name="Legs", exercises=[DraftExercise("Squat", 5, "5")]),
                ],
            ),
            DraftPhase(name="Block B", weeks="5-8", scheme="3×12", days=[DraftDay(name="Full")]),
        ],
    )
    pk = save_draft(store, draft)
    assert draft.pk == pk  # the draft learns its own id, so Save twice updates

    back = load_draft(store, pk)
    assert [p.name for p in back.phases] == ["Block A", "Block B"]
    assert [d.name for d in back.phases[0].days] == ["Pull", "Push", "Legs"]
    assert back.phases[0].days[0].exercises[0].reps == "5"
    assert back.description == "three days"


def test_update_replaces_children_instead_of_appending(store):
    # Was `women-home`. What this test needs is a first phase with enough days
    # that popping one is observable; `women-home` had 3. `push-pull-legs` also
    # opens on a 3-day phase, so `original_days` is still 3 and the assertion
    # below still spans the same 3 → 2 transition.
    #
    # No surviving routine has `women-home`'s single phase (the lightest left is
    # 2), but the extra phase is inert here: only `phases[0]` is mutated, and the
    # round trip through save/load covers it either way.
    pk = duplicate_builtin(store, "push-pull-legs")
    draft = load_draft(store, pk)
    original_days = len(draft.phases[0].days)

    draft.phases[0].days.pop()
    save_draft(store, draft)

    back = load_draft(store, pk)
    assert len(back.phases[0].days) == original_days - 1
    assert len(list_user_routines(store)) == 1


def test_duplicate_a_user_routine(store):
    pk = duplicate_builtin(store, "upper-lower", "Base")
    copy_pk = duplicate_user_routine(store, pk)
    assert copy_pk != pk
    assert load_draft(store, copy_pk).name == "Base (copy)"
    assert len(list_user_routines(store)) == 2


def test_nameless_exercises_are_dropped_not_stored_blank(store):
    draft = new_draft("Sparse")
    draft.phases[0].days[0].exercises = [
        DraftExercise(name="   ", sets=3, reps="10"),
        DraftExercise(name="Squat", sets=3, reps="10"),
    ]
    pk = save_draft(store, draft)
    assert [e.name for e in load_draft(store, pk).phases[0].days[0].exercises] == ["Squat"]


def test_sets_are_clamped(store):
    draft = new_draft("Clamped")
    draft.phases[0].days[0].exercises = [DraftExercise("Squat", 99, "5")]
    pk = save_draft(store, draft)
    assert load_draft(store, pk).phases[0].days[0].exercises[0].sets == 20


# ── the view ─────────────────────────────────────────────────


def test_editor_view_builds_in_every_state(store, page_mock):
    page_mock.data["store"] = store
    view = RoutineEditorView(page_mock, store)
    view.on_show()
    view.build()  # empty library

    duplicate_builtin(store, "recomp-ppl-ul")
    view.on_show()
    view.build()  # library with one routine

    view._open_existing(routine_pk(user_routine_id(1)) or 1)


def test_editor_view_full_flow(store, page_mock):
    """New routine → phase → days → exercises → reorder → save."""
    page_mock.data["store"] = store
    view = RoutineEditorView(page_mock, store)
    view.on_show()
    view._open_new()
    view.draft.name = "Flow"
    view._add_day()
    view._add_exercise(0, "Squat")
    view._add_exercise(0, "Leg Press")
    view._add_exercise(1, "Pull-ups")
    view._add_phase()
    view._add_exercise(0, "Deadlift")
    view.build()  # editor renders with two phases

    view._select_phase(0)
    view._move_exercise(0, 0, 1)
    view._move_day(0, 1)
    view.build()

    view._save()
    assert view.mode == "list"
    stored = list_user_routines(store)
    assert len(stored) == 1
    assert len(stored[0].phases) == 2
    day_names = [d.name for d in stored[0].days_for_phase(1)]
    assert day_names == ["Día 2", "Day 1"]  # the reorder stuck
    first_day = stored[0].days_for_phase(1)[1].exercises
    assert [exercise_key(e) for e in first_day] == ["Leg Press", "Squat"]


def test_editor_refuses_to_save_an_empty_routine(store, page_mock):
    page_mock.data["store"] = store
    view = RoutineEditorView(page_mock, store)
    view.on_show()
    view._open_new()
    view._save()
    assert view.mode == "edit"
    assert "ejercicio" in view.error
    assert list_user_routines(store) == []

    view._add_exercise(0, "Squat")
    view.draft.name = "   "
    view._save()
    assert view.mode == "edit"
    assert "nombre" in view.error
    assert list_user_routines(store) == []


def test_editor_never_leaves_a_routine_without_phases(store, page_mock):
    page_mock.data["store"] = store
    view = RoutineEditorView(page_mock, store)
    view.on_show()
    view._open_new()
    view._remove_phase()
    assert len(view.draft.phases) == 1
    assert view.error


def test_editor_back_unwinds_one_level(store, page_mock):
    page_mock.data["store"] = store
    view = RoutineEditorView(page_mock, store)
    view.on_show()
    assert view.handle_back() is False  # library: let main go Home
    view._open_new()
    assert view.handle_back() is True  # editor: back to the library
    assert view.mode == "list"
    assert view.handle_back() is False


def test_picker_dialog_opens_and_filters(store, page_mock):
    page_mock.data["store"] = store
    view = RoutineEditorView(page_mock, store)
    view.on_show()
    view._open_new()
    view._open_picker(0)
    page_mock.open.assert_called_once()
    dialog = page_mock.open.call_args[0][0]
    assert dialog.title.value == "Añadir ejercicio"
