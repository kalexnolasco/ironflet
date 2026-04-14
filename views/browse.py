"""Browse: filterable catalog of all exercises with details on tap."""

from __future__ import annotations

import flet as ft

from data import EXERCISE_CATALOG, MUSCLE_GROUPS
from exercise_details import details_for
from exercise_images import image_for
from i18n import t, t_exercise
from storage import Storage
from theme import (
    ACCENT, BORDER, CARD_BG, DIM, TEXT,
)
from views.exercise_dialog import open_exercise_detail


class BrowseView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.selected_group: str | None = None  # None = all

    def on_show(self):
        pass

    def handle_back(self) -> bool:
        if self.selected_group is not None:
            self.selected_group = None
            self.page.data["refresh_current"]()
            return True
        return False

    def _set_group(self, group: str | None):
        self.selected_group = group
        self.page.data["refresh_current"]()

    def _group_chip(self, group: str | None, label: str) -> ft.Container:
        active = self.selected_group == group
        return ft.Container(
            content=ft.Text(label, size=11, weight=ft.FontWeight.W_700,
                            color=ACCENT if active else DIM),
            bgcolor="#1d1410" if active else CARD_BG,
            border=ft.border.all(1, ACCENT if active else BORDER),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            on_click=lambda _, g=group: self._set_group(g),
            ink=True,
        )

    def _exercise_row(self, ex_name: str) -> ft.Control:
        thumb_src = image_for(ex_name)
        has_detail = details_for(ex_name) is not None

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
            content=ft.Text(t_exercise(ex_name), size=12, color="#ffffff",
                            weight=ft.FontWeight.W_500, max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS),
            width=250,
            alignment=ft.alignment.center_left,
        )

        trailing = (
            ft.Icon(ft.Icons.INFO_OUTLINE, color=ACCENT, size=16)
            if has_detail else ft.Container(width=16)
        )

        return ft.Container(
            content=ft.Row(
                [thumb, name_widget, trailing],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=CARD_BG,
            border=ft.border.all(1, BORDER),
            border_radius=10,
            margin=ft.margin.only(bottom=6),
            on_click=(lambda _, k=ex_name: open_exercise_detail(self.page, k))
                     if has_detail else None,
            ink=has_detail,
        )

    def _exercises_for_selected(self) -> list[str]:
        if self.selected_group is None:
            seen: set[str] = set()
            ordered: list[str] = []
            for group in MUSCLE_GROUPS:
                for ex in EXERCISE_CATALOG[group]:
                    if ex not in seen:
                        seen.add(ex)
                        ordered.append(ex)
            return ordered
        return EXERCISE_CATALOG.get(self.selected_group, [])

    def build(self) -> ft.Control:
        chips = [self._group_chip(None, t("All"))]
        chips += [self._group_chip(g, t(g)) for g in MUSCLE_GROUPS]

        exercises = self._exercises_for_selected()
        count = len(exercises)

        return ft.Column(
            [
                ft.Text(t("Exercises"), size=22, weight=ft.FontWeight.W_900, color=TEXT),
                ft.Text(t("Tap an exercise for details"), size=11, color=DIM),
                ft.Container(height=8),
                ft.Row(chips, spacing=6, wrap=True, run_spacing=6),
                ft.Container(height=10),
                ft.Text(f"{count} {t('exercises')}", size=11, color=DIM,
                        weight=ft.FontWeight.W_700),
                ft.Container(height=6),
                *[self._exercise_row(ex) for ex in exercises],
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )
