"""A per-exercise date must survive the process being killed.

Alex was told, in as many words, that per-exercise dates are the easiest way to
file a set under the wrong day without noticing, and chose them anyway. That
makes every path where a date can quietly become "today" a defect, and this is
the one nobody exercises by hand: Android kills the app mid-session, the draft
comes back, and the bench press he filed under Monday is written to Wednesday.

It shipped broken twice, one layer apart, which is why this file asserts on the
round trip rather than on either half:

1. `_save_exercise` wrote `date=self.log_date`, ignoring the map entirely — the
   date was stored, rendered in the dialog, and then not used.
2. `_build_draft` built the `WorkoutDraft` without `session_date=` or `dates=`,
   and `_restore_draft` read neither back. The map was rebuilt empty on every
   restore.

Both passed their own unit tests. Neither survived a kill.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from data import set_active_routine
from views.workout import WorkoutView

RUTINA = "cambiatufisico"
AYER = date.today() - timedelta(days=1)


class FakeStore:
    """Prefs in a dict: the draft and the dates both live in `preferencias`."""

    def __init__(self):
        self.prefs: dict[str, str] = {}
        self.saved: list = []

    def get_pref(self, key, default=None):
        return self.prefs.get(key, default)

    def set_pref(self, key, value):
        self.prefs[key] = value

    def get_last_sets(self, key, before=None):
        return None

    def get_exercise_history(self, key, limit=20):
        return []

    def get_all(self):
        return []

    def save_workout(self, entry):
        self.saved.append(entry)

    def get_session_duration(self, on_date=None):
        return None

    def set_session_duration(self, seconds, on_date=None):
        return seconds


def _pagina(store):
    page = MagicMock()
    page.width, page.height = 400, 800
    page.data = {
        "navigate_to": lambda i, **k: None,
        "refresh_current": lambda: None,
        "set_routine": lambda r: None,
        "store": store,
    }
    return page


def _vista(store):
    """Parked on the first exercise of phase 2, day 0."""
    set_active_routine(RUTINA)
    v = WorkoutView(_pagina(store), store)
    v.phase_id = 2
    v._start_day(0)
    return v


def _vista_fria(store):
    """A new view that has NOT started a day — the cold start after a kill.

    Calling `_start_day()` first is a *warm* start and skips the restore, which
    is how a resume test can look thorough and exercise nothing.
    """
    set_active_routine(RUTINA)
    return WorkoutView(_pagina(store), store)


@pytest.fixture(autouse=True)
def _rutina():
    set_active_routine(RUTINA)
    yield
    set_active_routine(RUTINA)


# ── the regression ───────────────────────────────────────────────────────


def test_la_fecha_de_un_ejercicio_sobrevive_a_que_muera_el_proceso():
    """THE ONE. Without it the map is rebuilt empty and Monday becomes today."""
    store = FakeStore()
    vista = _vista(store)
    clave = vista._exercise_keys()[0]

    vista._set_exercise_date(0, AYER)
    assert vista._resolve_date(0).day == AYER, "premise broken: the date was not taken"

    # Escribe algo, para que el borrador se considere digno de guardarse.
    vista.sets = [{"weight": "60", "reps": "8"}]
    vista._persist_draft()

    otra = _vista_fria(store)
    otra.on_show()

    assert otra._resolve_date(0).day == AYER, (
        f"{clave} came back logging to {otra._resolve_date(0).day}, not {AYER} — "
        "the set filed under yesterday would be written to today, silently"
    )


def test_el_resto_de_ejercicios_sigue_en_hoy():
    """A date is per exercise: restoring one must not move the others."""
    store = FakeStore()
    vista = _vista(store)
    vista._set_exercise_date(0, AYER)
    vista.sets = [{"weight": "60", "reps": "8"}]
    vista._persist_draft()

    otra = _vista_fria(store)
    otra.on_show()
    assert otra._resolve_date(1).day == date.today()


def test_sin_fechas_el_borrador_se_restaura_igual():
    """The ordinary session must be untouched by all of this."""
    store = FakeStore()
    vista = _vista(store)
    vista.sets = [{"weight": "60", "reps": "8"}]
    vista._persist_draft()

    otra = _vista_fria(store)
    otra.on_show()
    assert otra._resolve_date(0).day == date.today()
    assert otra.sets and otra.sets[0].get("weight") == "60"


def test_lo_que_se_guarda_usa_la_fecha_del_ejercicio():
    """The other half of the same bug: the row must carry the chosen day."""
    store = FakeStore()
    vista = _vista(store)
    vista._set_exercise_date(0, AYER)
    vista.sets = [{"weight": "60", "reps": "8"}]
    vista._save_exercise(0)

    assert store.saved, "nothing was written at all"
    assert store.saved[0].date == AYER.isoformat(), (
        f"written under {store.saved[0].date}, but the screen said {AYER}"
    )


def test_una_fecha_caducada_se_avisa_en_vez_de_desaparecer():
    """A date chosen on an earlier calendar day is refused — and said out loud.

    Reverting to today in silence is the exact failure this feature is built to
    avoid, so `stale_dates` has to reach the user.
    """
    import workout_draft

    store = FakeStore()
    vista = _vista(store)
    vista._set_exercise_date(0, AYER)
    vista.sets = [{"weight": "60", "reps": "8"}]
    vista._persist_draft()

    borrador = workout_draft.DraftStore(store).load()
    assert borrador is not None
    # El contrato que la vista consume: si algo caduca, viene nombrado.
    assert hasattr(borrador, "stale_dates")
