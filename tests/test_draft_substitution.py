"""Restoring a draft with a swap in force must not duplicate the row.

`entrenos.ejercicio` holds the movement Alex actually performed, so with a
substitution in force the prescribed key and the logged key differ on purpose:
the slot says "Leg Press", the row says "Hack Squat". Exactly one function in
the repo turns a position into the logged key — `WorkoutView._performed_key`,
which routes through `substitutions.key_to_log`.

The restore path did not use it. It compared the *prescribed* key against the
set of exercises already written, so a swapped position never matched, came
back looking unlogged, and saving again wrote a **second** row for the same day:
one under Hack Squat, one under Leg Press. Nothing raises — the history simply
splits in two, which is the failure `exercise_key()` exists to prevent.

Android killing the app mid-session is the case this matters in, and it is the
one case nobody exercises by hand.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import substitutions
from data import set_active_routine
from exercises import exercise_key
from substitutions import Scope, set_substitution
from views.workout import WorkoutView

RUTINA = "cambiatufisico"


class FakeStore:
    """Prefs in a dict — enough for the draft and the substitution state."""

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
    """A view parked on the first exercise of phase 2, day 0."""
    set_active_routine(RUTINA)
    v = WorkoutView(_pagina(store), store)
    v.phase_id = 2
    v._start_day(0)
    return v


def _vista_fria(store):
    """A brand-new view that has NOT started a day — the cold-start path.

    This is what `main.py` does after Android kills the process: construct the
    view and call `on_show()`. Calling `_start_day()` first would be a warm
    start, and the restore is skipped there — which is how a test can look like
    it exercises the resume and quietly exercise nothing.
    """
    set_active_routine(RUTINA)
    return WorkoutView(_pagina(store), store)


@pytest.fixture(autouse=True)
def _limpio():
    substitutions.reset_cache()
    yield
    substitutions.reset_cache()
    set_active_routine(RUTINA)


def _primero_sustituible(vista):
    """A position whose exercise has at least one valid alternative."""
    for i in range(len(vista._exercise_keys())):
        crudo = vista._prescribed_raw(i)
        opciones = substitutions.alternatives(exercise_key(crudo))
        if opciones:
            return i, exercise_key(crudo), opciones[0]
    pytest.skip("no exercise in this day has an alternative")


# ── the regression ───────────────────────────────────────────────────────


def test_una_posicion_sustituida_se_reconoce_como_registrada():
    """THE SPLIT. Prescribed key != logged key, so raw matching never fired."""
    store = FakeStore()
    vista = _vista(store)
    idx, prescrito, alt = _primero_sustituible(vista)
    realizado = getattr(alt, "name", None) or getattr(alt, "key", None) or str(alt)

    set_substitution(store, prescrito, realizado, Scope.TODAY)
    substitutions.reset_cache()
    vista._subs_cache = None

    registrado = vista._performed_key(idx)
    assert registrado == exercise_key(realizado), (
        f"the row would be written as {registrado!r}, not as the movement performed"
    )

    # La premisa: comparar la clave prescrita en crudo NO reconoce la posición.
    claves = vista._exercise_keys()
    assert claves[idx] != registrado, "premise broken: the swap changed nothing"

    # Y ahora el código de verdad. Se guarda un borrador con ese ejercicio ya
    # registrado y se restaura en una vista nueva, que es lo que ocurre cuando
    # Android mata el proceso a mitad de sesión.
    vista.completed = [{"exercise": registrado, "sets": [{"weight": 60, "reps": 8}]}]
    vista._logged_ex = {idx}
    vista._persist_draft()

    substitutions.reset_cache()
    otra = _vista_fria(store)
    otra.on_show()

    assert idx in otra._logged_ex, (
        "the swapped position came back looking unlogged — saving again writes "
        "a second row for the same day and the history splits in two"
    )


def test_sin_sustitucion_la_clave_registrada_es_la_prescrita():
    """The ordinary path must be untouched by the fix."""
    store = FakeStore()
    vista = _vista(store)
    for i in range(len(vista._exercise_keys())):
        assert vista._performed_key(i) == vista._exercise_keys()[i]


def test_la_sustitucion_sobrevive_a_que_muera_el_proceso():
    """It lives in `preferencias`, so a new view must find it again."""
    store = FakeStore()
    vista = _vista(store)
    idx, prescrito, alt = _primero_sustituible(vista)
    realizado = getattr(alt, "name", None) or getattr(alt, "key", None) or str(alt)
    set_substitution(store, prescrito, realizado, Scope.TODAY)

    substitutions.reset_cache()
    otra = _vista(store)  # proceso nuevo, mismo almacén
    otra._subs_cache = None
    assert otra._performed_key(idx) == exercise_key(realizado)


def test_el_historial_no_se_parte_en_dos():
    """Whatever is logged must be a key the app's routines already know.

    Guards the contract `tests/test_exercise_key.py` freezes: a row written
    under a name outside the catalogue is a row the bot cannot match either.
    """
    store = FakeStore()
    vista = _vista(store)
    idx, prescrito, alt = _primero_sustituible(vista)
    realizado = getattr(alt, "name", None) or getattr(alt, "key", None) or str(alt)
    set_substitution(store, prescrito, realizado, Scope.TODAY)
    substitutions.reset_cache()
    vista._subs_cache = None

    registrado = vista._performed_key(idx)
    assert registrado == exercise_key(registrado), "not a canonical key"
    assert registrado, "empty exercise key would be written to entrenos"


# ── scratch state must not ride along in a backup ────────────────────────


def test_las_claves_de_sesion_estan_declaradas_como_efimeras():
    """Every `*_PREF` that holds session state must be in `EPHEMERAL_PREF_KEYS`.

    `backup.py` skips that tuple by name. A key that belongs there and is not
    listed gets exported and restored, which resurrects a workout that ended
    months ago — or, for the notes, drops half a sentence typed in August onto
    whatever exercise is on screen in November.

    Asserted by *name* rather than by importing the view: `workout_draft` and
    `backup` must not import Flet, which is the whole reason the tuple is a
    list of literals.
    """
    from views import workout as w
    from workout_draft import DRAFT_PREF_KEY, EPHEMERAL_PREF_KEYS

    de_sesion = {DRAFT_PREF_KEY, w.LOG_DATE_PREF, w.NOTES_PREF}
    faltan = de_sesion - set(EPHEMERAL_PREF_KEYS)
    assert not faltan, (
        f"session-scoped prefs missing from EPHEMERAL_PREF_KEYS: {sorted(faltan)} — "
        "these would be exported and restored as if they were user data"
    )


def test_las_preferencias_de_verdad_no_son_efimeras():
    """The guard must not swallow real settings: the bar weight and the plate
    inventory describe Alex's gym and *should* survive a restore."""
    from views import workout as w
    from workout_draft import EPHEMERAL_PREF_KEYS

    for clave in (w.BAR_PREF, w.PLATES_PREF, w.ZEN_PREF):
        assert clave not in EPHEMERAL_PREF_KEYS, f"{clave} is a real setting, not scratch"


# ── a note is only worth writing if it comes back ────────────────────────


def test_la_nota_de_la_ultima_sesion_se_ve_al_volver_al_ejercicio():
    """ "Seat on hole 4" is useless unless it appears the next time he is there.

    Until this was wired, the note went into `entrenos.nota` and could be read
    on History and nowhere else — never on the screen where it applies, next to
    the machine it describes.
    """
    from storage import WorkoutEntry

    store = FakeStore()
    vista = _vista(store)
    clave = vista._performed_key(0)

    vista._history_cache[0] = [
        WorkoutEntry(
            date="2026-08-01",
            exercise=clave,
            muscle_group="Chest",
            phase=2,
            sets=[{"weight": 60, "reps": 8}],
            note="Seat on hole 4",
        )
    ]
    vista._last_sets_cache[0] = [{"weight": 60, "reps": 8}]
    vista.ex_idx = 0
    vista.zen = False

    textos = " ".join(_todos_los_textos(vista.build()))
    assert "Seat on hole 4" in textos, "last session's note never reaches the screen"


def test_sin_nota_no_se_pinta_nada():
    """No empty note row: most sessions have no note and that is normal."""
    from storage import WorkoutEntry

    store = FakeStore()
    vista = _vista(store)
    vista._history_cache[0] = [
        WorkoutEntry(
            date="2026-08-01",
            exercise=vista._performed_key(0),
            muscle_group="Chest",
            phase=2,
            sets=[{"weight": 60, "reps": 8}],
            note=None,
        )
    ]
    vista._last_sets_cache[0] = [{"weight": 60, "reps": 8}]
    vista.ex_idx = 0
    vista.zen = False
    vista.build()  # no debe reventar


def _todos_los_textos(control) -> list[str]:
    import flet as ft

    fuera: list[str] = []
    pendientes = [control]
    vistos: set[int] = set()
    while pendientes:
        c = pendientes.pop()
        if id(c) in vistos:
            continue
        vistos.add(id(c))
        if isinstance(c, ft.Text) and c.value:
            fuera.append(str(c.value))
        pendientes.extend(getattr(c, "controls", None) or [])
        contenido = getattr(c, "content", None)
        if contenido is not None:
            pendientes.append(contenido)
    return fuera
