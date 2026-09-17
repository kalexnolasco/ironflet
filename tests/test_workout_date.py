"""Logging a session under a day that is not today.

Alex: *"podamos actualizar para un dia anterior... la sesion ... osea que se
pueda cambiar el día... por ejemplo a veces nos olvidamos el movil y al llegar a
casa quiero actualizar el entreno."*

Writing the date was never the hard part — `WorkoutEntry` has always carried one
and `Storage.save_workout` writes whatever it is given. The hard part is that a
date is **sticky state on a long-lived view**: `ironflet-web` is a systemd unit,
so one `WorkoutView` instance serves weeks of workouts. A date left set from
last night would file tonight's session into it, silently, in the one part of
the app whose entire job is to be a faithful record.

So most of this file is not about choosing a date. It is about the date going
back to today by itself, and about it being impossible to miss while it has not.

Two halves:

* everything down to "the history" runs on a dict-backed fake and needs no
  database, same as tests/test_workout_zen.py;
* the last section writes real rows into PostgreSQL and reads them back through
  the public API, because "appears in the history on the right day" and "the
  streak counts it in the right week" both live in the seam between this view,
  `entrenos.fecha` and `analytics`, and no fake can speak for that seam.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from unittest.mock import MagicMock

import flet as ft
import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url

import views.workout as workout_module
from data import set_active_routine
from exercises import exercise_key
from storage import Entreno, Storage, WorkoutEntry, weekly_session_minimum
from views.workout import LOG_DATE_PREF, MAX_BACKDATE_DAYS, WorkoutView, _date_label

DEFAULT_ROUTINE = "cambiatufisico"


# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    """The `Storage` surface a `WorkoutView` touches on the date paths.

    `get_all` is here because the picker dialog reads the history once, to warn
    about a day that already holds rows and about moving an inferred program
    start. `saved` captures what would have reached `entrenos`.
    """

    def __init__(self, history: list[WorkoutEntry] | None = None):
        self.prefs: dict[str, str] = {}
        self.saved: list[WorkoutEntry] = []
        self.history: list[WorkoutEntry] = list(history or [])

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        self.prefs[key] = value

    def get_last_sets(self, key: str, before=None):
        return None

    def get_exercise_history(self, key: str, limit: int = 20):
        return []

    def get_all(self) -> list[WorkoutEntry]:
        return list(self.history)

    def save_workout(self, entry: WorkoutEntry) -> None:
        self.saved.append(entry)


@pytest.fixture
def page():
    p = MagicMock()
    p.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "set_routine": lambda r: None,
    }
    return p


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def view(page, store):
    """A view parked on the first exercise of the first day, logging to today."""
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store
    v = WorkoutView(page, store)
    v.phase_id = 1
    v._start_day(0)
    return v


def freeze_today(monkeypatch, day: date):
    """Move the view's idea of today.

    `views/workout.py` does `from datetime import date`, so the whole module
    reads one name. A `date` subclass is patched over it rather than a stub
    object: `date.fromisoformat` is used on the same name and arithmetic and
    comparisons against real dates have to keep working.
    """

    class Frozen(date):
        @classmethod
        def today(cls):
            return day

    monkeypatch.setattr(workout_module, "date", Frozen)


def log_one_set(view: WorkoutView, weight: str = "80", reps: str = "8"):
    """Type a set the user stands behind — a suggestion is never written."""
    view._update_set(0, "weight", weight)
    view._update_set(0, "reps", reps)


# ── walking a built control tree (same helper as test_workout_zen.py) ────


def _walk(control, seen=None):
    if seen is None:
        seen = set()
    if control is None or id(control) in seen:
        return
    seen.add(id(control))
    yield control
    for attr in ("content", "title", "leading", "trailing"):
        child = getattr(control, attr, None)
        if isinstance(child, ft.Control):
            yield from _walk(child, seen)
    for attr in ("controls", "actions"):
        children = getattr(control, attr, None)
        if isinstance(children, (list, tuple)):
            for child in children:
                if isinstance(child, ft.Control):
                    yield from _walk(child, seen)


def _texts(control) -> list[str]:
    return [c.value for c in _walk(control) if isinstance(c, ft.Text) and c.value]


def _said(control, needle: str) -> bool:
    return any(needle.lower() in t.lower() for t in _texts(control))


def _last_dialog(page):
    """The control handed to the most recent `page.open()`."""
    return page.open.call_args_list[-1][0][0]


def _button(dialog, label: str):
    """The tappable container whose own text contains `label`."""
    for c in _walk(dialog):
        if isinstance(c, ft.Container) and c.on_click is not None and _said(c, label):
            return c
    raise AssertionError(f"no button labelled {label!r} in the dialog")


def _field(dialog) -> ft.TextField:
    return next(c for c in _walk(dialog) if isinstance(c, ft.TextField))


# ── the label ────────────────────────────────────────────────────────────


def test_the_label_names_the_near_days_and_dates_the_rest():
    """A date the user has to decode is a date nobody reads."""
    today = date(2026, 8, 18)
    assert _date_label(today, today) == "Hoy"
    assert _date_label(today - timedelta(days=1), today) == "Ayer"
    assert _date_label(today - timedelta(days=3), today) == "sáb 15 ago · hace 3 días"


# ── what actually gets written ───────────────────────────────────────────


def test_a_fresh_view_logs_to_today(view):
    assert view.log_date == date.today()
    assert view.is_backdated() is False


def test_the_saved_row_carries_the_chosen_day(view, store):
    """The whole feature, in one assertion."""
    day = date.today() - timedelta(days=3)
    view._set_log_date(day)
    log_one_set(view)
    assert view._save_exercise(0) == "saved"
    assert store.saved[0].date == day.isoformat()


def test_an_ordinary_session_still_lands_on_today(view, store):
    log_one_set(view)
    view._save_exercise(0)
    assert store.saved[0].date == date.today().isoformat()


def test_the_write_timestamp_is_when_it_was_typed_not_the_training_day(view, store):
    """`fecha` is the day trained; `creado` is the day recorded. Both are true.

    Rewriting the timestamp too would claim the row was created three days ago,
    which it was not, and `creado` is what an audit of the shared database has
    to be able to trust.
    """
    view._set_log_date(date.today() - timedelta(days=2))
    log_one_set(view)
    view._save_exercise(0)
    written = date.fromtimestamp(store.saved[0].timestamp)
    assert written == date.today()


# ── the future is refused, and the far past too ──────────────────────────


def test_a_future_date_is_clamped_to_today(view):
    """`get_week_stats`, `training_streak` and `last_workout_date` all skip rows
    dated after today, so a future session would be written and then counted by
    nothing at all. There is nothing to log either — it has not happened."""
    view._set_log_date(date.today() + timedelta(days=2))
    assert view.log_date == date.today()
    assert view.is_backdated() is False


def test_the_dialog_refuses_the_future_rather_than_moving_it(view, page):
    """Refused, not silently snapped: a clamp reads as the app obeying."""
    view._open_date_dialog()
    dlg = _last_dialog(page)
    _field(dlg).value = (date.today() + timedelta(days=1)).isoformat()
    _button(dlg, "Usar esta fecha").on_click(None)
    assert view.log_date == date.today()
    assert _said(dlg, "futuro no")


def test_the_dialog_refuses_a_date_past_the_limit(view, page):
    """The realistic typo is a wrong *year*, and it is far cheaper to catch here
    than to unpick from the history and from an inferred program start."""
    view._open_date_dialog()
    dlg = _last_dialog(page)
    _field(dlg).value = (date.today() - timedelta(days=MAX_BACKDATE_DAYS + 1)).isoformat()
    _button(dlg, "Usar esta fecha").on_click(None)
    assert view.is_backdated() is False
    assert _said(dlg, "emasiado atrás")


def test_the_dialog_refuses_something_that_is_not_a_date(view, page):
    view._open_date_dialog()
    dlg = _last_dialog(page)
    _field(dlg).value = "last tuesday"
    _button(dlg, "Usar esta fecha").on_click(None)
    assert view.is_backdated() is False
    assert _said(dlg, "aaaa-mm-dd")


def test_yesterday_is_one_tap(view, page):
    view._open_date_dialog()
    dlg = _last_dialog(page)
    _button(dlg, "Ayer").on_click(None)
    _button(dlg, "Usar esta fecha").on_click(None)
    assert view.log_date == date.today() - timedelta(days=1)


# ── it is impossible to miss ─────────────────────────────────────────────


def test_the_exercise_screen_shouts_when_the_date_is_not_today(view):
    view._set_log_date(date.today() - timedelta(days=2))
    screen = view.build()
    assert _said(screen, "NO ES HOY")
    assert _said(screen, "Guardando en")


def test_zen_mode_does_not_get_to_hide_it(view):
    """Zen strips reference material. This is not reference material."""
    view._set_log_date(date.today() - timedelta(days=2))
    assert view.zen is True
    assert _said(view.build(), "NO ES HOY")


def test_an_ordinary_workout_is_not_taxed_for_the_feature(view):
    """The 95 % case pays nothing: no strip, and in zen not even the pill."""
    screen = view.build()
    assert not _said(screen, "NO ES HOY")
    assert not _said(screen, "Guardando en")


def test_the_setting_is_reachable_from_inside_a_session(view):
    """Out of zen, the small pill is the way in without leaving the exercise."""
    view._set_zen(False)
    assert _said(view.build(), "Hoy")


def test_the_day_list_always_says_where_the_session_will_go(view):
    view.show_day_list = True
    assert _said(view.build(), "REGISTRANDO EN")


def test_the_finish_dialog_names_a_date_that_is_not_today(view, page):
    """The last checkpoint before Finish flushes everything still pending."""
    view._set_log_date(date.today() - timedelta(days=2))
    log_one_set(view)
    view._ask_finish(None)
    assert _said(_last_dialog(page), "hoy no")


def test_the_summary_names_it_too(view, store):
    view._set_log_date(date.today() - timedelta(days=2))
    log_one_set(view)
    view._save_exercise(0)
    view.finished = True
    assert _said(view.build(), "Registrado en")


def test_saving_confirms_where_it_went(view, page):
    view._set_log_date(date.today() - timedelta(days=2))
    log_one_set(view)
    view._save(None)
    assert any(_said(call[0][0], "Guardado en") for call in page.open.call_args_list)


# ── it goes back to today by itself ──────────────────────────────────────


def test_finishing_the_session_puts_the_date_back(view):
    view._set_log_date(date.today() - timedelta(days=2))
    view._reset()
    assert view.log_date == date.today()
    assert view.is_backdated() is False


def test_discarding_the_session_puts_the_date_back(view):
    view._set_log_date(date.today() - timedelta(days=2))
    view._discard_workout()
    assert view.is_backdated() is False


def test_the_stored_copy_dies_with_the_session(view, store):
    view._set_log_date(date.today() - timedelta(days=2))
    assert store.prefs[LOG_DATE_PREF]
    view._reset()
    assert store.prefs[LOG_DATE_PREF] == ""


def test_a_choice_left_over_from_yesterday_is_dropped(view, monkeypatch):
    """The failure this feature is really guarding against.

    `ironflet-web` is a long-lived process: the same view object serves weeks of
    workouts. Without this, one Tuesday evening of catching up would keep
    writing Monday's date until someone noticed in History.
    """
    view._set_log_date(date.today() - timedelta(days=1))
    assert view.is_backdated() is True

    # The clock rolls over with the day still set and nothing open — no sets
    # typed, so `_workout_in_progress()` is False and the choice has outlived
    # everything it described.
    freeze_today(monkeypatch, date.today() + timedelta(days=1))
    assert view.is_backdated() is True, "still stale until something renders"
    view.build()
    assert view.is_backdated() is False


def test_a_live_session_keeps_its_date_across_midnight(view, monkeypatch):
    """The 22:30-to-00:10 session `workout_draft` already reasons about.

    The strip is on screen and the date is still the one he chose, so taking it
    away at midnight would be a change nobody asked for and nobody would see.
    """
    chosen = date.today() - timedelta(days=1)
    view._set_log_date(chosen)
    log_one_set(view)

    freeze_today(monkeypatch, date.today() + timedelta(days=1))
    view.build()
    assert view.log_date == chosen
    assert _said(view.build(), "NO ES HOY")


# ── the draft carries it ─────────────────────────────────────────────────


def test_the_draft_brings_the_date_back(page, store):
    """The crash path. Android kills the process mid-session; the draft restores
    the workout, and a date that did not come with it would silently move every
    remaining exercise to today — half a session under each of two days."""
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store
    chosen = date.today() - timedelta(days=2)

    first = WorkoutView(page, store)
    first.phase_id = 1
    first._start_day(0)
    first._set_log_date(chosen)
    log_one_set(first)
    first._persist_draft()

    revived = WorkoutView(page, store)
    revived.on_show()
    assert revived.day_idx == 0, "the draft did not restore — the rest proves nothing"
    assert revived.log_date == chosen
    assert revived.is_backdated() is True


def test_a_stored_date_from_another_day_is_refused_on_restore(page, store, monkeypatch):
    """Belt to the in-memory rule's braces: the row carries the day the choice
    was made on, so a draft resumed the next morning logs to *that* morning."""
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store

    first = WorkoutView(page, store)
    first.phase_id = 1
    first._start_day(0)
    first._set_log_date(date.today() - timedelta(days=1))
    log_one_set(first)
    first._persist_draft()

    freeze_today(monkeypatch, date.today() + timedelta(days=1))
    revived = WorkoutView(page, store)
    revived._load_log_date()
    assert revived.is_backdated() is False


def test_a_corrupt_stored_date_reads_as_today(page, store):
    set_active_routine(DEFAULT_ROUTINE)
    store.prefs[LOG_DATE_PREF] = "not-a-date|nor-this"
    v = WorkoutView(page, store)
    v._load_log_date()
    assert v.log_date == date.today()


# ── the two consequences, said out loud ──────────────────────────────────


def test_the_dialog_warns_that_the_day_already_has_rows(page):
    """`save_workout` INSERTs — there is no upsert — so re-logging a day that
    already has rows adds to it rather than replacing it. Only the *session*
    guard (`_logged_ex`) knows about duplicates, and it does not span sessions."""
    day = date.today() - timedelta(days=2)
    store = FakeStore(
        history=[
            WorkoutEntry(
                date=day.isoformat(), exercise="Squat", muscle_group="Legs", phase=1, sets=[]
            )
        ]
    )
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store
    v = WorkoutView(page, store)
    v.phase_id = 1
    v._start_day(0)
    v._set_log_date(day)

    v._open_date_dialog()
    assert _said(_last_dialog(page), "ya registrados ese día")


def test_the_dialog_warns_when_it_would_move_the_program_start(page):
    """`program_week` infers the start from the earliest logged session when
    nothing is pinned, so a date older than that start moves the whole program
    back and can change the week Plan reports. Documented here because it is
    otherwise discovered days later, on another screen, with no way left to
    connect it to a tap."""
    first_ever = date.today() - timedelta(days=10)
    store = FakeStore(
        history=[
            WorkoutEntry(
                date=first_ever.isoformat(),
                exercise="Squat",
                muscle_group="Legs",
                phase=1,
                sets=[],
            )
        ]
    )
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store
    v = WorkoutView(page, store)
    v.phase_id = 1
    v._start_day(0)
    v._set_log_date(first_ever - timedelta(days=1))

    v._open_date_dialog()
    assert _said(_last_dialog(page), "lo retrasa")


def test_no_warning_when_the_start_date_is_pinned(page):
    """A start Alex pinned himself is a fact; back-dating cannot move it."""
    first_ever = date.today() - timedelta(days=10)
    store = FakeStore(
        history=[
            WorkoutEntry(
                date=first_ever.isoformat(),
                exercise="Squat",
                muscle_group="Legs",
                phase=1,
                sets=[],
            )
        ]
    )
    store.prefs["program_start"] = f"{DEFAULT_ROUTINE}|{(first_ever).isoformat()}"
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store
    v = WorkoutView(page, store)
    v.phase_id = 1
    v._start_day(0)
    v._set_log_date(first_ever - timedelta(days=1))

    v._open_date_dialog()
    assert not _said(_last_dialog(page), "lo retrasa")


def test_an_unreachable_database_still_lets_him_pick(page):
    """Web mode talks to PostgreSQL over the network. A dialog that cannot read
    the history can still change the date; it just cannot warn about it."""

    class Broken(FakeStore):
        def get_all(self):
            raise RuntimeError("database unreachable")

        def get_pref(self, key, default=None):
            raise RuntimeError("database unreachable")

    store = Broken()
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store
    v = WorkoutView(page, store)
    v.phase_id = 1
    v._start_day(0)

    v._open_date_dialog()
    dlg = _last_dialog(page)
    _button(dlg, "Ayer").on_click(None)
    _button(dlg, "Usar esta fecha").on_click(None)
    assert v.log_date == date.today() - timedelta(days=1)


# ── the history: real rows, read back through the public API ─────────────


@pytest.fixture
def pg_store():
    """Storage against the per-process test database, `entrenos` emptied.

    Same resolution as tests/test_storage_metrics.py. Rows are deleted rather
    than tables dropped — other suites share this database.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ.get("DATABASE_URL")
        if not base:
            pytest.skip("no DATABASE_URL: there is no database to test against")
        url = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)
    if make_url(url).database == "entrenador":
        pytest.skip("points at the production database: leave it alone")

    almacen = Storage(url)
    with almacen._Session() as s:
        s.execute(delete(Entreno))
        s.commit()
    return almacen


@pytest.fixture
def pg_view(page, pg_store):
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = pg_store
    v = WorkoutView(page, pg_store)
    v.phase_id = 1
    v._start_day(0)
    return v


def test_a_backdated_session_lands_on_its_own_day(pg_view, pg_store):
    """ "Que aparece en el historial en su día" — end to end, through the seam.

    `get_today()` is the other half of the assertion: a row that showed up under
    both dates would mean `fecha` had not moved at all.
    """
    day = date.today() - timedelta(days=3)
    pg_view._set_log_date(day)
    log_one_set(pg_view, "82.5", "8")
    assert pg_view._save_exercise(0) == "saved"

    rows = pg_store.get_all()
    assert [r.date for r in rows] == [day.isoformat()]
    assert rows[0].sets == [{"weight": 82.5, "reps": 8}]
    assert pg_store.get_today() == []


def test_the_exercise_key_is_still_the_canonical_one(pg_view, pg_store):
    """Back-dating must not touch the most fragile contract in the system: the
    Telegram coach reads the same column and matches on this key."""
    pg_view._set_log_date(date.today() - timedelta(days=1))
    log_one_set(pg_view)
    pg_view._save_exercise(0)
    day = pg_view._current_day()
    assert pg_store.get_all()[0].exercise == exercise_key(day.exercises[0])


def test_the_streak_counts_it_in_the_week_it_belongs_to(pg_view, pg_store):
    """ "Que la racha lo cuenta donde toca."

    `get_streak()` is in **weeks**: a week counts once it holds `min_sessions`
    distinct training days, and the current, unfinished week is skipped rather
    than failed. So a session back-dated into last week completes *last* week's
    minimum — it does not touch this one, which is exactly the point.
    """
    minimum = weekly_session_minimum()
    today = date.today()
    last_monday = today - timedelta(days=today.weekday() + 7)

    # One short of the minimum, all in last week, written straight to storage.
    for i in range(minimum - 1):
        pg_store.save_workout(
            WorkoutEntry(
                date=(last_monday + timedelta(days=i)).isoformat(),
                exercise="Squat",
                muscle_group="Legs",
                phase=1,
                sets=[{"weight": 60.0, "reps": 10}],
            )
        )
    assert pg_store.get_streak() == 0, "last week is not complete yet — nothing to extend"

    # The missing day, logged tonight through the view.
    missing = last_monday + timedelta(days=minimum - 1)
    pg_view._set_log_date(missing)
    log_one_set(pg_view)
    assert pg_view._save_exercise(0) == "saved"

    assert pg_store.get_streak() == 1
    # And it did not quietly land in this week instead: nothing at all is dated
    # on or after this Monday.
    this_monday = today - timedelta(days=today.weekday())
    logged = {date.fromisoformat(r.date) for r in pg_store.get_all()}
    assert not [d for d in logged if d >= this_monday]


# ── the prefill must not read from the future ────────────────────────────


def _vista_con(store):
    """A view parked on the first exercise, over a store of the test's choosing.

    The `view` fixture builds its own `FakeStore`; these tests need one that
    records what it was asked for.
    """
    from unittest.mock import MagicMock

    p = MagicMock()
    p.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "set_routine": lambda r: None,
        "store": store,
    }
    set_active_routine(DEFAULT_ROUTINE)
    v = WorkoutView(p, store)
    v.phase_id = 1
    v._start_day(0)
    return v


def test_el_prerrelleno_pide_las_series_anteriores_a_la_fecha_registrada():
    """Back-dating Saturday on Monday must not offer Sunday's numbers.

    `_seed_sets` writes whatever this returns straight into the weight and reps
    boxes, and one tap turns a prefill into the logged record — so reading the
    newest row instead of the newest row *before* `log_date` does not look like
    a bug, it looks like a workout.
    """
    from datetime import date, timedelta

    pedidos: list[object] = []

    class StoreQueRegistra(FakeStore):
        def get_last_sets(self, key: str, before=None):
            pedidos.append(before)
            return None

    vista = _vista_con(StoreQueRegistra())
    vista.log_date = date.today() - timedelta(days=2)
    vista._last_sets_cache.clear()
    vista._last_sets(0)

    assert pedidos, "the prefill never asked the store for anything"
    assert pedidos[0] == vista.log_date, (
        f"asked for rows before {pedidos[0]!r}, but the session being logged is "
        f"{vista.log_date!r} — that is how numbers from a later session end up "
        "prefilled into an earlier one"
    )


def test_una_sesion_de_hoy_pregunta_por_hoy():
    """The ordinary case still wants "strictly before today": a row already
    saved for today is *this* session, not the previous one."""
    from datetime import date

    pedidos: list[object] = []

    class StoreQueRegistra(FakeStore):
        def get_last_sets(self, key: str, before=None):
            pedidos.append(before)
            return None

    vista = _vista_con(StoreQueRegistra())
    vista._last_sets_cache.clear()
    vista._last_sets(0)
    assert pedidos[0] == date.today()


def test_un_doble_con_firma_antigua_falla_ruidosamente():
    """THE TRAP THIS COST. `_last_sets` swallows exceptions on purpose — a
    database hiccup must degrade to "first time, no history" rather than blank
    the screen mid-set — and that also swallowed the `TypeError` from a store
    whose `get_last_sets` had no `before`. The prefill silently emptied and
    four tests failed somewhere else entirely.

    So: assert the real `Storage` accepts the argument. A fake drifting from it
    is then caught here instead of by a mystery three files away.
    """
    import inspect

    from storage import Storage

    assert "before" in inspect.signature(Storage.get_last_sets).parameters
