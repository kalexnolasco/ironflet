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

#: `get_exercise_history` keeps the last 20 sessions by default. A record has to
#: beat *everything*, so ask for the whole history of the exercise — otherwise a
#: best from 21 sessions ago is forgotten and the app invents a PR.
_PR_HISTORY_LIMIT = 100_000


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
        self.timer = RestTimer(page)

        self.phase_id: int = 0
        self.day_idx: int = -1
        self.ex_idx: int = 0
        self.sets: list[dict[str, str]] = [self._blank_set()]
        self.completed: list[dict] = []
        self.finished: bool = False

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
        pass

    def handle_back(self) -> bool:
        if self.finished:
            self._reset()
            self.page.data["refresh_current"]()
            return True
        if self.day_idx >= 0:
            self.day_idx = -1
            self.ex_idx = 0
            self.completed = []
            self._stop_session_timer()
            self.page.data["refresh_current"]()
            return True
        if self.phase_id > 0:
            self.phase_id = 0
            self.page.data["refresh_current"]()
            return True
        return False

    # ── State helpers ─────────────────────────────────────────
    @staticmethod
    def _blank_set() -> dict[str, str]:
        """A fresh draft row.

        The type is kept as the plain string that lands in the database, so the
        draft stays a `dict[str, str]` and `set_type_of` reads it unchanged.
        New rows are normal: it is the 90 % case and the one that costs no taps.
        """
        return {"weight": "", "reps": "", "rir": "", TYPE_KEY: SetType.NORMAL.value}

    def _reset(self):
        self.phase_id = 0
        self.day_idx = -1
        self.ex_idx = 0
        self.sets = [self._blank_set()]
        self.completed = []
        self.finished = False
        self.timer.stop()
        self._stop_session_timer()

    def _start_session_timer(self):
        self.session_started_at = time.time()
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
        if self.ex_idx > 0:
            self.ex_idx -= 1
            self.sets = [self._blank_set()]
            self.page.data["refresh_current"]()

    def _go_next_exercise(self):
        day = self._current_day()
        total = len(day.exercises) if day else 0
        if self.ex_idx + 1 < total:
            self.ex_idx += 1
            self.sets = [self._blank_set()]
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
        self.phase_id = pid
        self.day_idx = -1
        self.ex_idx = 0
        self.completed = []
        self.finished = False
        self.page.data["refresh_current"]()

    def _select_day(self, idx: int):
        self.day_idx = idx
        self.ex_idx = 0
        self.sets = [self._blank_set()]
        self.completed = []
        self.finished = False
        # A countdown left over from the previous session has nothing to do
        # with this one.
        self.timer.stop()
        if idx >= 0:
            self._start_session_timer()
        else:
            self._stop_session_timer()
        self.page.data["refresh_current"]()

    def _add_set(self, _):
        # Adding a row means the previous one is done — that is the moment the
        # rest starts, and the only one the user signals without extra taps.
        last = self.sets[-1]
        if last.get("weight") or last.get("reps"):
            self._start_rest(last)
        self.sets.append(self._blank_set())
        self.page.data["refresh_current"]()

    def _remove_set(self, i: int):
        if len(self.sets) > 1:
            self.sets.pop(i)
            self.page.data["refresh_current"]()

    def _update_set(self, i: int, field: str, value: str):
        self.sets[i][field] = value

    def _cycle_set_type(self, i: int):
        self.sets[i][TYPE_KEY] = next_set_type(self.sets[i].get(TYPE_KEY)).value
        self.page.data["refresh_current"]()

    def _skip(self, _):
        self._advance()

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

    def _save_next(self, _):
        valid = [s for s in self.sets if s.get("weight") or s.get("reps")]
        if valid:
            raw = self._current_exercise_raw()
            key = exercise_key(raw)  # canonical EN name, no brackets/star
            day = self._current_day()
            day_name_raw = day.name if day else ""
            sets_parsed = [self._parse_set(s) for s in valid]
            entry = WorkoutEntry(
                date=date.today().isoformat(),
                exercise=key,
                muscle_group=day_name_raw,
                phase=self.phase_id,
                sets=sets_parsed,
            )
            # Read the history *before* writing: a record is only a record
            # against what came before, and a list that already contains this
            # entry can never be beaten by it.
            previous: list[WorkoutEntry] = []
            with contextlib.suppress(Exception):
                previous = self.store.get_exercise_history(key, limit=_PR_HISTORY_LIMIT)

            self.store.save_workout(entry)
            self.completed.append({"exercise": key, "sets": sets_parsed})

            # The set is already in the database: a missing congratulation must
            # never cost the user their log, so nothing here may raise.
            with contextlib.suppress(Exception):
                self._announce_records(previous, entry)

            # Rest between exercises counts too — but not after the last one,
            # where `_advance` finishes the session and stops the clock.
            if not self._is_last_exercise():
                self._start_rest(sets_parsed[-1])
        self._advance()

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

    def _advance(self):
        if self._is_last_exercise():
            self.finished = True
            self.timer.stop()
            self._stop_session_timer()
        else:
            self.ex_idx += 1
            self.sets = [self._blank_set()]
        self.page.data["refresh_current"]()

    def _finish(self, _):
        self._reset()
        nav = self.page.data["navigate_to"]
        nav(0)

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
                self._back_btn("Phases", lambda _: self._select_phase(0)),
                ft.Text(phase.name, size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Container(height=10),
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

        return ft.Column(
            [
                ft.Container(height=20),
                ft.Text("🎉", size=56, text_align=ft.TextAlign.CENTER),
                ft.Text(
                    "Session Complete!",
                    size=22,
                    weight=ft.FontWeight.W_900,
                    color=C.text,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    f"{len(self.completed)} exercises logged",
                    size=13,
                    color=C.accent,
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
    def _set_row(self, i: int, s: dict, last_ref: dict | None) -> ft.Control:
        placeholder_w = str(last_ref["weight"]) if last_ref else "kg"
        placeholder_r = str(last_ref["reps"]) if last_ref else "reps"
        w_field = ft.TextField(
            value=s.get("weight", ""),
            hint_text=placeholder_w,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
            height=40,
            content_padding=ft.padding.symmetric(horizontal=6, vertical=8),
            expand=True,
            on_change=lambda e, idx=i: self._update_set(idx, "weight", e.control.value),
        )
        r_field = ft.TextField(
            value=s.get("reps", ""),
            hint_text=placeholder_r,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
            height=40,
            content_padding=ft.padding.symmetric(horizontal=6, vertical=8),
            expand=True,
            on_change=lambda e, idx=i: self._update_set(idx, "reps", e.control.value),
        )
        # RIR (reps in reserve): optional. Left blank it simply isn't stored.
        rir_field = ft.TextField(
            value=s.get("rir", ""),
            hint_text=str(last_ref.get("rir", "")) if last_ref and last_ref.get("rir") else "–",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            bgcolor=C.bg_page,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
            height=40,
            width=46,
            content_padding=ft.padding.symmetric(horizontal=2, vertical=8),
            on_change=lambda e, idx=i: self._update_set(idx, "rir", e.control.value),
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
        return ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        str(i + 1),
                        size=13,
                        weight=ft.FontWeight.W_900,
                        color=phase_color(self.phase_id) if self._phase() else C.accent,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=20,
                    alignment=ft.alignment.center,
                ),
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
        last_sets = self.store.get_last_sets(key)
        last_ref_for_placeholder = last_sets[0] if last_sets else None

        if last_sets:
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
            on_click=self._add_set,
            ink=True,
        )

        frames = image_frames(key)
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

        exercise_card = card(
            ft.Text(
                f"EXERCISE {self.ex_idx + 1}",
                size=10,
                color=phase_color(phase.id),
                weight=ft.FontWeight.W_900,
            ),
            ft.Text(display, size=19, weight=ft.FontWeight.W_900, color=C.text),
            ft.Container(height=8),
            image_block,
            ft.Container(height=8) if frames else ft.Container(),
            last_row,
            ft.Container(height=10),
            # Says out loud what now happens by itself, so the countdown that
            # appears after a set does not look like something went wrong.
            ft.Text(
                f"Rest · auto {format_rest(self._rest_seconds())} after each set",
                size=10,
                color=C.text_muted,
                weight=ft.FontWeight.W_700,
            ),
            ft.Container(height=4),
            self.timer.build(),
            ft.Container(height=14),
            header_row,
            *set_rows,
            ft.Container(height=6),
            add_btn,
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

        action_row = ft.Row(
            [
                ghost_button("Skip", on_click=self._skip, expand=True),
                primary_button(
                    "Save → Next" if self.ex_idx + 1 < total else "Save → Finish",
                    on_click=self._save_next,
                    expand=True,
                ),
            ],
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
                self._back_btn("Back", lambda _: None, raw_handler=lambda _: self._reset_to_days()),
                session_chip,
                ft.Text(
                    f"{self.ex_idx + 1}/{total}",
                    size=11,
                    color=C.text_muted,
                    weight=ft.FontWeight.W_700,
                ),
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
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            tight=True,
            spacing=0,
        )

    def _reset_to_days(self):
        self.day_idx = -1
        self.ex_idx = 0
        self.completed = []
        self.timer.stop()
        self._stop_session_timer()
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
        if self.phase_id == 0:
            return self._render_phase_select()
        if self.day_idx < 0:
            return self._render_day_select()
        if self.finished:
            return self._render_finished()
        return self._render_exercise()
