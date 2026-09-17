"""One day per **exercise**, and the mitigation that has to come with it.

Alex: *"hoy es miércoles, pero quiero poner mi entreno del lunes y martes"* —
two sessions filled in at one sitting. He was told, in as many words, that
dating each exercise separately is the easiest possible way to put a set on the
wrong day without noticing, and he chose it anyway.

**So the mitigation is the feature, and this file is where it is enforced.** The
rule these tests exist to defend is one sentence: *if a set can be written to a
day the user did not mean, without anything on screen having said so, the
feature has failed — however green everything else is.*

Three properties carry that, and each has a section below:

1. **The row goes where the exercise says**, not where the session does. Without
   this the whole thing is theatre: the screen says Monday and `entrenos.fecha`
   says Wednesday.
2. **Every exercise screen carries its day, once any day is in play** — the ones
   that resolve to today included, and zen mode does not get to hide it. The
   dangerous state was never "Monday is on screen". It is Monday on exercise 2
   with nothing on exercise 3 saying otherwise.
3. **Everything read "as of" a date follows that exercise's date** — the
   prefill above all, because a prefill is one tap from being the record.

Dict-backed fake, no PostgreSQL: every one of these is about what this view
resolves, renders and hands to `save_workout`. `tests/test_workout_date.py`
already covers the session-wide date against real rows.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import flet as ft
import pytest

from data import active_routine, set_active_routine
from exercises import exercise_key
from views.workout import WorkoutView, _date_label
from workout_draft import DateSource

DEFAULT_ROUTINE = "cambiatufisico"


# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    """The `Storage` surface this view touches while dating exercises.

    `last_sets_asked` records the `before=` cut-off of every prefill query,
    which is how section 3 proves the prefill followed the exercise's day and
    not the session's.
    """

    def __init__(self):
        self.prefs: dict[str, str] = {}
        self.saved: list = []
        self.notes: list[tuple] = []
        self.last_sets_asked: list = []

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        self.prefs[key] = value

    def get_last_sets(self, key: str, before=None):
        self.last_sets_asked.append((key, before))
        return None

    def get_exercise_history(self, key: str, limit: int = 20):
        return []

    def get_all(self):
        return []

    def save_workout(self, entry) -> None:
        self.saved.append(entry)

    def set_exercise_note(self, key, note, on_date=None):
        self.notes.append((key, note, on_date))
        return True

    def get_duration_map(self) -> dict[str, int]:
        return {}

    def get_session_duration(self, on_date=None):
        return None

    def set_session_duration(self, seconds, on_date=None):
        return seconds


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
    set_active_routine(DEFAULT_ROUTINE)
    page.data["store"] = store
    v = WorkoutView(page, store)
    v.phase_id = 1
    v._start_day(0)
    return v


MONDAY = date.today() - timedelta(days=2)
TUESDAY = date.today() - timedelta(days=1)


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
    return page.open.call_args_list[-1][0][0]


def _keys(view) -> list[str]:
    day = view._current_day()
    return [exercise_key(x) for x in day.exercises]


def _type_a_set(view, weight="80", reps="8"):
    """Type a set the user stands behind — a suggestion is never written."""
    view._update_set(0, "weight", weight)
    view._update_set(0, "reps", reps)


# ── 1. the row goes where the exercise says ──────────────────────────────


def test_the_saved_row_carries_the_exercises_own_day(view, store):
    """The whole feature, in one assertion.

    If this ever fails, everything below it is decoration: the screen would be
    saying Monday while `entrenos.fecha` said today.
    """
    view._set_exercise_date(0, MONDAY)
    _type_a_set(view)
    view._save_exercise(0)

    assert store.saved, "nothing reached save_workout"
    assert store.saved[0].date == MONDAY.isoformat()


def test_two_exercises_can_land_on_two_different_days(view, store):
    """Alex's actual request: Monday and Tuesday, one sitting."""
    view._set_exercise_date(0, MONDAY)
    view._set_exercise_date(1, TUESDAY)

    view.ex_idx = 0
    _type_a_set(view)
    view._save_exercise(0)
    view.ex_idx = 1
    _type_a_set(view)
    view._save_exercise(1)

    assert [e.date for e in store.saved] == [MONDAY.isoformat(), TUESDAY.isoformat()]


def test_an_undated_exercise_still_follows_the_session(view, store):
    """The default chain is exercise → session → today, and it must not break.

    Dating exercise 0 must not orphan exercise 1: it inherits the session's day,
    which is the behaviour that existed before any of this.
    """
    view._set_log_date(MONDAY)
    view._set_exercise_date(0, TUESDAY)

    view.ex_idx = 1
    _type_a_set(view)
    view._save_exercise(1)

    assert store.saved[0].date == MONDAY.isoformat()
    assert view._resolve_date(1).source is DateSource.SESSION


def test_an_ordinary_workout_still_lands_on_today(view, store):
    """Nothing chosen anywhere: today, exactly as before the feature existed."""
    _type_a_set(view)
    view._save_exercise(0)
    assert store.saved[0].date == date.today().isoformat()


def test_the_note_is_written_against_the_exercises_own_day(view, store):
    """`entrenos.nota` lives in the row, so it has to look for the right row.

    Written after the exercise is logged, which is the path that goes straight
    to `set_exercise_note` with a date. The session's day would find no row and
    drop the note without a word.
    """
    view._set_exercise_date(0, MONDAY)
    _type_a_set(view)
    view._save_exercise(0)
    view._set_note(0, "felt heavy")

    assert store.notes, "the note never reached the store"
    assert store.notes[-1][2] == MONDAY


# ── 2. the day is impossible to miss ─────────────────────────────────────


def test_an_ordinary_workout_is_not_taxed_for_the_feature(view):
    """Nothing dated anywhere: no strip, zero height, no cost."""
    strip = view._backdate_strip()
    assert _texts(strip) == []


def test_a_dated_exercise_says_so_on_its_own_screen(view):
    view._set_exercise_date(0, MONDAY)
    view.ex_idx = 0
    assert _said(view._backdate_strip(), "NO ES HOY")


def test_an_exercise_on_today_still_carries_a_day_line_once_anything_is_dated(view):
    """**The failure Alex was warned about, pinned.**

    Exercise 0 is on Monday, exercise 1 is on today. Under the old
    session-scoped rule exercise 1 showed nothing at all, so the reader carried
    Monday forward in their head and filed a Wednesday lift into it. Once any
    day is in play, every screen states its own — including the ones that are
    perfectly ordinary.
    """
    view._set_exercise_date(0, MONDAY)
    view.ex_idx = 1

    strip = view._backdate_strip()
    assert _texts(strip), "exercise 1 said nothing about which day it goes to"
    assert _said(strip, "HOY")


def test_the_strip_says_whose_day_it_is(view):
    """A date the reader has to *attribute* is a date they will attribute wrong."""
    view._set_exercise_date(0, MONDAY)
    view.ex_idx = 0
    assert _said(view._backdate_strip(), "solo este ejercicio")


def test_the_strip_does_not_claim_the_whole_session_when_it_is_not_true(view):
    """With exercise 0 moved, the session's day no longer covers the session.

    Saying "the whole session" on exercise 1 would be a lie by exactly the
    amount that matters — the one exercise that is somewhere else.
    """
    view._set_log_date(MONDAY)
    view._set_exercise_date(0, TUESDAY)
    view.ex_idx = 1
    assert _said(view._backdate_strip(), "el resto de esta sesión")


def test_zen_mode_does_not_get_to_hide_it(view):
    """Zen strips reference material. This is the difference between a log and a lie."""
    view._set_exercise_date(0, MONDAY)
    view.ex_idx = 0
    view.zen = True
    assert _said(view._backdate_strip(), "NO ES HOY")

    view.ex_idx = 1
    assert _texts(view._backdate_strip()), "zen mode silenced the day line on exercise 1"


def test_the_strip_reaches_the_built_exercise_screen(view):
    """A control nothing renders is a control that protects nobody."""
    view._set_exercise_date(0, MONDAY)
    view.ex_idx = 0
    view.zen = True
    assert _said(view.build(), "NO ES HOY")


def test_the_strip_warns_when_the_session_spans_more_than_one_day(view):
    """And it counts the exercises still sitting on the default.

    Two moved to Monday and Tuesday leaves five on today, so the honest answer
    is **three** days, not two. The half a per-exercise picker makes easy to
    forget is exactly the half nobody touched.
    """
    view._set_exercise_date(0, MONDAY)
    view._set_exercise_date(1, TUESDAY)
    view.ex_idx = 0

    assert view._dates_in_use() == (MONDAY, TUESDAY, date.today())
    assert _said(view._backdate_strip(), "escribe en 3 días")


def test_one_day_is_not_announced_as_several(view):
    """Everything on Monday is one session, and must not be called two."""
    for idx in range(len(_keys(view))):
        view._set_exercise_date(idx, MONDAY)
    assert view._multi_day_text() == ""


def test_the_today_pill_gives_way_to_the_strip(view):
    """Two controls answering "which day" on one card is one too many."""
    view.zen = False
    assert _said(view._log_date_chip(), "Hoy")

    view._set_exercise_date(0, MONDAY)
    assert _texts(view._log_date_chip()) == []


def test_the_day_list_admits_that_exercises_were_moved(view):
    """The session default alone is a half-truth once anything overrides it.

    This is the screen he lands on coming back to the workout, and the moved
    exercises are exactly the ones its headline does not describe.
    """
    view._set_exercise_date(0, MONDAY)
    assert _said(view._log_date_row(), "día propio")


def test_saving_says_which_day_it_went_to(view, page):
    """Confirmation after the write, naming the day *and* the scope."""
    view._set_exercise_date(0, MONDAY)
    view.ex_idx = 0
    _type_a_set(view)
    view._save(None)

    bar = page.open.call_args_list[-1][0][0]
    assert _said(bar, "Guardado en")
    assert _said(bar, "solo este ejercicio")


def test_an_ordinary_save_says_nothing(view, page):
    """A toast for the normal case is noise, and noise is why warnings go unread."""
    _type_a_set(view)
    view._save(None)
    said = page.open.call_args_list
    assert not any(_said(c[0][0], "Guardado en") for c in said)


def test_the_finish_dialog_names_every_day_it_is_about_to_write_to(view, page):
    """The last checkpoint before rows exist. This app does not delete history."""
    view._set_exercise_date(0, MONDAY)
    view._set_exercise_date(1, TUESDAY)
    view._ask_finish(None)

    dlg = _last_dialog(page)
    assert _said(dlg, "Escribiendo en")
    # By the label the rest of the app uses — "Yesterday", not a raw ISO date.
    for day in (MONDAY, TUESDAY):
        assert _said(dlg, _date_label(day)), f"{day} was not named in the finish dialog"


def test_the_summary_names_every_day_it_wrote_to(view, store):
    """Where it went, on the screen the session ends on."""
    view._set_exercise_date(0, MONDAY)
    view.ex_idx = 0
    _type_a_set(view)
    view._save_exercise(0)
    view.finished = True

    assert _said(view._render_finished(), "Registrado en")


# ── 3. everything read "as of" a date follows that exercise ──────────────


def test_the_prefill_asks_against_the_exercises_own_day(view, store):
    """A prefill is one tap from being the record, so it must not read the future.

    Exercise 0 is on Monday: its previous session is the newest row *before
    Monday*. Asking against today would offer Tuesday's numbers for a session
    that, on Monday, had not happened — and that does not look like a bug, it
    looks like a workout.
    """
    view._set_exercise_date(0, MONDAY)
    store.last_sets_asked.clear()
    view._last_sets_cache.clear()
    view._last_sets(0)

    assert store.last_sets_asked, "the prefill never asked the store for anything"
    assert store.last_sets_asked[-1][1] == MONDAY


def test_two_exercises_ask_against_their_two_days(view, store):
    view._set_exercise_date(0, MONDAY)
    view._set_exercise_date(1, TUESDAY)
    store.last_sets_asked.clear()
    view._last_sets_cache.clear()
    view._last_sets(0)
    view._last_sets(1)

    assert [asked[1] for asked in store.last_sets_asked] == [MONDAY, TUESDAY]


def test_moving_a_day_drops_what_was_read_against_the_old_one(view, store):
    """Caches are answers to "as of when". A stale one is a wrong prefill."""
    view._last_sets(0)
    assert 0 in view._last_sets_cache

    view._set_exercise_date(0, MONDAY)
    assert 0 not in view._last_sets_cache


def test_moving_one_exercise_leaves_the_others_reads_alone(view, store):
    """Exercise 1 did not move, so the history it was read against still holds."""
    view._last_sets(1)
    assert 1 in view._last_sets_cache

    view._set_exercise_date(0, MONDAY)
    assert 1 in view._last_sets_cache


def test_changing_the_day_keeps_what_was_typed(view):
    """Half of what Alex asked for: change the day *without losing the numbers*."""
    view.ex_idx = 0
    _type_a_set(view, weight="102.5", reps="6")
    view._set_exercise_date(0, MONDAY)

    rows = view.sets
    assert rows[0]["weight"] == "102.5"
    assert rows[0]["reps"] == "6"


def test_a_row_that_is_only_a_suggestion_is_dropped_when_the_day_moves(view):
    """It came from the old date and would sit on screen contradicting the new one."""
    view.ex_idx = 0
    view._sets_by_ex[0] = [dict(view._blank_set(), weight="60", reps="10", _suggested="1")]
    view._set_exercise_date(0, MONDAY)
    assert 0 not in view._sets_by_ex


# ── going back to the session's day, and expiring by itself ──────────────


def test_an_exercise_can_be_put_back_on_the_session_default(view):
    view._set_log_date(MONDAY)
    view._set_exercise_date(0, TUESDAY)
    assert view._date_for(0) == TUESDAY

    view._clear_exercise_date(0)
    assert view._date_for(0) == MONDAY
    assert view._resolve_date(0).source is DateSource.SESSION


def test_today_on_a_backdated_session_is_a_real_override(view):
    """The case that looks harmless and is not.

    With the session on Monday, "today" for one exercise is a deliberate choice
    and has to be kept — collapsing it to "no override" would quietly file that
    exercise under Monday with the screen still saying today.
    """
    view._set_log_date(MONDAY)
    view._set_exercise_date(0, date.today())

    assert view._date_for(0) == date.today()
    assert view._resolve_date(0).source is DateSource.EXERCISE


def test_finishing_the_session_forgets_the_per_exercise_days(view):
    """`ironflet-web` is a systemd unit: one view instance serves weeks.

    A Monday that outlived its session would be a day nobody chose for the next
    workout, with the strip dutifully reporting it as if they had.
    """
    view._set_exercise_date(0, MONDAY)
    view._reset()
    assert view._dates_by_key == {}
    assert view._any_date_chosen() is False


def test_discarding_the_session_forgets_them_too(view):
    view._set_exercise_date(0, MONDAY)
    view._discard_workout()
    assert view._dates_by_key == {}


def test_starting_another_day_forgets_them(view):
    """A day chosen against one day's exercises describes that day and no other."""
    view._set_exercise_date(0, MONDAY)
    view._start_day(1)
    assert view._dates_by_key == {}


def test_a_choice_left_over_from_yesterday_is_dropped(view, monkeypatch):
    """The dangerous failure is not picking the wrong day. It is a right one kept."""
    import views.workout as workout_module

    view._set_exercise_date(0, MONDAY)
    view._sets_by_ex = {}
    view.completed = []
    view.day_idx = -1

    tomorrow = date.today() + timedelta(days=1)

    class Frozen(date):
        @classmethod
        def today(cls):
            return tomorrow

    monkeypatch.setattr(workout_module, "date", Frozen)
    view._ensure_log_date_fresh()
    assert view._dates_by_key == {}


# ── the picker, opened on one exercise ───────────────────────────────────


def test_the_dialog_opens_scoped_to_the_exercise_it_was_tapped_from(view, page):
    view.ex_idx = 1
    view._open_date_dialog(ex_idx=1)
    dlg = _last_dialog(page)
    assert _said(dlg, "Registrar este ejercicio en")
    assert _said(dlg, "Solo se mueve este ejercicio")


def test_the_dialog_bare_is_still_about_the_whole_session(view, page):
    """The day list has always opened it this way and must keep doing so."""
    view._open_date_dialog()
    assert _said(_last_dialog(page), "Registrar este entreno en")


def test_the_dialog_can_switch_from_the_exercise_to_the_session(view, page):
    view._open_date_dialog(ex_idx=0)
    dlg = _last_dialog(page)
    assert _said(dlg, "Este ejercicio")
    assert _said(dlg, "Toda la sesión")


def test_the_dialog_offers_a_way_back_only_when_there_is_one(view, page):
    """A button that would do nothing teaches the wrong lesson about the day."""
    view._open_date_dialog(ex_idx=0)
    assert not _said(_last_dialog(page), "Volver al día de la sesión")

    view._set_exercise_date(0, MONDAY)
    view._open_date_dialog(ex_idx=0)
    assert _said(_last_dialog(page), "Volver al día de la sesión")


def test_no_future_date_survives_the_setter(view):
    """Not taste, arithmetic: every metric in the app skips a row dated ahead."""
    view._set_exercise_date(0, date.today() + timedelta(days=5))
    assert view._date_for(0) <= date.today()


def test_the_day_is_filed_by_name_so_editing_the_routine_cannot_move_it(view):
    """Same invariant as the draft's rows: by exercise, never by position."""
    view._set_exercise_date(0, MONDAY)
    assert set(view._dates_by_key) == {_keys(view)[0]}
    assert active_routine().id == DEFAULT_ROUTINE


# ── the whole-session note follows the sets, not the default ─────────────


def test_the_session_note_lands_on_the_day_the_sets_did(view, store):
    """`notas_sesion` is keyed by date alone, so one day has to be picked.

    Date every exercise to Monday one by one and the session default is still
    today — so the note about that workout would be filed against a day with no
    sets in it, while Monday, which has them, stayed silent.
    """
    saved: list = []
    store.set_session_note = lambda note, day=None: saved.append((note, day)) or note
    store.get_session_note = lambda day=None: ""

    for idx in range(len(_keys(view))):
        view._set_exercise_date(idx, MONDAY)
    view.ex_idx = 0
    _type_a_set(view)
    view._save_exercise(0)
    view._save_session_note("gym packed")

    assert saved == [("gym packed", MONDAY)]


def test_a_two_day_sitting_keeps_the_note_on_the_session_default(view, store):
    """The note covers both days and no rule picks a winner honestly."""
    saved: list = []
    store.set_session_note = lambda note, day=None: saved.append((note, day)) or note
    store.get_session_note = lambda day=None: ""

    view.ex_idx = 0
    _type_a_set(view)
    view._set_exercise_date(0, MONDAY)
    view._save_exercise(0)
    view.ex_idx = 1
    _type_a_set(view)
    view._save_exercise(1)
    view._save_session_note("two days at once")

    assert saved == [("two days at once", date.today())]


def test_the_note_block_names_the_day_it_will_use(view, store):
    """Whichever day it picked, the caption says so — it is never left implicit."""
    store.get_session_note = lambda day=None: ""
    for idx in range(len(_keys(view))):
        view._set_exercise_date(idx, MONDAY)
    view.ex_idx = 0
    _type_a_set(view)
    view._save_exercise(0)

    assert _said(view._session_note_block(), _date_label(MONDAY))
