"""The gym tools on the exercise screen: target, progression, plates, ramp, history.

Five features and one rule that binds all of them, taken from how these apps are
actually used in a gym: **nothing may block a set.** The research Alex ran on
Hevy, Strong and Boostcamp is unambiguous — a dialog that goes up while the rest
timer runs, with the phone on the floor and wet hands, is the worst interaction
the app can offer. So every test here that opens something also asserts that no
`AlertDialog` was opened, and the two panels that unfold assert they unfold
*without a rebuild*, because a rebuild under an open keyboard takes the caret out
of the number being typed.

None of this needs PostgreSQL. `WorkoutView` reaches for five `Storage` methods
on this path and a dict-backed fake covers all five, so the file runs in
milliseconds on a machine with no database — which also makes the "the database
is down" tests honest rather than theoretical.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import flet as ft
import pytest

from data import set_active_routine
from gym_tools import DEFAULT_INVENTORY, loadable_options
from progression import Action
from set_types import SetType, set_type_of
from storage import WorkoutEntry
from views.workout import HISTORY_SESSIONS, WorkoutView

# ── doubles ──────────────────────────────────────────────────────────────


class FakeStore:
    """Just enough `Storage` for the exercise screen, with the failure modes.

    `history` is keyed by canonical exercise name; anything not in it has never
    been trained. `fail` makes every read raise, which in web mode is a normal
    Tuesday — the app talks to PostgreSQL over the network.
    """

    def __init__(self, history: dict[str, list[WorkoutEntry]] | None = None, fail: bool = False):
        self.prefs: dict[str, str] = {}
        self.history = history or {}
        self.fail = fail

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        if self.fail:
            raise RuntimeError("database unreachable")
        return self.prefs.get(key, default)

    def set_pref(self, key: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("database unreachable")
        self.prefs[key] = value

    def get_last_sets(self, exercise: str, before=None):
        if self.fail:
            raise RuntimeError("database unreachable")
        entries = self.history.get(exercise)
        return list(entries[-1].sets) if entries else None

    def get_exercise_history(self, exercise: str, limit: int = 20):
        if self.fail:
            raise RuntimeError("database unreachable")
        return list(self.history.get(exercise, []))[-limit:]


def sessions(exercise: str, weight: float, reps: int, days_ago: tuple[int, ...], sets: int = 4):
    """`sets` identical sets of `weight`×`reps`, one session per entry in `days_ago`."""
    today = date.today()
    return [
        WorkoutEntry(
            date=(today - timedelta(days=gap)).isoformat(),
            exercise=exercise,
            muscle_group="Push",
            phase=1,
            sets=[{"weight": weight, "reps": reps} for _ in range(sets)],
        )
        for gap in sorted(days_ago, reverse=True)  # oldest first, as Storage returns them
    ]


@pytest.fixture
def page():
    p = MagicMock()
    p.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": MagicMock(),
        "set_routine": lambda r: None,
    }
    return p


def make_view(page, store, *, routine: str = "recomp-ppl-ul", phase: int = 1, day: int = 0):
    set_active_routine(routine)
    page.data["store"] = store
    view = WorkoutView(page, store)
    view.phase_id = phase
    view._start_day(day)
    # `_start_day` refreshes; the tests care about refreshes they cause.
    page.data["refresh_current"].reset_mock()
    return view


# ── walking a built control tree ─────────────────────────────────────────


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


def _visible_texts(control) -> list[str]:
    """Only what is actually on screen.

    Not `_walk` plus a `visible` filter: a folded panel is a hidden *container*
    full of perfectly visible children, and filtering leaf by leaf would report
    them all as on screen. This stops descending the moment it meets something
    switched off, which is what the user's eye does.
    """
    out: list[str] = []

    def descend(ctrl, seen):
        if ctrl is None or id(ctrl) in seen or not getattr(ctrl, "visible", True):
            return
        seen.add(id(ctrl))
        if isinstance(ctrl, ft.Text) and ctrl.value:
            out.append(ctrl.value)
        for attr in ("content", "title", "leading", "trailing"):
            child = getattr(ctrl, attr, None)
            if isinstance(child, ft.Control):
                descend(child, seen)
        for attr in ("controls", "actions"):
            children = getattr(ctrl, attr, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    if isinstance(child, ft.Control):
                        descend(child, seen)

    descend(control, set())
    return out


def _fields(control) -> list[ft.TextField]:
    return [c for c in _walk(control) if isinstance(c, ft.TextField)]


def _dialogs_opened(page) -> list:
    """Every `AlertDialog` handed to `page.open` — the thing that must stay empty."""
    return [
        call.args[0]
        for call in page.open.call_args_list
        if call.args and isinstance(call.args[0], ft.AlertDialog)
    ]


BENCH = "Barbell Bench Press"


@pytest.fixture
def trained(page):
    """Bench pressed to the top of the range: the double-progression jump is due."""
    store = FakeStore({BENCH: sessions(BENCH, 80.0, 8, (10, 7, 3))})
    return make_view(page, store), store


# ── 1. the prescribed target, on the row ─────────────────────────────────


def test_every_working_row_says_what_it_is_aiming_at(trained):
    """The scheme is in the title and the RIR in the phase notes — neither is on
    screen during the set. This is the line that puts both on the row."""
    view, _ = trained
    targets = [view._row_target(i, row) for i, row in enumerate(view.sets)]
    assert targets, "the exercise rendered no rows at all"
    assert all(t == "→ 5-8 @ RIR 2-3" for t in targets), targets


def test_the_target_reaches_the_screen(trained):
    view, _ = trained
    assert "→ 5-8 @ RIR 2-3" in _visible_texts(view.build())


def test_a_warm_up_row_claims_no_target():
    """A warm-up has no prescribed reps and no RIR. Printing the work set's
    target next to it would be an instruction to grind an approach set."""
    p = MagicMock()
    p.data = {"navigate_to": lambda i, **k: None, "refresh_current": MagicMock()}
    view = make_view(p, FakeStore({BENCH: sessions(BENCH, 80.0, 8, (3,))}))
    view._add_warmup_sets()
    warm = [(i, r) for i, r in enumerate(view.sets) if set_type_of(r) is SetType.WARMUP]
    assert warm, "the ramp inserted nothing"
    assert all(view._row_target(i, r) == "" for i, r in warm)


def test_a_pyramid_gives_each_row_its_own_number(page):
    """`[5×12,10,8,8,8]` is five different targets, and the row is the only
    place a per-set target can be read."""
    store = FakeStore()
    # CambiaTuFísico phase 5 opens on `Barbell Bench Press [5×12,10,8,8,8]`.
    view = make_view(page, store, routine="cambiatufisico", phase=5, day=0)
    raw = view._current_exercise_raw()
    if "," not in raw:  # pragma: no cover - the routine changed
        pytest.skip(f"first exercise of this day is not a pyramid: {raw}")
    view.sets = [view._blank_set() for _ in range(5)]
    targets = [view._row_target(i, r) for i, r in enumerate(view.sets)]
    assert len(set(targets)) > 1, targets


class _BarePhase:
    """A phase that prescribes nothing at all. There is no such phase in
    `data.py` — every one of the 348 exercise strings parses — so the honest
    degradation path has to be built rather than found."""

    id = 1
    name = "Bare"
    notes = ""
    subtitle = ""
    scheme = ""


def test_no_scheme_means_no_invented_rep_range(page):
    """Silence, not a guess.

    All three sources of a rep range are cut here — the exercise name has no
    `[4×5-8]`, the phase states no scheme, and the recommendation is absent,
    which is the shape of a database that will not answer. What survives is
    the RIR, and it survives because `progression` genuinely inherits it from
    the last phase that stated one. Nothing is made up to fill the gap.
    """
    view = make_view(page, FakeStore())
    view._current_exercise_raw = lambda: "Something With No Scheme"
    view._phase = lambda: _BarePhase()
    view._rec_cache[0] = None
    target = view._row_target(0, view._blank_set())
    assert "5-8" not in target
    assert target == "→ RIR 2-3"


# ── 2. the suggested progression ─────────────────────────────────────────


def test_the_jump_is_offered_before_the_first_set(trained):
    """Top of the range on every set last time → go up, and say so where it is
    read before anything is lifted."""
    view, _ = trained
    rec = view._recommendation(0)
    assert rec.action is Action.ADD_WEIGHT
    assert rec.weight == 82.5
    assert "Go up · 82.5 kg × 5-8" in _visible_texts(view.build())


def test_the_reason_is_folded_away_and_never_a_dialog(trained, page):
    """`reason` quotes last session's real numbers. It is worth having and it is
    not worth a modal: one tap unfolds it in place."""
    view, _ = trained
    tree = view.build()
    assert "Go up · 82.5 kg × 5-8" in _visible_texts(tree)
    assert view._reason_text.visible is False
    view._toggle_reason()
    assert view._reason_text.visible is True
    assert "80 kg" in view._reason_text.value
    assert _dialogs_opened(page) == []
    # And it did NOT rebuild the screen: the keyboard stays where it is.
    assert page.data["refresh_current"].call_count == 0


def test_without_history_nothing_is_invented(page):
    """The whole point of `Action.BASELINE`: no history, no weight. The card
    explains what to look for instead of printing a number nobody measured."""
    view = make_view(page, FakeStore())
    rec = view._recommendation(0)
    assert rec.action is Action.BASELINE
    assert rec.weight is None
    shown = _visible_texts(view.build())
    assert any(t.startswith("First time") for t in shown), shown
    # The explanation opens by default here, because it is the only content.
    assert any("baseline" in t for t in shown)


def test_the_banner_leaves_once_the_first_working_set_is_in(trained):
    """It is a planning surface. After set one it would be occupying the screen
    to answer a question that has been answered."""
    view, _ = trained
    assert any(t.startswith("Go up") for t in _visible_texts(view.build()))
    view._update_set(0, "reps", "8")  # typing claims the row
    assert view._has_confirmed_work() is True
    assert not any(t.startswith("Go up") for t in _visible_texts(view.build()))


def test_a_dead_database_still_renders_the_exercise(page):
    """Every read on this path is wrapped. A recommendation that cannot be
    computed costs the banner, never the screen."""
    view = make_view(page, FakeStore(fail=True))
    tree = view.build()
    assert _texts(tree), "the screen came back empty"
    assert view._exercise_history(0) == []


# ── 3. the plate calculator ──────────────────────────────────────────────


def test_the_plates_are_written_under_the_weight(trained):
    view, _ = trained
    assert view._plate_hint("80") == "20 + 10 per side"
    assert "20 + 10 per side" in _visible_texts(view.build())


def test_an_impossible_weight_names_both_neighbours(trained):
    """The honest answer to "can I load 81?" is "no — 80 or 82.5", which is
    exactly what has to be known *before* walking to the rack."""
    view, _ = trained
    hint = view._plate_hint("81")
    assert hint.startswith("not loadable · ")
    assert "80 kg" in hint and "82.5 kg" in hint


def test_a_weight_under_the_bar_says_so(trained):
    view, _ = trained
    assert view._plate_hint("12") == "under the bar · 20 kg is the lightest"


def test_the_bare_bar_is_named_not_left_blank(trained):
    view, _ = trained
    assert view._plate_hint("20") == "empty 20 kg bar"


def test_dumbbells_and_cables_get_no_plate_maths(page):
    """There are no plates on a dumbbell rack. A confident breakdown there
    would be arithmetic to ignore, which is worse than no line at all."""
    view = make_view(page, FakeStore())
    for idx, name in enumerate(view._current_day().exercises):
        view.ex_idx = idx
        if view._is_barbell(name):
            continue
        assert view._plate_hint("30") == "", name
        break
    else:  # pragma: no cover - the routine changed
        pytest.skip("this day has no non-barbell exercise")


def test_the_ez_bar_is_used_for_curls(page):
    """A 7.5 kg EZ bar read as a 20 kg Olympic one moves every curl by 12.5 kg."""
    view = make_view(page, FakeStore(), day=2)  # Pull day, holds EZ Bar Curl
    names = view._current_day().exercises
    idx = next((i for i, n in enumerate(names) if "EZ" in n), None)
    if idx is None:  # pragma: no cover - the routine changed
        pytest.skip("no EZ bar exercise on this day")
    view.ex_idx = idx
    assert view._bar_for_current().weight == 7.5


def test_typing_updates_the_hint_without_rebuilding_the_screen(trained, page):
    """The reason this is a text line and not a dialog, and the reason it is
    refreshed in place: a `refresh_current()` on every keystroke rebuilds the
    field being typed into and drops the caret out of the number."""
    view, _ = trained
    tree = view.build()
    weight_field = _fields(tree)[0]
    hints = [c for c in _walk(tree) if isinstance(c, ft.Text) and c.value == "20 + 10 per side"]
    assert hints, "the first row showed no plate hint to begin with"

    event = MagicMock()
    event.control.value = "100"
    weight_field.on_change(event)

    assert hints[0].value == "20 + 20 per side"  # 100 kg is 40 a side
    assert view.sets[0]["weight"] == "100"
    assert page.data["refresh_current"].call_count == 0
    assert _dialogs_opened(page) == []


def test_the_rack_in_the_preferences_is_the_one_used(page):
    """A gym with no 1.25s cannot make 81.25, and the hint must not pretend."""
    store = FakeStore({BENCH: sessions(BENCH, 80.0, 8, (3,))})
    store.prefs["plates"] = "20x2,10x2,5x2,2.5x2"
    view = make_view(page, store)
    assert view._plate_hint("82.5").startswith("not loadable")
    # And with the default rack it is perfectly loadable, so the difference is
    # the preference and not the arithmetic.
    assert loadable_options(82.5, view._bar_for_current(), DEFAULT_INVENTORY).loadable


def test_an_unreadable_plate_preference_falls_back_instead_of_breaking(page):
    store = FakeStore({BENCH: sessions(BENCH, 80.0, 8, (3,))})
    store.prefs["plates"] = "not a plate list at all"
    view = make_view(page, store)
    assert view._plate_hint("80") == "20 + 10 per side"


def test_a_silly_bar_preference_is_refused(page):
    """ "200" in the bar field is a typo for a plate. Honouring it would make
    every hint on every exercise read "not loadable"."""
    store = FakeStore({BENCH: sessions(BENCH, 80.0, 8, (3,))})
    store.prefs["bar_kg"] = "200"
    view = make_view(page, store)
    assert view._bar_for_current().weight == 20


def test_a_real_bar_preference_is_honoured(page):
    store = FakeStore({BENCH: sessions(BENCH, 80.0, 8, (3,))})
    store.prefs["bar_kg"] = "15"
    view = make_view(page, store)
    assert view._bar_for_current().weight == 15


# ── 4. the automatic warm-up ─────────────────────────────────────────────


def test_one_tap_inserts_the_whole_ramp(trained):
    view, _ = trained
    before = len(view.sets)
    view._add_warmup_sets()
    added = [r for r in view.sets if set_type_of(r) is SetType.WARMUP]
    assert 2 <= len(added) <= 4
    assert len(view.sets) == before + len(added)
    # In front, in the order they are performed, and climbing.
    weights = [float(r["weight"]) for r in view.sets[: len(added)]]
    assert weights == sorted(weights)


def test_every_ramp_weight_can_actually_be_loaded(trained):
    """A 43.7 kg warm-up is worse than useless: it is arithmetic mid-session."""
    view, store = trained
    view._add_warmup_sets()
    bar = view._bar_for_current()
    for row in view.sets:
        if set_type_of(row) is not SetType.WARMUP:
            continue
        options = loadable_options(row["weight"], bar, view._plate_inventory)
        assert options is not None and options.loadable, row


def test_the_ramp_stays_under_the_work_weight(trained):
    view, _ = trained
    view._add_warmup_sets()
    work = view._warmup_target()
    assert all(float(r["weight"]) < work for r in view.sets if set_type_of(r) is SetType.WARMUP), (
        view.sets
    )


def test_ramp_rows_are_offered_not_claimed(trained):
    """They are sets the app proposes and the user has not done. Writing them
    in confirmed would put warm-ups he never performed into `entrenos` on the
    next Save."""
    view, _ = trained
    view._add_warmup_sets()
    warm = [r for r in view.sets if set_type_of(r) is SetType.WARMUP]
    assert all(view._is_suggested(r) for r in warm)
    assert view._has_confirmed_work() is False


def test_the_ramp_aims_at_the_recommendation_not_at_last_time(trained):
    """The plan says 82.5 today. Ramping to last session's 80 leaves the last
    approach short of the weight actually being lifted."""
    view, _ = trained
    assert view._warmup_target() == 82.5


def test_a_weight_he_typed_beats_the_recommendation(trained):
    view, _ = trained
    view._update_set(0, "weight", "70")
    assert view._warmup_target() == 70.0


def test_the_button_disappears_once_the_ramp_is_in(trained):
    """Pressing it twice by accident must not stack two ramps."""
    view, _ = trained
    assert any(t.startswith("Add ") and "warm-up" in t for t in _visible_texts(view.build()))
    view._add_warmup_sets()
    assert not any(t.startswith("Add ") and "warm-up" in t for t in _visible_texts(view.build()))


def test_the_button_is_gone_once_the_exercise_has_started(trained):
    view, _ = trained
    view._update_set(0, "reps", "8")
    assert not any(t.startswith("Add ") and "warm-up" in t for t in _visible_texts(view.build()))


def test_no_ramp_where_there_are_no_plates(page):
    """A machine stack has nothing to solve for, and a "37.5 kg" approach on a
    stack that steps in fives is exactly the arithmetic this removes."""
    view = make_view(page, FakeStore())
    for idx, name in enumerate(view._current_day().exercises):
        view.ex_idx = idx
        if not view._is_barbell(name):
            assert view._warmup_plan() == [], name
            break
    else:  # pragma: no cover - the routine changed
        pytest.skip("this day has no non-barbell exercise")


def test_no_history_and_no_typed_weight_means_no_ramp(page):
    """`warmup_plan` is a percentage of a working weight. With no working
    weight the honest output is nothing, not a ramp off an invented number."""
    view = make_view(page, FakeStore())
    assert view._warmup_target() is None
    assert view._warmup_plan() == []
    assert not any(t.startswith("Add ") for t in _visible_texts(view.build()))


def test_the_ramp_shows_in_zen_mode(trained):
    """Zen strips *reference material*, and zen is on by default. Hiding an
    action that deletes itself after the first set would hide it always."""
    view, _ = trained
    assert view.zen is True
    assert any(t.startswith("Add ") and "warm-up" in t for t in _visible_texts(view.build()))


def test_adding_the_ramp_opens_nothing(trained, page):
    view, _ = trained
    view._add_warmup_sets()
    assert _dialogs_opened(page) == []


def test_a_ramp_survives_a_killed_process_without_forging_a_set(page):
    """The draft path, which the ramp deliberately does not change.

    A suggestion is written to the draft as an empty slot — that invariant is
    what stops a restored screen from claiming a weight nobody lifted — so the
    ramp comes back as an offer and not as work. What must not happen is a
    crash, a row of junk, or warm-ups landing in `entrenos` unasked; the button
    is still on screen, so redoing the ramp is one tap.
    """
    store = FakeStore({BENCH: sessions(BENCH, 80.0, 8, (3,))})
    view = make_view(page, store)
    view._add_warmup_sets()
    view._update_set(len(view.sets) - 1, "reps", "7")  # real work, so a draft is written
    view._persist_draft()

    revived = WorkoutView(page, store)
    revived.on_show()
    assert revived.day_idx == 0, "the draft did not restore — the rest proves nothing"
    for row in revived.sets:
        assert set(row) <= {"weight", "reps", "rir", "type", "_suggested"}, row
    assert _texts(revived.build())
    # The point: no warm-up came back *claimed*. A confirmed row is one the
    # user stood behind, and a restore may not promote an offer into one.
    warm = [r for r in revived.sets if set_type_of(r) is SetType.WARMUP]
    assert all(revived._is_suggested(r) for r in warm), warm


# ── 5. the exercise's own history, without leaving ───────────────────────


def test_the_last_sessions_are_one_tap_away(trained):
    view, _ = trained
    tree = view.build()
    assert "Last 3 sessions" in _visible_texts(tree)
    # Folded: mounted, so it can be unfolded in place, but not on screen.
    assert "4 sets" not in _visible_texts(tree)
    assert "4 sets" in _texts(tree)


def test_unfolding_costs_nothing_that_was_typed(trained, page):
    """Requirement 5's real constraint. A rebuild here would close the keyboard
    and drop the caret; flipping `visible` on a mounted control cannot."""
    view, _ = trained
    view._update_set(0, "weight", "82.5")
    tree = view.build()
    field = _fields(tree)[0]
    view._toggle_history()

    assert view._history_body.visible is True
    assert field.value == "82.5", "the field was rebuilt under the user"
    assert view.sets[0]["weight"] == "82.5"
    assert page.data["refresh_current"].call_count == 0
    assert _dialogs_opened(page) == []


def test_it_shows_at_most_five_sessions(page):
    """Far enough back to see a trend, short enough not to bury the set rows."""
    store = FakeStore({BENCH: sessions(BENCH, 80.0, 8, tuple(range(3, 30, 3)))})
    view = make_view(page, store)
    view._show_history = True
    shown = _visible_texts(view.build())
    assert shown.count("4 sets") == HISTORY_SESSIONS


def test_a_first_time_exercise_offers_no_panel(page):
    view = make_view(page, FakeStore())
    assert not any(t.startswith("Last ") for t in _texts(view.build()))


def test_the_panel_closes_when_the_exercise_changes(trained):
    """It is a question about *this* movement; carrying it open costs 150 px to
    answer a question nobody asked."""
    view, _ = trained
    view._toggle_history()
    assert view._show_history is True
    view._go_next_exercise()
    assert view._show_history is False


# ── 6. plurals ───────────────────────────────────────────────────────────


def test_the_finished_summary_counts_in_english(trained):
    """ "1 sets" and "2 warm-up" both shipped. Every session ends on this screen,
    so it is also where a broken plural is seen every single time."""
    view, _ = trained
    view.completed = [
        {
            "exercise": BENCH,
            "sets": [
                {"weight": 40.0, "reps": 8, "type": "warmup"},
                {"weight": 80.0, "reps": 8},
            ],
        },
        {
            "exercise": "Dips",
            "sets": [
                {"weight": 0.0, "reps": 10, "type": "warmup"},
                {"weight": 0.0, "reps": 10, "type": "warmup"},
                {"weight": 0.0, "reps": 10},
                {"weight": 0.0, "reps": 9},
            ],
        },
    ]
    view.finished = True
    shown = _texts(view.build())
    assert "1 set · 1 warm-up" in shown
    assert "2 sets · 2 warm-ups" in shown
    assert not any(t.startswith("1 sets") for t in shown)


def test_one_exercise_logged_reads_as_one(trained):
    view, _ = trained
    view.completed = [{"exercise": BENCH, "sets": [{"weight": 80.0, "reps": 8}]}]
    view.finished = True
    assert "1 exercise logged" in _texts(view.build())


# ── 7. the rule that binds all of it ─────────────────────────────────────


def test_nothing_on_this_screen_opens_a_dialog(trained, page):
    """The one thing the gym research is categorical about. Building the screen
    and using every new control must not put a modal between Alex and his set."""
    view, _ = trained
    view.build()
    view._toggle_history()
    view._toggle_reason()
    view._add_warmup_sets()
    view.build()
    assert _dialogs_opened(page) == []


@pytest.mark.parametrize("routine", ["recomp-ppl-ul", "cambiatufisico"])
def test_every_exercise_of_every_day_renders_and_ramps(page, routine):
    """The sweep. Five new blocks now read the exercise string, the phase prose
    and the plate solver on every render, and each of those has a shape that
    only some exercises have: a pyramid, a cluster, an EZ bar, a bodyweight
    movement with no load to solve for, a composite with a `+` in its name.

    A unit test on the bench press proves none of that. This walks all of it —
    every day of every phase of both routines, every exercise, ramp included —
    and asserts only that nothing raises and nothing comes back blank. It is
    the cheap version of the thing the tests kept missing: what Alex sees on
    the phone, on the exercise he actually opened.
    """
    from data import active_routine, set_active_routine

    set_active_routine(routine)
    program = active_routine()
    for phase in program.phases:
        for day_idx, day in enumerate(program.days_for_phase(phase.id)):
            view = make_view(page, FakeStore(), routine=routine, phase=phase.id, day=day_idx)
            for ex_idx, raw in enumerate(day.exercises):
                view.ex_idx = ex_idx
                assert _texts(view.build()), f"{routine} p{phase.id} d{day_idx}: {raw}"
                # The ramp writes rows, so it is exercised rather than only
                # rendered: a bad row here would be a bad row in `entrenos`.
                view._update_set(0, "weight", "60")
                view._add_warmup_sets()
                for row in view.sets:
                    assert set(row) <= {"weight", "reps", "rir", "type", "_suggested"}, row
                assert _texts(view.build())


# ── "failure on the last set" belongs to one row, and says so once ────────


def _pagina():
    from unittest.mock import MagicMock

    p = MagicMock()
    p.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": MagicMock(),
        "set_routine": lambda r: None,
    }
    return p


def _fila(peso="60", reps="8"):
    return {"weight": peso, "reps": reps}


def test_fase_de_solo_ultima_serie_no_marca_las_demas():
    """CambiaTuFísico phases 2 and 3 prescribe *only* "failure on the last set".

    `RirTarget.label()` renders that as "last set to failure", so printing it
    on every row told set one to go to failure — the opposite of the plan — and
    the last row then read "8-10 @ last set to failure · last to failure",
    which is what showed up on the phone.
    """
    vista = make_view(_pagina(), FakeStore(), routine="cambiatufisico", phase=2)
    vista.sets = [_fila(), _fila(), _fila()]

    lineas = [vista._row_target(i, r) for i, r in enumerate(vista.sets)]

    for texto in lineas[:-1]:
        assert "failure" not in texto, (
            f"a non-final set says {texto!r} — that reads as an order to grind it"
        )
    assert "to failure" in lineas[-1]
    assert lineas[-1].count("failure") == 1, f"clause printed twice: {lineas[-1]!r}"


def test_una_fase_con_rir_general_lo_muestra_en_todas():
    """Phase 1 states "RIR 1+" for every set: that one *is* for all rows."""
    vista = make_view(_pagina(), FakeStore(), routine="cambiatufisico", phase=1)
    vista.sets = [_fila(), _fila(), _fila()]

    lineas = [vista._row_target(i, r) for i, r in enumerate(vista.sets)]
    assert all("RIR" in t for t in lineas), lineas
    assert not any("last to failure" in t for t in lineas)


def test_los_calentamientos_no_llevan_objetivo():
    """A warm-up has no prescribed target and must not borrow the working one."""
    from set_types import TYPE_KEY, SetType

    vista = make_view(_pagina(), FakeStore(), routine="cambiatufisico", phase=2)
    calentamiento = _fila("30", "8")
    calentamiento[TYPE_KEY] = SetType.WARMUP.value
    vista.sets = [calentamiento, _fila(), _fila()]

    assert vista._row_target(0, vista.sets[0]) == ""
    assert vista._row_target(2, vista.sets[2]) != ""
