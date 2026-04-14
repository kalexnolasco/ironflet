"""Plan: 7 periodized phases + detail with exercises & weekly distribution."""

from __future__ import annotations

import flet as ft

from data import ROUTINES, active_routine
from exercise_details import details_for
from exercise_images import image_for
from i18n import exercise_key, t, t_exercise, weekday_label
from storage import Storage
from theme import (
    ACCENT, BORDER, CARD_BG, DIM, TEXT,
    card, chip, section_title,
)
from views.exercise_dialog import open_exercise_detail


class PlanView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.selected_phase_idx: int | None = None
        self.subview = "exercises"   # "exercises" | "distribution"
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
                        f"{t('PHASE')} {phase.id} · {t('WK')} {phase.weeks}",
                        size=10, color=phase.color, weight=ft.FontWeight.W_900,
                    ),
                    ft.Text(t(phase.name), size=18, weight=ft.FontWeight.W_900, color=TEXT),
                    ft.Text(t(phase.subtitle), size=11, color=DIM),
                    ft.Row(
                        [
                            chip(t(phase.scheme)),
                            chip(t("High freq.") if phase.freq == "high" else t("Low freq.")),
                        ],
                        spacing=6,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=CARD_BG,
            border=ft.border.all(1, BORDER),
            border_radius=14,
            padding=14,
            margin=ft.margin.only(bottom=8),
            on_click=lambda _, i=idx: self._select_phase(i),
            ink=True,
        )

    def _routine_selector(self) -> ft.Control:
        cur = active_routine()
        set_routine = self.page.data["set_routine"]

        def chip_for(r):
            on = (r.id == cur.id)
            return ft.Container(
                content=ft.Text(t(r.name), size=11, weight=ft.FontWeight.W_800,
                                color=ACCENT if on else DIM),
                bgcolor="#1d1410" if on else CARD_BG,
                border=ft.border.all(1, ACCENT if on else BORDER),
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=12, vertical=6),
                on_click=(None if on else (lambda _, rid=r.id: set_routine(rid))),
                ink=not on,
            )

        return ft.Row([chip_for(r) for r in ROUTINES], spacing=6, wrap=True, run_spacing=6)

    def _phase_list(self) -> ft.Control:
        routine = active_routine()
        return ft.Column(
            [
                ft.Text(t("Training Plan"), size=22, weight=ft.FontWeight.W_900, color=TEXT),
                ft.Container(height=4),
                self._routine_selector(),
                ft.Container(height=8),
                ft.Text(t(routine.description), size=11, color=DIM),
                ft.Container(height=10),
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
                content=ft.Image(src=thumb_src, fit=ft.ImageFit.COVER,
                                 width=44, height=44),
                bgcolor="#0f0f11",
                width=44, height=44,
                border_radius=6,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
        else:
            thumb = ft.Container(
                content=ft.Icon(ft.Icons.FITNESS_CENTER, color="#444", size=20),
                bgcolor="#101012",
                width=44, height=44,
                border_radius=6,
                alignment=ft.alignment.center,
            )

        name_widget = ft.Container(
            content=ft.Text(t_exercise(ex_raw), size=12, color="#ffffff",
                            weight=ft.FontWeight.W_500,
                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            width=250,
            alignment=ft.alignment.center_left,
        )
        return ft.Container(
            content=ft.Row(
                [thumb, name_widget,
                 (ft.Icon(ft.Icons.INFO_OUTLINE, color=ACCENT, size=16)
                  if has_detail else ft.Container(width=16))],
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
                    ft.Text(t(day.name), size=13, weight=ft.FontWeight.W_700,
                            color=ACCENT if is_open else TEXT, expand=True),
                    ft.Text(f"{len(day.exercises)}", size=11, color=DIM,
                            weight=ft.FontWeight.W_700),
                    ft.Icon(
                        ft.Icons.KEYBOARD_ARROW_UP if is_open
                        else ft.Icons.KEYBOARD_ARROW_DOWN,
                        color=ACCENT if is_open else DIM, size=18,
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
            bgcolor=CARD_BG,
            border=ft.border.all(1, ACCENT if is_open else BORDER),
            border_radius=12,
            margin=ft.margin.only(bottom=6),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    def _open_detail(self, key: str):
        open_exercise_detail(self.page, key)

    def _tab_button(self, label: str, key: str) -> ft.Container:
        active = self.subview == key
        return ft.Container(
            content=ft.Text(label, size=11, weight=ft.FontWeight.W_700,
                            color=ACCENT if active else DIM),
            bgcolor="#1d1410" if active else CARD_BG,
            border=ft.border.all(1, ACCENT if active else BORDER),
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
                    content=ft.Text(f"{t('WK')} {i + 1}", size=11, weight=ft.FontWeight.W_800,
                                    color=ACCENT if i == self.dist_week_idx else DIM),
                    bgcolor="#1d1410" if i == self.dist_week_idx else CARD_BG,
                    border=ft.border.all(1, ACCENT if i == self.dist_week_idx else BORDER),
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
                                content=ft.Text(weekday_label(i), size=10,
                                                weight=ft.FontWeight.W_800, color=ACCENT),
                                bgcolor=BORDER,
                                border_radius=6,
                                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                            ),
                            ft.Text(t(w), size=13, color=TEXT, weight=ft.FontWeight.W_700,
                                    expand=True),
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

        tabs_row: list[ft.Control] = [self._tab_button(t("Exercises"), "exercises")]
        if routine.week_rotation is not None and phase.id in (1, 2, 3):
            tabs_row.append(self._tab_button(t("Distribution"), "distribution"))

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
                            ft.Icon(ft.Icons.ARROW_BACK, color=ACCENT, size=16),
                            ft.Text(t("Phases"), color=ACCENT, size=12,
                                    weight=ft.FontWeight.W_700),
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
                                content=ft.Text(f"{t('PHASE')} {phase.id}", size=10,
                                                weight=ft.FontWeight.W_900, color="black"),
                                bgcolor=phase.color,
                                border_radius=6,
                                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                            ),
                            ft.Text(f"{t('Wk')} {phase.weeks}", size=11, color=DIM),
                        ],
                        spacing=8,
                    ),
                    ft.Text(t(phase.name), size=22, weight=ft.FontWeight.W_900, color=TEXT),
                    ft.Text(t(phase.subtitle), size=12, color=phase.color,
                            weight=ft.FontWeight.W_700),
                    ft.Container(height=6),
                    ft.Text(f"{t('Sets:')} {t(phase.scheme)}", size=12, color=TEXT),
                    ft.Text(f"{t('Rest:')} {t(phase.rest)}", size=11, color="#aaa"),
                    ft.Container(height=6),
                    ft.Text(t(phase.notes), size=11, color="#999"),
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
