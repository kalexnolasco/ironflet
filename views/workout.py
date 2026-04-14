"""Workout: guided flow phase → day → exercise by exercise."""

from __future__ import annotations

import asyncio
import time
from datetime import date

import flet as ft

from components.timer import RestTimer
from data import active_routine
from exercise_images import image_frames
from i18n import exercise_key, t, t_exercise
from storage import Storage, WorkoutEntry
from theme import (
    ACCENT,
    BORDER,
    BORDER_2,
    CARD_BG,
    DARK_BG,
    DIM,
    MUTED,
    TEXT,
    card,
    chip,
    ghost_button,
    primary_button,
)


class WorkoutView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.timer = RestTimer(page)

        self.phase_id: int = 0
        self.day_idx: int = -1
        self.ex_idx: int = 0
        self.sets: list[dict[str, str]] = [{"weight": "", "reps": ""}]
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
    def _reset(self):
        self.phase_id = 0
        self.day_idx = -1
        self.ex_idx = 0
        self.sets = [{"weight": "", "reps": ""}]
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
            self.sets = [{"weight": "", "reps": ""}]
            self.page.data["refresh_current"]()

    def _go_next_exercise(self):
        day = self._current_day()
        total = len(day.exercises) if day else 0
        if self.ex_idx + 1 < total:
            self.ex_idx += 1
            self.sets = [{"weight": "", "reps": ""}]
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
        self.sets = [{"weight": "", "reps": ""}]
        self.completed = []
        self.finished = False
        if idx >= 0:
            self._start_session_timer()
        else:
            self._stop_session_timer()
        self.page.data["refresh_current"]()

    def _add_set(self, _):
        self.sets.append({"weight": "", "reps": ""})
        self.page.data["refresh_current"]()

    def _remove_set(self, i: int):
        if len(self.sets) > 1:
            self.sets.pop(i)
            self.page.data["refresh_current"]()

    def _update_set(self, i: int, field: str, value: str):
        self.sets[i][field] = value

    def _skip(self, _):
        self._advance()

    def _save_next(self, _):
        valid = [s for s in self.sets if s.get("weight") or s.get("reps")]
        if valid:
            raw = self._current_exercise_raw()
            key = exercise_key(raw)  # canonical EN name, no brackets/star
            day = self._current_day()
            day_name_raw = day.name if day else ""
            sets_parsed = []
            for s in valid:
                try:
                    w = float(s.get("weight") or 0)
                except ValueError:
                    w = 0.0
                try:
                    r = int(float(s.get("reps") or 0))
                except ValueError:
                    r = 0
                sets_parsed.append({"weight": w, "reps": r})
            self.store.save_workout(
                WorkoutEntry(
                    date=date.today().isoformat(),
                    exercise=key,
                    muscle_group=day_name_raw,
                    phase=self.phase_id,
                    sets=sets_parsed,
                )
            )
            self.completed.append({"exercise": key, "sets": sets_parsed})
        self._advance()

    def _advance(self):
        day = self._current_day()
        total = len(day.exercises) if day else 0
        if self.ex_idx + 1 >= total:
            self.finished = True
            self.timer.stop()
            self._stop_session_timer()
        else:
            self.ex_idx += 1
            self.sets = [{"weight": "", "reps": ""}]
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
                ft.Text(t("Start Routine"), size=22, weight=ft.FontWeight.W_900, color=TEXT),
                ft.Text(
                    f"{t('Routine')}: {t(routine.name)}",
                    size=11,
                    color=ACCENT,
                    weight=ft.FontWeight.W_700,
                ),
                ft.Text(t("Choose your current phase"), size=11, color=MUTED),
                ft.Container(height=10),
                *[
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    f"{t('PHASE')} {p.id}",
                                    size=10,
                                    color=p.color,
                                    weight=ft.FontWeight.W_900,
                                ),
                                ft.Text(t(p.name), size=17, weight=ft.FontWeight.W_900, color=TEXT),
                                ft.Text(t(p.scheme), size=11, color=DIM),
                            ],
                            spacing=2,
                            tight=True,
                        ),
                        bgcolor=CARD_BG,
                        border=ft.border.all(1, BORDER),
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
                self._back_btn(t("Phases"), lambda _: self._select_phase(0)),
                ft.Text(t(phase.name), size=22, weight=ft.FontWeight.W_900, color=TEXT),
                ft.Container(height=10),
                *[
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(
                                            t(d.name),
                                            size=14,
                                            weight=ft.FontWeight.W_700,
                                            color=TEXT,
                                        ),
                                        ft.Text(
                                            f"{len(d.exercises)} {t('exercises')}",
                                            size=11,
                                            color=DIM,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED, color=phase.color, size=22),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        bgcolor=CARD_BG,
                        border=ft.border.all(1, BORDER),
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
    def _render_finished(self) -> ft.Control:
        completed_blocks = [
            card(
                ft.Text(t_exercise(c["exercise"]), size=13, weight=ft.FontWeight.W_700, color=TEXT),
                ft.Row(
                    [chip(f"{s['weight']:g}kg × {s['reps']}", color=ACCENT) for s in c["sets"]],
                    wrap=True,
                    spacing=6,
                    run_spacing=4,
                ),
                padding=12,
                margin=ft.margin.only(bottom=6),
            )
            for c in self.completed
        ]
        duration_txt = self._format_elapsed(self._session_elapsed_s())

        return ft.Column(
            [
                ft.Container(height=20),
                ft.Text("🎉", size=56, text_align=ft.TextAlign.CENTER),
                ft.Text(
                    t("Session Complete!"),
                    size=22,
                    weight=ft.FontWeight.W_900,
                    color=TEXT,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    f"{len(self.completed)} {t('exercises logged')}",
                    size=13,
                    color=ACCENT,
                    weight=ft.FontWeight.W_700,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=6),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.TIMER_OUTLINED, color=ACCENT, size=14),
                        ft.Text(
                            f"{t('Duration')}: {duration_txt}",
                            size=12,
                            color="#bbbbbb",
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
                primary_button(t("Back to Home"), on_click=self._finish, expand=True),
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
            bgcolor=DARK_BG,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
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
            bgcolor=DARK_BG,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=14,
            height=40,
            content_padding=ft.padding.symmetric(horizontal=6, vertical=8),
            expand=True,
            on_change=lambda e, idx=i: self._update_set(idx, "reps", e.control.value),
        )
        return ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        str(i + 1),
                        size=13,
                        weight=ft.FontWeight.W_900,
                        color=self._phase().color if self._phase() else ACCENT,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=28,
                    alignment=ft.alignment.center,
                ),
                w_field,
                r_field,
                ft.Container(
                    content=ft.Icon(ft.Icons.CLOSE, size=14, color="#555"),
                    width=32,
                    height=40,
                    border=ft.border.all(1, "#222"),
                    border_radius=6,
                    alignment=ft.alignment.center,
                    on_click=lambda _, idx=i: self._remove_set(idx),
                    ink=True,
                ),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _render_exercise(self) -> ft.Control:
        phase = self._phase()
        day = self._current_day()
        assert phase and day
        total = len(day.exercises)
        raw = self._current_exercise_raw()
        key = exercise_key(raw)
        display = t_exercise(raw)
        last_sets = self.store.get_last_sets(key)
        last_ref_for_placeholder = last_sets[0] if last_sets else None

        if last_sets:
            last_row = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            t("LAST SESSION"), size=10, color=MUTED, weight=ft.FontWeight.W_700
                        ),
                        ft.Row(
                            [
                                chip(f"{s['weight']:g}kg × {s['reps']}", color=ACCENT)
                                for s in last_sets
                            ],
                            wrap=True,
                            spacing=6,
                            run_spacing=4,
                        ),
                    ],
                    spacing=6,
                ),
                bgcolor=DARK_BG,
                border_radius=10,
                padding=10,
            )
        else:
            last_row = ft.Text(t("First time - no history"), size=11, color="#444", italic=True)

        set_rows = [self._set_row(i, s, last_ref_for_placeholder) for i, s in enumerate(self.sets)]
        header_row = ft.Row(
            [
                ft.Container(
                    ft.Text(
                        t("SET"),
                        size=9,
                        color="#444",
                        weight=ft.FontWeight.W_700,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=28,
                ),
                ft.Container(
                    ft.Text(
                        t("KG"),
                        size=9,
                        color="#444",
                        weight=ft.FontWeight.W_700,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    expand=True,
                ),
                ft.Container(
                    ft.Text(
                        t("REPS"),
                        size=9,
                        color="#444",
                        weight=ft.FontWeight.W_700,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    expand=True,
                ),
                ft.Container(width=32),
            ],
            spacing=6,
        )
        add_btn = ft.Container(
            content=ft.Text(t("+ Set"), size=11, color=MUTED, weight=ft.FontWeight.W_700),
            border=ft.border.all(1, "#2a2a2d"),
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
                bgcolor="#0f0f11",
                border_radius=10,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
        else:
            self._anim_image = None
            self._anim_frames = None
            image_block = ft.Container()

        exercise_card = card(
            ft.Text(
                f"{t('EXERCISE')} {self.ex_idx + 1}",
                size=10,
                color=phase.color,
                weight=ft.FontWeight.W_900,
            ),
            ft.Text(display, size=19, weight=ft.FontWeight.W_900, color=TEXT),
            ft.Container(height=8),
            image_block,
            ft.Container(height=8) if frames else ft.Container(),
            last_row,
            ft.Container(height=10),
            self.timer.build(),
            ft.Container(height=14),
            header_row,
            *set_rows,
            ft.Container(height=6),
            add_btn,
            border_color=phase.color,
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
                ghost_button(t("Skip"), on_click=self._skip, expand=True),
                primary_button(
                    t("Save → Next") if self.ex_idx + 1 < total else t("Save → Finish"),
                    on_click=self._save_next,
                    expand=True,
                ),
            ],
            spacing=8,
        )

        session_label = ft.Text(
            self._format_elapsed(self._session_elapsed_s()),
            size=12,
            color=ACCENT,
            weight=ft.FontWeight.W_800,
        )
        self._session_label = session_label
        session_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.TIMER_OUTLINED, color=ACCENT, size=14),
                    session_label,
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=DARK_BG,
            border=ft.border.all(1, BORDER_2),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
        )

        header = ft.Row(
            [
                self._back_btn(
                    t("Back"), lambda _: None, raw_handler=lambda _: self._reset_to_days()
                ),
                session_chip,
                ft.Text(
                    f"{self.ex_idx + 1}/{total}", size=11, color="#555", weight=ft.FontWeight.W_700
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        progress = ft.ProgressBar(
            value=(self.ex_idx / total) if total else 0,
            color=phase.color,
            bgcolor=BORDER,
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
                    ft.Icon(ft.Icons.ARROW_BACK, color=ACCENT, size=16),
                    ft.Text(label, color=ACCENT, size=12, weight=ft.FontWeight.W_700),
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
