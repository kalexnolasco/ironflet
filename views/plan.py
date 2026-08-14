"""Plan: the phases of the active routine, and where routines are chosen.

Choosing a routine is also where people go looking for "make me one of my own",
so the way into the routine editor lives here rather than in a tab of its own:
duplicating the built-in you already follow is the realistic first step, and it
is offered on the built-ins themselves.
"""

from __future__ import annotations

import flet as ft

from data import ROUTINES, active_routine
from dates import weekday_label
from exercise_details import details_for
from exercise_images import image_for
from exercises import exercise_key, phase_color
from routine_builder import duplicate_builtin, is_user_routine, routine_pk
from storage import Storage
from theme import (
    C,
    Radius,
    Space,
    card,
    chip,
    ghost_button,
    muted_text,
)
from views.exercise_dialog import open_exercise_detail

# View index owned by main.py; named so the call sites read as intent.
VIEW_ROUTINE_EDITOR = 7


class PlanView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.selected_phase_idx: int | None = None
        self.subview = "exercises"  # "exercises" | "distribution"
        self.dist_week_idx = 0
        self._expanded_days: set[str] = set()

    def on_show(self):
        pass

    def handle_back(self) -> bool:
        if self.selected_phase_idx is not None:
            self.selected_phase_idx = None
            self.page.data["refresh_current"]()
            return True
        return False

    # ─────────────────────────────────────────────────────────
    def _select_phase(self, idx: int):
        self.selected_phase_idx = idx
        self.subview = "exercises"
        self.dist_week_idx = 0
        self.page.data["refresh_current"]()

    def _back_to_list(self):
        self.selected_phase_idx = None
        self.page.data["refresh_current"]()

    def _set_subview(self, v: str):
        self.subview = v
        self.page.data["refresh_current"]()

    def _set_dist_week(self, i: int):
        self.dist_week_idx = i
        self.page.data["refresh_current"]()

    # ─────────────────────────────────────────────────────────
    def _phase_card(self, phase, idx: int) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        f"PHASE {phase.id} · WK {phase.weeks}",
                        size=10,
                        color=phase_color(phase.id),
                        weight=ft.FontWeight.W_900,
                    ),
                    ft.Text(phase.name, size=18, weight=ft.FontWeight.W_900, color=C.text),
                    ft.Text(phase.subtitle, size=11, color=C.text_secondary),
                    ft.Row(
                        [
                            chip(phase.scheme),
                            chip("High freq." if phase.freq == "high" else "Low freq."),
                        ],
                        spacing=6,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=14,
            padding=14,
            margin=ft.margin.only(bottom=8),
            on_click=lambda _, i=idx: self._select_phase(i),
            ink=True,
        )

    # ── routines ─────────────────────────────────────────────
    def _open_editor(self, pk: int | None = None):
        """Into the routine editor, on `pk` if the host can open one directly.

        `edit_routine` is an optional hook: main.py holds the view instances, so
        only it can put the editor on a specific routine. Without it this still
        lands on the editor's library, which lists the same routine one tap away.
        """
        opener = self.page.data.get("edit_routine")
        if pk is not None and callable(opener):
            opener(pk)
            return
        self.page.data["navigate_to"](VIEW_ROUTINE_EDITOR)

    def _edit_active(self, _=None):
        self._open_editor(routine_pk(active_routine().id))

    def _duplicate(self, routine_id: str):
        """Copy a built-in and open the copy. The original is untouched.

        This is the honest path to owning a routine: nobody writes 24 weeks of
        periodisation from an empty screen, they change the two exercises they
        disagree with. `duplicate_builtin` already re-syncs `data.ROUTINES`.
        """
        self._open_editor(duplicate_builtin(self.store, routine_id))

    def _routine_chip(self, r, active_id: str) -> ft.Control:
        on = r.id == active_id
        set_routine = self.page.data["set_routine"]
        parts: list[ft.Control] = [
            ft.Text(
                r.name,
                size=11,
                weight=ft.FontWeight.W_800,
                color=C.accent if on else C.text_secondary,
            )
        ]
        if not is_user_routine(r.id):
            # The copy button sits on the template it copies. Its own on_click
            # keeps the tap from also switching the active routine — you can
            # fork a routine you have not adopted.
            parts.append(
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.CONTENT_COPY_OUTLINED,
                        size=13,
                        color=C.accent if on else C.text_muted,
                    ),
                    on_click=lambda _, rid=r.id: self._duplicate(rid),
                    ink=True,
                    border_radius=Radius.sm,
                    padding=2,
                    tooltip=f"Duplicate '{r.name}' into an editable routine",
                )
            )
        return ft.Container(
            content=ft.Row(parts, spacing=6, tight=True),
            bgcolor=C.accent_soft if on else C.bg_surface,
            border=ft.border.all(1, C.accent if on else C.border),
            border_radius=Radius.sm,
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            on_click=(None if on else (lambda _, rid=r.id: set_routine(rid))),
            ink=not on,
        )

    def _routine_selector(self) -> ft.Control:
        active_id = active_routine().id
        return ft.Row(
            [self._routine_chip(r, active_id) for r in ROUTINES],
            spacing=6,
            wrap=True,
            run_spacing=6,
        )

    def _routine_actions(self) -> ft.Control:
        buttons: list[ft.Control] = []
        if is_user_routine(active_routine().id):
            buttons.append(
                ghost_button("Edit this routine", on_click=self._edit_active, expand=True)
            )
        buttons.append(
            ghost_button(
                "My routines",
                on_click=lambda _: self._open_editor(),
                expand=True,
                tooltip="Create, edit or delete your own routines",
            )
        )
        return ft.Row(buttons, spacing=Space.x2)

    def _phase_list(self) -> ft.Control:
        routine = active_routine()
        return ft.Column(
            [
                ft.Text("Training Plan", size=22, weight=ft.FontWeight.W_900, color=C.text),
                ft.Container(height=Space.x1),
                self._routine_selector(),
                ft.Container(height=Space.x1),
                muted_text("Tap a copy icon to fork a built-in routine and make it yours."),
                ft.Container(height=Space.x2),
                self._routine_actions(),
                ft.Container(height=Space.x3),
                ft.Text(routine.description, size=11, color=C.text_secondary),
                ft.Container(height=Space.x3),
                *[self._phase_card(p, i) for i, p in enumerate(routine.phases)],
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )

    # ─────────────────────────────────────────────────────────
    def _toggle_day(self, name: str):
        if name in self._expanded_days:
            self._expanded_days.remove(name)
        else:
            self._expanded_days.add(name)
        self.page.data["refresh_current"]()

    def _exercise_row(self, ex_raw: str) -> ft.Control:
        key = exercise_key(ex_raw)
        thumb_src = image_for(key)
        has_detail = details_for(key) is not None

        thumb: ft.Control
        if thumb_src:
            thumb = ft.Container(
                content=ft.Image(src=thumb_src, fit=ft.ImageFit.COVER, width=44, height=44),
                bgcolor=C.bg_sunken,
                width=44,
                height=44,
                border_radius=6,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
        else:
            thumb = ft.Container(
                content=ft.Icon(ft.Icons.FITNESS_CENTER, color=C.text_muted, size=20),
                bgcolor=C.bg_sunken,
                width=44,
                height=44,
                border_radius=6,
                alignment=ft.alignment.center,
            )

        name_widget = ft.Container(
            content=ft.Text(
                ex_raw,
                size=12,
                color=C.text,
                weight=ft.FontWeight.W_500,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            width=250,
            alignment=ft.alignment.center_left,
        )
        return ft.Container(
            content=ft.Row(
                [
                    thumb,
                    name_widget,
                    (
                        ft.Icon(ft.Icons.INFO_OUTLINE, color=C.accent, size=16)
                        if has_detail
                        else ft.Container(width=16)
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border_radius=8,
            on_click=(lambda _, k=key: self._open_detail(k)) if has_detail else None,
            ink=has_detail,
        )

    def _day_tile(self, day) -> ft.Control:
        is_open = day.name in self._expanded_days
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        day.name,
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color=C.accent if is_open else C.text,
                        expand=True,
                    ),
                    ft.Text(
                        f"{len(day.exercises)}",
                        size=11,
                        color=C.text_secondary,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Icon(
                        ft.Icons.KEYBOARD_ARROW_UP if is_open else ft.Icons.KEYBOARD_ARROW_DOWN,
                        color=C.accent if is_open else C.text_secondary,
                        size=18,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            on_click=lambda _, n=day.name: self._toggle_day(n),
            ink=True,
        )
        children: list[ft.Control] = [header]
        if is_open:
            children.append(
                ft.Container(
                    content=ft.Column(
                        [self._exercise_row(ex) for ex in day.exercises],
                        spacing=2,
                        tight=True,
                    ),
                    padding=ft.padding.only(left=6, right=6, bottom=8, top=0),
                )
            )
        return ft.Container(
            content=ft.Column(children, spacing=0, tight=True),
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.accent if is_open else C.border),
            border_radius=12,
            margin=ft.margin.only(bottom=6),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    def _open_detail(self, key: str):
        open_exercise_detail(self.page, key)

    def _tab_button(self, label: str, key: str) -> ft.Container:
        active = self.subview == key
        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.W_700,
                color=C.accent if active else C.text_secondary,
            ),
            bgcolor=C.accent_soft if active else C.bg_surface,
            border=ft.border.all(1, C.accent if active else C.border),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            on_click=lambda _, k=key: self._set_subview(k),
            ink=True,
        )

    def _distribution(self) -> ft.Control:
        rotation = active_routine().week_rotation or []
        week = rotation[self.dist_week_idx] if rotation else []
        week_tabs = ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        f"WK {i + 1}",
                        size=11,
                        weight=ft.FontWeight.W_800,
                        color=C.accent if i == self.dist_week_idx else C.text_secondary,
                    ),
                    bgcolor=C.accent_soft if i == self.dist_week_idx else C.bg_surface,
                    border=ft.border.all(1, C.accent if i == self.dist_week_idx else C.border),
                    border_radius=8,
                    padding=ft.padding.symmetric(horizontal=14, vertical=6),
                    on_click=lambda _, idx=i: self._set_dist_week(idx),
                    ink=True,
                )
                for i in range(len(rotation))
            ],
            spacing=6,
        )
        rows = []
        for i, w in enumerate(week):
            rows.append(
                card(
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(
                                    weekday_label(i),
                                    size=10,
                                    weight=ft.FontWeight.W_800,
                                    color=C.accent,
                                ),
                                bgcolor=C.border,
                                border_radius=6,
                                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                            ),
                            ft.Text(
                                w, size=13, color=C.text, weight=ft.FontWeight.W_700, expand=True
                            ),
                        ],
                        spacing=10,
                    ),
                    padding=10,
                    margin=ft.margin.only(bottom=6),
                )
            )
        return ft.Column([week_tabs, ft.Container(height=10), *rows], spacing=0, tight=True)

    def _phase_detail(self) -> ft.Control:
        idx = self.selected_phase_idx
        assert idx is not None
        routine = active_routine()
        phase = routine.phases[idx]
        days = routine.days_for_phase(phase.id)

        tabs_row: list[ft.Control] = [self._tab_button("Exercises", "exercises")]
        if routine.week_rotation is not None and phase.id in (1, 2, 3):
            tabs_row.append(self._tab_button("Distribution", "distribution"))

        body: ft.Control
        if self.subview == "distribution":
            body = self._distribution()
        else:
            body = ft.Column([self._day_tile(d) for d in days], spacing=6, tight=True)

        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ARROW_BACK, color=C.accent, size=16),
                            ft.Text("Phases", color=C.accent, size=12, weight=ft.FontWeight.W_700),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=lambda _: self._back_to_list(),
                    padding=ft.padding.symmetric(vertical=6),
                    ink=True,
                ),
                card(
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(
                                    f"PHASE {phase.id}",
                                    size=10,
                                    weight=ft.FontWeight.W_900,
                                    color=C.on_accent,
                                ),
                                bgcolor=phase_color(phase.id),
                                border_radius=6,
                                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                            ),
                            ft.Text(f"Wk {phase.weeks}", size=11, color=C.text_secondary),
                        ],
                        spacing=8,
                    ),
                    ft.Text(phase.name, size=22, weight=ft.FontWeight.W_900, color=C.text),
                    ft.Text(
                        phase.subtitle,
                        size=12,
                        color=phase_color(phase.id),
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Container(height=6),
                    ft.Text(f"Sets: {phase.scheme}", size=12, color=C.text),
                    ft.Text(f"Rest: {phase.rest}", size=11, color=C.text_secondary),
                    ft.Container(height=6),
                    ft.Text(phase.notes, size=11, color=C.text_muted),
                ),
                ft.Container(height=12),
                ft.Row(tabs_row, spacing=6),
                ft.Container(height=10),
                body,
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=0,
            expand=True,
            tight=True,
        )

    def build(self) -> ft.Control:
        if self.selected_phase_idx is None:
            return self._phase_list()
        return self._phase_detail()
