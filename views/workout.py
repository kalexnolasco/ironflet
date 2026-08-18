"""Workout: guided flow phase → day → exercise by exercise."""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import date

import flet as ft

from analytics import Record, detect_new_records
from components.timer import RestTimer
from data import active_routine
from exercise_images import image_frames
from exercises import exercise_key, phase_color
from set_types import (
    TYPE_KEY,
    SetType,
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
from storage import Storage, WorkoutEntry
from theme import (
    C,
    Radius,
    card,
    chip,
    ghost_button,
    primary_button,
)
from workout_draft import DraftStore, WorkoutDraft, is_blank_row

#: `get_exercise_history` keeps the last 20 sessions by default. A record has to
#: beat *everything*, so ask for the whole history of the exercise — otherwise a
#: best from 21 sessions ago is forgotten and the app invents a PR.
_PR_HISTORY_LIMIT = 100_000

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

        # Image animation state (frame-swap loop)
        self._anim_tick_id: int = 0
        self._anim_image: ft.Image | None = None
        self._anim_frames: tuple[str, str] | None = None

        # Session chronometer
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
        if self.finished:
            self._reset()
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
    # So the honest answer is "not from here". Closing it needs either a Flet
    # extension or ~3 lines in the build template's `main.dart` calling
    # `WakelockPlus.enable()` — `tool.flet.template.url` accepts a plain local
    # directory, so that fork costs a copy, not a hosted repo. Until then the
    # mitigation is the one already built: the rest timer beeps and vibrates at
    # zero, so a dark screen does not mean a missed set. That is why the mute
    # button survives the decluttering in `build_large()`.

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

    def _last_sets(self, ex_idx: int) -> list[dict] | None:
        """Previous session of exercise `ex_idx`, read once per workout."""
        if ex_idx in self._last_sets_cache:
            return self._last_sets_cache[ex_idx]
        day = self._current_day()
        if not day or not (0 <= ex_idx < len(day.exercises)):
            return None
        key = exercise_key(day.exercises[ex_idx])
        last = None
        # A database hiccup must degrade to "first time, no history", not to a
        # blank screen in the middle of a set.
        with contextlib.suppress(Exception):
            last = self.store.get_last_sets(key)
        self._last_sets_cache[ex_idx] = last
        return last

    def _seed_sets(self, ex_idx: int) -> list[dict[str, str]]:
        """Opening rows for an exercise: last session's, marked as suggestions.

        Alex's actual complaint was retyping numbers the screen was already
        showing him — they sat in `hint_text`, a grey placeholder you can read
        but not keep. Hevy and Strong both answer this the same way and so does
        this: the previous session is written into the fields, rendered muted,
        and does **not** count as logged until he vouches for it, by editing a
        field or tapping the set number.

        That last half is the whole point. A prefilled field nobody reviews
        writes a weight he never lifted into `entrenos`, and `analytics`
        happily turns it into a personal record — a corrupted history and a
        fake PR are a worse bug than the typing this saves. So: zero taps to
        *see* last time's numbers, one tap to claim them, and never a number
        logged that he did not touch.
        """
        last = self._last_sets(ex_idx)
        if not last:
            return [self._blank_set()]
        rows: list[dict[str, str]] = []
        for one in last:
            row = self._blank_set()
            row["weight"] = _num_text(one.get("weight"))
            row["reps"] = _num_text(one.get("reps"))
            row["rir"] = _num_text(one.get("rir"))
            # The type belongs to the plan, not to the performance: a session
            # that opened with two warm-ups opens with two warm-ups again.
            row[TYPE_KEY] = set_type_of(one).value
            row[_SUGGESTED_KEY] = "1"
            rows.append(row)
        return rows

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
        self._scope = ()
        self._sets_by_ex = {}
        self._last_sets_cache = {}
        self._logged_ex = set()
        self.completed = []
        self.finished = False
        self.show_day_list = False
        self.show_phase_list = False
        self.timer.stop()
        self._stop_session_timer()
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
        # Set the scope by hand: `_ensure_scope` would otherwise notice the
        # change and wipe the buffer we are about to fill.
        self._scope = self._current_scope()
        self._sets_by_ex = {}
        self._last_sets_cache = {}
        self._logged_ex = set()

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
        done = {c.get("exercise") for c in self.completed}
        self._logged_ex = {i for i, k in enumerate(keys) if k in done}

        if draft.started_at:
            self._resume_session_timer(float(draft.started_at))
        else:
            self._start_session_timer()

        if draft.dropped:
            # Rows that belonged to an exercise no longer in this day. Silently
            # losing them would look like the bug this whole change is about.
            with contextlib.suppress(Exception):
                self._toast(
                    f"Resumed. Dropped sets for: {', '.join(draft.dropped)}",
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
            self._persist_draft()
            self.page.data["refresh_current"]()

    def _go_next_exercise(self):
        day = self._current_day()
        total = len(day.exercises) if day else 0
        if self.ex_idx + 1 < total:
            self.ex_idx += 1
            self._persist_draft()
            self.page.data["refresh_current"]()

    def _current_day(self):
        days = active_routine().days_for_phase(self.phase_id)
        if self.phase_id and 0 <= self.day_idx < len(days):
            return days[self.day_idx]
        return None

    def _current_exercise_raw(self) -> str:
        """Full exercise string from data (may include [scheme] and *)."""
        d = self._current_day()
        if d and 0 <= self.ex_idx < len(d.exercises):
            return d.exercises[self.ex_idx]
        return ""

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
            # says "Saved" rather than pretending there is still work to do.
            return "logged"
        rows = self._sets_by_ex.get(idx) or []
        valid = [s for s in rows if not self._is_suggested(s) and self._has_content(s)]
        if not valid:
            pending = any(self._is_suggested(s) and self._has_content(s) for s in rows)
            return "unconfirmed" if pending else "empty"

        key = exercise_key(day.exercises[idx])  # canonical EN name, no brackets/star
        sets_parsed = [self._parse_set(s) for s in valid]
        entry = WorkoutEntry(
            date=date.today().isoformat(),
            exercise=key,
            muscle_group=day.name,
            phase=self.phase_id,
            sets=sets_parsed,
        )
        # Read the history *before* writing: a record is only a record against
        # what came before, and a list that already contains this entry can
        # never be beaten by it.
        previous: list[WorkoutEntry] = []
        with contextlib.suppress(Exception):
            previous = self.store.get_exercise_history(key, limit=_PR_HISTORY_LIMIT)

        self.store.save_workout(entry)
        self.completed.append({"exercise": key, "sets": sets_parsed})
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
            self._toast("Could not save — check the connection.", ft.Icons.ERROR_OUTLINE, C.danger)
            return
        if status == "unconfirmed":
            # Everything on screen is still a suggestion. Saving nothing while
            # the fields are full of numbers reads as a bug and silently loses
            # the exercise, so say what is missing.
            self._toast(
                "Nothing confirmed yet — tap a set number, or Confirm all.",
                ft.Icons.INFO_OUTLINE,
                C.warning,
            )
            return
        if status == "empty":
            self._toast(
                "Nothing to save yet — fill in a set first.",
                ft.Icons.INFO_OUTLINE,
                C.warning,
            )
            return
        if status == "logged":
            # Reached by tapping the "Saved" pill. A dead control that eats the
            # tap is worse than one that explains itself.
            self._toast(
                "Already saved in this session — it cannot be logged twice.",
                ft.Icons.CHECK_CIRCLE,
                C.success,
            )
            return
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
                            f"New PR — {entry.exercise}: {details}",
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
                f"{logged} exercise{'' if logged == 1 else 's'} logged · "
                f"{self._format_elapsed(self._session_elapsed_s())}",
                size=12,
                color=C.text_secondary,
            )
        ]
        if unsaved:
            lines.append(ft.Container(height=6))
            lines.append(
                ft.Text(
                    "These have sets you have not saved yet. They will be "
                    "written to your history now:",
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
            "Finish this session?", size=16, weight=ft.FontWeight.W_900, color=C.text
        )
        dlg.content = ft.Column(lines, spacing=2, tight=True)
        dlg.actions = [
            ghost_button("Keep training", on_click=close),
            primary_button("Save & finish" if unsaved else "Finish", on_click=confirm),
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
                "Could not save everything — the session stays open.",
                ft.Icons.ERROR_OUTLINE,
                C.danger,
            )
            self.page.data["refresh_current"]()
            return
        if saved:
            self._toast(
                f"Saved {saved} more exercise{'' if saved == 1 else 's'}.",
                ft.Icons.CHECK_CIRCLE,
                C.success,
            )
        self._finish_session()

    def _finish_session(self):
        self.finished = True
        self.timer.stop()
        self._stop_session_timer()
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
            "Discard this workout?", size=16, weight=ft.FontWeight.W_900, color=C.text
        )
        dlg.content = ft.Text(
            "Sets you already saved stay in your history. Anything typed and "
            "not saved yet will be lost.",
            size=12,
            color=C.text_secondary,
        )
        dlg.actions = [
            ghost_button("Keep training", on_click=close),
            primary_button("Discard", on_click=confirm),
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
        self.completed = []
        self.finished = False
        self.timer.stop()
        self._stop_session_timer()
        self.session_started_at = None
        self.session_ended_at = None
        self._clear_draft()

    # ── Render: phase select ──────────────────────────────────
    def _render_phase_select(self) -> ft.Control:
        routine = active_routine()
        return ft.Column(
            [
                ft.Text("Start Routine", size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Text(
                    f"Routine: {routine.name}",
                    size=11,
                    color=C.accent,
                    weight=ft.FontWeight.W_700,
                ),
                ft.Text("Choose your current phase", size=11, color=C.text_muted),
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
                                    f"PHASE {p.id}",
                                    size=10,
                                    # `p.color` is the raw hex from data.py,
                                    # picked against a black background: on a
                                    # white card #FFD93D is 1.38:1, invisible.
                                    color=phase_color(p.id),
                                    weight=ft.FontWeight.W_900,
                                ),
                                ft.Text(p.name, size=17, weight=ft.FontWeight.W_900, color=C.text),
                                ft.Text(p.scheme, size=11, color=C.text_secondary),
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
                self._back_btn("Phases", lambda _: self._show_phases()),
                ft.Text(phase.name, size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Container(height=10),
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
                                            f"{len(d.exercises)} exercises",
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

    def _in_progress_banner(self) -> ft.Control:
        """ "You have a workout open" — the way back in, and the way out.

        The only exit from a live session, and it asks first. Without this the
        day list would be a dead end: tapping the day you are already training
        resumes it, and nothing on screen would say why.
        """
        if not self._workout_in_progress():
            return ft.Container()
        days = active_routine().days_for_phase(self.phase_id)
        name = days[self.day_idx].name if 0 <= self.day_idx < len(days) else "Workout"
        done = len(self.completed)
        detail = f"{done} logged · {self._format_elapsed(self._session_elapsed_s())}"
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PLAY_CIRCLE_FILL_ROUNDED, color=C.accent, size=18),
                            ft.Column(
                                [
                                    ft.Text(
                                        f"In progress · {name}",
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
                                "Discard",
                                on_click=lambda _: self._ask_discard(
                                    lambda: self.page.data["refresh_current"]()
                                ),
                                expand=True,
                            ),
                            primary_button(
                                "Resume",
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
            count = f"{len(working_sets(c['sets']))} sets"
            if warm:
                count += f" · {len(warm)} warm-up"
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
        duration_txt = self._format_elapsed(self._session_elapsed_s())

        # Finish is reachable from the first exercise now, so a session can end
        # with nothing written — a wrong day picked, a warm-up cut short.
        # Confetti over an empty log is a lie, and the count read
        # "1 exercises logged" either way.
        logged = len(self.completed)
        if logged:
            hero = "🎉"
            title = "Session Complete!"
            subtitle = f"{logged} exercise{'' if logged == 1 else 's'} logged"
            subtitle_color = C.accent
        else:
            hero = "👋"
            title = "Session closed"
            subtitle = "Nothing logged this time"
            subtitle_color = C.text_muted

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
                ft.Row(
                    [
                        ft.Icon(ft.Icons.TIMER_OUTLINED, color=C.accent, size=14),
                        ft.Text(
                            f"Duration: {duration_txt}",
                            size=12,
                            color=C.text_secondary,
                            weight=ft.FontWeight.W_700,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=6,
                    tight=True,
                ),
                ft.Container(height=16),
                *completed_blocks,
                ft.Container(height=10),
                primary_button("Back to Home", on_click=self._finish, expand=True),
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
            return "LOGGED — MOVE ON"
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
            return f"SET {i + 1} OF {total}{target}"
        return "ALL SETS IN — SAVE THIS EXERCISE"

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
                "Zen mode on — tap to bring the rest of the app back"
                if on
                else "Zen mode off — tap to focus on the workout"
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

        def touched(idx: int, field: str, value: str):
            """A keystroke: store it and, the first time, un-suggest the row.

            The restyle is done in place instead of through
            `refresh_current()`: rebuilding the tree under a keyboard steals
            the focus and the caret, mid-number.
            """
            was_suggested = self._is_suggested(s)
            self._update_set(idx, field, value)
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
            tooltip=f"{label_for(set_type)} — tap to change",
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
            tooltip=("Tap to confirm this set" if suggested else f"Set {i + 1}"),
            on_click=(lambda _, idx=i: self._confirm_set(idx)) if suggested else None,
            ink=suggested,
        )
        return ft.Row(
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
            last_row = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "LAST SESSION", size=10, color=C.text_muted, weight=ft.FontWeight.W_700
                        ),
                        ft.Row(
                            [self._set_chip(s) for s in last_sets],
                            wrap=True,
                            spacing=6,
                            run_spacing=4,
                        ),
                    ],
                    spacing=6,
                ),
                bgcolor=C.bg_page,
                border_radius=10,
                padding=10,
            )
        else:
            last_row = ft.Text("First time - no history", size=11, color=C.text_muted, italic=True)

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
        header_row = ft.Row(
            [
                column_head("SET", 20),
                column_head("TYPE", 30),
                column_head("KG"),
                column_head("REPS"),
                column_head("RIR", 46),
                ft.Container(width=30),
            ],
            spacing=5,
        )
        add_btn = ft.Container(
            content=ft.Text("+ Set", size=11, color=C.text_muted, weight=ft.FontWeight.W_700),
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
            # "Same as last time" in one tap — the whole point of prefilling.
            # Only rendered while something is unconfirmed, so the button
            # disappears the moment it would do nothing.
            row_actions.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.DONE_ALL, size=14, color=C.accent),
                            ft.Text(
                                f"Confirm all ({pending})",
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
        prefill_note: ft.Control = (
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.HISTORY, size=13, color=C.text_secondary),
                        ft.Text(
                            "From your last session — tap the set number to confirm",
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
                            "Logged in this session",
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
        frames = None if zen else image_frames(key)
        if frames:
            image = ft.Image(
                src=frames[0],
                fit=ft.ImageFit.COVER,
                width=float("inf"),
                height=180,
                border_radius=10,
                gapless_playback=True,
            )
            self._anim_image = image
            self._anim_frames = frames
            self.page.run_task(self._animate_loop, self._anim_tick_id)
            image_block: ft.Control = ft.Container(
                content=image,
                bgcolor=C.bg_sunken,
                border_radius=10,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
        else:
            self._anim_image = None
            self._anim_frames = None
            image_block = ft.Container()

        # The three things worth reading with the phone on the floor: which
        # exercise, which set and how much, and how much rest is left. In zen
        # mode the first two get the size, and `build_large` gives the third.
        if zen:
            rest_block: ft.Control = self.timer.build_large(
                caption=f"AUTO {format_rest(self._rest_seconds())} AFTER EACH SET"
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
                        f"Rest · auto {format_rest(self._rest_seconds())} after each set",
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
            ft.Text(
                f"EXERCISE {self.ex_idx + 1}",
                size=10,
                color=phase_color(phase.id),
                weight=ft.FontWeight.W_900,
            ),
            ft.Text(display, size=24 if zen else 19, weight=ft.FontWeight.W_900, color=C.text),
            next_line,
            ft.Container(height=8),
            image_block,
            ft.Container(height=8) if frames else ft.Container(),
            last_row,
            ft.Container(height=10),
            rest_block,
            ft.Container(height=14),
            logged_note,
            prefill_note,
            header_row,
            *set_rows,
            ft.Container(height=6),
            actions_row,
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
        # "Skip" is gone rather than kept as a third button, because with Save
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
                        ft.Text("Saved", size=14, weight=ft.FontWeight.W_800, color=C.success),
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
                "Save",
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
            finish_label = f"Finish session · {len(unsaved)} unsaved"
        elif day_complete:
            # Save is spent and both arrows are dead: Finish is the only live
            # control on the screen, so it stops being the quiet one.
            finish_tint = C.accent
            finish_label = "Finish session"
        else:
            finish_tint = C.text_secondary
            finish_label = "Finish session"

        action_row = ft.Row(
            [
                self._step_button(
                    ft.Icons.CHEVRON_LEFT,
                    "Previous exercise",
                    lambda _: self._go_prev_exercise(),
                    enabled=self.ex_idx > 0,
                ),
                save_slot,
                self._step_button(
                    ft.Icons.CHEVRON_RIGHT,
                    "Next exercise",
                    lambda _: self._go_next_exercise(),
                    enabled=self.ex_idx + 1 < total,
                ),
            ],
            spacing=8,
        )
        # Its own row, centred and narrower than Save: it ends the session, so
        # it must be findable at a glance and awkward to hit by accident. The
        # confirmation in `_ask_finish` is the real guard; this is the first one.
        finish_row = ft.Row(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.FLAG_ROUNDED, size=15, color=finish_tint),
                            ft.Text(
                                finish_label,
                                size=12,
                                weight=ft.FontWeight.W_700,
                                color=finish_tint,
                            ),
                        ],
                        spacing=6,
                        tight=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    border=ft.border.all(1, finish_tint),
                    border_radius=Radius.md,
                    padding=ft.padding.symmetric(horizontal=18, vertical=10),
                    alignment=ft.alignment.center,
                    tooltip="End the session — anything unsaved is written first",
                    on_click=self._ask_finish,
                    ink=True,
                )
            ],
            alignment=ft.MainAxisAlignment.CENTER,
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
                self._back_btn("Back", lambda _: None, raw_handler=lambda _: self._back_to_days()),
                session_chip,
                ft.Text(
                    f"{self.ex_idx + 1}/{total}",
                    size=11,
                    color=C.text_muted,
                    weight=ft.FontWeight.W_700,
                ),
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
        """
        self.show_day_list = True
        self._persist_draft()
        self.page.data["refresh_current"]()

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
        """Swap between frame 0 and 1 every ~700ms for the active image."""
        showing_second = False
        while tick_id == self._anim_tick_id:
            await asyncio.sleep(0.7)
            if (
                tick_id != self._anim_tick_id
                or self._anim_image is None
                or self._anim_frames is None
            ):
                return
            showing_second = not showing_second
            self._anim_image.src = self._anim_frames[1] if showing_second else self._anim_frames[0]
            try:
                self.page.update()
            except Exception:
                return

    # ── Dispatcher ────────────────────────────────────────────
    def build(self) -> ft.Control:
        # Invalidate any running frame-swap task before rebuild
        self._anim_tick_id += 1
        # A routine swap from outside (`main.set_routine`) leaves `phase_id`
        # and `day_idx` pointing into a routine that no longer exists; catch it
        # before anything indexes with them.
        self._ensure_scope()
        # `show_*` pick the screen without touching the state underneath, which
        # is what makes stepping out of a workout and back in free.
        if self.phase_id == 0 or self.show_phase_list:
            return self._render_phase_select()
        if self.day_idx < 0 or self.show_day_list:
            return self._render_day_select()
        if self.finished:
            return self._render_finished()
        return self._render_exercise()
