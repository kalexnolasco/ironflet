"""Workout: guided flow phase → day → exercise by exercise."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import date, timedelta

import flet as ft

import abdomen
import extras
from analytics import Record, detect_new_records
from components.timer import RestTimer
from data import active_routine
from dates import day_name, month_name
from exercise_images import image_frames_props, image_props
from exercises import exercise_key, phase_color
from gym_tools import (
    DEFAULT_BAR,
    DEFAULT_INVENTORY,
    Bar,
    PlateInventory,
    WarmupSet,
    bar_for_exercise,
    loadable_options,
    round_to_loadable,
    warmup_plan,
)
from program_week import StartSource, load_program_start
from progression import (
    Action,
    Equipment,
    Recommendation,
    RirTarget,
    Scheme,
    classify_equipment,
    parse_scheme,
    recommend,
    rir_for_phase,
)
from session_plan import ProposedSet, SessionPlan, plan_sets, to_draft_rows
from set_types import (
    TYPE_KEY,
    SetType,
    describir_esquema,
    format_rest,
    label_for,
    next_set_type,
    rest_seconds_for_phase,
    set_type_of,
    short_label_for,
    tag_set,
    warmup_sets,
    working_sets,
)
from storage import (
    MAX_SESSION_SECONDS,
    MIN_SESSION_SECONDS,
    NOTE_MAX_LEN,
    Storage,
    WorkoutEntry,
    clean_note,
    format_duration,
)
from substitutions import (
    Alternative,
    Scope,
    StartingPoint,
    Substitution,
    active_substitutions,
    alternatives,
    clear_substitution,
    key_to_log,
    set_substitution,
    starting_point,
    swap_prescription,
)
from theme import (
    C,
    Radius,
    card,
    chip,
    ghost_button,
    primary_button,
)
from views.help_dialog import help_icon
from views.shared_ui import dialog_height, dialog_width, plural
from workout_draft import (
    MAX_BACKDATE_DAYS,
    DateSource,
    DraftStore,
    LogDate,
    ResolvedDate,
    WorkoutDraft,
    is_blank_row,
)

#: `get_exercise_history` keeps the last 20 sessions by default. A record has to
#: beat *everything*, so ask for the whole history of the exercise — otherwise a
#: best from 21 sessions ago is forgotten and the app invents a PR.
_PR_HISTORY_LIMIT = 100_000

#: Preference keys for the gym's own hardware, both plain strings in
#: `preferencias` (see `views/profile.py`). Neither needs a schema change, which
#: is why they are preferences and not columns — the shared-database rule in
#: CLAUDE.md makes a new column a two-repo commit.
#:
#: `bar_kg` is the *fallback* bar and `plates` is `PlateInventory.to_text()`.
#: Both are optional: absent or unreadable falls back to the 20 kg Olympic bar
#: and the default Spanish-gym rack, which is what Alex actually trains on.
BAR_PREF = "bar_kg"
PLATES_PREF = "plates"

#: How many past sessions the in-place history panel shows. Five covers a
#: month of a twice-weekly movement — far enough back to see a trend, short
#: enough to read without scrolling past the set rows.
HISTORY_SESSIONS = 5

#: How much history the recommendation reads. `progression.recommend` only
#: looks at the last two sessions, but the panel above shares this one query
#: (one round-trip per exercise instead of two), so it asks for the panel's
#: worth plus a little slack.
HISTORY_LIMIT = 12

#: A row seeded from the previous session carries this key until the user
#: vouches for it. **Present means "suggested, not lifted yet"; absent means
#: confirmed.** Absent-is-confirmed is the safe default for `_blank_set()` — a
#: row typed from scratch is by definition the user's own — and it keeps every
#: pre-existing code path correct without extra bookkeeping.
#:
#: It never reaches the database: `_parse_set` builds a fresh dict out of
#: weight/reps/rir/type and copies nothing else.
_SUGGESTED_KEY = "_suggested"

#: Preference key for zen mode. Values are "on"/"off"; anything unrecognised —
#: including a missing row, or a database that will not answer — reads as ON,
#: because focus is what Alex asked for and a storage hiccup must not silently
#: put the food diary back in front of him mid-set.
ZEN_PREF = "zen_mode"

#: Preference key holding the date the session in progress is being logged to.
#:
#: The value is ``"<log date>|<the calendar day the choice was made on>"``, both
#: ISO. The second half is not decoration: it is what makes a forgotten choice
#: expire by itself, because a date chosen yesterday can never be adopted today.
#: See `_load_log_date`.
#:
#: Its own key rather than a field on `WorkoutDraft` for two reasons. The draft
#: payload is versioned (`DRAFT_VERSION`) and shared with `backup.py`'s skip
#: list, so a new field there is a format bump; and this value is re-validated
#: on read anyway, so the two can never disagree in a way that costs a date.
LOG_DATE_PREF = "workout_log_date"

#: Preference key holding the notes typed during the session in progress.
#:
#: The value is JSON: ``{"date": "<log date>", "notes": {<exercise key>: text}}``.
#: Its own key rather than a field on `WorkoutDraft` for exactly the reason
#: `LOG_DATE_PREF` is one — the draft payload is versioned (`DRAFT_VERSION`) and
#: named in `backup.py`'s skip list, so a new field there is a format bump in a
#: module this screen does not own.
#:
#: Only **exercise** notes live here, and only until their exercise is written.
#: A session note has a table of its own (`notas_sesion`) and needs no workout
#: row, so it goes straight to the database the moment it is typed; an exercise
#: note lives *inside* the `entrenos` row (`entrenos.nota`) and therefore cannot
#: be stored until that row exists.
NOTES_PREF = "workout_notes"

#: How much of a note the collapsed chip shows. Long enough to recognise which
#: note it is, short enough not to wrap on a 420 px row.
NOTE_PREVIEW_CHARS = 48

# MAX_BACKDATE_DAYS — how far back a session may be filed — is **imported from
# `workout_draft`, not redeclared here**.
#
# Alex's case is "I forgot my phone": hours, or a couple of days. A month is
# generous for that and still refuses the realistic typo — `2025-08-16` for
# `2026-08-16` is a year-old date that would move the inferred program start
# (see `_backdate_warnings`) and drag the Plan screen with it, and it is far
# easier to catch here than to undo later.
#
# It moved because `clamp_log_date` and `LogDate.in_window` enforce the same
# window on the draft's own dates. Two copies of the number would be two
# windows, and the one that disagreed would only be found by a date this screen
# accepted and the restore silently threw away. The import re-exports it, so
# `from views.workout import MAX_BACKDATE_DAYS` still resolves.

#: The longest session the minutes field will take, as minutes. Derived, never
#: retyped: `storage.clean_duration` is the thing that actually refuses, and a
#: field that let a value through only to have the write reject it would be a
#: worse error message in a worse place.
MAX_SESSION_MINUTES = MAX_SESSION_SECONDS // 60


def _num_text(value) -> str:
    """A stored number as the text a field shows — `82.5` → "82.5", `80.0` → "80".

    Three programs write `entrenos.series`, so the value may not be a number at
    all; `:g` on a string is a crashed screen. Anything unusable becomes an
    empty field, which is exactly what the user should see.
    """
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value).strip()


def _num_value(text) -> float | None:
    """A field's text as a number, or None. The inverse of `_num_text`.

    Kept here rather than reaching for `gym_tools._num`: that one is private,
    and this side has its own rule — a comma is a decimal point, because the
    Android keyboard on a Spanish phone offers a comma and typing "82,5" is
    not a mistake anybody should be punished for.
    """
    if isinstance(text, bool) or text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    try:
        return float(str(text).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _date_label(day: date, today: date | None = None) -> str:
    """A logging date as the phrase that goes on screen.

    Deliberately not an ISO string. "2026-08-16" is a number to decode; "Sat 16
    Aug · 2 days ago" is read at a glance, which is the whole job of the warning
    strip this feeds. `views/nutrition_view.py` already words its day header
    this way, so the two screens say "Yesterday" the same.
    """
    today = today or date.today()
    gap = (today - day).days
    if gap == 0:
        return "Hoy"
    if gap == 1:
        return "Ayer"
    stamp = f"{day_name(day.weekday())} {day.day} {month_name(day.month - 1)}"
    if gap < 0:
        # Only reachable from a hand-edited preference row: `_set_log_date`
        # clamps and the dialog refuses. Say something true rather than
        # "-3 days ago".
        return f"{stamp} · en el futuro"
    return f"{stamp} · hace {gap} días"


def _set_type_color(set_type: SetType) -> str:
    """Colour for a set type, resolved at render time.

    Not a module-level dict: `C.*` returns the *current* palette's value, so a
    table built at import time would freeze whichever theme was active then.
    """
    if set_type is SetType.WARMUP:
        return C.warning
    if set_type is SetType.DROPSET:
        return C.accent_2
    if set_type is SetType.FAILURE:
        return C.danger
    return C.text_muted


class WorkoutView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        # The store is handed over rather than left to `RestTimer._store_ref()`
        # to dig out of `page.data`: this view already holds it, and the timer
        # needs it to know whether the rest alert is muted. The alert itself —
        # sound, haptics, the ten-second warning — is entirely `timer.py`'s;
        # this view only decides *when* a rest starts.
        self.timer = RestTimer(page, store)
        #: Owns the write policy for the draft (coalesced while typing,
        #: immediate on a tap) and every rule about when a draft is too old or
        #: no longer fits the routine. Never raises at this caller.
        self._drafts = DraftStore(store)

        self.phase_id: int = 0
        self.day_idx: int = -1
        self.ex_idx: int = 0
        #: El buscador de ejercicios, cuando está abierto. `handle_back` lo
        #: mira antes que nada: sin esto, un back con el diálogo puesto sale de
        #: la pantalla del ejercicio y lo deja flotando sobre la lista del día.
        self._add_dialog: ft.AlertDialog | None = None
        #: Sesión de solo abdomen, para los días sin pesas. Alex pidió abdomen
        #: «cada día» y entrena cuatro o cinco: sin esto, «cada día» sería «los
        #: días que voy al gimnasio».
        self.solo_abdomen: bool = False
        #: Sesión sin rutina: solo los ejercicios que Alex ha elegido hoy.
        #: «Llego al gimnasio sin plan y hago cuatro cosas», que hasta ahora
        #: obligaba a entrar por una fase y fingir que tocaba pecho.
        self.libre: bool = False
        #: Pedido por `empezar_libre` cuando no hay nada elegido: el buscador
        #: se abre en el primer `build`, que es cuando ya hay `page` con la
        #: pantalla montada debajo.
        self._abrir_buscador_al_pintar: bool = False
        # Draft rows are kept PER EXERCISE. One shared `self.sets` list was the
        # bug behind "I changed exercise and it reset": stepping to the next
        # movement threw the half-typed rows on the floor, unsaved and without
        # a word. `sets` below is now a window onto this buffer.
        self._sets_by_ex: dict[int, list[dict[str, str]]] = {}
        # Last session per exercise, memoised. Two reasons, not one: it halves
        # the database round-trips per render, and it pins what "LAST SESSION"
        # means for the whole workout — without it, walking back to an exercise
        # already logged today would show *today* as its own previous session.
        self._last_sets_cache: dict[int, list[dict] | None] = {}
        # Exercise indexes already written to `entrenos` in this session.
        # `save_workout` INSERTs, it does not upsert, so a second press on an
        # exercise already logged would fork today's history into two rows.
        self._logged_ex: set[int] = set()
        # Past sessions of each exercise, and the recommendation built from
        # them. Memoised for the same two reasons `_last_sets_cache` is: one
        # database round-trip per exercise instead of one per render, and a
        # recommendation that cannot change under the user halfway through the
        # exercise it is describing. Both are keyed by position and both are
        # dropped by `_ensure_scope`.
        self._history_cache: dict[int, list] = {}
        self._rec_cache: dict[int, Recommendation | None] = {}
        # What `session_plan.plan_sets` says each exercise opens with. Memoised
        # like the two above and for the third of the same reasons: the plan is
        # read on every render (the row targets come off it) and it must not
        # change under the user halfway through the exercise it describes.
        self._plan_cache: dict[int, SessionPlan | None] = {}
        # `substitutions.starting_point` for a swapped exercise. Two
        # `recommend_from_store` calls live behind it, so it is memoised like
        # everything else on this path rather than run on every render.
        self._start_cache: dict[int, StartingPoint | None] = {}
        # Substitutions in force, keyed by the *prescribed* exercise. `None`
        # means "not read yet"; an empty dict means "read, and there are none",
        # which is the 99 % case and must cost no round-trip to re-establish.
        self._subs_cache: dict[str, Substitution] | None = None
        # Exercise notes typed but not yet written, keyed by position. They go
        # into `entrenos.nota` with the sets when the exercise is saved, and
        # straight through `set_exercise_note` when it already is.
        self._notes_by_ex: dict[int, str] = {}
        # Is the note box unfolded? Same shape as `_show_history` below: a mode,
        # reset when the exercise changes, flipped in place without a rebuild.
        self._show_note: bool = False
        self._note_body: ft.Control | None = None
        self._note_chip: ft.Text | None = None
        # The whole-session note for `log_date`. It lives in `notas_sesion`, not
        # in a workout row, so it is read from and written to the database
        # directly; `None` here means "not read yet", which is not "empty".
        self._session_note_cache: str | None = None
        # Is the "last sessions" panel unfolded? A single flag, not one per
        # exercise: it is a mode ("show me the numbers"), and it is reset when
        # the exercise changes so it never silently costs screen height on a
        # movement he did not ask about.
        self._show_history: bool = False
        # Controls whose *visibility* is flipped in place, without rebuilding
        # the tree. That is the whole point: a rebuild under an open keyboard
        # takes the focus and the caret with it, mid-number.
        self._history_body: ft.Control | None = None
        self._history_arrow: ft.Icon | None = None
        self._reason_text: ft.Control | None = None
        # (routine, phase, day) the buffer describes. `main.set_routine()`
        # rewrites `phase_id`/`day_idx` on this instance from the outside, so
        # the buffer has to be able to notice on its own that it now belongs to
        # a different workout — see `_ensure_scope`.
        self._scope: tuple = ()
        self.completed: list[dict] = []
        self.finished: bool = False
        # Going back is now *screen* navigation, not a state reset: while these
        # are True the workout underneath stays fully intact, `day_idx` and
        # `phase_id` included, so walking out and back in costs nothing.
        self.show_day_list: bool = False
        self.show_phase_list: bool = False
        # Zen mode. Default on, and deliberately NOT read from storage here:
        # `__init__` runs for all nine views at start-up and this is the one
        # flag whose value only matters once a day is actually open, where
        # `_arm_zen` reads it. See `hides_nav` for what it costs the shell.
        self.zen: bool = True

        # The date every set of this session is written under. Today until Alex
        # says otherwise, and back to today the moment the session it belonged
        # to is over — see the "Fecha de registro" block below for the full rule.
        self.log_date: date = date.today()
        # The real calendar day on which `log_date` was last chosen. `None` means
        # "never chosen", i.e. plain today, and is the state a fresh view is in.
        self._log_date_chosen_on: date | None = None
        # Per-exercise overrides of the two lines above, keyed by the exercise's
        # canonical name — never by position, for the reason `pending` is keyed
        # that way: editing the routine must not move Monday onto a different
        # movement. Empty is the ordinary state; every exercise then inherits
        # `log_date`. Resolution lives in `WorkoutDraft.resolve_date`, never
        # here — see `_date_state`.
        self._dates_by_key: dict[str, LogDate] = {}
        # `{iso date: seconds}` for every day that was ever timed, read through
        # `Storage.get_duration_map()` — one query, no limit. `None` is "not
        # read yet", which is **not** the same as "nothing timed"; a day simply
        # missing from the dict is the normal "that session was never timed".
        # Dropped by `_forget_durations()` after every write so the summary
        # screen always paints what the table actually holds.
        self._duration_cache: dict[str, int] | None = None

        # Image animation state (frame-swap loop)
        self._anim_tick_id: int = 0
        self._anim_image: ft.Image | None = None
        #: Both frames, mounted at once. The animation toggles `visible`
        #: between them instead of re-sending the picture — see `_animate_loop`.
        self._anim_layers: list[ft.Image] = []
        self._anim_frames: tuple[str, str] | None = None

        # The gym's hardware, read from `preferencias` once per workout — see
        # `_ensure_gear`. `None` means "not read yet", which is not the same as
        # "no preference": the plate hint runs on every keystroke and must
        # never turn a character into a database round-trip.
        self._plate_inventory: PlateInventory | None = None
        self._bar_override: float | None = None

        # Session chronometer
        #: True once the clock's own answer actually reached the table. NOT the
        #: same as "the clock was entitled to answer": an existing row is never
        #: overwritten, and the caption has to describe the number on screen
        #: rather than the one that would have been written.
        self._duration_written: bool = False
        self.session_started_at: float | None = None
        self.session_ended_at: float | None = None
        self._session_tick_id: int = 0
        self._session_label: ft.Text | None = None

    def on_show(self):
        """Pick an interrupted workout back up.

        The session used to live in memory only: a page reload, the phone going
        to sleep or a `systemctl restart` lost it whole. The draft is written on
        every state change and this is where it comes back — but only when
        nothing is already open here, because live state always beats a
        snapshot of itself.
        """
        if self.phase_id or self.day_idx >= 0 or self.completed or self.finished:
            return
        self._restore_draft()

    def handle_back(self) -> bool:
        """Unwind one screen. It must never cost a single logged number.

        On Android this fires on an edge swipe nobody meant, and Esc on the
        desktop is one key away from everything. It used to wipe `ex_idx` and
        `completed` — the whole day's progress — on the way out of a workout.
        Now every step only changes *screen*: the workout state stays put and
        is waiting, on the same exercise, when the user walks back in.
        Abandoning a session is `_ask_discard`, an explicit button behind a
        confirmation, and nothing else.
        """
        if self._add_dialog is not None:
            self._cerrar_add(self._add_dialog)
            return True
        if self.finished:
            self._reset()
            self.page.data["refresh_current"]()
            return True
        if self.solo_abdomen or self.libre:
            # No hay lista de días a la que volver — ni el abdomen ni un
            # entreno libre salen de ninguna fase—, así que el paso atrás es
            # salir del modo. Se guarda el borrador primero: lo tecleado es lo
            # mismo de valioso aquí que en una sesión de pesas.
            self._persist_draft()
            self.solo_abdomen = False
            self.libre = False
            self.show_phase_list = True
            self.page.data["refresh_current"]()
            return True
        if self._on_exercise_screen():
            self.show_day_list = True
            self._persist_draft()
            self.page.data["refresh_current"]()
            return True
        if self.phase_id > 0 and not self.show_phase_list:
            self.show_phase_list = True
            self.page.data["refresh_current"]()
            return True
        return False

    def _on_exercise_screen(self) -> bool:
        return (
            self.phase_id > 0
            and self.day_idx >= 0
            and not self.show_day_list
            and not self.show_phase_list
            and not self.finished
        )

    # ── Zen mode ──────────────────────────────────────────────
    #
    # Alex: "al momento de poner una rutina se tendría que poner en modo ZEN de
    # IronFlet, ya que si estoy entrenando no veré otra cosa de esa app... lo que
    # sí, puede que cambie de música."
    #
    # Two halves, and the second one bounds the first. Inside IronFlet, while he
    # is training, nothing but the training. Outside it, **nothing may get in his
    # way** — so zen mode is a layout, and only a layout. It does not pin the app
    # in the foreground, it does not go immersive-fullscreen, it does not touch
    # the system bars and it does not intercept the back gesture. Leaving for
    # Spotify has to cost exactly what it costs today, and it does: this code
    # cannot make it cost anything, because it never asks the OS for anything.
    #
    # What it actually removes is the bottom navigation bar (`hides_nav`, which
    # `main.py` honours) and the reference material on the exercise screen — the
    # animated form image, the "LAST SESSION" chips, the prefill explainer. All
    # of that is worth having when planning a workout and is noise at rep seven.
    # What it *adds* is size: the exercise, the next set and the rest left get
    # big enough to read with the phone on the floor.
    #
    # WHAT ZEN MODE DOES NOT DO, AND CANNOT: keep the screen awake.
    #
    # The phone still dims and locks mid-set, and no amount of Python here will
    # change that on Flet 0.28.3. This was checked rather than assumed:
    #
    #   * The Dart client answers exactly nine `page._invoke_method` names
    #     (`reducers.dart`), all of them clipboard/url/window-on-desktop. None
    #     touches the screen.
    #   * `grep -rn wakelock` over the installed `flet` Dart package returns
    #     nothing — the client never calls `WakelockPlus`, even though
    #     `GeneratedPluginRegistrant.java` *does* register `WakelockPlusPlugin`,
    #     so the plugin is sitting in the APK with no caller.
    #   * The only `wakelock` in the Python package is a property of `Video`,
    #     and `Video` has no implementation in this client's Dart side at all.
    #
    # Re-verified against the installed 0.28.3 while wiring up the gym tools,
    # because "the screen must stay on" was asked for again and a second-hand
    # answer is not an answer:
    #
    #   * `flet.core.page.Page` exposes no screen/wake/keep-awake member of any
    #     kind, and `flet.core.window` does not exist in this version — the
    #     desktop window API lives on `Page` and is desktop-only regardless.
    #   * `_invoke_method` is still called with exactly those nine names.
    #   * `wakelock` still appears in precisely one Python file,
    #     `flet/core/video.py`, as an attribute of a control this client cannot
    #     render.
    #
    # There is no supported call, and there is no unsupported one either — Flet
    # 0.28.3 offers no JavaScript evaluation, so even the web build cannot ask
    # the browser for a Screen Wake Lock. **The app cannot keep the screen on.
    # Anything that claimed otherwise would be pretending.**
    #
    # Where it *is* solved, because it is closer than it looks and because the
    # answer must not read as "impossible" when it is only impossible from here:
    # `build/flutter/pubspec.yaml` already carries `wakelock_plus: ^1.2.10`, so
    # the plugin has been shipping inside the APK with nobody calling it. Three
    # lines of Dart close that, and `tool.flet.template.url` accepts a plain
    # local directory — which is what `build_template/` in this repo is. Its
    # `lib/main.dart` calls `WakelockPlus.enable()` on Android and iOS at
    # start-up. **That is a build-system change, not a Python one**, which is
    # exactly why there is no code for it in this file rather than a stub
    # pretending to do something.
    #
    # The mitigation this view owns either way: the rest timer beeps and
    # vibrates at zero, so a screen that did go dark never means a missed set.
    # That is why the mute button survives the decluttering in `build_large()`.

    def _zen_pref(self) -> bool:
        """The remembered choice. Missing, unreadable or junk all read as ON."""
        raw = None
        with contextlib.suppress(Exception):
            raw = self.store.get_pref(ZEN_PREF, "on")
        return (raw or "on").strip().lower() not in ("off", "0", "false", "no")

    def _set_zen(self, on: bool, *, persist: bool = True):
        self.zen = bool(on)
        if persist:
            # Never at the caller's expense: a preference that will not save is
            # a cosmetic loss, and this runs on the tap that starts a workout.
            with contextlib.suppress(Exception):
                self.store.set_pref(ZEN_PREF, "on" if self.zen else "off")

    def _arm_zen(self, *, fresh_day: bool):
        """Decide zen on the way into the exercise screen.

        `fresh_day=True` — he just picked a day, which is literally the moment
        Alex described ("al momento de poner una rutina"), so zen goes on and is
        written down. That also re-arms it for the next workout after a session
        where he stepped out of it, which is the behaviour he asked for.

        `fresh_day=False` — resuming: back from the day list, or rebuilt from
        the draft after the app died. Neither is a new workout, so the stored
        choice wins and an opt-out survives both, including a crash mid-set.
        """
        if fresh_day:
            self._set_zen(True)
        else:
            self._set_zen(self._zen_pref(), persist=False)

    def _toggle_zen(self, _=None):
        self._set_zen(not self.zen)
        # Through `refresh_current`, not `page.update()`: the whole point is that
        # `main.py` re-reads `hides_nav()` on rebuild and shows or hides the bar.
        self.page.data["refresh_current"]()

    def hides_nav(self) -> bool:
        """Should the shell hide its bottom navigation bar right now?

        Read by `main.py` after every `build()`. Deliberately narrow: only the
        exercise screen. The day list, the phase list and the summary all keep
        the bar, so backing out of a set is always a way back to the rest of the
        app — zen mode can never become a room with no door.
        """
        return self.zen and self._on_exercise_screen()

    # ── Logging date ──────────────────────────────────────────
    #
    # Alex: "podamos actualizar para un dia anterior... la sesion ... osea que
    # se pueda cambiar el día... por ejemplo a veces nos olvidamos el movil y al
    # llegar a casa quiero actualizar el entreno."
    #
    # The data layer was never the obstacle: `WorkoutEntry` has carried a `date`
    # since the first commit and `Storage.save_workout` writes whatever it is
    # given. This view simply hardcoded `date.today()`. So the feature is a
    # choice, a place to make it, and — the part that actually matters — a
    # guarantee that it is never made by accident.
    #
    # WHERE IT LIVES. On the day-select screen, one line above the day cards.
    # That is the last screen before a session starts and the only one already
    # asking "which workout is this", so the date belongs in the same breath as
    # the day. Putting it on the exercise screen would tax every ordinary
    # workout with a control that is wrong 95 % of the time; putting it behind
    # Finish would ask the question after the answer stopped being changeable
    # without thought. The exercise screen therefore shows a small "Today" chip
    # (so the setting is still reachable from inside a session, one tap, no
    # navigation) and, when the date is *not* today, a full-width warning strip
    # that no layout — zen mode included — is allowed to hide.
    #
    # WHEN IT GOES BACK TO TODAY. The dangerous failure is not picking the wrong
    # date. It is picking the right one on Tuesday and finding it still set on
    # Wednesday: a whole session filed under a stale day, nothing on screen
    # saying so, in the one part of the app whose entire job is to be a faithful
    # record. So the choice is scoped to a session *and* to a day:
    #
    #   * `_reset()` and `_discard_workout()` clear it — finishing or abandoning
    #     a workout ends the only thing the date belonged to;
    #   * `_ensure_log_date_fresh()`, run from `build()`, clears it as soon as
    #     the real calendar day has moved on and no workout is open;
    #   * the persisted copy carries the day the choice was made on, so a draft
    #     restored the next morning comes back logging to *that* morning.
    #
    # A live session is deliberately exempt from the day-rollover rule. A
    # backdated session that is still open sits behind a warning strip that
    # cannot be missed, and yanking its date away at midnight — the 22:30 to
    # 00:10 session `workout_draft` already reasons about — would be a change
    # nobody asked for and nobody would see.
    #
    # NO FUTURE DATES. Not taste, arithmetic: `analytics.training_streak` skips
    # rows dated after today, `Storage.get_week_stats` filters them out of the
    # trailing week, and `program_week.last_workout_date` ignores them. A
    # session logged for next Tuesday would be written, reported as saved, and
    # then counted by nothing at all — a silent no-op, which is the worst answer
    # available. There is also nothing to log: a workout you have not done yet
    # has no sets. The picker refuses, and says why.
    #
    # WHAT ELSE MOVES WHEN THE DATE MOVES. Two things, both real, both surfaced
    # in the dialog by `_backdate_warnings` rather than left to be discovered:
    # the weekly streak counts the session in the week the date falls in (not
    # this one), and — when the program start is being *inferred* from the
    # earliest logged session — a date older than that start moves the whole
    # program back and can change the week Plan reports.
    #
    # ── ONE DATE PER EXERCISE ─────────────────────────────────────────────
    #
    # Alex: *"hoy es miércoles, pero quiero poner mi entreno del lunes y
    # martes"* — two sessions, one sitting. So the date is no longer one value
    # for the whole workout: `log_date` is now the session **default**, and
    # `_dates_by_key` holds the exercises that were filed somewhere else.
    #
    # He was told, in as many words, that this is the easiest possible way to
    # put a set on the wrong day without noticing, and chose it anyway. **The
    # mitigation is therefore the feature**, and it is three rules:
    #
    #   1. `resolve_date` never returns a bare date. It returns a `ResolvedDate`
    #      carrying a `DateSource`, so nothing on screen can print a day without
    #      saying whether it belongs to this exercise or to the whole session. A
    #      reader who has to *attribute* a date is a reader who will attribute
    #      it wrong.
    #   2. Once any date is in play, **every exercise screen carries its own day
    #      line** — including the exercises that resolve to today. That is
    #      `_backdate_strip`, and zen mode does not get to hide it. The
    #      dangerous state is not "Monday is on screen", it is "Monday is on
    #      exercise 2 and nothing on exercise 3 says otherwise".
    #   3. The session says out loud, before the write and again at Finish, when
    #      it spans more than one day (`_dates_in_use`, `_is_multi_day` —
    #      `WorkoutDraft`'s, not a second implementation).
    #
    # WHERE THE RULES LIVE. Not here. `workout_draft.WorkoutDraft` owns the
    # default chain (exercise → session → today), the clamping, the expiry
    # stamp and the multi-day question; this view holds the two fields and asks
    # (`_date_state`). A second copy of "which day does this exercise go to"
    # is exactly how the screen and the restored draft would come to disagree
    # about a day nobody could see was in dispute.
    #
    # ── HOW LONG THE SESSION LASTED ───────────────────────────────────────
    #
    # The chronometer used to be pixels: it ticked, it was read, and it died
    # with the view. `storage.duraciones_sesion` gives it somewhere to go — one
    # row per **day**, never per exercise, because what it measures is one
    # start and one stop.
    #
    # Which makes the back-dating above a problem rather than a detail: filling
    # Monday in on Wednesday, the clock measures how long the typing took. That
    # is not a datum, it is noise wearing a datum's clothes, and averaged into
    # the real ones it never comes out again. So the measurement is **only
    # proposed when nothing was back-dated at all** (`_duration_is_measured`);
    # otherwise the field opens empty and says why. And a session that writes to
    # two days proposes nothing to either: no arithmetic divides one
    # chronometer between two sessions honestly.

    def _min_log_date(self, today: date | None = None) -> date:
        return (today or date.today()) - timedelta(days=MAX_BACKDATE_DAYS)

    def is_backdated(self) -> bool:
        """Is this session being written under a day that is not today?

        Public like `hides_nav`: it is a fact about the view other code (and
        every test in tests/test_workout_date.py) has a right to ask for.
        """
        return self.log_date != date.today()

    def _log_date_text(self) -> str:
        return _date_label(self.log_date)

    def _set_log_date(self, day: date, *, persist: bool = True) -> date:
        """Point the *session* at `day`. Returns the date actually adopted.

        Clamped rather than trusted. The dialog validates and explains before
        ever calling this, so the clamp is for programmatic callers and for the
        day-rollover corner where "today" moved under a value already held.

        Exercises carrying a date of their own are deliberately left alone:
        each was chosen against that exercise, and wiping them from here would
        undo work that is no longer on screen. Same rule, and the same reason,
        as `WorkoutDraft.with_session_date`.
        """
        today = date.today()
        chosen = min(max(day, self._min_log_date(today)), today)
        self.log_date = chosen
        # Choosing today *is* the default state, not a choice to remember: it
        # leaves nothing behind to go stale and nothing to write down.
        self._log_date_chosen_on = None if chosen == today else today
        if persist:
            self._persist_log_date()
        self._forget_dated_reads()
        return chosen

    def _reset_log_date(self, *, persist: bool = True):
        self.log_date = date.today()
        self._log_date_chosen_on = None
        if persist:
            self._persist_log_date()
        self._forget_dated_reads()

    # ── The day of each exercise ──────────────────────────────
    def _session_log_date(self) -> LogDate | None:
        """The session default as `workout_draft` spells it. `None` is today.

        Driven by `log_date` first and the stamp second, **not the other way
        round**. The two are set together by `_set_log_date` and `_load_log_date`
        and can only come apart if something assigns the field directly — and
        when they do, the honest reading of "log_date is Monday, stamp missing"
        is "Monday, chosen just now", never "ignore Monday". Keying off the
        stamp instead made a directly-assigned date invisible to every consumer
        that goes through `resolve_date`, which is all of them: the row would
        still have been written to Monday while the prefill, the recommendation
        and the strip all quietly went on describing today.
        """
        if self.log_date == date.today() and self._log_date_chosen_on is None:
            return None
        return LogDate(self.log_date, self._log_date_chosen_on or date.today())

    def _date_state(self) -> WorkoutDraft:
        """This view's dates, in the object that owns the rules about them.

        Built on demand rather than held, because the two fields behind it are
        the state and this is only a lens onto them — a cached copy would be a
        second place for the dates to live, and the whole point of going through
        `WorkoutDraft` is that there is one.

        Cheap: a dataclass over two small dicts. It buys `resolve_date`,
        `with_date`, `dates_in_use` and `is_multi_day` without a single one of
        their rules being retyped here.
        """
        return WorkoutDraft(
            routine_id=active_routine().id,
            phase_id=self.phase_id,
            day_idx=max(self.day_idx, 0),
            day_name="",
            ex_idx=max(self.ex_idx, 0),
            exercise="",
            session_date=self._session_log_date(),
            dates=dict(self._dates_by_key),
        )

    def _key_at(self, ex_idx: int | None = None) -> str:
        """The **prescribed** key of a position — the one dates are filed under.

        Prescribed, not performed: `fit_to_routine` prunes the draft's date map
        against the routine's own exercises, so a date stored under a
        substitute's name would be dropped on the next restore. The substitution
        decides what goes in `entrenos.ejercicio`; it does not decide which slot
        the user pointed at a day.
        """
        idx = self.ex_idx if ex_idx is None else ex_idx
        keys = self._exercise_keys()
        return keys[idx] if 0 <= idx < len(keys) else ""

    def _resolve_date(self, ex_idx: int | None = None) -> ResolvedDate:
        """Which day an exercise is filed under, **and where that came from**.

        The source is not a nicety: it is what lets the strip say "this exercise
        only" instead of printing a date the reader has to attribute.
        """
        return self._date_state().resolve_date(self._key_at(ex_idx))

    def _date_for(self, ex_idx: int | None = None) -> date:
        """`_resolve_date(...).day`, for the callers that only write a row."""
        return self._resolve_date(ex_idx).day

    def _any_date_chosen(self) -> bool:
        """Has anything in this session been pointed at a day on purpose?

        The switch behind rule 2 in the block above: while this is False the
        ordinary workout pays nothing for the feature, and the moment it is True
        every exercise screen starts carrying its own day line.
        """
        return self._log_date_chosen_on is not None or bool(self._dates_by_key)

    def _dates_in_use(self) -> tuple[date, ...]:
        """Every distinct day this session would write to, oldest first.

        Asked over the whole day's exercises, not only the dated ones: the half
        a per-exercise picker makes easy to forget is the exercises still
        sitting on the default.
        """
        return self._date_state().dates_in_use(self._exercise_keys())

    def _is_multi_day(self) -> bool:
        return len(self._dates_in_use()) > 1

    def _multi_day_text(self) -> str:
        """ "This session writes to 2 days — Mon 17 Aug, Today." or "".

        Said *before* the save, which is the only place it is still cheap.
        """
        days = self._dates_in_use()
        if len(days) < 2:
            return ""
        names = ", ".join(_date_label(d).split(" · ")[0] for d in days)
        return f"Esta sesión escribe en {plural(len(days), 'día')} — {names}."

    def _scope_text(self, resolved: ResolvedDate) -> str:
        """ "this exercise only" / "the whole session" — never left to be guessed."""
        if resolved.source is DateSource.EXERCISE:
            return "solo este ejercicio"
        if self._dates_by_key:
            # Some other exercise was moved, so "the whole session" would be a
            # lie by exactly the amount that matters.
            return "el resto de esta sesión"
        return "toda la sesión"

    def _forget_dated_reads(self, ex_idx: int | None = None):
        """Drop everything that was read *as of* a date that has just moved.

        `_last_sets`, the history, the recommendation, the plan and the
        substitution starting point are all answers to "as of the day being
        logged". Leaving them cached after the day changed is how a prefill from
        the wrong side of the move ends up one tap from the history.

        **Typed rows are never touched.** Changing the day of an exercise must
        not cost what is already in the boxes — that is half of what Alex asked
        for. Rows that are still nothing but suggestions *are* dropped, because
        those came from the old date and would otherwise stay on screen
        contradicting the new one; the property re-seeds them on next read.
        """
        if ex_idx is not None:
            targets = {ex_idx}
        else:
            # The session default moved, so everything that *inherits* it did.
            # Exercises with a date of their own did not, and must keep the
            # history they were read against.
            keys = self._exercise_keys()
            targets = {i for i, key in enumerate(keys) if key not in self._dates_by_key}
        for idx in targets:
            for cache in (
                self._last_sets_cache,
                self._history_cache,
                self._rec_cache,
                self._plan_cache,
                self._start_cache,
            ):
                cache.pop(idx, None)
            rows = self._sets_by_ex.get(idx)
            if rows is not None and not any(
                not self._is_suggested(r) and self._has_content(r) for r in rows
            ):
                self._sets_by_ex.pop(idx, None)

    def _set_exercise_date(self, ex_idx: int, day: date) -> date:
        """File one exercise under `day`, leaving everything typed where it is.

        Straight through `WorkoutDraft.with_date`, which clamps into the legal
        window, stamps the choice with today so it can expire by itself, and
        *removes* the override when it lands back on what the exercise would
        inherit anyway — including the case that looks harmless and is not:
        "today" on a session filed under Monday is a real override and is kept.
        """
        key = self._key_at(ex_idx)
        if not key:
            return self._date_for(ex_idx)
        state = self._date_state().with_date(key, day, chosen_on=date.today())
        self._dates_by_key = dict(state.dates)
        self._forget_dated_reads(ex_idx)
        # `force=True`: a date is never a keystroke. Coalescing one opens a
        # window in which the screen says Monday and the stored draft does not.
        self._persist_draft()
        return self._date_for(ex_idx)

    def _clear_exercise_date(self, ex_idx: int) -> date:
        """Put one exercise back on the session default."""
        key = self._key_at(ex_idx)
        if not key or key not in self._dates_by_key:
            return self._date_for(ex_idx)
        self._dates_by_key = dict(self._date_state().without_date(key).dates)
        self._forget_dated_reads(ex_idx)
        self._persist_draft()
        return self._date_for(ex_idx)

    def _persist_log_date(self):
        """Mirror the choice into `preferencias`, or clear the row.

        Never at the caller's expense — this runs on a tap during a workout, and
        a preference that will not save costs a restored date, not a set.
        """
        value = ""
        if self._log_date_chosen_on is not None:
            value = f"{self.log_date.isoformat()}|{self._log_date_chosen_on.isoformat()}"
        with contextlib.suppress(Exception):
            self.store.set_pref(LOG_DATE_PREF, value)

    def _load_log_date(self):
        """Adopt the persisted choice — but only if it was made today.

        Everything else reads as "log to today": an empty row, junk, a date
        chosen on another day, a date outside the allowed window. That is the
        one answer that can never be wrong by surprise, which is the property
        this whole feature is built around.
        """
        raw = ""
        with contextlib.suppress(Exception):
            raw = self.store.get_pref(LOG_DATE_PREF, "") or ""
        today = date.today()
        chosen_iso, _, made_on_iso = str(raw).partition("|")
        try:
            chosen = date.fromisoformat(chosen_iso.strip())
            made_on = date.fromisoformat(made_on_iso.strip())
        except ValueError:
            # `persist` only when there was something to clean up: an empty row
            # is the normal case and must not cost a write on every restore.
            self._reset_log_date(persist=bool(raw))
            return
        if made_on != today or not (self._min_log_date(today) <= chosen <= today):
            self._reset_log_date(persist=True)
            return
        self.log_date = chosen
        self._log_date_chosen_on = made_on

    def _ensure_log_date_fresh(self):
        """Snap back to today once the choice has outlived its session.

        Called from `build()`. `build()` is meant to be a pure render, and this
        is the same exception `_ensure_scope` already is: the state it repairs
        goes stale while nothing is calling anything — the clock passes
        midnight, the app sits on a tab — so the render is the first moment
        anybody could notice.

        Every stamp is checked, not just the session's: a workout dated only per
        exercise has `_log_date_chosen_on is None` and would otherwise keep
        yesterday's choices forever. Newest wins, so one fresh tap keeps the
        whole set alive — the alternative expires half a session and leaves the
        other half on screen looking chosen.
        """
        stamps = [d.chosen_on for d in self._dates_by_key.values()]
        if self._log_date_chosen_on is not None:
            stamps.append(self._log_date_chosen_on)
        if not stamps or max(stamps) == date.today():
            return
        if self._workout_in_progress():
            # Open session: the strip is on screen and the dates are still his.
            return
        self._dates_by_key = {}
        self._reset_log_date()

    def _backdate_warnings(self, chosen: date, entries: list, start) -> list[str]:
        """What choosing `chosen` will do beyond writing the sets.

        Pure: the caller reads the history once when the dialog opens and this
        is re-run on every tap. Both warnings describe behaviour that already
        exists elsewhere in the app and would otherwise be discovered days
        later, in Plan or in History, with no way left to connect it to a tap.
        """
        out: list[str] = []
        stamp = chosen.isoformat()
        names = sorted({e.exercise for e in entries if str(getattr(e, "date", "")) == stamp})
        if names:
            shown = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
            out.append(
                f"{plural(len(names), 'ejercicio')} ya registrados ese "
                f"día ({shown}). Guardar añade filas — nunca las reemplaza."
            )
        # Only when the start date is a *guess*. A start Alex pinned himself is
        # a fact and no amount of back-dating moves it.
        if (
            start is not None
            and getattr(start, "source", None) is StartSource.FIRST_WORKOUT
            and start.day is not None
            and chosen < start.day
        ):
            out.append(
                f"Anterior a tu primera sesión registrada ({start.day.isoformat()}), que es "
                "de donde se deduce el inicio del programa — esto lo retrasa y puede cambiar "
                "la semana que muestra Plan."
            )
        return out

    def _open_date_dialog(self, _=None, *, ex_idx: int | None = None):
        """Pick the day a session — or one exercise of it — is filed under.

        Four taps' worth of shortcuts and a typed field, not an `ft.DatePicker`.
        That was checked rather than assumed: Flet 0.28.3 does ship one, it
        renders as a full-screen Material calendar on a phone, and there is not
        one anywhere in this app — `views/plan.py::open_start_date_dialog`
        already declined to introduce the first, for a screen with the same
        shape of question. A month-grid modal to answer "yesterday" is more
        gesture, more surface and more inconsistency for less speed. The four
        buttons cover every case Alex described in one tap; the field covers the
        rest in the app's existing idiom.

        `ex_idx` is the scope it **opens** on, not the only one it can reach:
        the exercise screen passes its own position (that is where the tap came
        from and what the user is looking at), the day list passes nothing, and
        either can be switched to the other in one tap. Defaulting to the
        session when called bare keeps the day-list behaviour it has always had.

        The scope switch is two buttons rather than a segmented control because
        the whole dialog is already built out of `ghost_button`, and a control
        this app owns nowhere else would be a third idiom on a screen that
        exists to stop confusion.

        The history is read **once**, here, and the warnings below it are
        recomputed locally on every tap — so the note is live and the database
        is touched once per dialog, not once per keystroke.
        """
        today = date.today()
        entries: list = []
        start = None
        # A dialog that cannot reach the database still has to let him pick a
        # date; it just cannot warn him about the history it could not read.
        with contextlib.suppress(Exception):
            entries = list(self.store.get_all())
        with contextlib.suppress(Exception):
            start = load_program_start(self.store, entries=entries)

        # The scope is mutable and the closures below read it, so it lives in a
        # one-key dict rather than a name they would each shadow.
        scope: dict[str, int | None] = {"ex": ex_idx}
        ex_name = self._raw_at(ex_idx) if ex_idx is not None else ""

        field = ft.TextField(
            label="Fecha (AAAA-MM-DD)",
            value=self._date_for(ex_idx).isoformat(),
            dense=True,
            color=C.text,
            border_color=C.border_strong,
            focused_border_color=C.accent,
            label_style=ft.TextStyle(color=C.text_secondary),
        )
        blurb = ft.Text("", size=11, color=C.text_secondary, width=300)
        note = ft.Text("", size=11, color=C.warning)
        err = ft.Text("", size=11, color=C.danger)
        dlg = ft.AlertDialog(modal=False)

        def show_note(day: date | None):
            lines = self._backdate_warnings(day, entries, start) if day else []
            note.value = "\n".join(lines)

        def describe():
            if scope["ex"] is None:
                blurb.value = (
                    "El día en que las series se hicieron de verdad. Todo ejercicio al "
                    "que no des un día propio cae bajo él."
                )
            else:
                blurb.value = (
                    f"El día en que {ex_name or 'este ejercicio'} se hizo de verdad. "
                    "Solo se mueve este ejercicio — el resto conserva el día de la sesión."
                )

        def fill(day: date):
            field.value = day.isoformat()
            err.value = ""
            show_note(day)
            self.page.update()

        def pick_scope(target: int | None):
            scope["ex"] = target
            describe()
            field.value = self._date_for(target).isoformat()
            err.value = ""
            show_note(self._date_for(target))
            self.page.update()

        def save(_):
            text = (field.value or "").strip()
            try:
                chosen = date.fromisoformat(text)
            except ValueError:
                err.value = "Usa AAAA-MM-DD"
                self.page.update()
                return
            if chosen > today:
                # Refused, not clamped: see the block comment above. Silently
                # moving the date to today would be the app pretending to obey.
                err.value = (
                    "El futuro no — un entreno que no has hecho no tiene nada que registrar."
                )
                self.page.update()
                return
            if chosen < self._min_log_date(today):
                err.value = f"Demasiado atrás — el límite son {MAX_BACKDATE_DAYS} días."
                self.page.update()
                return
            if scope["ex"] is None:
                self._set_log_date(chosen)
            else:
                self._set_exercise_date(scope["ex"], chosen)
            self.page.close(dlg)
            self.page.data["refresh_current"]()

        def reset_to_session(_):
            if scope["ex"] is not None:
                self._clear_exercise_date(scope["ex"])
            self.page.close(dlg)
            self.page.data["refresh_current"]()

        # Today and Yesterday by name; the two before by weekday, which is how
        # anybody actually remembers a missed session ("that was Saturday").
        shortcuts = [
            ghost_button(
                _date_label(today - timedelta(days=n), today).split(" · ")[0],
                on_click=lambda _, n=n: fill(today - timedelta(days=n)),
                expand=True,
            )
            for n in range(4)
        ]
        describe()
        show_note(self._date_for(ex_idx))

        rows: list[ft.Control] = []
        if ex_idx is not None:
            rows.append(
                ft.Row(
                    [
                        ghost_button(
                            "Este ejercicio",
                            on_click=lambda _: pick_scope(ex_idx),
                            expand=True,
                        ),
                        ghost_button(
                            "Toda la sesión",
                            on_click=lambda _: pick_scope(None),
                            expand=True,
                        ),
                    ],
                    spacing=8,
                )
            )
        rows.append(blurb)
        rows.extend([ft.Row(shortcuts[:2], spacing=8), ft.Row(shortcuts[2:], spacing=8), field])
        if ex_idx is not None and self._key_at(ex_idx) in self._dates_by_key:
            # Only offered when there is an override to undo. A button that
            # would do nothing is a button that teaches the wrong lesson about
            # what the exercise's day currently is.
            rows.append(
                ghost_button(
                    f"Volver al día de la sesión ({self._log_date_text()})",
                    on_click=reset_to_session,
                    expand=True,
                )
            )
        rows.extend([note, err])

        dlg.title = ft.Text(
            "Registrar este entreno en" if ex_idx is None else "Registrar este ejercicio en",
            size=16,
            weight=ft.FontWeight.W_900,
            color=C.text,
        )
        dlg.content = ft.Container(
            content=ft.Column(rows, spacing=10, tight=True, scroll=ft.ScrollMode.AUTO),
            width=dialog_width(self.page),
            height=dialog_height(self.page, 340),
        )
        dlg.actions = [
            ghost_button("Cancelar", on_click=lambda _: self.page.close(dlg)),
            primary_button("Usar esta fecha", on_click=save),
        ]
        dlg.actions_alignment = ft.MainAxisAlignment.END
        dlg.bgcolor = C.bg_surface
        self.page.open(dlg)

    # ── State helpers ─────────────────────────────────────────
    @staticmethod
    def _blank_set() -> dict[str, str]:
        """A fresh draft row.

        The type is kept as the plain string that lands in the database, so the
        draft stays a `dict[str, str]` and `set_type_of` reads it unchanged.
        New rows are normal: it is the 90 % case and the one that costs no taps.
        """
        return {"weight": "", "reps": "", "rir": "", TYPE_KEY: SetType.NORMAL.value}

    # ── Per-exercise draft rows ───────────────────────────────
    def _current_scope(self) -> tuple:
        return (active_routine().id, self.phase_id, self.day_idx)

    def _ensure_scope(self):
        """Drop the buffer as soon as it stops describing this workout.

        `main.set_routine()` rewrites `phase_id` / `day_idx` / `ex_idx` on this
        instance directly, without going through any method here. A buffer that
        only ever reset itself from inside this class would survive that and
        hand one program's exercise 3 the rows typed for another's.
        """
        scope = self._current_scope()
        if scope != self._scope:
            self._scope = scope
            self._sets_by_ex = {}
            self._last_sets_cache = {}
            self._logged_ex = set()
            self._history_cache = {}
            self._rec_cache = {}
            self._plan_cache = {}
            self._start_cache = {}
            self._notes_by_ex = {}
            # Same argument as the notes: a date chosen against one day's
            # exercises describes that day's session and nothing else.
            self._dates_by_key = {}
            # Substitutions are scoped to a routine and a phase, so a scope
            # change can invalidate every one of them at once.
            self._subs_cache = None

    @property
    def sets(self) -> list[dict[str, str]]:
        """Draft rows of the exercise currently on screen.

        Reads *and* writes land in `_sets_by_ex`, so leaving an exercise and
        coming back finds the rows exactly as they were left. Every caller that
        used to treat `self.sets` as a plain list still works unchanged.
        """
        self._ensure_scope()
        rows = self._sets_by_ex.get(self.ex_idx)
        if rows is None:
            rows = self._seed_sets(self.ex_idx)
            self._sets_by_ex[self.ex_idx] = rows
        return rows

    @sets.setter
    def sets(self, rows: list[dict[str, str]]):
        self._ensure_scope()
        self._sets_by_ex[self.ex_idx] = list(rows)

    # ── Substitutions: the machine was busy ───────────────────
    #
    # Everything here is a *caller* of `substitutions.py`. The catalogue, what
    # counts as a legal swap, where the pair is stored and — above all — which
    # name ends up in `entrenos.ejercicio` are all decided there. This view
    # asks; it never derives.
    #
    # The rule that makes the feature safe is one function: `key_to_log()`. A
    # swapped exercise is written to the database under the name of the movement
    # that was **actually performed**, so three weeks later the gap in Leg Press
    # is a gap because the Leg Press was not done — and the Hack Squat row says
    # what was.

    def _subs(self) -> dict[str, Substitution]:
        """Swaps in force for this workout, keyed by prescribed exercise.

        Read once and cached, because this is on the render path and
        `active_substitutions` is a database round-trip. Dropped whenever the
        scope changes or a swap is made, which are the only moments it can go
        stale. A database that will not answer means "sin sustituciones", never a
        dead screen.
        """
        if self._subs_cache is None:
            found: dict[str, Substitution] = {}
            with contextlib.suppress(Exception):
                found = active_substitutions(
                    self.store,
                    routine_id=active_routine().id,
                    phase_id=self.phase_id or None,
                    today=self.log_date,
                )
            self._subs_cache = found
        return self._subs_cache

    def _prescribed_raw(self, ex_idx: int | None = None) -> str:
        """The routine's own string for a position — what the *plan* asked for.

        Kept separate from `_current_exercise_raw`, which answers the different
        question "what is being done". They are the same string until a swap is
        in force, and the whole point of the swap is that they then differ.
        """
        day = self._current_day()
        idx = self.ex_idx if ex_idx is None else ex_idx
        if day and 0 <= idx < len(day.exercises):
            return day.exercises[idx]
        return ""

    def _substitution_at(self, ex_idx: int) -> Substitution | None:
        raw = self._prescribed_raw(ex_idx)
        return self._subs().get(exercise_key(raw)) if raw else None

    def _performed_key(self, ex_idx: int) -> str:
        """**The value that goes into `entrenos.ejercicio`.**

        `substitutions.key_to_log` and nothing else: it is the single function
        in the repo that answers this, and re-deriving it from the cached map
        here would be a second implementation of the one rule that must not have
        two. It degrades to `exercise_key()` on its own when there is no swap.
        """
        raw = self._prescribed_raw(ex_idx)
        if not raw:
            return ""
        with contextlib.suppress(Exception):
            return key_to_log(
                raw,
                store=self.store,
                routine_id=active_routine().id,
                phase_id=self.phase_id or None,
                today=self.log_date,
            )
        return exercise_key(raw)

    def _raw_at(self, ex_idx: int) -> str:
        """The exercise string a position is *training*, brackets kept.

        With a swap in force this is `swap_prescription`'s answer — the
        substitute's name carrying the slot's own scheme — so the plan, the
        rest, the bar and the recommendation all read the prescription of the
        slot while pointing at the movement being done.
        """
        if ex_idx == self.ex_idx:
            # The one on screen goes through `_current_exercise_raw`, which is
            # what every other tool on this screen already reads.
            return self._current_exercise_raw()
        raw = self._prescribed_raw(ex_idx)
        swap = self._substitution_at(ex_idx)
        return swap_prescription(raw, swap.performed) if swap else raw

    def _swap_scopes(self) -> tuple[Scope, ...]:
        """Which scopes may be offered. PHASE needs a phase to belong to."""
        return (Scope.TODAY, Scope.PHASE) if self.phase_id else (Scope.TODAY,)

    def _apply_substitution(self, performed: str, scope: Scope):
        """Record a swap for the exercise on screen and re-read everything.

        The caches are dropped for this position only: the exercise is now a
        different movement, so its history, its last session, its recommendation
        and its plan all belonged to something else. Rows already typed are
        deliberately kept — they are what he just lifted, on the machine he is
        standing at, and the swap is the app catching up with that.
        """
        idx = self.ex_idx
        try:
            set_substitution(
                self.store,
                self._prescribed_raw(idx),
                performed,
                scope,
                routine_id=active_routine().id,
                phase_id=self.phase_id or None,
                today=self.log_date,
            )
        except Exception:
            self._toast("No se pudo guardar el cambio.", ft.Icons.ERROR_OUTLINE, C.danger)
            return
        self._forget_exercise(idx)
        self._toast(
            f"Sustituido por {exercise_key(performed)} — "
            f"{'solo hoy' if scope is Scope.TODAY else 'el resto de esta fase'}.",
            ft.Icons.SWAP_HORIZ,
            C.accent_2,
        )
        self.page.data["refresh_current"]()

    def _clear_current_substitution(self):
        idx = self.ex_idx
        with contextlib.suppress(Exception):
            clear_substitution(
                self.store,
                self._prescribed_raw(idx),
                routine_id=active_routine().id,
                phase_id=self.phase_id or None,
                today=self.log_date,
            )
        self._forget_exercise(idx)
        self.page.data["refresh_current"]()

    def _forget_exercise(self, ex_idx: int):
        """Drop everything memoised about one position — but never typed work.

        A swap makes this position a different movement, so its history, its
        last session, its recommendation and its plan all described something
        else and have to go.

        The rows are the interesting case, and they split in two. Rows that are
        still **suggestions** came from the replaced exercise: leaving them would
        offer the Smith machine's weights on a barbell, one tap from the history,
        which is the exact failure `_seed_sets` is built around. Rows Alex
        **typed** are what he just lifted on the machine he is standing at, and
        no swap may throw those away — so the buffer is only dropped when there
        is nothing of his in it.
        """
        self._subs_cache = None
        self._last_sets_cache.pop(ex_idx, None)
        self._history_cache.pop(ex_idx, None)
        self._rec_cache.pop(ex_idx, None)
        self._plan_cache.pop(ex_idx, None)
        self._start_cache.pop(ex_idx, None)
        rows = self._sets_by_ex.get(ex_idx) or []
        if not any(not self._is_suggested(r) and self._has_content(r) for r in rows):
            self._sets_by_ex.pop(ex_idx, None)

    # ── What the plan opens with ──────────────────────────────

    def _plan(self, ex_idx: int) -> SessionPlan | None:
        """`session_plan`'s answer for one position. None only if it threw.

        Not one rule about how many rows an exercise opens with is written in
        this file. The bracket parsing, the phase fallback, the pyramid, the
        drop tails, the AMRAP rows and the combination-is-one-row decision all
        live in `session_plan.py`, which is tested against the whole routine and
        shared with nothing that can drift from it.
        """
        if ex_idx in self._plan_cache:
            return self._plan_cache[ex_idx]
        plan: SessionPlan | None = None
        raw = self._raw_at(ex_idx)
        if raw:
            # Never worth a dead screen: an unreadable prescription already has
            # a defined answer inside `plan_sets`, and an exception here would
            # only mean the module changed under us.
            with contextlib.suppress(Exception):
                plan = plan_sets(raw, self._phase(), last_session=self._last_sets(ex_idx))
        self._plan_cache[ex_idx] = plan
        return plan

    def _starting_point(self, ex_idx: int) -> StartingPoint | None:
        """Where to start on a substitute, per `substitutions.starting_point`.

        None when nothing is swapped here, which is the usual case. **No weight
        is invented anywhere in this file**: that module refuses to translate
        120 kg of leg press into a squat, and the reference line it returns says
        out loud that the original's number is context and not a target.
        """
        if ex_idx in self._start_cache:
            return self._start_cache[ex_idx]
        swap = self._substitution_at(ex_idx)
        point: StartingPoint | None = None
        if swap is not None:
            with contextlib.suppress(Exception):
                point = starting_point(
                    self.store,
                    self._prescribed_raw(ex_idx),
                    swap.performed,
                    phase=self._phase(),
                    routine=active_routine(),
                    today=self._date_for(ex_idx),
                )
        self._start_cache[ex_idx] = point
        return point

    def _proposal_for_row(self, i: int) -> ProposedSet | None:
        """The plan's row `i`, or None once the user has gone off-plan.

        Matched by *ordinal among non-warm-up rows* rather than by list index:
        the ramp inserts rows in front and `+ Set` appends them, and neither
        moves the plan. An extra row past the end of the plan simply has no
        proposal, which is the honest answer — the plan never asked for it.
        """
        plan = self._plan(self.ex_idx)
        if plan is None or not plan.is_known():
            return None
        rows = self.sets
        if not (0 <= i < len(rows)) or set_type_of(rows[i]) is SetType.WARMUP:
            return None
        ordinal = sum(1 for r in rows[:i] if set_type_of(r) is not SetType.WARMUP)
        return plan.proposals[ordinal] if ordinal < len(plan.proposals) else None

    def _last_sets(self, ex_idx: int) -> list[dict] | None:
        """Previous session of exercise `ex_idx`, read once per workout.

        "Anterior" means the most recent row *before* `log_date`, not the most
        recent row in the table. On a back-dated session those differ, and the
        difference is not academic: log Saturday on Monday having trained
        Sunday, and the prefill offers Sunday's numbers for a session that, on
        Saturday, had not happened. `_seed_sets` writes that straight into the
        weight and reps boxes, and one tap turns a prefill into the record — so
        a wrong answer here does not look like a bug, it looks like a workout.

        "Before" means before **this exercise's** day, not the session's: with
        one exercise filed under Monday and the next under Tuesday, a single
        cut-off would prefill one of them from a session that had not happened
        yet. `_forget_dated_reads` drops this cache whenever that day moves.

        The resolved date is also today on an ordinary session, where "strictly
        before today" is exactly what is wanted anyway: a row already saved for
        today is *this* session, not the previous one.
        """
        if ex_idx in self._last_sets_cache:
            return self._last_sets_cache[ex_idx]
        # The history of the movement being *done*, which is the substitute
        # when one is in force. Prefilling a Hack Squat from the Leg Press it
        # replaced would put a number from a different machine in the box.
        key = self._performed_key(ex_idx)
        if not key:
            return None
        last = None
        # A database hiccup must degrade to "first time, no history", not to a
        # blank screen in the middle of a set.
        with contextlib.suppress(Exception):
            last = self.store.get_last_sets(key, before=self._date_for(ex_idx))
        self._last_sets_cache[ex_idx] = last
        return last

    def _suggested_from(self, one: dict, set_type: SetType | None = None) -> dict[str, str]:
        """One logged set as a muted, unclaimed draft row.

        `set_type` overrides what the stored set says, which is how a row the
        *plan* calls a drop keeps being a drop even when last session logged it
        as an ordinary set. Left None the stored type is kept, which is what a
        warm-up needs.
        """
        row = self._blank_set()
        row["weight"] = _num_text(one.get("weight"))
        row["reps"] = _num_text(one.get("reps"))
        row["rir"] = _num_text(one.get("rir"))
        row[TYPE_KEY] = (set_type or set_type_of(one)).value
        row[_SUGGESTED_KEY] = "1"
        return row

    def _seed_sets(self, ex_idx: int) -> list[dict[str, str]]:
        """Opening rows for an exercise: **the plan's**, filled in from last time.

        Two questions with two different answers, and conflating them is what
        this used to get wrong:

        * **How many rows, of what kind** — the plan's, via `session_plan`. An
          exercise with no history used to open one empty row while the routine
          asked for three, and phase 6's `[4×10,10,8,6+12↓]` opened four
          look-alike rows with the drop set nowhere on screen. The drop now
          arrives already typed as a drop, because `to_draft_rows` carries the
          type across and nothing here overrides it.
        * **What is written in them** — last session's numbers, as suggestions,
          exactly as before. Alex's original complaint was retyping numbers the
          screen was already showing him in `hint_text`, where you can read them
          but not keep them.

        The suggestion half is still the safe half. A prefilled field nobody
        reviews writes a weight he never lifted into `entrenos`, and `analytics`
        turns it into a personal record: zero taps to *see* last time's numbers,
        one tap to claim them, and never a number logged that he did not touch.
        The plan's extra rows arrive blank, which is the visible, honest form of
        "the plan asks for a fifth set and there is nothing to copy into it".

        Warm-ups are kept in front of the plan's rows: the plan prescribes work,
        the ramp up to it is `gym_tools.warmup_plan`'s business, and a session
        that opened with two warm-ups opens with two warm-ups again.
        """
        last = self._last_sets(ex_idx)
        plan = self._plan(ex_idx)

        if plan is None or not plan.is_known():
            # No readable prescription. Falling back to the plan's single row
            # would *lose* rows on a routine whose phases state no scheme, so
            # the pre-plan behaviour stands: one row per set of last session,
            # and one blank row when there is no last session.
            if not last:
                return [self._blank_set()]
            return [self._suggested_from(one) for one in last]

        previous = list(last or [])
        rows = [self._suggested_from(one) for one in previous if set_type_of(one) is SetType.WARMUP]
        # Warm-ups are not prescribed sets, so they are not what the plan's rows
        # are filled from — `session_plan.history_set_count` counts the same way.
        performed = [one for one in previous if set_type_of(one) is not SetType.WARMUP]

        for position, blank in enumerate(to_draft_rows(plan)):
            if position < len(performed):
                # The type is the plan's, never the stored set's: last session
                # may have logged the drop as a normal set, and the plan is the
                # thing that knows it is a drop.
                rows.append(self._suggested_from(performed[position], set_type_of(blank)))
            else:
                rows.append(blank)
        return rows or [self._blank_set()]

    # ── Gym tools: the bar, the rack, the ramp, the recommendation ────
    #
    # Everything below is a *caller* of `gym_tools.py` and `progression.py`.
    # Not one line of plate arithmetic, warm-up percentage or progression rule
    # is written here, and none may be: those two modules are pure, tested and
    # shared with the Telegram coach in ../agente/, and a second copy of any of
    # their rules living in a Flet view is how the app and the coach start
    # telling Alex two different numbers.

    def _ensure_gear(self):
        """Load the bar and the plate inventory from `preferencias`. Once.

        Cached on the instance because `_plate_hint` runs on **every keystroke**
        in a weight field: a `get_pref` there is a database round-trip per
        character, over the network in web mode and over the gym's wifi on the
        phone. Re-read when a day starts (`_start_day`), which is the only
        moment a change made on the Profile screen has to be noticed.

        Both preferences are optional and both degrade to the default rather
        than raising: a corrupt row must cost the *hint*, never the session.
        `PlateInventory.from_text` already falls back on anything unreadable.
        """
        if self._plate_inventory is not None:
            return
        self._plate_inventory = DEFAULT_INVENTORY
        with contextlib.suppress(Exception):
            self._plate_inventory = PlateInventory.from_text(self.store.get_pref(PLATES_PREF))
        with contextlib.suppress(Exception):
            value = _num_value(self.store.get_pref(BAR_PREF))
            # An upper bound as well as a lower one: "200" in the bar field is
            # a typo for a plate weight, and honouring it would make every
            # single hint on every exercise read "no montable".
            if value is not None and 0 < value <= 60:
                self._bar_override = value

    def _bar_for(self, raw: str) -> Bar:
        """The bar this exercise is loaded on.

        `gym_tools.bar_for_exercise` reads the *name* — an EZ curl is a 7.5 kg
        bar, not a 20 — and only falls back to the Olympic default when the
        name says nothing. The stored preference replaces exactly that
        fallback and never a bar the name named: a gym whose straight bars are
        15 kg still curls on the EZ bar.
        """
        self._ensure_gear()
        bar = bar_for_exercise(raw)
        if self._bar_override is not None and bar is DEFAULT_BAR:
            return Bar("Bar", self._bar_override)
        return bar

    def _bar_for_current(self) -> Bar:
        return self._bar_for(self._current_exercise_raw())

    @staticmethod
    def _is_barbell(raw: str) -> bool:
        """Does plate maths mean anything for this exercise?

        `progression.classify_equipment` is the single classifier in the repo;
        deriving it again from the name here would be a second one, and the
        two would drift. A dumbbell has no plates to solve for and a cable
        stack even less, so both the plate hint and the warm-up ramp stay out
        of their way entirely rather than printing confident nonsense.
        """
        return classify_equipment(raw) is Equipment.BARBELL

    def _round_fn(self, raw: str):
        """`progression`'s rounding hook, wired to *this* gym's rack.

        Only for barbells. `round_fn` overrides the whole lookup inside
        `progression.loadable_weight`, so handing it over for a cable stack
        would round a pulley to plate maths — the module's own default already
        rounds those onto their equipment step, which is right.
        """
        if not self._is_barbell(raw):
            return None
        bar, inventory = self._bar_for(raw), self._plate_inventory
        return lambda weight: round_to_loadable(weight, bar, inventory)

    def _exercise_history(self, ex_idx: int) -> list:
        """Past sessions of exercise `ex_idx`, newest last. One query, memoised.

        Shared by the recommendation and by the history panel on purpose: they
        are two views of the same rows, and reading them twice would double the
        round-trips for nothing. A database that will not answer degrades to
        "no history", which every caller here already handles.
        """
        if ex_idx in self._history_cache:
            return self._history_cache[ex_idx]
        rows: list = []
        key = self._performed_key(ex_idx)
        if key:
            with contextlib.suppress(Exception):
                rows = list(self.store.get_exercise_history(key, limit=HISTORY_LIMIT))
        self._history_cache[ex_idx] = rows
        return rows

    def _recommendation(self, ex_idx: int) -> Recommendation | None:
        """What `progression.py` says to do today. None only if it threw.

        `recommend`, not `recommend_from_store`: the history is already in
        hand, and passing it in keeps this to the one query above.

        `today=self._date_for(ex_idx)` is deliberate. The gap rules (hold the
        jump after three weeks, re-enter at 90 % after eight) are about the time
        between *sessions*, so on a back-dated log the question is "how long
        before the day being written", not "before this evening" — and with a
        per-exercise date the day being written is this exercise's, not the
        session's.
        """
        if ex_idx in self._rec_cache:
            return self._rec_cache[ex_idx]
        rec: Recommendation | None = None
        # `_raw_at`, not the routine's own string: with a swap in force the
        # substitute has to be asked with the slot's prescription, so it reads
        # its own history against the plan's sets and reps.
        raw = self._raw_at(ex_idx)
        if raw:
            # Nothing about a recommendation is worth a dead screen mid-set.
            with contextlib.suppress(Exception):
                rec = recommend(
                    raw,
                    self._exercise_history(ex_idx),
                    phase=self._phase(),
                    routine=active_routine(),
                    today=self._date_for(ex_idx),
                    round_fn=self._round_fn(raw),
                )
        self._rec_cache[ex_idx] = rec
        return rec

    def _scheme_and_rir(self) -> tuple[Scheme, RirTarget | None]:
        """The prescribed target, split so a row can print half of it.

        Both halves come from `progression`'s pure readers, so this works with
        the database face-down: the scheme is parsed out of the exercise string
        (`"[4×5-8]"`), falling back to the phase's own, and the RIR out of the
        phase prose — inherited from an earlier phase when this one does not
        restate it, which is how the plan is actually written.
        """
        raw = self._current_exercise_raw()
        phase = self._phase()
        return parse_scheme(raw, getattr(phase, "scheme", "") or ""), rir_for_phase(
            phase, active_routine()
        )

    def _plate_hint(self, weight_text) -> str:
        """One line of plate maths for the weight in a row. "" when it is moot.

        This is the plate calculator, and it is deliberately **not** a control
        you open: it is text that is already on screen next to the number it
        describes. A dialog here would be the single worst interaction in the
        app — it blocks while the rest timer runs, with the phone on the floor
        and the next set starting.

        When the weight cannot be built from the plates in the room the same
        line says both neighbours, which is precisely what has to be known
        *before* walking to the rack.
        """
        raw = self._current_exercise_raw()
        if not self._is_barbell(raw):
            return ""
        if not str(weight_text or "").strip():
            return ""
        self._ensure_gear()
        options = loadable_options(weight_text, self._bar_for(raw), self._plate_inventory)
        if options is None:
            return ""
        if options.exact is not None:
            if options.exact.bar_only:
                return f"barra de {_num_text(options.exact.bar)} kg, sin discos"
            return f"{options.exact.label()} por lado"
        if options.under_bar:
            if options.above is None:
                return ""
            return f"por debajo de la barra · {_num_text(options.above.total)} kg es lo más ligero"
        near = [o for o in (options.below, options.above) if o is not None]
        if not near:
            return ""
        return "no montable · " + " o ".join(f"{_num_text(o.total)} kg" for o in near)

    def _row_target(self, i: int, row: dict) -> str:
        """What row `i` is aiming at: `"→ 5-8 @ RIR 2-3"`. "" when unknown.

        Requirement 1, and the reason it is *per row* rather than one line at
        the top: the set count and rep range live in the exercise title and the
        RIR lives in the phase description, so at the one moment they matter —
        halfway through the set, looking at the row being filled in — neither
        is on screen.

        Two things genuinely differ row by row, which is what earns the line
        its height. A warm-up has no prescribed target and says so by staying
        silent, and a pyramid (`[5×12,10,8,8,8]`) has a different number of
        reps for every set. The last working row also carries the phase's
        "failure on the last set" clause, which belongs on that row and
        nowhere else.

        The per-row number now comes from `session_plan` when it has one, which
        is what lets a drop row and an AMRAP row say what *they* are aiming at —
        `→ 12` under the drop of set 4, `→ max` on a `[3×failure]`. The older
        chain below it is untouched and still answers for any row the plan does
        not cover: a `+ Set` past the end of it, or a routine whose phase
        prescribes nothing at all.
        """
        set_type = set_type_of(row)
        if set_type is SetType.WARMUP:
            return ""
        proposal = self._proposal_for_row(i)
        if set_type is SetType.DROPSET or (proposal is not None and proposal.is_drop()):
            # No RIR on a drop: the load has just been stripped and the row is
            # the tail of the set above it, not a set with a target of its own.
            return f"→ {proposal.reps_label}" if proposal and proposal.reps_label else ""
        if set_type is SetType.FAILURE:
            # "max" is an instruction, not a number, and an RIR beside it would
            # contradict it. `session_plan` leaves these untargeted on purpose.
            label = proposal.reps_label if proposal is not None else ""
            return f"→ {label}" if label else ""
        if set_type is not SetType.NORMAL:
            return ""
        scheme, rir = self._scheme_and_rir()

        # Which *working* set this is. Warm-up rows sit in the same list, so
        # counting rows would tell a pyramid that set 1 is set 4.
        rows = self.sets
        ordinal = sum(1 for r in rows[:i] if set_type_of(r) is SetType.NORMAL)

        # The plan's own answer for this row first. It is the same number the
        # two branches below would reach for a plain range or a pyramid, and it
        # is the only one that stays right once drop rows sit between the
        # working ones — counting NORMAL rows would then hand set 3 set 2's
        # target.
        reps = proposal.reps_label if proposal is not None else ""
        if not reps and scheme.per_set and ordinal < len(scheme.per_set):
            # A pyramid states each set outright — `[5×12,10,8,8,8]` — and that
            # is the most specific thing anyone knows about this row. It is
            # read before the recommendation because `recommend` flattens a
            # pyramid to its min-max when it has no history to shape it with,
            # and "8-12" on set 1 would be losing information the plan gave.
            reps = str(scheme.per_set[ordinal])
        rec = self._recommendation(self.ex_idx)
        if not reps and rec is not None and ordinal < len(rec.per_set):
            target = rec.per_set[ordinal]
            if target.reps_low is not None:
                reps = (
                    str(target.reps_low)
                    if target.reps_low == target.reps_high
                    else f"{target.reps_low}-{target.reps_high}"
                )
        if not reps:
            # `reps_label()` is "5-8 reps"; the word is the column header two
            # lines up, so on a 420 px row it is 5 characters of nothing.
            reps = scheme.reps_label().replace(" reps", "")

        # "Failure on the last set" is a real instruction in several phases and
        # it applies to exactly ONE row, so the clause is resolved per row here
        # rather than taken from `full_label()`, which prints it on all of them.
        #
        # The subtlety that made this wrong twice: when a phase says *only*
        # "failure on the last set" and states no general RIR — CambiaTuFísico
        # phases 2 and 3 — `RirTarget.label()` itself returns "última al
        # fallo". Printing that on row 1 reads as an instruction to take set
        # one to failure, which is the opposite of the plan; and appending the
        # clause on the last row on top of it produced the literal
        # "8-10 @ última al fallo · la última al fallo" seen on the phone.
        #
        # So a last-set-only prescription is not an RIR for the other rows.
        # They get none, and only the final working set carries the clause.
        ultima_de_trabajo = max(
            (n for n, r in enumerate(rows) if set_type_of(r) is SetType.NORMAL), default=-1
        )
        es_la_ultima = i == ultima_de_trabajo
        solo_ultima = rir is not None and rir.low is None and rir.last_set is not None

        if rir is None:
            rir_text = ""
        elif solo_ultima:
            rir_text = (
                ("al fallo" if rir.last_set == (0, 0) else f"RIR {rir.last_set[0]}")
                if es_la_ultima
                else ""
            )
        else:
            rir_text = rir.label()

        parts = [p for p in (reps, rir_text) if p]
        if not parts:
            return ""
        text = "→ " + " @ ".join(parts)

        # A phase that states both a general RIR and a different last-set one
        # still needs the tail, and only on that row.
        if rir is not None and not solo_ultima and rir.last_set == (0, 0) and es_la_ultima:
            text += " · la última al fallo"
        return text

    def _has_confirmed_work(self) -> bool:
        """Has a real working set been claimed on this exercise yet?

        The switch behind both the progression banner and the warm-up ramp:
        they are planning tools, they belong on screen before the first set,
        and the moment one is confirmed they have said everything they had to
        say. Warm-ups deliberately do not count — confirming the ramp is not
        starting the exercise.
        """
        return any(
            set_type_of(row) is not SetType.WARMUP
            and not self._is_suggested(row)
            and self._has_content(row)
            for row in self.sets
        )

    def _warmup_target(self) -> float | None:
        """The weight the ramp is climbing towards, in order of authority.

        1. A working row Alex **typed or claimed**. A number he owns beats
           anything computed, always.
        2. The recommendation. It knows last session went to the top of the
           range and today is 2.5 kg heavier; warming up to yesterday's weight
           when the plan says go up leaves the last approach 2.5 kg short.
        3. A row still showing last session as a suggestion — better than
           nothing when the database could not be reached for step 2.

        None when all three are silent, which is the first-ever session of an
        exercise. No target, no ramp, nothing invented: `warmup_plan` is a
        percentage of a working weight, and there is no working weight yet.
        """
        suggested: float | None = None
        for row in self.sets:
            if set_type_of(row) is SetType.WARMUP:
                continue
            value = _num_value(row.get("weight"))
            if not value or value <= 0:
                continue
            if not self._is_suggested(row):
                return value
            if suggested is None:
                suggested = value
        rec = self._recommendation(self.ex_idx)
        if rec is not None and rec.weight:
            return float(rec.weight)
        return suggested

    def _warmup_plan(self) -> list[WarmupSet]:
        """The ramp for this exercise, or empty when there is nothing to ramp.

        Barbell only, and that is a limitation with a reason rather than an
        oversight: every weight `warmup_plan` returns is a weight it has
        checked can be assembled from the plates in the room, and there are no
        plates to check on a machine stack or a dumbbell rack. Offering a
        "37.5 kg" ramp set on a stack that steps in fives would be exactly the
        arithmetic-in-the-gym this whole feature exists to remove. Alex's
        routine is almost entirely barbell work, which is where the ramp is
        worth having anyway.
        """
        raw = self._current_exercise_raw()
        if not self._is_barbell(raw):
            return []
        target = self._warmup_target()
        if target is None:
            return []
        self._ensure_gear()
        plan: list[WarmupSet] = []
        with contextlib.suppress(Exception):
            plan = warmup_plan(target, self._bar_for(raw), self._plate_inventory)
        return plan

    def _add_warmup_sets(self, _=None):
        """One tap: the whole ramp, as rows, already tagged as warm-ups.

        Inserted **as suggestions**, muted, exactly like the prefill from last
        session — because that is what they are: sets the app proposes and the
        user has not done yet. Confirming one is a tap on its set number, which
        is the tap he makes anyway when a set ends, and which also starts the
        rest timer. Writing them in confirmed would have been fewer taps and a
        lie: it would put warm-ups he never performed into `entrenos` the next
        time Save is pressed.

        They go in front of the existing rows because that is the order they
        are done in, and `set_types.tag_set` writes the type so the stored
        shape is the one every reader in the repo (and the coach) already
        understands. Warm-ups are excluded from volume and from personal
        records by `analytics`, so the ramp can never inflate a number.
        """
        plan = self._warmup_plan()
        if not plan:
            return
        rows: list[dict[str, str]] = []
        for entry in plan:
            draft = self._blank_set()
            draft["weight"] = _num_text(entry.weight)
            draft["reps"] = str(entry.reps)
            # Through `tag_set` rather than by writing TYPE_KEY by hand: it is
            # the one function that decides how a type is spelled on a row.
            row = {str(k): str(v) for k, v in tag_set(draft, SetType.WARMUP).items()}
            row[_SUGGESTED_KEY] = "1"
            rows.append(row)
        self.sets = rows + list(self.sets)
        self._persist_draft()
        self._toast(
            f"{plural(len(rows), 'serie de calentamiento añadida', 'series de calentamiento añadidas')} — confirma cada una al acabarla",
            ft.Icons.LOCAL_FIRE_DEPARTMENT,
            C.warning,
        )
        self.page.data["refresh_current"]()

    def _toggle_history(self, _=None):
        """Unfold the past-sessions panel **without rebuilding the screen**.

        This is requirement 5's real constraint: "without losing what you have
        typed". A `refresh_current()` here would rebuild every `TextField` in
        the tree, and on Android that closes the keyboard and drops the caret
        out of the number being typed. Flipping `visible` on two controls that
        are already mounted touches nothing else on the screen.
        """
        self._show_history = not self._show_history
        if self._history_body is not None:
            self._history_body.visible = self._show_history
            with contextlib.suppress(Exception):
                self._history_body.update()
        if self._history_arrow is not None:
            self._history_arrow.name = (
                ft.Icons.EXPAND_LESS if self._show_history else ft.Icons.EXPAND_MORE
            )
            with contextlib.suppress(Exception):
                self._history_arrow.update()

    def _toggle_reason(self, _=None):
        """Show or hide the sentence behind the recommendation. Same trick."""
        control = self._reason_text
        if control is None:
            return
        control.visible = not control.visible
        with contextlib.suppress(Exception):
            control.update()

    @staticmethod
    def _is_suggested(row: dict) -> bool:
        return bool(row.get(_SUGGESTED_KEY))

    def _has_content(self, row: dict) -> bool:
        return bool(row.get("weight") or row.get("reps"))

    def _confirm_row(self, i: int) -> bool:
        """Promote a suggestion to a set the user stands behind."""
        rows = self.sets
        if 0 <= i < len(rows) and self._is_suggested(rows[i]):
            rows[i].pop(_SUGGESTED_KEY, None)
            return True
        return False

    def _pending_count(self) -> int:
        return sum(1 for r in self.sets if self._is_suggested(r) and self._has_content(r))

    def _workout_in_progress(self) -> bool:
        """True when there is something on this screen worth protecting.

        Suggestions do not count: they are the app's guess, not the user's
        work, and throwing away a guess costs nobody anything.
        """
        self._ensure_scope()
        if self.day_idx < 0 or self.finished:
            return False
        if self.completed or self.ex_idx > 0:
            return True
        return any(
            not self._is_suggested(r) and self._has_content(r)
            for rows in self._sets_by_ex.values()
            for r in rows
        )

    def _reset(self):
        self.phase_id = 0
        self.day_idx = -1
        self.ex_idx = 0
        # Una sesión de abdomen o libre terminada no puede dejar la pantalla
        # en ese modo: la siguiente vez que se abra Entreno habría que salir de
        # algo que nadie pidió, y la lista de fases no se vería.
        self.solo_abdomen = False
        self.libre = False
        self._scope = ()
        self._sets_by_ex = {}
        self._last_sets_cache = {}
        self._logged_ex = set()
        self._history_cache = {}
        self._rec_cache = {}
        self._plan_cache = {}
        self._start_cache = {}
        self._subs_cache = None
        self.completed = []
        self.finished = False
        self.show_day_list = False
        self.show_phase_list = False
        self.timer.stop()
        self._stop_session_timer()
        # Same argument as the session default below, and more urgent: a
        # per-exercise Monday that survived into the next workout would be a
        # date nobody chose for it, on a screen whose strip would then dutifully
        # report Monday as if it had been asked for.
        self._dates_by_key = {}
        self._forget_durations()
        # The date belonged to the session that just ended. Leaving it set is
        # exactly the "it was still on yesterday" failure the whole feature is
        # designed around. `persist=False` because `_clear_draft` below wipes
        # the stored copy anyway — one write, not two.
        self._reset_log_date(persist=False)
        # Whatever brought us here — finishing, or an explicit discard — the
        # session is over. A draft left behind would resurrect it on the next
        # visit to the Train tab.
        self._clear_draft()

    # ── Draft (survives a reload, a sleeping phone, a restart) ─
    def _exercise_keys(self) -> list[str]:
        """Canonical keys of the current day, in order — the draft's own index.

        `workout_draft` stores half-written rows **by exercise name**, not by
        position, so editing the routine cannot move Alex's bench weights onto
        a squat. This view thinks in positions, so this list is the translation
        between the two, and it is the only place that does it.
        """
        day = self._current_day()
        return [exercise_key(x) for x in day.exercises] if day else []

    def _rows_for_draft(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        """Screen rows → rows worth persisting.

        A suggestion is written out as an **empty placeholder**, never as its
        numbers. `workout_draft.normalize_row` keeps only weight/reps/rir/type,
        so a suggested row put in the draft would come back on restore
        indistinguishable from one the user confirmed — a weight nobody lifted,
        one tap away from the history and from a fake PR. The placeholder still
        holds the *slot*, so the row count survives and the suggestion is built
        again from the database, where it came from in the first place.
        """
        out: list[dict[str, str]] = []
        for row in rows:
            if self._is_suggested(row):
                placeholder = self._blank_set()
                placeholder[TYPE_KEY] = row.get(TYPE_KEY, SetType.NORMAL.value)
                out.append(placeholder)
            else:
                out.append({k: v for k, v in row.items() if k != _SUGGESTED_KEY})
        return out

    def _rows_from_draft(self, rows: list[dict], ex_idx: int) -> list[dict[str, str]]:
        """Persisted rows → screen rows, suggestions rebuilt from storage.

        The inverse of `_rows_for_draft`: anything with a number in it is the
        user's and comes back confirmed; an empty slot is re-offered as this
        session's suggestion, so a restored screen looks exactly like the one
        he left without a single unreviewed number having survived the trip.
        """
        seeded = self._seed_sets(ex_idx)
        out: list[dict[str, str]] = []
        for i, row in enumerate(rows):
            clean = {str(k): str(v) for k, v in row.items() if k != _SUGGESTED_KEY}
            if self._has_content(clean):
                out.append(clean)
            elif i < len(seeded) and self._is_suggested(seeded[i]):
                out.append(dict(seeded[i]))
            else:
                out.append(clean or self._blank_set())
        return out or [self._blank_set()]

    def _build_draft(self) -> WorkoutDraft | None:
        day = self._current_day()
        keys = self._exercise_keys()
        if day is None or not (0 <= self.ex_idx < len(keys)):
            return None
        pending: dict[str, list[dict[str, str]]] = {}
        for idx, rows in self._sets_by_ex.items():
            if not (0 <= idx < len(keys)):
                continue
            kept = self._rows_for_draft(rows)
            # An exercise showing nothing but suggestions has no user input to
            # restore; leaving it out keeps the payload small and stops an
            # untouched day from resurfacing as a "workout in progress".
            if any(not is_blank_row(r) for r in kept):
                pending[keys[idx]] = kept
        return WorkoutDraft(
            routine_id=active_routine().id,
            phase_id=self.phase_id,
            day_idx=self.day_idx,
            day_name=day.name,
            ex_idx=self.ex_idx,
            exercise=keys[self.ex_idx],
            pending=pending,
            completed=self.completed,
            # THE DATES TRAVEL WITH THE DRAFT. Without these two the whole
            # per-exercise date feature evaporates the moment Android kills the
            # process: the map is rebuilt empty, every exercise resolves to
            # today, and the set Alex filed under Monday is written to
            # Wednesday — silently, which is the one outcome this feature was
            # warned about and designed against.
            session_date=self._session_log_date(),
            dates=dict(self._dates_by_key),
            started_at=self.session_started_at,
        )

    def _persist_draft(self, *, force: bool = True):
        """Checkpoint the session.

        `force=True` for anything the user experiences as an action — a set
        added, an exercise changed, a save. `force=False` for keystrokes, which
        `DraftStore` coalesces so typing "127.5" is not five UPDATEs.
        """
        if self.finished or self.phase_id <= 0 or self.day_idx < 0:
            return
        draft = self._build_draft()
        if draft is None:
            return
        # `DraftStore` already swallows storage errors; this covers the rest.
        # A draft that fails to save must never cost the user the tap he just
        # made — it is a safety net under the session, not the session.
        with contextlib.suppress(Exception):
            self._drafts.save(draft, force=force)

    def _clear_draft(self):
        with contextlib.suppress(Exception):
            self._drafts.clear()
        # The chosen date is part of that draft's session in everything but
        # storage location, so it dies with it. Cleared unconditionally rather
        # than through `_persist_log_date`: this runs on paths that have already
        # reset the in-memory value, and the row must go either way.
        with contextlib.suppress(Exception):
            self.store.set_pref(LOG_DATE_PREF, "")
        # Same argument for the notes still waiting on an exercise that was
        # never written: they described the session that has just ended, and a
        # note that outlived its workout would surface under the next one.
        # Anything already saved is in `entrenos.nota` and is untouched by this.
        self._clear_notes()

    def _restore_draft(self):
        """Rebuild the session from the draft.

        `DraftStore.load` has already refused anything expired, corrupt, of a
        foreign version or no longer fitting the routine, and has re-pointed
        what survived by name. The bounds are still re-checked here: this side
        is the one that indexes with them, and an `IndexError` on the Train tab
        is a dead screen.
        """
        draft = None
        with contextlib.suppress(Exception):
            draft = self._drafts.load()
        if draft is None:
            return
        days = active_routine().days_for_phase(draft.phase_id)
        if not (0 <= draft.day_idx < len(days)):
            return

        self.phase_id = draft.phase_id
        self.day_idx = draft.day_idx
        self.finished = False
        self.show_phase_list = False
        self.show_day_list = False
        # A restore is the same workout coming back, not a new one — so it must
        # not silently re-enable zen on someone who had stepped out of it. This
        # is the path a killed process takes, which makes it the one where a
        # surprise change of layout would be least welcome.
        self._arm_zen(fresh_day=False)
        # Same argument for the date, with one extra guarantee: `_load_log_date`
        # refuses a choice made on another calendar day, so a session resumed
        # the next morning comes back logging to *that* morning rather than
        # quietly continuing to write into a day that is now two days old.
        self._load_log_date()
        # Set the scope by hand: `_ensure_scope` would otherwise notice the
        # change and wipe the buffer we are about to fill.
        self._scope = self._current_scope()
        self._sets_by_ex = {}
        self._last_sets_cache = {}
        self._logged_ex = set()
        self._history_cache = {}
        self._rec_cache = {}
        self._plan_cache = {}
        self._start_cache = {}
        self._subs_cache = None
        # The notes belong to the same session the draft does, and they are
        # keyed by exercise name, so this has to come after the scope is set and
        # before the rows are put back.
        self._load_notes()
        self._show_note = False

        # THE DATES COME BACK WITH IT. `_load_log_date()` above only restores
        # the *session* date; without this the per-exercise map is empty after
        # any restore and every exercise silently resolves to today — the set
        # filed under Monday lands on Wednesday.
        #
        # `DraftStore.load()` has already applied the calendar-day rule to each
        # entry and dropped the ones that no longer stand, reporting them in
        # `stale_dates`. Read, not re-derived: applying that rule a second time
        # here is how the two copies drift apart.
        self._dates_by_key = dict(draft.dates)
        if draft.stale_dates:
            # Silently reverting a date to today is precisely the failure this
            # feature is built to avoid, so it is said out loud.
            with contextlib.suppress(Exception):
                self._toast(
                    f"De vuelta a hoy para: {', '.join(draft.stale_dates)}",
                    ft.Icons.EVENT_BUSY,
                    C.warning,
                )

        keys = self._exercise_keys()
        if not (0 <= draft.ex_idx < len(keys)):
            self._reset()
            return
        self.ex_idx = draft.ex_idx
        for idx, key in enumerate(keys):
            rows = draft.pending.get(key)
            if rows:
                self._sets_by_ex[idx] = self._rows_from_draft(rows, idx)
        self.completed = [c for c in draft.completed if isinstance(c, dict)]
        # Which exercises are already in `entrenos` is derived, not stored:
        # `completed` carries the keys, and matching them back to positions
        # cannot go stale the way a saved index can.
        #
        # Resolved through `_performed_key`, NOT against `keys`. With a swap in
        # force the two differ by design — the slot says "Leg Press", the row
        # says "Hack Squat" — so comparing the prescribed key left every swapped
        # position looking unlogged. Saving again then wrote a **second** row for
        # the same day, one under each name, and nothing raised: the history just
        # split in two, which is the exact failure `exercise_key()` exists to
        # prevent. `_performed_key` is the single function that answers "what
        # goes into `entrenos.ejercicio`", so it has to be the one asked here.
        done = {c.get("exercise") for c in self.completed}
        self._logged_ex = {i for i in range(len(keys)) if self._performed_key(i) in done}

        if draft.started_at:
            self._resume_session_timer(float(draft.started_at))
        else:
            self._start_session_timer()

        if draft.dropped:
            # Rows that belonged to an exercise no longer in this day. Silently
            # losing them would look like the bug this whole change is about.
            with contextlib.suppress(Exception):
                self._toast(
                    f"Retomado. Series descartadas de: {', '.join(draft.dropped)}",
                    ft.Icons.INFO_OUTLINE,
                    C.warning,
                )

    def _start_session_timer(self):
        self._resume_session_timer(time.time())

    def _resume_session_timer(self, started_at: float):
        """Restart the ticking clock from a start instant that already passed.

        A restored session shows the time since the user actually began, not
        since the app came back — the chronometer is what tells him whether he
        has been in the gym forty minutes or two hours.
        """
        self.session_started_at = started_at
        self.session_ended_at = None
        self._session_tick_id += 1
        self.page.run_task(self._session_tick_loop, self._session_tick_id)

    def _stop_session_timer(self):
        if self.session_started_at and not self.session_ended_at:
            self.session_ended_at = time.time()
        self._session_tick_id += 1  # invalidate any running loop

    def _session_elapsed_s(self) -> int:
        if not self.session_started_at:
            return 0
        end = self.session_ended_at or time.time()
        return max(0, int(end - self.session_started_at))

    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    # ── How long the session lasted ───────────────────────────
    #
    # `_format_elapsed` above and `storage.format_duration` are not duplicates
    # and must not be merged. The first is the **running clock** — it counts
    # seconds because a clock that did not move would look broken. The second is
    # the **record** — "1h 12m", no seconds, because nobody trained for
    # 4 320 seconds and printing the third digit claims a precision the
    # measurement never had. Live control → `_format_elapsed`; anything read
    # back out of `duraciones_sesion` → `format_duration`, always.

    def _durations(self) -> dict[str, int]:
        """`{iso: seconds}` for every timed day. One query, memoised per screen.

        A database that will not answer means "nothing timed" — the summary of
        a finished session must not turn into an error screen over a number
        that is decoration on it.
        """
        if self._duration_cache is None:
            found: dict[str, int] = {}
            with contextlib.suppress(Exception):
                found = dict(self.store.get_duration_map())
            self._duration_cache = found
        return self._duration_cache

    def _forget_durations(self):
        self._duration_cache = None

    def _logged_days(self) -> tuple[date, ...]:
        """The days this session actually put rows into, oldest first.

        Read off `completed`, not off the date map: the map says where the next
        write *would* go, and the summary screen is asking where writes already
        went. A session that logged nothing has no day to time, which is the
        honest answer — there was no session.
        """
        days: set[date] = set()
        for one in self.completed:
            if not isinstance(one, dict):
                continue
            with contextlib.suppress(TypeError, ValueError):
                days.add(date.fromisoformat(str(one.get("date") or "")))
        return tuple(sorted(days))

    def _session_note_day(self) -> date:
        """Which day a whole-session note belongs to.

        `notas_sesion` is keyed by date alone, so exactly one day has to be
        picked — and the session default is the **wrong** pick as soon as the
        exercises were dated one by one. File Monday's whole workout exercise
        by exercise, leaving the session default on today, and the note about
        that workout would land on today: a note about a day with no sets in it,
        and the day that does have the sets left silent.

        So: the day the session actually wrote to, whenever there is exactly
        one. A sitting that covered two days falls back to the session default,
        because the note covers both and no rule picks a winner honestly — and
        `_session_note_block` prints the day it chose either way.
        """
        days = self._logged_days()
        return days[0] if len(days) == 1 else self.log_date

    def _clock_measures(self, days: tuple[date, ...]) -> bool:
        """Would the chronometer be an honest reading for a session on `days`?

        The distinction Alex drew himself, and the reason this is not simply
        "whatever the clock says". Three conditions, all necessary:

        * the clock ran at all, and for long enough to be a session rather than
          a mis-tap (`MIN_SESSION_SECONDS`);
        * every row went into **one** day — no arithmetic divides one
          chronometer between two sessions honestly, so a multi-day sitting
          proposes nothing to either day;
        * that day is **today**. Filling Monday in on Wednesday, the clock
          measured how long the typing took. That is not a datum, it is noise
          wearing a datum's clothes, and once averaged in with the real ones it
          never comes back out.

        False is not a failure. It is the ordinary state of a back-dated
        session, and all it means is that the field opens empty and says why.

        `days` is a parameter because the answer is asked at two moments about
        two different sets: the Finish dialog asks about the days the session is
        *about to* write to (`_dates_in_use`), and everything after the flush
        asks about the days it actually wrote to (`_logged_days`).
        """
        if self.session_started_at is None:
            return False
        if self._session_elapsed_s() < MIN_SESSION_SECONDS:
            return False
        return len(days) == 1 and days[0] == date.today()

    def _duration_is_measured(self) -> bool:
        """`_clock_measures` against the days this session actually wrote to."""
        return self._clock_measures(self._logged_days())

    def _store_measured_duration(self):
        """Write the clock's answer — only when the clock is entitled to one.

        Runs once, from `_finish_session`. Deliberately a write and not a
        prompt: when `_duration_is_measured()` holds, the number is a real
        measurement of a real session and the alternative is losing it to a
        dialog nobody opened. It is not silent — the summary screen prints it
        immediately, labelled as measured, one tap from being corrected.

        **An existing row is never overwritten.** Two sessions in one day, or a
        time Alex already typed, are both cases where the row on disk is the
        better answer; `set_session_duration` upserts, so the guard has to be
        here.
        """
        if not self._duration_is_measured():
            return
        day = self._logged_days()[0]
        with contextlib.suppress(Exception):
            if self.store.get_session_duration(day) is None:
                self.store.set_session_duration(self._session_elapsed_s(), day)
        self._forget_durations()

    def _open_duration_dialog(self, day: date):
        """Say how long the session on `day` lasted. Blank means "not timed".

        Minutes, not `H:MM:SS`. Nobody knows their session to the second and a
        field that asks for seconds invites a number invented to fill it;
        `format_duration` drops them on the way out for the same reason.

        The clock is offered as a shortcut **only when it measured this
        session** (`_duration_is_measured`). On a back-dated day the button is
        replaced by the sentence explaining its absence, because a shortcut that
        pastes the typing time is the single most likely way this field gets a
        wrong number into the table.

        Nothing is clamped. `storage.clean_duration` refuses anything over
        `MAX_SESSION_SECONDS` with a message already written in user English, so
        it is shown as-is: silently trimming 14 h to 8 h would store a number
        nobody measured wearing the face of one that was.
        """
        current = self._durations().get(day.isoformat())
        field = ft.TextField(
            label="Minutos",
            # `max(1, ...)`: a stored duration under 30 s rounds to "0", and a
            # zero in this box means "not timed" — so opening the dialog on a
            # short session and saving would silently delete it.
            value=str(max(1, round(current / 60))) if current else "",
            hint_text="p. ej. 72",
            keyboard_type=ft.KeyboardType.NUMBER,
            # Digits, not a value cap: `clean_duration` is what refuses a real
            # number that is too big, and it does it with a sentence. This only
            # stops a stuck key turning into a five-digit session.
            max_length=len(str(MAX_SESSION_MINUTES)),
            dense=True,
            color=C.text,
            border_color=C.border_strong,
            focused_border_color=C.accent,
            label_style=ft.TextStyle(color=C.text_secondary),
        )
        err = ft.Text("", size=11, color=C.danger)
        dlg = ft.AlertDialog(modal=False)

        def fill(minutes: int):
            field.value = str(minutes)
            err.value = ""
            self.page.update()

        def save(_):
            text = (field.value or "").strip()
            seconds: float | None = None
            if text:
                try:
                    minutes = float(text.replace(",", "."))
                except ValueError:
                    err.value = "Minutos, en número."
                    self.page.update()
                    return
                if minutes < 0:
                    err.value = "Minutos, en número."
                    self.page.update()
                    return
                seconds = minutes * 60
            try:
                self.store.set_session_duration(seconds, day)
            except ValueError as exc:
                # Already a sentence Alex can read — see `clean_duration`.
                err.value = str(exc)
                self.page.update()
                return
            except Exception:
                err.value = "No se pudo guardar — revisa la conexión."
                self.page.update()
                return
            self._forget_durations()
            self.page.close(dlg)
            self.page.data["refresh_current"]()

        rows: list[ft.Control] = [
            ft.Text(
                f"¿Cuánto duró {_date_label(day)}?",
                size=12,
                color=C.text_secondary,
            )
        ]
        if self._duration_is_measured() and day == date.today():
            elapsed = self._session_elapsed_s()
            rows.append(
                ghost_button(
                    f"Usar el reloj — {format_duration(elapsed)}",
                    on_click=lambda _: fill(max(1, round(elapsed / 60))),
                    expand=True,
                )
            )
        elif self.session_started_at is not None:
            rows.append(
                ft.Text(
                    "Aquí no se ofrece el reloj: corrió mientras tecleabas la sesión, "
                    "y eso no es lo que duró el entreno.",
                    size=11,
                    color=C.warning,
                )
            )
        rows.append(
            ft.Row(
                [
                    ghost_button(str(m), on_click=lambda _, m=m: fill(m), expand=True)
                    for m in (30, 45, 60, 75, 90)
                ],
                spacing=6,
            )
        )
        rows.extend(
            [
                field,
                ft.Text(
                    "Déjalo vacío para 'sin cronometrar' — es una respuesta real, "
                    f"y la honesta para una sesión que nadie midió. "
                    f"Lo más largo aceptado: {format_duration(MAX_SESSION_SECONDS)}.",
                    size=10,
                    color=C.text_muted,
                ),
                err,
            ]
        )

        dlg.title = ft.Text("Tiempo de sesión", size=16, weight=ft.FontWeight.W_900, color=C.text)
        dlg.content = ft.Container(
            content=ft.Column(rows, spacing=10, tight=True, scroll=ft.ScrollMode.AUTO),
            width=dialog_width(self.page),
            height=dialog_height(self.page, 300),
        )
        dlg.actions = [
            ghost_button("Cancelar", on_click=lambda _: self.page.close(dlg)),
            primary_button("Guardar", on_click=save),
        ]
        dlg.actions_alignment = ft.MainAxisAlignment.END
        dlg.bgcolor = C.bg_surface
        self.page.open(dlg)

    async def _session_tick_loop(self, tick_id: int):
        while tick_id == self._session_tick_id:
            await asyncio.sleep(1)
            if tick_id != self._session_tick_id or self._session_label is None:
                return
            self._session_label.value = self._format_elapsed(self._session_elapsed_s())
            try:
                self.page.update()
            except Exception:
                return

    def _go_prev_exercise(self):
        # No `self.sets = [blank]` here any more. Both of these used to throw
        # the rows on the floor, which is literally what Alex reported: a swipe
        # — and this one fires on an accidental drag — erased what he had
        # typed, unsaved and unannounced. The rows now live per exercise.
        if self.ex_idx > 0:
            self.ex_idx -= 1
            self._show_history = False
            self._show_note = False
            self._persist_draft()
            self.page.data["refresh_current"]()

    def _go_next_exercise(self):
        day = self._current_day()
        total = len(day.exercises) if day else 0
        if self.ex_idx + 1 < total:
            self.ex_idx += 1
            # The history panel is a question about *this* movement. Carrying
            # it open into the next one costs 150 px of screen to answer a
            # question nobody asked.
            self._show_history = False
            self._show_note = False
            self._persist_draft()
            self.page.data["refresh_current"]()

    def _current_day(self):
        """El día que se está entrenando, **con los extras de hoy al final**.

        Un solo punto, y por eso el resto de la vista no se enteró del cambio:
        piensa en posiciones sobre `day.exercises`, así que un ejercicio más al
        final es una posición más y ya está — la navegación, el total, el
        borrador y el guardado siguen igual.

        `extras.dia_con_extras` **copia** el `TrainingDay`. Devolver el de
        `data.ROUTINES` y añadirle algo aquí lo dejaría en el plan para
        siempre, en todas las fases que reusan ese día.
        """
        if self.libre:
            # Ya *es* la lista de extras; volver a pasarla por
            # `dia_con_extras` no añadiría nada, pero el abdomen sí se respeta:
            # está encendido para todos los días, y un entreno libre es un día.
            return abdomen.dia_con_abdomen(extras.dia_libre(self.store), self.store)
        if self.solo_abdomen:
            # Ya *es* el abdomen: pasarlo por `dia_con_abdomen` lo duplicaría.
            # Los extras sí se respetan — nada impide meter algo más un día de
            # descanso.
            return extras.dia_con_extras(abdomen.dia_suelto(self.store), self.store)
        dia = self._routine_day()
        if dia is None:
            return None
        # El orden importa y es siempre el mismo: lo que manda el plan, lo que
        # se hace cada día, y lo que se añadió hoy. Un ejercicio que cambia de
        # sitio según qué esté activo es un ejercicio que se busca cada vez.
        return extras.dia_con_extras(abdomen.dia_con_abdomen(dia, self.store), self.store)

    def _routine_day(self):
        """El día tal como lo prescribe la rutina, sin extras ni abdomen.

        Lo que hace falta para saber dónde acaba el plan y empieza lo de hoy.
        En una sesión de solo abdomen el «plan» es el propio abdomen.
        """
        if self.libre:
            return extras.dia_libre(self.store)
        if self.solo_abdomen:
            return abdomen.dia_suelto(self.store)
        days = active_routine().days_for_phase(self.phase_id)
        if self.phase_id and 0 <= self.day_idx < len(days):
            return days[self.day_idx]
        return None

    def _current_exercise_raw(self) -> str:
        """Full exercise string being trained (may include [scheme] and *).

        With a substitution in force this is the *substitute* carrying the
        slot's scheme — `substitutions.swap_prescription`'s answer — so the bar,
        the plate hint, the rest, the equipment classification and the plan all
        describe the machine Alex is actually standing at, while the sets and
        reps stay the ones the routine prescribed for the slot.
        """
        raw = self._prescribed_raw()
        if not raw:
            return ""
        swap = self._substitution_at(self.ex_idx)
        return swap_prescription(raw, swap.performed) if swap else raw

    def _phase(self):
        for p in active_routine().phases:
            if p.id == self.phase_id:
                return p
        return None

    # ── Actions ───────────────────────────────────────────────
    def _select_phase(self, pid: int):
        if pid == self.phase_id and self._workout_in_progress():
            # Re-picking the phase you are already training in is navigation,
            # not a restart. Wiping here is how the back gesture used to eat
            # the day: you left the exercise screen and came back through the
            # front door, and the front door reset everything.
            self.show_phase_list = False
            self.show_day_list = True
            self.page.data["refresh_current"]()
            return
        if self._workout_in_progress():
            self._ask_discard(lambda: self._start_phase(pid))
            return
        self._start_phase(pid)

    def _start_phase(self, pid: int):
        self.phase_id = pid
        self.day_idx = -1
        self.ex_idx = 0
        self.completed = []
        self.finished = False
        self.show_phase_list = False
        self.show_day_list = False
        self._ensure_scope()
        self.page.data["refresh_current"]()

    def _select_day(self, idx: int):
        if idx == self.day_idx and self._workout_in_progress():
            self._resume_day()
            return
        if self._workout_in_progress():
            self._ask_discard(lambda: self._start_day(idx))
            return
        self._start_day(idx)

    def _resume_day(self):
        """Walk back into the workout already open on this day."""
        self.show_day_list = False
        self.show_phase_list = False
        self.finished = False
        # Resuming, not starting: whatever he chose last is what he gets back.
        self._arm_zen(fresh_day=False)
        # The clock kept running while the day list was on screen — the user
        # never left the gym — so it is only restarted if it was stopped.
        if self.session_started_at is None:
            self._start_session_timer()
        elif self.session_ended_at is not None:
            self._resume_session_timer(self.session_started_at)
        self._persist_draft()
        self.page.data["refresh_current"]()

    def _start_day(self, idx: int):
        self.day_idx = idx
        self.ex_idx = 0
        self.completed = []
        self.finished = False
        self.show_day_list = False
        self.show_phase_list = False
        # A fresh day gets a fresh buffer, and `_ensure_scope` will not see the
        # change on its own when the same day is restarted.
        self._scope = self._current_scope()
        self._sets_by_ex = {}
        self._last_sets_cache = {}
        self._logged_ex = set()
        self._history_cache = {}
        self._rec_cache = {}
        self._plan_cache = {}
        self._start_cache = {}
        self._notes_by_ex = {}
        self._session_note_cache = None
        # Same argument as the notes above, and it bites harder: the map is
        # keyed by exercise name, so a day left over from Monday's Push session
        # would silently claim any exercise Tuesday's Pull session shares with
        # it — a date nobody chose for it, on a screen that would report it as
        # if they had. `_ensure_scope` catches the routine being swapped from
        # outside; this catches the ordinary "start another day".
        self._dates_by_key = {}
        self._forget_durations()
        # A day starting is also the moment a swap made last week stops
        # applying, so the map is re-read rather than carried over.
        self._subs_cache = None
        self._show_history = False
        self._show_note = False
        # A new workout is the moment to notice that the rack changed — a bar
        # or a plate set edited on the Profile screen is picked up here and
        # nowhere else, because every other read of it happens per keystroke.
        self._plate_inventory = None
        self._bar_override = None
        # A countdown left over from the previous session has nothing to do
        # with this one.
        self.timer.stop()
        if idx >= 0:
            # "Al momento de poner una rutina" — this is that moment.
            self._arm_zen(fresh_day=True)
            self._start_session_timer()
            self._persist_draft()
        else:
            self._stop_session_timer()
            self._clear_draft()
        self.page.data["refresh_current"]()

    def _add_set(self, _):
        # Adding a row means the previous one is done — that is the moment the
        # rest starts, and the only one the user signals without extra taps.
        # It also vouches for a suggestion still sitting in that row: nobody
        # moves on to set 3 without having done set 2.
        last = self.sets[-1]
        self._confirm_row(len(self.sets) - 1)
        if self._has_content(last):
            self._start_rest(last)
        self.sets.append(self._blank_set())
        self._persist_draft()
        self.page.data["refresh_current"]()

    def _remove_set(self, i: int):
        if len(self.sets) > 1:
            self.sets.pop(i)
            self._persist_draft()
            self.page.data["refresh_current"]()

    def _update_set(self, i: int, field: str, value: str):
        rows = self.sets
        if not (0 <= i < len(rows)):
            return
        rows[i][field] = value
        # Typing *is* the review. A number the user just changed is his, so the
        # row stops being a suggestion the moment he touches it — that is what
        # makes "same weight, one more rep" cost exactly one edit.
        rows[i].pop(_SUGGESTED_KEY, None)
        # Unforced: this fires once per character, and `DraftStore` coalesces
        # it to at most one write every few seconds. Without it, a phone that
        # sleeps with the keyboard open loses the number being typed.
        self._persist_draft(force=False)

    def _cycle_set_type(self, i: int):
        # Deliberately does not confirm the row: relabelling a set as a warm-up
        # says nothing about whether that weight was lifted.
        self.sets[i][TYPE_KEY] = next_set_type(self.sets[i].get(TYPE_KEY)).value
        self._persist_draft()
        self.page.data["refresh_current"]()

    def _confirm_set(self, i: int):
        """Claim a suggested row: 'yes, that is what I just did.'

        One-way on purpose. Un-confirming would be a silent way to drop a set
        the user typed himself; the row's own X button is the explicit way.
        """
        if self._confirm_row(i):
            # Confirming carries exactly the news `_add_set` carries — that set
            # is over — so the rest starts here too, at no extra tap.
            self._start_rest(self.sets[i])
            self._persist_draft()
            self.page.data["refresh_current"]()

    def _confirm_all(self, _):
        """One tap for "same as last time" — the case Alex was retyping."""
        changed = False
        for row in self.sets:
            if self._is_suggested(row) and self._has_content(row):
                row.pop(_SUGGESTED_KEY, None)
                changed = True
        if changed:
            # No rest timer here on purpose: this is a bulk transcription of
            # sets already done, not the signal that one has just ended.
            self._persist_draft()
            self.page.data["refresh_current"]()

    # ── Notes ─────────────────────────────────────────────────
    #
    # Two notes with two different lifetimes, and `storage.py` already draws the
    # line: an **exercise** note is a column on the `entrenos` row and dies with
    # it ("the cable broke, moved to the machine"); a **session** note is a row
    # of its own, one per day, and exists whether or not anything was logged
    # ("slept badly, everything felt heavy").
    #
    # Where each one goes on screen follows from when it is written. Typing on a
    # phone, standing up, between two sets, is the worst input situation this app
    # has — so the exercise note is one tap from the rows, opens *in place*, and
    # never blocks: no dialog, no navigation, no rebuild that would take the
    # keyboard away mid-word. The session note is not written mid-set at all; it
    # is written when the session is over, so it lives on the finished screen
    # where there is room for it and nothing is waiting on it.
    #
    # Every string is trimmed by `storage.clean_note`, which is the single
    # definition of that rule — blank becomes "no note", and 1000 characters is
    # the cap on both sides of the shared database.

    def _note_for(self, ex_idx: int) -> str:
        return self._notes_by_ex.get(ex_idx, "")

    def _set_note(self, ex_idx: int, text: str, *, persist: bool = True):
        """Hold an exercise note, and put it where it can survive a restart.

        Two destinations, decided by whether the exercise is already written:

        * **Not yet logged** — the note is kept here and goes into `entrenos`
          with the sets. There is no row to attach it to yet, and inventing one
          would be inventing a workout.
        * **Already logged** — straight to `set_exercise_note`, because the row
          exists and `_save_exercise` refuses to write it twice.
        """
        cleaned = clean_note(text) or ""
        if cleaned:
            self._notes_by_ex[ex_idx] = cleaned
        else:
            self._notes_by_ex.pop(ex_idx, None)
        if ex_idx in self._logged_ex:
            key = self._performed_key(ex_idx)
            # False means the row is not there after all; nothing to do about it
            # from here, and the note stays in memory so it is not lost.
            with contextlib.suppress(Exception):
                # The exercise's own day, not the session's: the row this note
                # belongs to was written under `_date_for(ex_idx)`, so anything
                # else here would look for a row that is not there and drop the
                # note without a word.
                self.store.set_exercise_note(key, cleaned or None, on_date=self._date_for(ex_idx))
        if persist:
            self._persist_notes()

    def _persist_notes(self):
        """Checkpoint the unsaved notes, stamped with the day they belong to.

        Same shape and same reasoning as `_persist_log_date`: the stamp is what
        makes a forgotten note expire by itself instead of surfacing under
        tomorrow's session.
        """
        keys = self._exercise_keys()
        payload = {
            "date": self.log_date.isoformat(),
            "notes": {
                keys[idx]: text
                for idx, text in self._notes_by_ex.items()
                if 0 <= idx < len(keys) and text
            },
        }
        with contextlib.suppress(Exception):
            self.store.set_pref(NOTES_PREF, json.dumps(payload) if payload["notes"] else "")

    def _load_notes(self):
        """Re-read the notes of the session being resumed. Never raises.

        Keyed by exercise name, exactly like the draft's rows and for the same
        reason: editing the routine must not move a note about the bench onto a
        squat. Anything unparseable, or stamped with another date, is dropped —
        this is a convenience, and a wrong note is worse than no note.
        """
        self._notes_by_ex = {}
        raw = None
        with contextlib.suppress(Exception):
            raw = self.store.get_pref(NOTES_PREF)
        if not raw:
            return
        payload: dict = {}
        with contextlib.suppress(ValueError, TypeError):
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, dict) else {}
        if payload.get("date") != self.log_date.isoformat():
            return
        stored = payload.get("notes")
        if not isinstance(stored, dict):
            return
        keys = self._exercise_keys()
        for idx, key in enumerate(keys):
            text = clean_note(stored.get(key))
            if text:
                self._notes_by_ex[idx] = text

    def _clear_notes(self):
        self._notes_by_ex = {}
        self._session_note_cache = None
        with contextlib.suppress(Exception):
            self.store.set_pref(NOTES_PREF, "")

    def _toggle_note(self, _=None):
        """Unfold the note box **without rebuilding the screen**.

        Same trick as `_toggle_history`, and here it matters more: the control
        being revealed is a text field, and a rebuild on the way in would mount
        a second one and hand the keyboard to neither.
        """
        self._show_note = not self._show_note
        if self._note_body is not None:
            self._note_body.visible = self._show_note
            with contextlib.suppress(Exception):
                self._note_body.update()

    def _note_typed(self, value: str):
        """A keystroke in the note box. Held now, written on blur."""
        cleaned = clean_note(value) or ""
        if cleaned:
            self._notes_by_ex[self.ex_idx] = cleaned
        else:
            self._notes_by_ex.pop(self.ex_idx, None)
        if self._note_chip is not None:
            self._note_chip.value = self._note_chip_text()
            with contextlib.suppress(Exception):
                self._note_chip.update()

    def _note_chip_text(self) -> str:
        note = self._note_for(self.ex_idx)
        if not note:
            return "Nota"
        if len(note) <= NOTE_PREVIEW_CHARS:
            return note
        return note[:NOTE_PREVIEW_CHARS].rstrip() + "…"

    def _session_note(self) -> str:
        """The note on the whole session, read once per screen.

        `None` from the cache means "not read yet"; a database that will not
        answer reads as empty, which is exactly what an empty box shows.
        """
        if self._session_note_cache is None:
            found = ""
            with contextlib.suppress(Exception):
                found = self.store.get_session_note(self._session_note_day()) or ""
            self._session_note_cache = found
        return self._session_note_cache

    def _save_session_note(self, value: str):
        """Write the session note for `_session_note_day()`. Blank clears it.

        Straight to the database with no draft in between: `notas_sesion` needs
        no workout row, so there is nothing to wait for, and the one screen this
        is typed on is the screen the session ends on.
        """
        cleaned = clean_note(value)
        stored = cleaned
        try:
            stored = self.store.set_session_note(cleaned, self._session_note_day())
        except Exception:
            self._toast("No se pudo guardar la nota.", ft.Icons.ERROR_OUTLINE, C.danger)
            return
        self._session_note_cache = stored or ""

    # ── Rest ──────────────────────────────────────────────────
    def _rest_seconds(self, finished_set: dict | None = None) -> int:
        """Seconds to rest after `finished_set` of the current exercise.

        The phase's own prescription wins when it can be read; otherwise this
        is the coach's 180 s for basics / 90 s for the rest, so Telegram and the
        app never tell Alex two different numbers. A warm-up is cut short — it
        is not the set you need to recover from.
        """
        return rest_seconds_for_phase(
            self._current_exercise_raw(),
            self._phase(),
            set_type_of(finished_set or {}),
        )

    def _start_rest(self, finished_set: dict | None = None):
        # RestTimer.start() bumps its own `_tick_id`, which kills the previous
        # countdown — so restarting is safe and never stacks loops.
        self.timer.start(self._rest_seconds(finished_set))

    def _toast(self, message: str, icon: str, color: str):
        self.page.open(
            ft.SnackBar(
                content=ft.Row(
                    [
                        ft.Icon(icon, color=color, size=16),
                        ft.Text(
                            message,
                            size=12,
                            color=C.text,
                            weight=ft.FontWeight.W_700,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=C.bg_surface,
            )
        )

    def _parse_set(self, draft: dict) -> dict:
        """Draft row → the dict stored in `entrenos.series`.

        `tag_set` writes the type only when it is not normal, so an ordinary set
        comes out exactly as this app and the Telegram coach have always written
        it, and no reader has to learn a new shape.
        """
        try:
            weight = float(draft.get("weight") or 0)
        except ValueError:
            weight = 0.0
        try:
            reps = int(float(draft.get("reps") or 0))
        except ValueError:
            reps = 0
        parsed = {"weight": weight, "reps": reps}
        # RIR is optional: only stored when filled in, so old entries
        # and the ones written by the Telegram coach stay compatible.
        if str(draft.get("rir") or "").strip():
            with contextlib.suppress(ValueError):
                parsed["rir"] = float(draft["rir"])
        return tag_set(parsed, draft.get(TYPE_KEY))

    # ── Saving ────────────────────────────────────────────────
    def _unsaved_exercises(self) -> list[tuple[int, str]]:
        """Exercises holding work the user stands behind that is not in the database.

        Suggestions are deliberately excluded. An untouched prefill is the
        app's guess at what he *might* lift, and sweeping it into `entrenos`
        on the way out would write a weight nobody performed — the exact
        failure `_seed_sets` was built to avoid. Only rows he typed or claimed
        count as pending work.

        Used twice: to label the Finish button, and to decide what Finish has
        to write before it is allowed to close the session.
        """
        self._ensure_scope()
        keys = self._exercise_keys()
        out: list[tuple[int, str]] = []
        for idx in sorted(self._sets_by_ex):
            if idx in self._logged_ex or not (0 <= idx < len(keys)):
                continue
            rows = self._sets_by_ex[idx]
            if any(not self._is_suggested(r) and self._has_content(r) for r in rows):
                out.append((idx, keys[idx]))
        return out

    def _save_exercise(self, idx: int, *, announce: bool = True) -> str:
        """Write one exercise to `entrenos`, and nothing else. Never navigates.

        The index is a parameter, not `self.ex_idx`, because Finish flushes
        exercises that are not on screen. Returns what happened so the caller
        can decide what to say:

        - ``"logged"``   already written in this session, nothing done
        - ``"empty"``    no numbers to write
        - ``"unconfirmed"`` numbers on screen, but every one still a suggestion
        - ``"saved"``    written

        Storage errors are **not** swallowed: a save that silently failed and
        reported success is how a session ends up cleared with nothing in the
        database. The callers catch and keep the workout open instead.
        """
        day = self._current_day()
        if day is None or not (0 <= idx < len(day.exercises)):
            return "empty"
        if idx in self._logged_ex:
            # `save_workout` INSERTs — there is no upsert — so a second write
            # would fork today into two rows for the same exercise, which
            # `get_last_sets` and `detect_new_records` both read as two
            # separate sessions. Refusing is the honest answer; the button
            # says "Guardado" rather than pretending there is still work to do.
            return "logged"
        rows = self._sets_by_ex.get(idx) or []
        valid = [s for s in rows if not self._is_suggested(s) and self._has_content(s)]
        if not valid:
            pending = any(self._is_suggested(s) and self._has_content(s) for s in rows)
            return "unconfirmed" if pending else "empty"

        # `key_to_log`, not `exercise_key`: with a substitution in force the row
        # has to be written under the exercise that was actually performed. That
        # is the whole point of the feature — a Leg Press logged as Leg Press
        # because the Hack Squat was free would poison both histories at once.
        key = self._performed_key(idx)
        logged_on = self._date_for(idx)
        sets_parsed = [self._parse_set(s) for s in valid]
        entry = WorkoutEntry(
            # The one line the whole "log yesterday's session" feature comes
            # down to. `_date_for` — never `self.log_date` — because the day is
            # now per exercise: it walks exercise → session → today through
            # `WorkoutDraft.resolve_date`, so it is today unless Alex said
            # otherwise about *this* exercise or about the session, and it can
            # never be a future date. See the "Fecha de registro" block.
            #
            # `entry.timestamp` is deliberately left alone: `creado` records
            # when the row was *written*, which for a backdated session is
            # tonight, and that is the truth. Only `fecha` — the day trained —
            # moves, and it is the column every metric reads.
            date=logged_on.isoformat(),
            exercise=key,
            muscle_group=day.name,
            phase=self.phase_id,
            sets=sets_parsed,
            # The note goes in with the sets rather than through
            # `set_exercise_note` afterwards: it lives in this row, so writing
            # it here is one INSERT instead of an INSERT and an UPDATE that
            # could fail separately and leave the note on the floor.
            note=self._notes_by_ex.get(idx) or None,
        )
        # Read the history *before* writing: a record is only a record against
        # what came before, and a list that already contains this entry can
        # never be beaten by it.
        previous: list[WorkoutEntry] = []
        with contextlib.suppress(Exception):
            previous = self.store.get_exercise_history(key, limit=_PR_HISTORY_LIMIT)

        self.store.save_workout(entry)
        # The day travels with the entry. Without it the summary screen — and
        # `_logged_days`, which decides which days may be given a time — would
        # have to re-derive it from a date map that the next tap can change,
        # and a session that wrote to Monday and Tuesday would have no honest
        # way to say which lift went where. `workout_draft` already reserves an
        # optional `"date"` on `completed` entries for exactly this.
        self.completed.append({"exercise": key, "sets": sets_parsed, "date": logged_on.isoformat()})
        self._logged_ex.add(idx)
        # The rows are in the database now, so the copy kept here is only a
        # record of what was sent. Dropping the suggestion flags stops the
        # "not confirmed" banner from reappearing on the way back.
        for row in valid:
            row.pop(_SUGGESTED_KEY, None)

        if announce:
            # The sets are already in the database: a missing congratulation
            # must never cost the user their log, so nothing here may raise.
            with contextlib.suppress(Exception):
                self._announce_records(previous, entry)
        return "saved"

    def _save(self, _):
        """The Save button. It writes this exercise and stays put.

        Save used to be `Save → Next`, one control doing two jobs, and on the
        last exercise a third — it ended the session. Splitting them is what
        Alex asked for: moving on is Next's job and closing the session is
        Finish's, and neither is a side effect of writing a set down.

        Nothing is lost by not advancing: the rows live in `_sets_by_ex` and
        in the draft, so an exercise left unsaved is still there at Finish
        time, which is where `_unsaved_exercises` picks it up.
        """
        rows = self.sets  # the property seeds this exercise's rows if needed
        try:
            status = self._save_exercise(self.ex_idx)
        except Exception:
            self._toast(
                "No se pudo guardar — revisa la conexión.", ft.Icons.ERROR_OUTLINE, C.danger
            )
            return
        if status == "unconfirmed":
            # Everything on screen is still a suggestion. Saving nothing while
            # the fields are full of numbers reads as a bug and silently loses
            # the exercise, so say what is missing.
            self._toast(
                "Aún no has confirmado nada — toca el número de una serie, o Confirmar todas.",
                ft.Icons.INFO_OUTLINE,
                C.warning,
            )
            return
        if status == "empty":
            self._toast(
                "Todavía no hay nada que guardar — rellena una serie primero.",
                ft.Icons.INFO_OUTLINE,
                C.warning,
            )
            return
        if status == "logged":
            # Reached by tapping the "Guardado" pill. A dead control that eats the
            # tap is worse than one that explains itself.
            self._toast(
                "Ya guardado en esta sesión — no se puede registrar dos veces.",
                ft.Icons.CHECK_CIRCLE,
                C.success,
            )
            return
        resolved = self._resolve_date(self.ex_idx)
        if resolved.day != date.today():
            # Confirmation, not decoration: a write that went somewhere other
            # than today says so out loud, once per exercise, and says *why*
            # that day — "this exercise only" against "the whole session" is
            # the difference between a deliberate choice and a leftover one.
            # Nothing is said on an ordinary save; a toast for the normal case
            # is noise, and noise is what stops warnings being read.
            self._toast(
                f"Guardado en {_date_label(resolved.day)} — {self._scope_text(resolved)}.",
                ft.Icons.EVENT_BUSY,
                C.warning,
            )
        # Rest between exercises counts too — except after the last one, where
        # the next thing to happen is Finish.
        if not self._is_last_exercise():
            last_done = next((r for r in reversed(rows) if self._has_content(r)), None)
            self._start_rest(last_done)
        self._persist_draft()
        self.page.data["refresh_current"]()

    def _flush_unsaved(self) -> tuple[int, bool]:
        """Write every exercise still holding pending work. Returns (count, ok).

        `ok` is False the moment a write fails. The caller must then leave the
        session open: finishing would clear the draft and take everything that
        did not make it into the database with it — precisely the loss the
        persistent draft exists to prevent.
        """
        saved = 0
        for idx, _key in self._unsaved_exercises():
            try:
                if self._save_exercise(idx, announce=False) == "saved":
                    saved += 1
            except Exception:
                return saved, False
        return saved, True

    def _announce_records(self, history: list, entry: WorkoutEntry):
        """A PR is the reward that keeps people logging. Discreet: one bar."""
        records: list[Record] = detect_new_records(history, entry)
        if not records:
            return
        details = " · ".join(f"{r.label} {r.value:g} kg" for r in records)
        self.page.open(
            ft.SnackBar(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.EMOJI_EVENTS, color=C.warning, size=16),
                        ft.Text(
                            f"Nuevo récord — {entry.exercise}: {details}",
                            size=12,
                            color=C.text,
                            weight=ft.FontWeight.W_700,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=C.bg_surface,
            )
        )

    def _is_last_exercise(self) -> bool:
        day = self._current_day()
        total = len(day.exercises) if day else 0
        return self.ex_idx + 1 >= total

    # ── Añadir un ejercicio a la sesión de hoy ────────────────

    def _ask_add_exercise(self, _=None):
        """El buscador de los 875, y la lista de lo ya añadido hoy.

        **La búsqueda es la función, no la lista.** Un desplegable de 875
        entradas no se navega: se escriben tres letras y se toca. Por eso el
        campo va arriba, enfocado, y los chips de grupo debajo para el caso en
        que no se sepa cómo se llama lo que se busca — «algo de hombro».
        """
        import catalogo

        resultados = ft.Column(spacing=0, tight=True, scroll=ft.ScrollMode.AUTO, expand=True)
        # Arranca filtrado por lo que se está entrenando hoy. Abrirlo en «Abs
        # Triset, Alternate DB Curl» — los dos primeros de 875 por orden
        # alfabético — es abrirlo en el sitio menos útil posible.
        estado = {"q": "", "grupo": self._grupo_del_dia()}

        # Sin `autofocus`. Con el teclado abierto de entrada, de la lista se
        # veían **dos filas**: el diálogo conserva su altura y el teclado se
        # come la mitad de abajo. Y el camino más corto casi nunca es escribir
        # — es «algo de pecho», que son los chips de aquí al lado.
        campo = ft.TextField(
            hint_text="Busca: curl, press, sentadilla…",
            dense=True,
            border_color=C.border,
            color=C.text,
            text_size=13,
            prefix_icon=ft.Icons.SEARCH,
        )

        def pintar():
            ya = {x.lower() for x in extras.de_hoy(self.store)}
            en_el_dia = {
                exercise_key(x).lower()
                for x in (self._routine_day().exercises if self._routine_day() else [])
            }
            filas: list[ft.Control] = []

            actuales = extras.de_hoy(self.store)
            if actuales:
                filas.append(
                    ft.Container(
                        content=ft.Text(
                            f"AÑADIDOS HOY · {len(actuales)}",
                            size=10,
                            weight=ft.FontWeight.W_700,
                            color=C.text_muted,
                        ),
                        padding=ft.padding.only(bottom=4, top=2),
                    )
                )
                filas += [self._fila_extra_puesto(n, pintar) for n in actuales]
                filas.append(ft.Divider(height=12, color=C.border))

            encontrados = catalogo.buscar(estado["q"], estado["grupo"], limite=40)

            # El grupo viene preseleccionado por el día que se entrena, y eso
            # crea un callejón: buscar «crunch» un día de pecho no devuelve
            # nada, porque los crunch son de abdomen. Antes de decir que no hay
            # nada se mira sin el filtro — y si ahí sí hay, se enseña y se dice
            # por qué. Un buscador que contesta «nada» teniendo la respuesta es
            # peor que uno lento.
            fuera_del_grupo = False
            if not encontrados and estado["q"] and estado["grupo"]:
                encontrados = catalogo.buscar(estado["q"], "", limite=40)
                fuera_del_grupo = bool(encontrados)

            if fuera_del_grupo:
                filas.append(
                    ft.Container(
                        content=ft.Text(
                            f"Nada de {estado['grupo']} con ese nombre. Esto es de otros grupos:",
                            size=11,
                            color=C.text_secondary,
                        ),
                        padding=ft.padding.only(bottom=6, top=2),
                    )
                )
            elif not encontrados:
                filas.append(
                    ft.Container(
                        content=ft.Text(
                            "Nada con ese nombre. Prueba en inglés: los ejercicios se "
                            "guardan con su nombre original para que el historial no se "
                            "parta en dos.",
                            size=11,
                            color=C.text_secondary,
                        ),
                        padding=10,
                    )
                )
            for e in encontrados:
                puesto = e.nombre.lower() in ya
                en_plan = e.nombre.lower() in en_el_dia
                filas.append(self._fila_catalogo(e, puesto, en_plan, pintar))

            resultados.controls = filas
            self.page.update()
            # Después de pintar: la lista aparece ya, y las fotos que falten
            # entran solas cuando lleguen.
            self._pedir_miniaturas(encontrados, pintar)

        def al_escribir(_):
            estado["q"] = campo.value or ""
            pintar()

        campo.on_change = al_escribir

        def chip_grupo(clave: str, etiqueta: str) -> ft.Control:
            activo = estado["grupo"] == clave

            def elegir(_):
                estado["grupo"] = "" if activo else clave
                pintar()

            return ft.Container(
                content=ft.Text(
                    etiqueta,
                    size=11,
                    color=C.on_accent if activo else C.text_secondary,
                    weight=ft.FontWeight.W_700 if activo else ft.FontWeight.W_500,
                ),
                bgcolor=C.accent if activo else C.bg_sunken,
                padding=ft.padding.symmetric(horizontal=10, vertical=5),
                border_radius=Radius.sm,
                on_click=elegir,
                ink=True,
            )

        # Una fila con scroll, no `wrap`: envueltos ocupaban dos filas y cada
        # fila de aquí arriba es un resultado menos abajo.
        grupos = ft.Row(
            [chip_grupo(g, g) for g in catalogo.grupos()],
            spacing=5,
            scroll=ft.ScrollMode.AUTO,
            tight=True,
        )

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=C.bg_surface,
            title=ft.Text(
                "Añadir a la sesión de hoy", size=16, weight=ft.FontWeight.W_900, color=C.text
            ),
            content=ft.Container(
                content=ft.Column(
                    [
                        campo,
                        grupos,
                        ft.Container(height=4),
                        resultados,
                    ],
                    spacing=8,
                    tight=True,
                ),
                width=dialog_width(self.page),
                height=dialog_height(self.page, 460),
            ),
            actions=[
                ft.TextButton(
                    "Listo",
                    on_click=lambda _: self._cerrar_add(dlg),
                    style=ft.ButtonStyle(color=C.accent),
                )
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=lambda _: self.page.data["refresh_current"](),
        )
        self._add_dialog = dlg
        pintar()
        self.page.open(dlg)

    def empezar_abdomen(self):
        """Arranca una sesión de solo abdomen. La llama Inicio.

        Elige una fase para que las series prescritas y el descanso salgan de
        algún sitio: la que ya estuviera puesta, o la primera de la rutina. Un
        día de abdomen no tiene fase propia y sin ninguna, `progression.py` se
        queda sin `scheme` que leer.
        """
        self._entrar_en_modo("abdomen")

    def _cuenta_del_dia(self, dia) -> str:
        """«7 ejercicios», o «7 + 3 de abdomen» cuando el abdomen está puesto.

        Contar solo los de la rutina prometía siete y entregaba diez, y la
        diferencia no se descubría hasta estar dentro. Que el abdomen sea
        aparte en la frase tampoco es cosmético: es lo que hace evidente de
        dónde salen los tres que no estaban en el plan.
        """
        base = len(dia.exercises)
        try:
            extra = len(abdomen.dia_con_abdomen(dia, self.store).exercises) - base
        except Exception:
            extra = 0
        if extra <= 0:
            return plural(base, "ejercicio")
        return f"{plural(base, 'ejercicio')} + {extra} de abdomen"

    def empezar_libre(self):
        """Arranca un entreno sin rutina. La llama Inicio.

        Si aún no hay nada elegido abre el buscador, porque si no la pantalla
        sale con el abdomen del día —o con nada— y sin decir de dónde ha
        salido.
        """
        self._entrar_en_modo("libre")
        if not extras.de_hoy(self.store):
            self._abrir_buscador_al_pintar = True

    def _entrar_en_modo(self, modo: str):
        """Cambia a «libre», «abdomen» o de vuelta a la rutina, limpiando.

        Lo que se limpia es `_sets_by_ex`, y no es higiene: ese diccionario
        guarda **lo tecleado, indexado por posición**, así que entrar en otro
        día con él puesto pone las filas del press de banca bajo el primer
        crunch. Pasó — 60 kg × 10 prellenados en un abdominal, a un toque de
        Guardar y del historial.

        El borrador se persiste antes: cambiar de modo no puede costar lo que
        estaba escrito en la sesión que se deja.
        """
        self._persist_draft()
        self.libre = modo == "libre"
        self.solo_abdomen = modo == "abdomen"
        self.show_phase_list = False
        self.show_day_list = False
        self.day_idx = 0
        self.ex_idx = 0
        self.completed = []
        self.finished = False
        if not self.phase_id:
            fases = active_routine().phases
            self.phase_id = fases[0].id if fases else 1
        self._sets_by_ex = {}
        self._logged_ex = set()
        self._olvidar_cache_ejercicios()

    def _grupo_del_dia(self) -> str:
        """El grupo muscular que toca hoy, sacado del nombre del día.

        Los días se llaman «Chest - Biceps», «Shoulder - Leg»: la primera
        mitad es el grupo principal y coincide con las claves de
        `EXERCISE_CATALOG` porque **es el mismo vocabulario** — `TrainingDay.
        name` va literal a `entrenos.grupo` (trampa 22) y por eso está en
        inglés. Vacío si no reconoce nada, que deja el buscador sin filtro.
        """
        dia = self._routine_day()
        if dia is None:
            return ""
        import catalogo

        cabeza = dia.name.split("-")[0].strip().split("+")[0].strip()
        return cabeza if cabeza in catalogo.grupos() else ""

    async def _abrir_buscador_pronto(self):
        """Abre el buscador en el siguiente ciclo, con la pantalla ya montada."""
        await asyncio.sleep(0.1)
        with contextlib.suppress(Exception):
            self._ask_add_exercise()

    def _cerrar_add(self, dlg):
        self._add_dialog = None
        self.page.close(dlg)
        # Solo ahora: la pantalla de detrás tiene que contar los ejercicios
        # nuevos, y refrescarla con cada añadido cerraría el diálogo encima.
        self.page.data["refresh_current"]()

    def _fila_catalogo(self, e, puesto: bool, en_plan: bool, al_cambiar) -> ft.Control:
        """Un resultado de la búsqueda. Dice si ya está y por qué no se puede."""
        if en_plan:
            nota, activo = "ya está en el plan de hoy", False
        elif puesto:
            nota, activo = "añadido", False
        else:
            nota, activo = e.descripcion(), True

        def anadir(_):
            if extras.anadir(self.store, e.nombre):
                self._olvidar_cache_ejercicios()
                self._bajar_foto(e.slug)
                al_cambiar()

        return ft.Container(
            content=ft.Row(
                [
                    self._miniatura(e.nombre),
                    ft.Column(
                        [
                            ft.Text(
                                e.nombre,
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=C.text if activo else C.text_muted,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(nota, size=10, color=C.text_muted),
                        ],
                        spacing=1,
                        expand=True,
                        tight=True,
                    ),
                    ft.Icon(
                        ft.Icons.ADD_CIRCLE_OUTLINE if activo else ft.Icons.CHECK,
                        size=18,
                        color=C.accent if activo else C.text_muted,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=anadir if activo else None,
            ink=activo,
            padding=ft.padding.symmetric(vertical=7, horizontal=4),
            border_radius=Radius.sm,
        )

    def _miniatura(self, nombre: str) -> ft.Control:
        """La foto de un resultado, o un hueco de su tamaño.

        Siempre ocupa lo mismo — 46×34 — esté la foto o no: una lista donde
        las filas cambian de alto según lo que se haya descargado salta bajo
        el dedo mientras se lee.

        `cache_width` no es opcional (trampa 11): la miniatura es pequeña en
        disco pero decodifica a lo que mida, y cuarenta resultados sin eso es
        una lista que mata la app por memoria.
        """
        props = image_props(nombre, thumb=True)
        if not props:
            return ft.Container(width=46, height=34)
        return ft.Container(
            content=ft.Image(
                **props,
                fit=ft.ImageFit.COVER,
                cache_width=92,
                cache_height=68,
                border_radius=4,
            ),
            width=46,
            height=34,
            border_radius=4,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

    def _pedir_miniaturas(self, ejercicios, al_cambiar):
        """Baja las miniaturas que falten de lo que hay en pantalla.

        Solo lo visible: cuarenta resultados son ~400 KB, y bajar las 875 de
        golpe para enseñar cuarenta sería gastar la conexión de alguien que
        está en un gimnasio. El resto llega cuando se busca otra cosa.
        """
        import asset_manager
        import catalogo

        faltan = [
            s
            for s in {catalogo.slug_de(e.nombre) for e in ejercicios}
            if s and asset_manager.thumb_path(s) is None
        ]
        if not faltan:
            return

        async def _bajar():
            if await asset_manager.descargar_miniaturas(faltan):
                al_cambiar()

        with contextlib.suppress(Exception):
            self.page.run_task(_bajar)

    def _fila_extra_puesto(self, nombre: str, al_cambiar) -> ft.Control:
        """Un extra ya añadido, con su papelera — salvo si ya tiene series.

        Quitar uno registrado dejaría la fila en `entrenos` sin nada en
        pantalla que la explique. El historial se edita en Historial, que es
        donde borrar algo cuesta lo que tiene que costar.
        """
        guardado = self._extra_ya_guardado(nombre)

        def quitar(_):
            if extras.quitar(self.store, nombre):
                self._olvidar_cache_ejercicios()
                al_cambiar()

        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(nombre, size=12, color=C.text, expand=True, max_lines=1),
                    ft.Text("guardado", size=10, color=C.success)
                    if guardado
                    else ft.Container(
                        content=ft.Icon(ft.Icons.CLOSE, size=15, color=C.text_muted),
                        on_click=quitar,
                        ink=True,
                        width=28,
                        height=28,
                        alignment=ft.alignment.center,
                        border_radius=Radius.sm,
                        tooltip="Quitarlo de hoy",
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(vertical=4, horizontal=4),
        )

    def _extra_ya_guardado(self, nombre: str) -> bool:
        """¿Hay ya una fila de hoy para ese ejercicio?"""
        try:
            clave = exercise_key(nombre)
            return any(
                exercise_key(e.exercise) == clave
                for e in self.store.get_workouts_on(self.session_date())
            )
        except Exception:
            return False

    def _bajar_foto(self, slug: str):
        """Pide la foto del ejercicio recién añadido, sin esperar.

        El tarball trae los 87 slugs del catálogo de casa, así que un ejercicio
        de los otros 788 no tendría foto nunca — tampoco al reinstalar, porque
        `missing_slugs()` mide contra `EXERCISE_IMAGE` y ese slug no está ahí.

        En segundo plano y sin decir nada: se está en mitad de un entreno y una
        foto que no llega no puede interrumpir eso. Sin red simplemente no hay
        foto, que es como estaba antes.
        """
        if not slug:
            return
        with contextlib.suppress(Exception):
            import asset_manager

            self.page.run_task(asset_manager.descargar_uno, slug)

    def _olvidar_cache_ejercicios(self):
        """Los índices se han movido: todo lo memoizado por posición miente.

        Un extra entra al final, así que en teoría no mueve nada — pero quitar
        uno de en medio sí, y estos diccionarios están indexados por posición
        (`_sets_by_ex`, `_last_sets_cache`). Vaciar lo memoizado cuesta una
        consulta; equivocarse cuesta pintar las series de un ejercicio bajo el
        nombre de otro.
        """
        self._last_sets_cache.clear()
        with contextlib.suppress(AttributeError):
            self._rec_cache.clear()

    def _session_button(self, icono, texto: str, tinte: str, ayuda: str, accion) -> ft.Control:
        """Un botón de los que actúan sobre la sesión entera, no sobre la serie."""
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icono, size=15, color=tinte),
                    ft.Text(texto, size=12, weight=ft.FontWeight.W_700, color=tinte),
                ],
                spacing=6,
                tight=True,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            border=ft.border.all(1, tinte),
            border_radius=Radius.md,
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            alignment=ft.alignment.center,
            tooltip=ayuda,
            on_click=accion,
            ink=True,
        )

    # ── Finishing: on screen from the first exercise ──────────
    def _ask_finish(self, _):
        """Confirm before closing the session.

        Finish used to be unreachable until the last exercise, which is what
        Alex hit: the session ends when he is done, not when the app has
        walked him through every row of the plan. So it is now on screen from
        exercise 1 — and that makes it a destructive control one tap away from
        Save, because it stops the clock and clears the draft.

        Hence the dialog, and hence its most important job: naming the
        exercises that are typed but not yet written, and writing them. The
        rest of this view spends a lot of effort never losing a number; an
        always-visible exit that dropped them would give it all back.
        """
        unsaved = self._unsaved_exercises()
        logged = len(self.completed)
        dlg = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dlg)

        def confirm(_):
            self.page.close(dlg)
            self._confirm_finish()

        lines: list[ft.Control] = [
            ft.Text(
                f"{plural(logged, 'ejercicio')} en el registro · "
                f"{self._format_elapsed(self._session_elapsed_s())}",
                size=12,
                color=C.text_secondary,
            )
        ]
        # Last checkpoint before the flush below writes everything still
        # pending. If a day is wrong, this is the final place it is cheap to
        # notice — afterwards it is rows in `entrenos`, and this app does not
        # delete history. So it names **every** day being written, not just the
        # session default: a sitting that fills in Monday and Tuesday has two
        # answers to "where is this going" and printing one of them is worse
        # than printing neither.
        days = self._dates_in_use()
        if days != (date.today(),):
            names = ", ".join(_date_label(d) for d in days)
            lines.append(
                ft.Text(
                    f"Escribiendo en {names}."
                    if len(days) > 1
                    else f"Escribiendo en {names} — hoy no.",
                    size=12,
                    color=C.warning,
                    weight=ft.FontWeight.W_700,
                )
            )
        # And what the clock is going to be allowed to claim. Said here rather
        # than only on the summary because "the timer measured your typing" is
        # the sort of thing a reader wants to hear *before* trusting a number,
        # not after.
        lines.append(
            ft.Text(
                (
                    f"Se guardará un tiempo de sesión de {format_duration(self._session_elapsed_s())} "
                    "— podrás corregirlo ahora mismo."
                    if self._clock_measures(days)
                    else "El reloj no se guarda como tu tiempo de sesión — "
                    "podrás teclear el real ahora mismo."
                ),
                size=11,
                color=C.text_secondary,
            )
        )
        if unsaved:
            lines.append(ft.Container(height=6))
            lines.append(
                ft.Text(
                    "Estos tienen series sin guardar. Se escriben en tu historial ahora:",
                    size=12,
                    color=C.warning,
                    weight=ft.FontWeight.W_700,
                )
            )
            lines.append(
                ft.Text(
                    " · ".join(name for _idx, name in unsaved),
                    size=12,
                    color=C.text,
                )
            )

        dlg.title = ft.Text(
            "¿Terminar la sesión?", size=16, weight=ft.FontWeight.W_900, color=C.text
        )
        dlg.content = ft.Column(lines, spacing=2, tight=True)
        dlg.actions = [
            ghost_button("Seguir entrenando", on_click=close),
            primary_button("Guardar y terminar" if unsaved else "Terminar", on_click=confirm),
        ]
        dlg.actions_alignment = ft.MainAxisAlignment.END
        dlg.bgcolor = C.bg_surface
        self.page.open(dlg)

    def _confirm_finish(self):
        saved, ok = self._flush_unsaved()
        if not ok:
            # Some of it did not make it. Closing now would clear the draft and
            # lose the rest, so the session stays exactly where it is and the
            # user can try Finish again.
            self._toast(
                "No se pudo guardar todo — la sesión sigue abierta.",
                ft.Icons.ERROR_OUTLINE,
                C.danger,
            )
            self.page.data["refresh_current"]()
            return
        if saved:
            self._toast(
                f"Guardados {plural(saved, 'ejercicio más', 'ejercicios más')}.",
                ft.Icons.CHECK_CIRCLE,
                C.success,
            )
        self._finish_session()

    def _finish_session(self):
        self.finished = True
        self.timer.stop()
        # Order matters: the clock has to be stopped before it is read, or the
        # stored duration keeps counting for as long as the summary is on
        # screen — the exact "it measured the typing" failure, at one remove.
        self._stop_session_timer()
        self._store_measured_duration()
        # Everything in this session is already in `entrenos`. A draft left
        # behind would resurrect a finished workout on the next visit to the
        # Train tab — and offer to log it a second time.
        self._clear_draft()
        self.page.data["refresh_current"]()

    def _finish(self, _):
        self._reset()
        nav = self.page.data["navigate_to"]
        nav(0)

    # ── Abandoning a workout: explicit, and only here ─────────
    def _ask_discard(self, then):
        """Confirm before throwing a live workout away.

        This is the *only* path that discards one. Everything else — back,
        Esc, an edge swipe, re-picking the phase — is navigation now. The
        callback runs on Yes and nothing happens on No, which is what an
        accidental tap deserves.
        """
        dlg = ft.AlertDialog(modal=True)

        def close(_=None):
            self.page.close(dlg)

        def confirm(_):
            self.page.close(dlg)
            self._discard_workout()
            then()

        dlg.title = ft.Text(
            "¿Descartar este entreno?", size=16, weight=ft.FontWeight.W_900, color=C.text
        )
        dlg.content = ft.Text(
            "Las series ya guardadas se quedan en tu historial. Lo tecleado y "
            "no guardado se pierde.",
            size=12,
            color=C.text_secondary,
        )
        dlg.actions = [
            ghost_button("Seguir entrenando", on_click=close),
            primary_button("Descartar", on_click=confirm),
        ]
        dlg.actions_alignment = ft.MainAxisAlignment.END
        dlg.bgcolor = C.bg_surface
        self.page.open(dlg)

    def _discard_workout(self):
        """Drop the in-flight session. Saved sets are untouched — they are
        already rows in `entrenos` and this app does not delete history."""
        self.day_idx = -1
        self.ex_idx = 0
        self._scope = ()
        self._sets_by_ex = {}
        self._last_sets_cache = {}
        self._logged_ex = set()
        self._history_cache = {}
        self._rec_cache = {}
        self._plan_cache = {}
        self._start_cache = {}
        self._subs_cache = None
        self.completed = []
        self.finished = False
        self.timer.stop()
        self._stop_session_timer()
        self.session_started_at = None
        self.session_ended_at = None
        # See `_reset`: every date here — the session's and each exercise's — is
        # scoped to the session being thrown away.
        self._dates_by_key = {}
        self._forget_durations()
        self._reset_log_date(persist=False)
        self._clear_draft()

    # ── Render: phase select ──────────────────────────────────
    def _render_phase_select(self) -> ft.Control:
        routine = active_routine()
        return ft.Column(
            [
                ft.Text("Empezar sesión", size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Text(
                    f"Rutina: {routine.name}",
                    size=11,
                    color=C.accent,
                    weight=ft.FontWeight.W_700,
                ),
                ft.Text("Elige tu fase actual", size=11, color=C.text_muted),
                ft.Container(height=10),
                # Backing all the way out of a live workout must not hide it:
                # without this the only way back would be to re-pick the phase
                # and hope, which is exactly the guesswork this change removes.
                self._in_progress_banner(),
                *[
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    f"FASE {p.id}",
                                    size=10,
                                    # `p.color` is the raw hex from data.py,
                                    # picked against a black background: on a
                                    # white card #FFD93D is 1.38:1, invisible.
                                    color=phase_color(p.id),
                                    weight=ft.FontWeight.W_900,
                                ),
                                ft.Text(p.name, size=17, weight=ft.FontWeight.W_900, color=C.text),
                                ft.Text(
                                    describir_esquema(p.scheme), size=11, color=C.text_secondary
                                ),
                            ],
                            spacing=2,
                            tight=True,
                        ),
                        bgcolor=C.bg_surface,
                        border=ft.border.all(1, C.border),
                        border_radius=12,
                        padding=14,
                        margin=ft.margin.only(bottom=8),
                        on_click=lambda _, pid=p.id: self._select_phase(pid),
                        ink=True,
                    )
                    for p in routine.phases
                ],
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=0,
            expand=True,
            tight=True,
        )

    # ── Render: day select ────────────────────────────────────
    def _render_day_select(self) -> ft.Control:
        phase = self._phase()
        assert phase
        days = active_routine().days_for_phase(phase.id)
        return ft.Column(
            [
                # Not `_select_phase(0)`: that is a *state* change and it used
                # to drag the open workout down with it. Showing the phase list
                # is a screen, and `phase_id` stays where it is.
                self._back_btn("Fases", lambda _: self._show_phases()),
                ft.Text(phase.name, size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Container(height=10),
                # Above the day cards, not below: the date is part of choosing
                # which session this is, and it has to be answered before the
                # tap that starts one.
                self._log_date_row(),
                self._in_progress_banner(),
                *[
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(
                                            d.name,
                                            size=14,
                                            weight=ft.FontWeight.W_700,
                                            color=C.text,
                                        ),
                                        ft.Text(
                                            self._cuenta_del_dia(d),
                                            size=11,
                                            color=C.text_secondary,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Icon(
                                    ft.Icons.PLAY_ARROW_ROUNDED,
                                    color=phase_color(phase.id),
                                    size=22,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        bgcolor=C.bg_surface,
                        border=ft.border.all(1, C.border),
                        border_radius=12,
                        padding=14,
                        margin=ft.margin.only(bottom=8),
                        on_click=lambda _, i=i: self._select_day(i),
                        ink=True,
                    )
                    for i, d in enumerate(days)
                ],
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            tight=True,
            spacing=0,
        )

    def _show_phases(self):
        self.show_phase_list = True
        self.page.data["refresh_current"]()

    # ── Render: the logging date, in its three sizes ──────────
    def _log_date_row(self) -> ft.Control:
        """The day-select screen's line. Always on screen, quiet until it isn't.

        Quiet is the point: it sits between the phase title and the day cards,
        one line tall, saying "Today" for the ordinary workout. It is the home
        of this setting because it is the last thing seen before a session
        starts, so "which day is this" is answered before the first set instead
        of after the last.
        """
        off = self.is_backdated()
        tint = C.warning if off else C.text_muted
        lines: list[ft.Control] = [
            ft.Text("REGISTRANDO EN", size=9, color=tint, weight=ft.FontWeight.W_900),
            ft.Text(
                self._log_date_text(),
                size=13,
                color=C.text,
                weight=ft.FontWeight.W_900,
            ),
        ]
        moved = len(self._dates_by_key)
        if moved:
            # The session default alone would be a half-truth on this screen:
            # the exercises with a day of their own are exactly the ones this
            # line does not describe, and this is the screen he lands on when he
            # comes back to the workout.
            lines.append(
                ft.Text(
                    f"{plural(moved, 'ejercicio')} con día propio",
                    size=10,
                    color=C.warning,
                    weight=ft.FontWeight.W_700,
                )
            )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.EVENT_BUSY if off else ft.Icons.EVENT_AVAILABLE,
                        size=15,
                        color=tint,
                    ),
                    ft.Column(lines, spacing=0, expand=True),
                    ft.Text("Cambiar", size=11, color=C.accent, weight=ft.FontWeight.W_700),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.warning if off else C.border),
            border_radius=12,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            margin=ft.margin.only(bottom=8),
            tooltip="Cambiar el día bajo el que se escribe esta sesión",
            on_click=self._open_date_dialog,
            ink=True,
        )

    def _backdate_strip(self) -> ft.Control:
        """The exercise screen's day line. **This is the control the feature
        lives or dies by**, and it answers for one exercise, not for the session.

        Two states, and the second one is the whole reason this was rewritten:

        * **Nothing dated anywhere** — zero height. The ordinary workout, which
          is 95 % of them, pays nothing at all for a feature it never uses.
        * **Anything dated anywhere** — every exercise screen carries this line,
          *including the exercises that resolve to today*. Alex's real exposure
          was never "Monday is on screen". It is Monday on exercise 2 with
          nothing on exercise 3 saying otherwise, so the reader carries Monday
          forward in their head and files a Wednesday lift into it. A line that
          only appears when something is wrong teaches the reader that no line
          means nothing to check; a line that is always there once dates are in
          play has to be read, and reading it is the mitigation.
        * **Zen mode does not remove it, in either state.** Zen strips reference
          material. This is not reference material, it is the difference between
          a log and a lie.

        The day is never printed bare. `_scope_text` says whether it came from
        this exercise or from the session, because a reader who has to
        *attribute* a date is a reader who will attribute it wrong — and when
        the session touches two days the strip says that too, before the write
        rather than in History a week later.
        """
        if not self._any_date_chosen():
            return ft.Container()
        resolved = self._resolve_date()
        off = resolved.day != date.today()
        # Warning ink is spent only on the day that is not today. An exercise
        # sitting on today inside a dated session is not an alarm — it is the
        # fact the reader most needs and least expects — so it gets the same
        # unmissable line in the app's ordinary accent.
        tint = C.warning if off else C.accent
        lines: list[ft.Control] = [
            ft.Text(
                "NO ES HOY" if off else "HOY",
                size=9,
                color=tint,
                weight=ft.FontWeight.W_900,
            ),
            ft.Text(
                f"Guardando en {_date_label(resolved.day)} · {self._scope_text(resolved)}",
                size=13,
                color=C.text,
                weight=ft.FontWeight.W_900,
            ),
        ]
        multi = self._multi_day_text()
        if multi:
            lines.append(ft.Text(multi, size=10, color=C.text_secondary))
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.EVENT_BUSY if off else ft.Icons.EVENT_AVAILABLE,
                        size=17,
                        color=tint,
                    ),
                    ft.Column(lines, spacing=0, expand=True),
                    ft.Text("Cambiar", size=11, color=tint, weight=ft.FontWeight.W_700),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_sunken,
            border=ft.border.all(1, tint),
            border_radius=Radius.md,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            margin=ft.margin.only(bottom=10),
            tooltip=(
                "Estas series van a un día pasado — toca para cambiarlo"
                if off
                else "Estas series van a hoy — toca para archivar este ejercicio en otro día"
            ),
            # Scoped to the exercise on screen, which is what the tap came from
            # and what the strip is describing. The dialog can still reach the
            # whole session in one more tap.
            on_click=lambda _: self._open_date_dialog(ex_idx=self.ex_idx),
            ink=True,
        )

    def _log_date_chip(self) -> ft.Control:
        """The small "Today" pill on the exercise card's first line.

        Renders only when **no date has been chosen anywhere in this session**
        and zen mode is off — the one case where the strip above says nothing.
        The moment anything is dated the strip takes over on every exercise, and
        two controls saying "which day" on one card would be one too many.

        Without this pill the setting would be unreachable from inside a session
        without walking back to the day list; with it the whole cost is one
        muted pill on a line that otherwise holds nothing but "EXERCISE 3".
        """
        if self.zen or self._any_date_chosen():
            return ft.Container()
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.EVENT_AVAILABLE, size=11, color=C.text_muted),
                    ft.Text("Hoy", size=10, color=C.text_muted, weight=ft.FontWeight.W_700),
                ],
                spacing=3,
                tight=True,
            ),
            border=ft.border.all(1, C.border),
            border_radius=Radius.sm,
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
            tooltip="Registrando en hoy — toca para archivar este ejercicio en otro día",
            on_click=lambda _: self._open_date_dialog(ex_idx=self.ex_idx),
            ink=True,
        )

    def _in_progress_banner(self) -> ft.Control:
        """ "Tienes un entreno abierto" — the way back in, and the way out.

        The only exit from a live session, and it asks first. Without this the
        day list would be a dead end: tapping the day you are already training
        resumes it, and nothing on screen would say why.
        """
        if not self._workout_in_progress():
            return ft.Container()
        days = active_routine().days_for_phase(self.phase_id)
        name = days[self.day_idx].name if 0 <= self.day_idx < len(days) else "Entreno"
        done = len(self.completed)
        detail = f"{done} en el registro · {self._format_elapsed(self._session_elapsed_s())}"
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PLAY_CIRCLE_FILL_ROUNDED, color=C.accent, size=18),
                            ft.Column(
                                [
                                    ft.Text(
                                        f"En curso · {name}",
                                        size=13,
                                        weight=ft.FontWeight.W_900,
                                        color=C.text,
                                    ),
                                    ft.Text(detail, size=11, color=C.text_secondary),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            ghost_button(
                                "Descartar",
                                on_click=lambda _: self._ask_discard(
                                    lambda: self.page.data["refresh_current"]()
                                ),
                                expand=True,
                            ),
                            primary_button(
                                "Retomar",
                                on_click=lambda _: self._resume_day(),
                                expand=True,
                            ),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=10,
            ),
            bgcolor=C.accent_soft,
            border=ft.border.all(1, C.accent),
            border_radius=12,
            padding=12,
            margin=ft.margin.only(bottom=12),
        )

    # ── Render: finished ──────────────────────────────────────
    @staticmethod
    def _set_chip(one_set: dict) -> ft.Control:
        """One logged set as a chip.

        Sets that are not plain working sets carry their badge and their own
        colour: a warm-up that reads like a top set is exactly the confusion
        this is here to end. Rows written before types existed — and the ones
        the Telegram coach writes — have no `"type"` and render as normal.
        """

        # `:g` on a value the table never promised is a crashed screen: three
        # programs write this JSON, so read it the way `set_types` does.
        def num(value) -> str:
            return f"{value:g}" if isinstance(value, (int, float)) else str(value)

        label = f"{num(one_set.get('weight') or 0)}kg × {num(one_set.get('reps') or 0)}"
        rir = one_set.get("rir")
        if rir is not None:
            label += f" · RIR {num(rir)}"
        set_type = set_type_of(one_set)
        if set_type is SetType.NORMAL:
            return chip(label, color=C.accent)
        return chip(f"{short_label_for(set_type)} · {label}", color=_set_type_color(set_type))

    def _render_finished(self) -> ft.Control:
        completed_blocks = []
        for c in self.completed:
            warm = warmup_sets(c["sets"])
            # Both of these read "1 sets" and "2 warm-up" before `plural`
            # existed. The summary of a finished session is the one screen
            # every workout ends on, so it is also the one where a broken
            # plural is seen every single time.
            count = plural(len(working_sets(c["sets"])), "serie")
            if warm:
                count += f" · {plural(len(warm), 'calentamiento')}"
            completed_blocks.append(
                card(
                    ft.Row(
                        [
                            ft.Text(
                                c["exercise"],
                                size=13,
                                weight=ft.FontWeight.W_700,
                                color=C.text,
                                expand=True,
                            ),
                            ft.Text(count, size=10, color=C.text_muted),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [self._set_chip(s) for s in c["sets"]],
                        wrap=True,
                        spacing=6,
                        run_spacing=4,
                    ),
                    padding=12,
                    margin=ft.margin.only(bottom=6),
                )
            )
        # Finish is reachable from the first exercise now, so a session can end
        # with nothing written — a wrong day picked, a warm-up cut short.
        # Confetti over an empty log is a lie, and the count read
        # "1 exercises logged" either way.
        logged = len(self.completed)
        if logged:
            hero = "🎉"
            title = "¡Sesión completa!"
            subtitle = f"{plural(logged, 'ejercicio registrado', 'ejercicios registrados')}"
            subtitle_color = C.accent
        else:
            hero = "👋"
            title = "Sesión cerrada"
            subtitle = "Esta vez no se registró nada"
            subtitle_color = C.text_muted

        # Says where it went. Without this the summary would read exactly the
        # same for a session filed under today and one filed under Saturday,
        # and the only way to find out would be the History tab. Every day is
        # named, because a sitting that filled in Monday and Tuesday has two
        # answers and this is the last screen that can give both.
        written = self._logged_days()
        date_line: ft.Control = (
            ft.Row(
                [
                    ft.Icon(ft.Icons.EVENT_BUSY, color=C.warning, size=14),
                    ft.Text(
                        f"Registrado en {', '.join(_date_label(d) for d in written)}",
                        size=12,
                        color=C.warning,
                        weight=ft.FontWeight.W_700,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=6,
                tight=True,
            )
            if written and written != (date.today(),)
            else ft.Container()
        )

        return ft.Column(
            [
                ft.Container(height=20),
                ft.Text(hero, size=56, text_align=ft.TextAlign.CENTER),
                ft.Text(
                    title,
                    size=22,
                    weight=ft.FontWeight.W_900,
                    color=C.text,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    subtitle,
                    size=13,
                    color=subtitle_color,
                    weight=ft.FontWeight.W_700,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=6),
                date_line,
                ft.Container(height=16),
                self._duration_block(),
                # Above the exercise list rather than under it: the session is
                # over, this is the one thing left to do, and a note buried
                # below eight cards on a phone is a note nobody writes.
                self._session_note_block(),
                *completed_blocks,
                ft.Container(height=10),
                primary_button("Volver a Inicio", on_click=self._finish, expand=True),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            tight=True,
            spacing=4,
        )

    # ── Render: active exercise ───────────────────────────────
    def _next_set_hint(self) -> str:
        """The one line worth reading from across the gym: what to do next.

        The next set is the first row he has not claimed — a suggestion carries
        last session's numbers, an empty row carries none — so this doubles as
        "the weight to put on the bar" without him having to find the right row
        on a 420 px screen with the phone on the floor.

        It never guesses past the end: once every row is his, the exercise is
        waiting to be written, and once written there is nothing left to do here.
        """
        if self.ex_idx in self._logged_ex:
            return "REGISTRADO — SIGUE"
        rows = self.sets
        total = len(rows)
        for i, row in enumerate(rows):
            if not self._is_suggested(row) and self._has_content(row):
                continue
            weight, reps = row.get("weight", ""), row.get("reps", "")
            if weight and reps:
                target = f" · {weight} kg × {reps}"
            elif weight:
                target = f" · {weight} kg"
            elif reps:
                target = f" · × {reps}"
            else:
                target = ""
            return f"SERIE {i + 1} DE {total}{target}"
        return "TODAS LAS SERIES HECHAS — GUARDA ESTE EJERCICIO"

    def _zen_toggle(self) -> ft.Control:
        """The way out of zen mode, and back in. Always on screen, one tap.

        This is what keeps zen from being a trap. It is not hidden behind a
        long-press or a settings screen: the state is visible in the header and
        flipping it is a single tap with a 40 px target, which is the size a
        sweaty thumb needs.
        """
        on = self.zen
        return ft.Container(
            content=ft.Icon(
                ft.Icons.CENTER_FOCUS_STRONG if on else ft.Icons.CENTER_FOCUS_WEAK,
                size=18,
                color=C.accent if on else C.text_muted,
            ),
            width=40,
            height=40,
            bgcolor=C.accent_soft if on else C.bg_sunken,
            border=ft.border.all(1, C.accent if on else C.border),
            border_radius=Radius.md,
            alignment=ft.alignment.center,
            tooltip=(
                "Modo zen activo — toca para recuperar el resto de la app"
                if on
                else "Modo zen apagado — toca para centrarte en el entreno"
            ),
            on_click=self._toggle_zen,
            ink=True,
        )

    def _step_button(self, icon: str, tooltip: str, on_click, *, enabled: bool) -> ft.Control:
        """A square arrow flanking Save. Fixed width, so Save keeps the rest.

        Disabled means **no handler at all**, not a greyed one: a Flet
        `Container` with `ink=True` ripples under the finger whether or not
        anything happens, and a ripple that does nothing reads as a tap that
        was missed rather than one that was refused.
        """
        return ft.Container(
            content=ft.Icon(icon, size=22, color=C.accent if enabled else C.text_muted),
            width=52,
            height=48,
            border=ft.border.all(1, C.border_strong if enabled else C.border),
            border_radius=Radius.md,
            alignment=ft.alignment.center,
            tooltip=tooltip if enabled else None,
            on_click=on_click if enabled else None,
            ink=enabled,
        )

    def _progression_banner(self) -> ft.Control:
        """What `progression.py` says to do today, above the rows. Never modal.

        Requirement 2. It is on screen exactly while it is useful — before the
        first working set of the exercise — and it removes itself the moment
        one is confirmed, so it costs nothing for the rest of the movement and
        can never appear halfway through a set.

        The whole card is one big tap target and the tap does one harmless
        thing: it unfolds the sentence explaining the number, in place. That
        sentence is `progression`'s `reason`, which quotes the real numbers of
        the previous session — the argument, not a slogan. A dialog would have
        been the obvious way to show it and the wrong one: it blocks while the
        rest timer runs, with the phone on the floor.

        With no history at all `progression` returns `BASELINE` and no weight.
        Nothing is invented here either: the card says so and opens with the
        explanation of what to look for, because that is the case where the
        user has the least to go on.
        """
        # Dropped first, on every path: a reference to a control that is not
        # going to be in this tree is a reference `_toggle_reason` would flip
        # on something nobody can see.
        self._reason_text = None
        if self.ex_idx in self._logged_ex or self._has_confirmed_work():
            return ft.Container()
        rec = self._recommendation(self.ex_idx)
        if rec is None:
            return ft.Container()

        # Colours resolved here, inside the call: `C` reads the *active*
        # palette at attribute-access time and a module-level table would
        # freeze whichever theme was loaded at import.
        looks = {
            Action.ADD_WEIGHT: ("Sube", ft.Icons.TRENDING_UP, C.success),
            Action.REPEAT: ("Mismo peso", ft.Icons.REPLAY, C.accent),
            Action.BACK_OFF: ("Baja", ft.Icons.TRENDING_DOWN, C.warning),
            Action.HOLD_STALE: ("Mantén", ft.Icons.PAUSE_CIRCLE_OUTLINE, C.warning),
            Action.HOLD_DELOAD: ("Descarga — mantén", ft.Icons.SPA_OUTLINED, C.accent_2),
            Action.BASELINE: ("Primera vez", ft.Icons.HELP_OUTLINE, C.text_secondary),
        }
        verb, icon, tint = looks.get(rec.action, ("Hoy", ft.Icons.FITNESS_CENTER, C.accent))
        headline = rec.headline()
        line = f"{verb} · {headline}" if headline else verb

        # Open by default only when there is no number: then the sentence *is*
        # the content. Otherwise the number is the content and the argument is
        # one tap away.
        reason = ft.Text(
            rec.reason,
            size=10,
            color=C.text_secondary,
            visible=rec.action is Action.BASELINE,
        )
        self._reason_text = reason

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon, size=16, color=tint),
                            ft.Text(
                                line,
                                size=14,
                                weight=ft.FontWeight.W_900,
                                color=tint,
                                expand=True,
                            ),
                            ft.Icon(ft.Icons.INFO_OUTLINE, size=14, color=C.text_muted),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    reason,
                ],
                spacing=6,
                tight=True,
            ),
            bgcolor=C.bg_sunken,
            border=ft.border.all(1, tint),
            border_radius=Radius.md,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            margin=ft.margin.only(top=8),
            tooltip="Toca para ver el porqué",
            on_click=self._toggle_reason,
            ink=True,
        )

    def _warmup_strip(self) -> ft.Control:
        """One tap that puts the whole approach ramp on screen as rows.

        Requirement 4. It is a single target the size of a button rather than
        one chip per warm-up, because four small targets is four chances to
        press the wrong one with wet hands, and because the ramp is one
        decision: warm up for this weight, or do not.

        Visible only before the first working set, and only while there is no
        warm-up row already in the list — so it never turns up mid-exercise,
        and pressing it twice by accident cannot stack two ramps.

        Rendered in zen mode too, unlike the reference material zen strips out.
        Zen removes what is worth reading *before* a workout and clutter during
        one; this is the opposite — an action, taken at the start, that deletes
        itself afterwards. Hiding it in zen would hide it by default, since zen
        is on by default.
        """
        if self.ex_idx in self._logged_ex or self._has_confirmed_work():
            return ft.Container()
        if any(set_type_of(row) is SetType.WARMUP for row in self.sets):
            return ft.Container()
        plan = self._warmup_plan()
        if not plan:
            return ft.Container()

        preview = " · ".join(f"{_num_text(w.weight)}×{w.reps}" for w in plan)
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, size=15, color=C.warning),
                            ft.Text(
                                f"Añadir {plural(len(plan), 'serie de calentamiento', 'series de calentamiento')}",
                                size=12,
                                weight=ft.FontWeight.W_900,
                                color=C.warning,
                                expand=True,
                            ),
                            ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=15, color=C.warning),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(preview, size=10, color=C.text_secondary, weight=ft.FontWeight.W_700),
                ],
                spacing=2,
                tight=True,
            ),
            bgcolor=C.bg_sunken,
            border=ft.border.all(1, C.warning),
            border_radius=Radius.md,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            margin=ft.margin.only(bottom=8),
            tooltip="Todos los pesos de aquí se montan con tus discos",
            on_click=self._add_warmup_sets,
            ink=True,
        )

    def _history_block(self) -> ft.Control:
        """The last few sessions of *this* exercise, without leaving the screen.

        Requirement 5. Until now the screen showed exactly one previous session
        and only as grey prefill, so "am I actually moving up?" meant leaving
        the workout for the History tab — and leaving mid-exercise is the thing
        this view spends most of its code preventing.

        Folded away by default and unfolded **in place**: `_toggle_history`
        flips the visibility of two mounted controls and never rebuilds the
        tree, so a half-typed weight keeps its text, its focus and its caret.
        That is what "without losing what you wrote" has to mean on a phone.
        """
        self._history_body = None
        self._history_arrow = None
        entries = self._exercise_history(self.ex_idx)
        if not entries:
            return ft.Container()
        # `get_exercise_history` returns oldest first; the interesting end is
        # the recent one.
        recent = list(reversed(entries))[:HISTORY_SESSIONS]

        blocks: list[ft.Control] = []
        for entry in recent:
            sets = list(getattr(entry, "sets", None) or [])
            when = str(getattr(entry, "date", "") or "")
            label = when
            with contextlib.suppress(ValueError, TypeError):
                # Relative to the day *this exercise* is being filed under, not
                # to the wall clock: on an exercise moved to Monday, "Today" in
                # its own history panel has to mean Monday or the panel is
                # reading a different calendar from the strip above it.
                label = _date_label(date.fromisoformat(when), self._date_for(self.ex_idx))
            blocks.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        label,
                                        size=10,
                                        color=C.text_secondary,
                                        weight=ft.FontWeight.W_700,
                                        expand=True,
                                    ),
                                    ft.Text(
                                        plural(len(working_sets(sets)), "serie"),
                                        size=10,
                                        color=C.text_muted,
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Row(
                                [self._set_chip(one) for one in sets],
                                wrap=True,
                                spacing=6,
                                run_spacing=4,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    bgcolor=C.bg_page,
                    border_radius=8,
                    padding=8,
                )
            )

        body = ft.Column(blocks, spacing=6, tight=True, visible=self._show_history)
        self._history_body = body
        arrow = ft.Icon(
            ft.Icons.EXPAND_LESS if self._show_history else ft.Icons.EXPAND_MORE,
            size=16,
            color=C.accent,
        )
        self._history_arrow = arrow
        toggle = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.HISTORY, size=14, color=C.accent),
                    ft.Text(
                        # "Últimas 1 sesión" is the "1 sets" bug in Spanish, so
                        # the adjective drops the count instead of disagreeing
                        # with it; `plural` handles every other number.
                        "Última sesión"
                        if len(recent) == 1
                        else f"Últimas {plural(len(recent), 'sesión')}",
                        size=11,
                        color=C.accent,
                        weight=ft.FontWeight.W_700,
                        expand=True,
                    ),
                    arrow,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_radius=8,
            tooltip="Sesiones anteriores de este ejercicio — nada de lo escrito se toca",
            on_click=self._toggle_history,
            ink=True,
        )
        return ft.Column([toggle, body], spacing=4, tight=True)

    # ── Render: what the plan asked for ───────────────────────
    def _plan_strip(self) -> ft.Control:
        """One line naming the prescription the rows were opened from.

        Two things earn it its height, and both are things that used to be
        invisible:

        * **A drop set exists.** Phase 6 is called "Drop Sets + Compound" and
          its `[4×10,10,8,6+12↓]` used to open four identical rows. The drop row
          is now there and typed, and this says so before the first set.
        * **The plan and last session disagree.** `session_plan` follows the
          plan — the routine is periodized over 24 weeks and copying last
          session's set count copies the previous phase's prescription — and it
          reports both numbers precisely so the other one is not lost. "Plan · 5
          sets · última sesión 4 series" is the whole disagreement, on one line.
          (The "5 sets" half is `SessionPlan.label()`, still English: it lives in
          `session_plan.py`, which no translation pass has reached yet.)

        Neither of these is noise during a set, so both survive zen mode. The
        plain "3 sets" case does not: it is reference material, and zen exists to
        take reference material off the screen.
        """
        if self.ex_idx in self._logged_ex:
            return ft.Container()
        plan = self._plan(self.ex_idx)
        if plan is None or not plan.is_known():
            return ft.Container()

        disagrees = plan.disagrees_with_history()
        notable = plan.has_drop() or disagrees
        if self.zen and not notable:
            return ft.Container()

        text = f"Plan · {plan.label()}"
        if disagrees:
            text += f" · última sesión {plural(plan.history_set_count, 'serie')}"
        tint = C.accent_2 if plan.has_drop() else C.text_secondary
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECKLIST_RTL, size=13, color=tint),
                    ft.Text(
                        text,
                        size=10,
                        color=tint,
                        weight=ft.FontWeight.W_700,
                        expand=True,
                        max_lines=2,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            # `reason` is `session_plan`'s own sentence quoting what it read the
            # rows off, in the words data.py uses. Kept as a tooltip rather than
            # a second line: it answers "why these rows", which is a question
            # asked once and not during a set.
            tooltip=plan.reason or None,
            bgcolor=C.bg_sunken,
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=8, vertical=5),
            margin=ft.margin.only(bottom=6),
        )

    # ── Render: swapping the exercise ─────────────────────────
    def _substitution_strip(self) -> ft.Control:
        """The banner that says you are not doing what the plan asked for.

        This is the requirement in one control: three weeks from now the hole in
        the Leg Press history has to be explainable, and the only moment it can
        be made obvious is while it is being created. So it is loud, it names
        both exercises, it names the scope, and it says outright which key the
        set is going to be written under — because that key is the thing that
        will still be there in three weeks.

        It survives zen mode for the same reason `_backdate_strip` does: zen
        removes reference material, not the answer to "what am I actually
        logging".
        """
        swap = self._substitution_at(self.ex_idx)
        if swap is None:
            return ft.Container()
        scope_text = "solo hoy" if swap.scope is Scope.TODAY else "para el resto de la fase"
        lines: list[ft.Control] = [
            ft.Row(
                [
                    ft.Icon(ft.Icons.SWAP_HORIZ, size=15, color=C.accent_2),
                    ft.Text(
                        f"SUSTITUTO · {swap.performed}",
                        size=11,
                        color=C.accent_2,
                        weight=ft.FontWeight.W_900,
                        expand=True,
                        max_lines=2,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(
                f"En lugar de {swap.prescribed} — {scope_text}. "
                f"Va a tu historial como {swap.key_to_log}.",
                size=10,
                color=C.text_secondary,
                max_lines=3,
            ),
        ]
        # The first session on a substitute has no history to work from, and
        # `starting_point` is the module's answer to that: the original's number
        # as context, explicitly not as a target. Once there is confirmed work
        # on the row it has said everything it had to say.
        if not self.zen and not self._has_confirmed_work():
            point = self._starting_point(self.ex_idx)
            if point is not None and not point.has_history:
                lines += [
                    ft.Text(line, size=10, color=C.text_muted, max_lines=3)
                    for line in point.lines()
                ]
        return ft.Container(
            content=ft.Column(lines, spacing=3, tight=True),
            bgcolor=C.bg_sunken,
            border=ft.border.all(1, C.accent_2),
            border_radius=Radius.md,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            margin=ft.margin.only(bottom=8),
            tooltip="Toca para cambiar o quitar esta sustitución",
            on_click=self._open_swap_dialog,
            ink=True,
        )

    def _swap_button(self) -> ft.Control:
        """The way into the swap dialog: one square in the header, always there.

        In the header rather than beside the rows because it is a decision made
        on arriving at a busy machine — before the first set, not between two of
        them — and because the row area is already six tap targets wide.
        """
        active = self._substitution_at(self.ex_idx) is not None
        return ft.Container(
            content=ft.Icon(
                ft.Icons.SWAP_HORIZ, size=18, color=C.accent_2 if active else C.text_muted
            ),
            width=40,
            height=40,
            bgcolor=C.bg_sunken,
            border=ft.border.all(1, C.accent_2 if active else C.border),
            border_radius=Radius.md,
            alignment=ft.alignment.center,
            tooltip=(
                "Sustituido — toca para cambiarlo o quitarlo"
                if active
                else "¿Máquina ocupada? Cambia este ejercicio"
            ),
            on_click=self._open_swap_dialog,
            ink=True,
        )

    def _alternative_row(self, option: Alternative, chosen_scope) -> ft.Control:
        """One offered substitute. The whole card is the tap target.

        `option.reason` is written by `substitutions.py` and is already an
        English sentence ("Same movement, cable instead of machine."), so it is
        printed rather than re-worded here — the module that decided *why* two
        exercises are interchangeable is the one that should say it.
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                option.key,
                                size=13,
                                weight=ft.FontWeight.W_700,
                                color=C.text,
                                expand=True,
                                max_lines=2,
                            ),
                            chip(
                                option.equipment,
                                color=C.accent if option.is_direct else C.text_secondary,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(option.reason, size=10, color=C.text_muted, max_lines=3),
                ],
                spacing=3,
                tight=True,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.accent if option.is_direct else C.border),
            border_radius=Radius.md,
            padding=10,
            margin=ft.margin.only(bottom=6),
            on_click=lambda _, k=option.key: self._apply_substitution(k, chosen_scope["scope"]),
            ink=True,
        )

    def _open_swap_dialog(self, _=None):
        """Pick the exercise actually being done, and for how long.

        A dialog, unlike everything else on this screen — and the exception is
        the point rather than an oversight. The rule this view lives by is that
        nothing may block *a set*; this is chosen on arriving at an occupied
        machine, with nothing running, and it is a choice between eight named
        options with a reason each, which is not something a row of chips can
        carry.

        The list comes from `substitutions.alternatives`, which derives it from
        movement pattern and equipment rather than from a hand-written table of
        pairs, and which only ever returns names this app already knows — a key
        it does not know would land in `entrenos.ejercicio` with no image, no
        muscles and no meaning for the Telegram coach.
        """
        prescribed = self._prescribed_raw()
        if not prescribed:
            return
        current = self._substitution_at(self.ex_idx)
        options: tuple[Alternative, ...] = ()
        with contextlib.suppress(Exception):
            options = alternatives(prescribed)

        # Held in a dict rather than a `nonlocal`: the row handlers below are
        # built once and read it when tapped, so the scope chosen afterwards is
        # the one that applies.
        chosen = {"scope": current.scope if current else Scope.TODAY}
        scopes = self._swap_scopes()
        scope_row = ft.Row(spacing=6, wrap=True)
        dlg = ft.AlertDialog(modal=False)

        def scope_chip(scope: Scope) -> ft.Control:
            active = chosen["scope"] is scope
            label = "Solo hoy" if scope is Scope.TODAY else "El resto de esta fase"
            return ft.Container(
                content=ft.Text(
                    label,
                    size=11,
                    weight=ft.FontWeight.W_700,
                    color=C.on_accent if active else C.text_secondary,
                ),
                bgcolor=C.accent if active else C.bg_sunken,
                border_radius=Radius.pill,
                padding=ft.padding.symmetric(horizontal=12, vertical=6),
                on_click=lambda _, s=scope: pick_scope(s),
                ink=True,
            )

        def pick_scope(scope: Scope):
            chosen["scope"] = scope
            scope_row.controls = [scope_chip(s) for s in scopes]
            self.page.update()

        def clear(_):
            self.page.close(dlg)
            self._clear_current_substitution()

        scope_row.controls = [scope_chip(s) for s in scopes]

        body: list[ft.Control] = [
            ft.Text(
                f"Prescrito: {exercise_key(prescribed)}",
                size=12,
                color=C.text_secondary,
                weight=ft.FontWeight.W_700,
                max_lines=2,
            ),
            ft.Text(
                "Todo lo que apuntes aquí se guarda bajo el ejercicio que de "
                "verdad haces, así tu historial refleja lo que pasó.",
                size=10,
                color=C.text_muted,
                max_lines=3,
            ),
            ft.Container(height=2),
            scope_row,
            ft.Container(height=4),
        ]
        if current is not None:
            body.append(
                ft.Text(
                    f"Ahora mismo haces {current.performed}.",
                    size=11,
                    color=C.accent_2,
                    weight=ft.FontWeight.W_700,
                )
            )
        if options:
            body += [self._alternative_row(o, chosen) for o in options]
        else:
            # Said plainly rather than shown as an empty box: a combination, an
            # exercise the catalogue does not know, and one with no partner at
            # all are three different reasons for the same empty list, and none
            # of them is something the user can fix from here.
            body.append(
                ft.Text(
                    "No hay ejercicio equivalente para este. Nada del catálogo "
                    "entrena el mismo patrón con otro material.",
                    size=11,
                    color=C.text_muted,
                    max_lines=4,
                )
            )

        dlg.title = ft.Text(
            "Sustituir este ejercicio", size=16, weight=ft.FontWeight.W_900, color=C.text
        )
        dlg.content = ft.Container(
            content=ft.Column(body, spacing=6, tight=True, scroll=ft.ScrollMode.AUTO),
            width=dialog_width(self.page),
            height=dialog_height(self.page, 420),
        )
        dlg.actions = [
            ghost_button("Cancelar", on_click=lambda _: self.page.close(dlg)),
            *([ghost_button("Hacer el prescrito", on_click=clear)] if current else []),
        ]
        dlg.actions_alignment = ft.MainAxisAlignment.END
        dlg.bgcolor = C.bg_surface
        self.page.open(dlg)

    # ── Render: the note on this exercise ─────────────────────
    def _note_block(self) -> ft.Control:
        """The exercise note: one tap to open, no dialog, no rebuild.

        "Writing on a phone standing up between two sets is uncomfortable" is
        the whole design brief, and it rules out three things this could have
        been: a dialog (blocks while the rest timer runs), a separate screen
        (loses the rows), and an always-open field (a keyboard target sitting
        under the numbers, one mis-tap from the reps box).

        What is left is a chip that shows the note when there is one and the
        word "Nota" when there is not, and a box that unfolds under it *in
        place* — `_toggle_note` flips `visible` on a mounted control, so nothing
        typed anywhere else on the screen is rebuilt, and the caret in a weight
        field survives opening it.

        The note is stored with the exercise when it is saved; if the exercise
        is already saved it goes straight into its row. Either way it ends up in
        `entrenos.nota`, which is where a note about one exercise belongs.
        """
        note = self._note_for(self.ex_idx)
        chip_text = ft.Text(
            self._note_chip_text(),
            size=10,
            color=C.accent if note else C.text_muted,
            weight=ft.FontWeight.W_700,
            expand=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._note_chip = chip_text

        field = ft.TextField(
            value=note,
            hint_text="¿Qué tal ha ido? ¿Qué has cambiado?",
            multiline=True,
            min_lines=2,
            max_lines=4,
            max_length=NOTE_MAX_LEN,
            text_size=12,
            color=C.text,
            bgcolor=C.bg_page,
            border_color=C.border_strong,
            focused_border_color=C.accent,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=8),
            on_change=lambda e: self._note_typed(e.control.value),
            # The cheapest honest checkpoint, same as the number fields: the box
            # lost focus, so the sentence in it is finished.
            on_blur=lambda _: self._set_note(self.ex_idx, self._note_for(self.ex_idx)),
        )
        body = ft.Container(content=field, visible=self._show_note, margin=ft.margin.only(top=4))
        self._note_body = body

        toggle = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.STICKY_NOTE_2_OUTLINED,
                        size=14,
                        color=C.accent if note else C.text_muted,
                    ),
                    chip_text,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_sunken,
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            tooltip="Una nota de este ejercicio — se guarda con las series",
            on_click=self._toggle_note,
            ink=True,
        )
        return ft.Column([toggle, body], spacing=0, tight=True)

    # ── Render: the note on the whole session ─────────────────
    def _duration_row(self, day: date, seconds: int | None) -> ft.Control:
        """One day's session time, as a line you can tap to change.

        `format_duration` decides the text, never this method: "1h 12m",
        "45m", "<1m", and empty for nothing at all. Empty is why the caller
        cannot just print it — a row reading "0m" would claim a session that
        lasted no time, when what is true is that nobody timed it.
        """
        text = format_duration(seconds)
        timed = bool(text)
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.TIMER_OUTLINED if timed else ft.Icons.TIMER_OFF_OUTLINED,
                        size=15,
                        color=C.accent if timed else C.text_muted,
                    ),
                    ft.Text(
                        _date_label(day),
                        size=12,
                        color=C.text_secondary,
                        weight=ft.FontWeight.W_700,
                        expand=True,
                    ),
                    ft.Text(
                        text or "Sin cronometrar",
                        size=13,
                        color=C.text if timed else C.text_muted,
                        weight=ft.FontWeight.W_900,
                    ),
                    ft.Text(
                        "Cambiar" if timed else "Añadir",
                        size=11,
                        color=C.accent,
                        weight=ft.FontWeight.W_700,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_sunken,
            border_radius=Radius.sm,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            margin=ft.margin.only(top=6),
            tooltip=f"Di cuánto duró la sesión de {_date_label(day)}",
            on_click=lambda _, d=day: self._open_duration_dialog(d),
            ink=True,
        )

    def _duration_block(self) -> ft.Control:
        """ "How long did it last?", on the screen the session ends on.

        One row per day this session wrote to — which is one row for an
        ordinary workout and two for the sitting Alex described, where the
        chronometer belongs to neither of them. Nothing at all when nothing was
        logged: there is no session to have lasted anything.

        A **measured** time is already in the table by the time this renders
        (`_store_measured_duration`), so the ordinary live workout finds its own
        duration filled in and the caption says where it came from. A back-dated
        one finds "Sin cronometrar" and a caption saying why the clock was not
        trusted — which is the asking Alex wanted, put somewhere he is standing
        still rather than in a modal thrown at him mid-Finish.
        """
        days = self._logged_days()
        if not days:
            return ft.Container()
        stored = self._durations()
        if self._duration_is_measured():
            caption = "Medido por el cronómetro. Toca para corregirlo."
        elif self.session_started_at is not None:
            caption = (
                "El cronómetro corrió mientras tecleabas esto, así que no se guardó "
                "como tu tiempo de sesión. Toca para poner el real."
            )
        else:
            caption = "Toca un día para decir cuánto duró."
        return card(
            ft.Row(
                [
                    ft.Icon(ft.Icons.TIMER_OUTLINED, size=16, color=C.accent),
                    ft.Text(
                        "Tiempo de sesión",
                        size=12,
                        weight=ft.FontWeight.W_900,
                        color=C.text,
                        expand=True,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(caption, size=10, color=C.text_muted),
            *[self._duration_row(d, stored.get(d.isoformat())) for d in days],
            padding=12,
            margin=ft.margin.only(bottom=6),
        )

    def _session_note_block(self) -> ft.Control:
        """The session note, on the screen the session ends on.

        Deliberately not on the exercise screen. It is about the day — slept
        badly, gym packed, back tweaked — and it is written once, at the end,
        with the phone in hand and nothing waiting. `notas_sesion` needs no
        workout row, so this works on a session that logged nothing at all,
        which is exactly the session most worth explaining.
        """
        field = ft.TextField(
            value=self._session_note(),
            hint_text="¿Cómo ha ido la sesión?",
            multiline=True,
            min_lines=2,
            max_lines=5,
            max_length=NOTE_MAX_LEN,
            text_size=12,
            color=C.text,
            bgcolor=C.bg_page,
            border_color=C.border_strong,
            focused_border_color=C.accent,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=8),
            on_blur=lambda e: self._save_session_note(e.control.value),
        )
        return card(
            ft.Row(
                [
                    ft.Icon(ft.Icons.EDIT_NOTE, size=16, color=C.accent),
                    ft.Text(
                        "Nota de la sesión",
                        size=12,
                        weight=ft.FontWeight.W_900,
                        color=C.text,
                        expand=True,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(
                f"Sobre el día entero — se guarda en {_date_label(self._session_note_day())}.",
                size=10,
                color=C.text_muted,
            ),
            ft.Container(height=6),
            field,
            padding=12,
            margin=ft.margin.only(bottom=6),
        )

    def _set_row(self, i: int, s: dict, last_ref: dict | None) -> ft.Control:
        placeholder_w = _num_text(last_ref.get("weight")) if last_ref else "kg"
        placeholder_r = _num_text(last_ref.get("reps")) if last_ref else "reps"
        # A suggested row is last session's numbers, not this session's work.
        # It reads muted and hollow on purpose: the confirmed rows around it
        # are the ones in full ink, so which is which is a glance, not a
        # reading exercise.
        suggested = self._is_suggested(s)
        field_color = C.text_muted if suggested else C.text
        field_border = C.border if suggested else C.border_strong

        def fields() -> list[ft.TextField]:
            return [w_field, r_field, rir_field]

        def refresh_plate_hint(value):
            """Re-run the plate maths for this row, in place.

            Same rule as the restyle below and for the same reason: this fires
            on every character of a weight, and a `refresh_current()` here
            would rebuild the field being typed into. `visible` is flipped
            rather than the text set to `""` so an empty hint costs no height
            at all — with five rows on a 420 px screen, five blank lines is a
            whole set row's worth of nothing.
            """
            text = self._plate_hint(value)
            plate_hint.value = text
            plate_hint.visible = bool(text)
            with contextlib.suppress(Exception):
                plate_hint.update()

        def touched(idx: int, field: str, value: str):
            """A keystroke: store it and, the first time, un-suggest the row.

            The restyle is done in place instead of through
            `refresh_current()`: rebuilding the tree under a keyboard steals
            the focus and the caret, mid-number.
            """
            was_suggested = self._is_suggested(s)
            self._update_set(idx, field, value)
            if field == "weight":
                refresh_plate_hint(value)
            if not was_suggested:
                return
            for f in fields():
                f.color = C.text
                f.border_color = C.border_strong
            num_text.color = confirmed_number_color
            with contextlib.suppress(Exception):
                for f in fields():
                    f.update()
                num_badge.update()

        def blurred(_):
            # The cheapest honest moment to checkpoint: the field lost focus,
            # so the number in it is finished. Saving on every keystroke would
            # hammer the database for nothing.
            self._persist_draft()

        w_field = ft.TextField(
            value=s.get("weight", ""),
            hint_text=placeholder_w,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            bgcolor=C.bg_page,
            border_color=field_border,
            focused_border_color=C.accent,
            color=field_color,
            text_size=14,
            height=40,
            content_padding=ft.padding.symmetric(horizontal=6, vertical=8),
            expand=True,
            on_change=lambda e, idx=i: touched(idx, "weight", e.control.value),
            on_blur=blurred,
        )
        r_field = ft.TextField(
            value=s.get("reps", ""),
            hint_text=placeholder_r,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            bgcolor=C.bg_page,
            border_color=field_border,
            focused_border_color=C.accent,
            color=field_color,
            text_size=14,
            height=40,
            content_padding=ft.padding.symmetric(horizontal=6, vertical=8),
            expand=True,
            on_change=lambda e, idx=i: touched(idx, "reps", e.control.value),
            on_blur=blurred,
        )
        # RIR (reps in reserve): optional. Left blank it simply isn't stored.
        rir_field = ft.TextField(
            value=s.get("rir", ""),
            hint_text=_num_text(last_ref.get("rir")) if last_ref and last_ref.get("rir") else "–",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            bgcolor=C.bg_page,
            border_color=field_border,
            focused_border_color=C.accent,
            color=field_color,
            text_size=14,
            height=40,
            width=46,
            content_padding=ft.padding.symmetric(horizontal=2, vertical=8),
            on_change=lambda e, idx=i: touched(idx, "rir", e.control.value),
            on_blur=blurred,
        )
        # One tap cycles Normal → Warm-up → Drop → Failure. A badge, not a
        # form: four options do not deserve a dropdown on a 420 px screen.
        set_type = set_type_of(s)
        type_color = _set_type_color(set_type)
        type_chip = ft.Container(
            content=ft.Text(
                short_label_for(set_type),
                size=12,
                weight=ft.FontWeight.W_900,
                color=type_color,
                text_align=ft.TextAlign.CENTER,
            ),
            width=30,
            height=40,
            bgcolor=C.bg_sunken,
            border=ft.border.all(1, C.border if set_type is SetType.NORMAL else type_color),
            border_radius=Radius.sm,
            alignment=ft.alignment.center,
            tooltip=f"{label_for(set_type)} — toca para cambiar",
            on_click=lambda _, idx=i: self._cycle_set_type(idx),
            ink=True,
        )
        # The set number doubles as the confirm button — it costs no width on a
        # 420 px row and it is already where the eye goes when a set ends.
        confirmed_number_color = phase_color(self.phase_id) if self._phase() else C.accent
        num_text = ft.Text(
            str(i + 1),
            size=13,
            weight=ft.FontWeight.W_900,
            color=C.text_muted if suggested else confirmed_number_color,
            text_align=ft.TextAlign.CENTER,
        )
        num_badge = ft.Container(
            content=num_text,
            width=20,
            height=40,
            alignment=ft.alignment.center,
            tooltip=("Toca para confirmar esta serie" if suggested else f"Serie {i + 1}"),
            on_click=(lambda _, idx=i: self._confirm_set(idx)) if suggested else None,
            ink=suggested,
        )
        entry_row = ft.Row(
            [
                num_badge,
                type_chip,
                w_field,
                r_field,
                rir_field,
                ft.Container(
                    content=ft.Icon(ft.Icons.CLOSE, size=14, color=C.text_muted),
                    width=30,
                    height=40,
                    border=ft.border.all(1, C.border),
                    border_radius=6,
                    alignment=ft.alignment.center,
                    on_click=lambda _, idx=i: self._remove_set(idx),
                    ink=True,
                ),
            ],
            spacing=5,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── the line under the row ──
        #
        # Two answers, both about *this* row, both non-interactive text: what
        # goes on the bar for the weight in the field (left, under KG) and what
        # this set is aiming for (right, towards REPS). Nothing here is
        # tappable, so nothing here can block, swallow a tap meant for a field,
        # or open while the rest timer is running.
        hint_text = self._plate_hint(s.get("weight", ""))
        plate_hint = ft.Text(
            hint_text,
            size=9,
            color=C.text_secondary,
            weight=ft.FontWeight.W_700,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            visible=bool(hint_text),
            expand=True,
        )
        target_text = self._row_target(i, s)
        target_hint = ft.Text(
            target_text,
            size=9,
            color=C.text_muted,
            weight=ft.FontWeight.W_700,
            no_wrap=True,
            text_align=ft.TextAlign.RIGHT,
            visible=bool(target_text),
        )
        # The container itself stays mounted even when both halves are hidden —
        # a Row with no visible child is worth ~2 px, and it is what lets
        # `refresh_plate_hint` make the hint appear mid-keystroke without a
        # rebuild. A row on a cable machine with no scheme in its name looks
        # exactly like it did before this feature existed.
        sub_line = ft.Container(
            content=ft.Row(
                [plate_hint, target_hint],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            # 20 (set number) + 30 (type) + two 5 px gaps: lines the hint up
            # under the KG field it is describing.
            padding=ft.padding.only(left=60, right=2, bottom=2),
        )
        return ft.Column([entry_row, sub_line], spacing=1, tight=True)

    def _render_exercise(self) -> ft.Control:
        phase = self._phase()
        day = self._current_day()
        assert phase and day
        total = len(day.exercises)
        raw = self._current_exercise_raw()
        key = exercise_key(raw)
        display = raw
        # One read, used by every branch below. Zen mode is a *layout*: this
        # method stays single, so the two versions of the screen cannot drift
        # apart the way two copies of a 200-line render always do.
        zen = self.zen
        # Through the cache, not straight to the store: the exercise just
        # logged would otherwise come back as its own "last session".
        last_sets = self._last_sets(self.ex_idx)
        last_ref_for_placeholder = last_sets[0] if last_sets else None

        if zen:
            # Last session's numbers are already sitting in the fields as
            # suggestions — the chips repeat them, and repeating them is exactly
            # the kind of thing that is useful before a workout and clutter
            # during one. `last_ref_for_placeholder` above is untouched, so the
            # hints inside the empty fields still work.
            last_row: ft.Control = ft.Container()
        elif last_sets:
            # LAST SESSION'S NOTE. "Seat on hole 4", "left wrist hurts
            # supinated" — a note is worth writing only because it comes back
            # the next time he is standing at that machine, and until this line
            # it never did: it went into `entrenos.nota` and could be read on
            # History and nowhere else.
            #
            # Off `_history()`, which is already in the cache and already
            # keyed through `_performed_key` (so a swapped slot shows the
            # substitute's note, not the prescribed exercise's).
            # `Storage.get_exercise_note()` answers the same question with an
            # extra round-trip, and this screen runs between sets.
            note_row: list[ft.Control] = []
            historial = self._exercise_history(self.ex_idx)
            ultima_nota = clean_note(getattr(historial[-1], "note", None)) if historial else None
            if ultima_nota:
                note_row = [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.STICKY_NOTE_2_OUTLINED, size=12, color=C.text_muted),
                            ft.Text(
                                ultima_nota,
                                size=11,
                                color=C.text_secondary,
                                italic=True,
                                expand=True,
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    )
                ]

            last_row = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "ÚLTIMA SESIÓN",
                            size=10,
                            color=C.text_muted,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Row(
                            [self._set_chip(s) for s in last_sets],
                            wrap=True,
                            spacing=6,
                            run_spacing=4,
                        ),
                        *note_row,
                    ],
                    spacing=6,
                ),
                bgcolor=C.bg_page,
                border_radius=10,
                padding=10,
            )
        else:
            last_row = ft.Text(
                "Primera vez — sin historial", size=11, color=C.text_muted, italic=True
            )

        set_rows = [self._set_row(i, s, last_ref_for_placeholder) for i, s in enumerate(self.sets)]

        def column_head(text: str, width: int | None = None) -> ft.Container:
            return ft.Container(
                ft.Text(
                    text,
                    size=9,
                    color=C.text_muted,
                    weight=ft.FontWeight.W_700,
                    text_align=ft.TextAlign.CENTER,
                ),
                width=width,
                expand=width is None,
            )

        # Widths mirror `_set_row`; the phone is 420 px wide and the columns
        # have to line up with the fields below them.
        #
        # "Nº", not "SERIE": that column is 20 px because the set-number badge
        # under it is 20 px, and widening the head to fit a five-letter word
        # would slide KG/REPS/RIR off the fields they label. "SERIE" wrapped to
        # "SERI"/"E" on the phone; the column holds 1, 2, 3 — a number.
        header_row = ft.Row(
            [
                column_head("Nº", 20),
                column_head("TIPO", 30),
                column_head("KG"),
                column_head("REPS"),
                column_head("RIR", 46),
                # The `?` lives here on purpose: TYPE shows a bare letter
                # (N/W/D/F) and RIR a bare number, and neither says what it
                # means. This slot was already reserved as an empty 30 px box.
                help_icon(self.page, size=30),
            ],
            spacing=5,
        )
        add_btn = ft.Container(
            content=ft.Text("+ Serie", size=11, color=C.text_muted, weight=ft.FontWeight.W_700),
            border=ft.border.all(1, C.border),
            border_radius=8,
            padding=8,
            alignment=ft.alignment.center,
            expand=True,
            on_click=self._add_set,
            ink=True,
        )
        pending = self._pending_count()
        row_actions: list[ft.Control] = [add_btn]
        if pending:
            # "Igual que la última vez" in one tap — the whole point of prefilling.
            # Only rendered while something is unconfirmed, so the button
            # disappears the moment it would do nothing.
            row_actions.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.DONE_ALL, size=14, color=C.accent),
                            ft.Text(
                                f"Confirmar todas ({pending})",
                                size=11,
                                color=C.accent,
                                weight=ft.FontWeight.W_700,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    border=ft.border.all(1, C.accent),
                    border_radius=8,
                    padding=8,
                    alignment=ft.alignment.center,
                    expand=True,
                    on_click=self._confirm_all,
                    ink=True,
                )
            )
        actions_row = ft.Row(row_actions, spacing=6)

        # Said once, above the rows, instead of guessed from a grey field: the
        # muted rows are a proposal until they are claimed, and nothing muted
        # is ever written to the history.
        #
        # Two wordings, because after the ramp is added the muted rows are no
        # longer all from last session — four of them are warm-ups the app just
        # computed, and calling those "your last session" is a small lie on the
        # one line whose whole job is explaining what the muted rows are.
        ramped = any(set_type_of(row) is SetType.WARMUP for row in self.sets)
        prefill_note: ft.Control = (
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.HISTORY, size=13, color=C.text_secondary),
                        ft.Text(
                            "Toca el número de la serie al terminarla"
                            if ramped
                            else "De tu última sesión — toca el número de la serie para confirmar",
                            size=10,
                            color=C.text_secondary,
                            weight=ft.FontWeight.W_700,
                            expand=True,
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=C.bg_sunken,
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                margin=ft.margin.only(bottom=6),
            )
            if pending and not zen
            else ft.Container()
        )

        already_logged = self.ex_idx in self._logged_ex
        logged_note: ft.Control = (
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=13, color=C.success),
                        ft.Text(
                            "Registrado en esta sesión",
                            size=10,
                            color=C.success,
                            weight=ft.FontWeight.W_700,
                        ),
                    ],
                    spacing=6,
                    tight=True,
                ),
                margin=ft.margin.only(bottom=6),
            )
            if already_logged
            else ft.Container()
        )

        # No form image in zen mode, and — because `_animate_loop` is only
        # started below — no frame-swap task either. It is 180 px of the tallest
        # thing on the screen plus a repaint every 700 ms, spent on a photo he
        # stopped needing after set one. Stepping out of zen brings it back.
        # `image_frames_props`, not `image_frames`: the assets-relative URL the
        # latter returns resolves to nothing inside the APK, so on the phone
        # this was 180 px of empty grey box on every single exercise — the
        # "images don't download" report. They downloaded; nothing could show
        # them. See the delivery note in exercise_images.py.
        #
        # No `cache_width` here, unlike the 44 px thumbnails in browse.py and
        # plan.py: this is one image at nearly full screen width, so decoding
        # it small would only make it blurry.
        # SHOWN IN ZEN TOO. It used to be hidden there, on the reasoning that a
        # form photo is something you need before a set and not during one. The
        # reasoning was fine and the outcome was wrong: **zen is on by default**,
        # so in practice the photos were never visible at all — which is exactly
        # how Alex reported it ("en modo ZEN no muestra las imagenes").
        #
        # Shorter in zen, because there the screen is read standing over a phone
        # on the floor and the countdown has to keep the height it needs.
        frames = image_frames_props(key)
        alto = 120 if zen else 180
        if frames:
            # TWO CONTROLS, NOT ONE WHOSE SOURCE IS SWAPPED. On Android the
            # frames travel as base64, so re-pointing a single Image every
            # 700 ms would push ~70 KB of string down the socket per swap —
            # about 100 KB/s, continuously, for the whole workout. Mounted once
            # and toggled by `visible`, the bytes cross exactly once.
            capas = [
                ft.Image(
                    **props,
                    fit=ft.ImageFit.COVER,
                    width=float("inf"),
                    height=alto,
                    border_radius=10,
                    gapless_playback=True,
                    visible=(i == 0),
                    error_content=ft.Icon(ft.Icons.FITNESS_CENTER, color=C.text_muted, size=28),
                )
                for i, props in enumerate(frames)
            ]
            self._anim_layers = capas
            self._anim_image = capas[0]
            self._anim_frames = frames
            # A slug with only one usable frame gets both entries pointing at
            # it; animating that is a repaint that changes nothing.
            if frames[0] != frames[1]:
                self.page.run_task(self._animate_loop, self._anim_tick_id)
            image_block: ft.Control = ft.Container(
                content=ft.Stack(capas),
                bgcolor=C.bg_sunken,
                height=alto,
                border_radius=10,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
        else:
            self._anim_layers = []
            self._anim_image = None
            self._anim_frames = None
            image_block = ft.Container()

        # The three things worth reading with the phone on the floor: which
        # exercise, which set and how much, and how much rest is left. In zen
        # mode the first two get the size, and `build_large` gives the third.
        if zen:
            rest_block: ft.Control = self.timer.build_large(
                caption=f"AUTO {format_rest(self._rest_seconds())} TRAS CADA SERIE"
            )
            next_line: ft.Control = ft.Container(
                content=ft.Text(
                    self._next_set_hint(),
                    size=15,
                    weight=ft.FontWeight.W_900,
                    color=phase_color(phase.id),
                ),
                margin=ft.margin.only(top=2),
            )
        else:
            rest_block = ft.Column(
                [
                    # Says out loud what now happens by itself, so the countdown
                    # that appears after a set does not look like something went
                    # wrong.
                    ft.Text(
                        f"Descanso · auto {format_rest(self._rest_seconds())} tras cada serie",
                        size=10,
                        color=C.text_muted,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Container(height=4),
                    self.timer.build(),
                ],
                spacing=0,
                tight=True,
            )
            next_line = ft.Container()

        exercise_card = card(
            # First thing in the card, before the exercise name, and it survives
            # zen mode. Empty — literally zero height — until some day has been
            # chosen somewhere in this session, which is the 95 % case; from
            # then on it is on **every** exercise screen, today's included.
            self._backdate_strip(),
            # Directly above the name, because it changes what the name means:
            # the title below is the exercise being *done*, and without this
            # there would be nothing on screen saying it is not the one the plan
            # asked for. Zero height whenever nothing is swapped.
            self._substitution_strip(),
            ft.Row(
                [
                    ft.Text(
                        f"EJERCICIO {self.ex_idx + 1}",
                        size=10,
                        color=phase_color(phase.id),
                        weight=ft.FontWeight.W_900,
                        expand=True,
                    ),
                    self._log_date_chip(),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(display, size=24 if zen else 19, weight=ft.FontWeight.W_900, color=C.text),
            next_line,
            # The two planning surfaces sit here, directly under the name and
            # above everything else, because both answer "what am I doing on
            # this exercise today" and both delete themselves as soon as the
            # first working set is confirmed. Below the rows they would be read
            # after the decision they exist to inform.
            self._progression_banner(),
            self._history_block(),
            ft.Container(height=8),
            image_block,
            ft.Container(height=8) if frames else ft.Container(),
            last_row,
            ft.Container(height=10),
            rest_block,
            ft.Container(height=14),
            logged_note,
            # Last thing before the rows, because it *writes* rows: the button
            # is next to the place its result appears.
            self._warmup_strip(),
            # What the plan asked for, immediately above the rows it opened.
            self._plan_strip(),
            prefill_note,
            header_row,
            *set_rows,
            ft.Container(height=6),
            actions_row,
            ft.Container(height=8),
            # Last in the card, below the rows: it is written after a set rather
            # than before one, and putting a keyboard target above the numbers
            # would be one mis-tap from the reps box.
            self._note_block(),
            border_color=phase_color(phase.id),
        )

        def on_horizontal_drag_end(e):
            vx = getattr(e, "primary_velocity", 0) or 0
            if vx < -250:
                self._go_next_exercise()
            elif vx > 250:
                self._go_prev_exercise()

        swipeable_card = ft.GestureDetector(
            content=exercise_card,
            on_horizontal_drag_end=on_horizontal_drag_end,
            drag_interval=100,
        )

        # ── Actions ──
        # Three jobs, three controls, and the frequent one gets the width.
        #
        #   [ ‹ ] [        Save        ] [ › ]
        #            [ Finish session ]
        #
        # What was here before was `[ Skip ] [ Save → Next / Save → Finish ]`:
        # two buttons for four different actions, and no way to end the session
        # before the last exercise. Save now only saves; the arrows only move;
        # Finish only finishes and is on screen the whole time.
        #
        # "Saltar" is gone rather than kept as a third button, because with Save
        # no longer advancing it *is* Next — `_skip` was `_advance()`, i.e.
        # "move on without writing anything", which is exactly what the right
        # arrow does. Two buttons for one action is how you press the wrong one.
        # It also keeps the swipe gesture (`_go_next_exercise`) from being the
        # only affordance for stepping backwards.
        if already_logged:
            # `_save_exercise` refuses a second write — `save_workout` INSERTs —
            # so this reads as state, not as an offer. It stays tappable so the
            # tap gets an explanation instead of being swallowed.
            save_slot: ft.Control = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=C.success),
                        ft.Text("Guardado", size=14, weight=ft.FontWeight.W_800, color=C.success),
                    ],
                    spacing=6,
                    tight=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                border=ft.border.all(1, C.success),
                border_radius=Radius.lg,
                height=48,
                alignment=ft.alignment.center,
                expand=True,
                on_click=self._save,
                ink=True,
            )
        else:
            save_slot = primary_button(
                "Guardar",
                icon=ft.Icons.CHECK_ROUNDED,
                on_click=self._save,
                expand=True,
                height=48,
            )

        unsaved = self._unsaved_exercises()
        day_complete = total > 0 and len(self._logged_ex) >= total
        if unsaved:
            # The count is the point Alex was making — "con ello ya nos
            # daríamos cuenta". What has not been written is visible before he
            # commits to leaving, not discovered afterwards in History.
            finish_tint = C.warning
            finish_label = f"Terminar sesión · {len(unsaved)} sin guardar"
        elif day_complete:
            # Save is spent and both arrows are dead: Finish is the only live
            # control on the screen, so it stops being the quiet one.
            finish_tint = C.accent
            finish_label = "Terminar sesión"
        else:
            finish_tint = C.text_secondary
            finish_label = "Terminar sesión"

        action_row = ft.Row(
            [
                self._step_button(
                    ft.Icons.CHEVRON_LEFT,
                    "Ejercicio anterior",
                    lambda _: self._go_prev_exercise(),
                    enabled=self.ex_idx > 0,
                ),
                save_slot,
                self._step_button(
                    ft.Icons.CHEVRON_RIGHT,
                    "Ejercicio siguiente",
                    lambda _: self._go_next_exercise(),
                    enabled=self.ex_idx + 1 < total,
                ),
            ],
            spacing=8,
        )
        # Su propia fila, centrada y más estrecha que Guardar: las dos son
        # acciones sobre la *sesión* y no sobre la serie, así que viven lejos
        # de Guardar. Terminar además tiene que ser incómodo de tocar sin
        # querer — la confirmación de `_ask_finish` es el guardia de verdad,
        # esto es el primero.
        finish_row = ft.Row(
            [
                self._session_button(
                    ft.Icons.ADD_ROUNDED,
                    "Ejercicio",
                    C.text_secondary,
                    "Añadir un ejercicio a la sesión de hoy",
                    self._ask_add_exercise,
                ),
                self._session_button(
                    ft.Icons.FLAG_ROUNDED,
                    finish_label,
                    finish_tint,
                    "Cerrar la sesión — lo no guardado se escribe antes",
                    self._ask_finish,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
        )

        session_label = ft.Text(
            self._format_elapsed(self._session_elapsed_s()),
            size=12,
            color=C.accent,
            weight=ft.FontWeight.W_800,
        )
        self._session_label = session_label
        session_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.TIMER_OUTLINED, color=C.accent, size=14),
                    session_label,
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=C.bg_page,
            border=ft.border.all(1, C.border_strong),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
        )

        header = ft.Row(
            [
                # Back stays first and stays labelled even in zen mode: it is
                # the door out of the exercise screen, and therefore the door
                # back to the navigation bar. Hiding it would turn a layout into
                # a cage, which is the one thing zen mode must never be.
                self._back_btn("Atrás", lambda _: None, raw_handler=lambda _: self._back_to_days()),
                session_chip,
                ft.Text(
                    f"{self.ex_idx + 1}/{total}",
                    size=11,
                    color=C.text_muted,
                    weight=ft.FontWeight.W_700,
                ),
                self._swap_button(),
                self._zen_toggle(),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        progress = ft.ProgressBar(
            value=(self.ex_idx / total) if total else 0,
            color=phase_color(phase.id),
            bgcolor=C.border,
            bar_height=4,
        )

        return ft.Column(
            [
                header,
                ft.Container(height=6),
                progress,
                ft.Container(height=14),
                swipeable_card,
                ft.Container(height=12),
                action_row,
                ft.Container(height=8),
                finish_row,
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            tight=True,
            spacing=0,
        )

    def _back_to_days(self):
        """The header's Back chip: same promise as the hardware back button.

        It used to be `_reset_to_days` and it destroyed `ex_idx`, `completed`
        and the running clock. Looking at the day list is not quitting.

        Y ahora *delega*, en vez de repetir esas tres líneas. La copia decía
        «same promise» y había dejado de cumplirla: `handle_back` aprendió a
        salir de una sesión de solo abdomen y esto no, así que el chip llevaba
        a la lista de días de una fase que no se estaba entrenando. Dos sitios
        que deciden lo mismo terminan decidiendo cosas distintas.
        """
        self.handle_back()

    def _back_btn(self, label: str, on_click, raw_handler=None) -> ft.Control:
        handler = raw_handler or on_click
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ARROW_BACK, color=C.accent, size=16),
                    ft.Text(label, color=C.accent, size=12, weight=ft.FontWeight.W_700),
                ],
                spacing=4,
                tight=True,
            ),
            on_click=handler,
            padding=ft.padding.symmetric(vertical=6),
            ink=True,
        )

    async def _animate_loop(self, tick_id: int):
        """Cross-fade between the two frames every ~700 ms.

        Toggles `visible` on two mounted controls rather than re-pointing one.
        Both frames are already on the client, so a swap is two booleans; the
        old version re-sent the frame itself, which on Android is ~70 KB of
        base64 per swap — roughly 100 KB/s down the socket, all workout long.
        """
        showing_second = False
        while tick_id == self._anim_tick_id:
            await asyncio.sleep(0.7)
            capas = self._anim_layers
            if tick_id != self._anim_tick_id or len(capas) < 2:
                return
            showing_second = not showing_second
            capas[0].visible = not showing_second
            capas[1].visible = showing_second
            self._anim_image = capas[1] if showing_second else capas[0]
            try:
                self.page.update()
            except Exception:
                return

    # ── Dispatcher ────────────────────────────────────────────
    def build(self) -> ft.Control:
        # Invalidate any running frame-swap task before rebuild
        self._anim_tick_id += 1
        # Un entreno libre sin nada elegido abre el buscador, y lo hace aquí
        # porque `empezar_libre` corre desde Inicio, antes de que esta pantalla
        # exista: un diálogo abierto ahí se pinta sobre la pantalla anterior.
        if self._abrir_buscador_al_pintar:
            self._abrir_buscador_al_pintar = False
            with contextlib.suppress(Exception):
                self.page.run_task(self._abrir_buscador_pronto)
        # A routine swap from outside (`main.set_routine`) leaves `phase_id`
        # and `day_idx` pointing into a routine that no longer exists; catch it
        # before anything indexes with them.
        self._ensure_scope()
        # And a date chosen on a day that has since ended has nothing left to
        # describe. Same exception to "build() is a pure render" as the line
        # above, for the same reason: nothing else runs while the clock passes
        # midnight, so the render is the first chance anyone gets.
        self._ensure_log_date_fresh()
        # `show_*` pick the screen without touching the state underneath, which
        # is what makes stepping out of a workout and back in free.
        if self.phase_id == 0 or self.show_phase_list:
            return self._render_phase_select()
        if self.day_idx < 0 or self.show_day_list:
            return self._render_day_select()
        if self.finished:
            return self._render_finished()
        return self._render_exercise()
