"""Home: summary, stats, CTA, language toggle."""

from __future__ import annotations

from datetime import date

import flet as ft

from i18n import day_name, get_language, month_name, t
from storage import Storage
from theme import (
    ACCENT,
    BORDER,
    CARD_BG,
    MUTED,
    TEXT,
    card,
    chip,
    primary_button,
    section_title,
)


def today_display() -> str:
    d = date.today()
    return f"{day_name(d.weekday())}, {d.day} {month_name(d.month - 1)}"


class HomeView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store

    def on_show(self):
        pass

    def handle_back(self) -> bool:
        return False

    def _stat_card(self, value: str, label: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        value,
                        size=22,
                        weight=ft.FontWeight.W_900,
                        color=ACCENT,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        label,
                        size=11,
                        weight=ft.FontWeight.W_700,
                        color="#cccccc",
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=4,
            ),
            bgcolor=CARD_BG,
            border=ft.border.all(1, BORDER),
            border_radius=14,
            padding=ft.padding.symmetric(horizontal=8, vertical=10),
            expand=True,
            height=72,
        )

    def _lang_toggle(self) -> ft.Container:
        cur = get_language()
        set_lang = self.page.data["set_language"]

        def pill(code: str) -> ft.Container:
            active = cur == code
            return ft.Container(
                content=ft.Text(
                    code.upper(),
                    size=10,
                    weight=ft.FontWeight.W_900,
                    color=ACCENT if active else "#555",
                ),
                bgcolor="#1d1410" if active else CARD_BG,
                border=ft.border.all(1, ACCENT if active else BORDER),
                border_radius=6,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                on_click=(None if active else (lambda _, c=code: set_lang(c))),
                ink=not active,
            )

        return ft.Row([pill("en"), pill("es")], spacing=4, tight=True)

    def _today_item(self, w) -> ft.Container:
        from i18n import t_exercise

        set_chips = [
            chip(
                f"{s['weight']:g}kg × {s['reps']}"
                if s.get("weight", 0) > 0
                else f"{s['reps']} reps",
                color=ACCENT,
            )
            for s in w.sets
        ]
        return card(
            ft.Row(
                [
                    ft.Text(
                        t_exercise(w.exercise),
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color=TEXT,
                        expand=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    chip(t(w.muscle_group), color=ACCENT),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row(set_chips, wrap=True, spacing=6, run_spacing=4) if set_chips else ft.Container(),
            padding=12,
            margin=ft.margin.only(bottom=6),
        )

    def build(self) -> ft.Control:
        streak = self.store.get_streak()
        stats = self.store.get_week_stats()
        today = self.store.get_today()

        vol = stats["volume"]
        vol_str = f"{vol / 1000:.1f}k" if vol >= 1000 else f"{int(vol)}"

        nav_fn = self.page.data["navigate_to"]
        profile_btn = ft.Container(
            content=ft.Icon(ft.Icons.SETTINGS, color=ACCENT, size=18),
            bgcolor=CARD_BG,
            border=ft.border.all(1, BORDER),
            border_radius=8,
            width=34,
            height=34,
            alignment=ft.alignment.center,
            on_click=lambda _: nav_fn(5),
            ink=True,
            tooltip=t("Settings"),
        )

        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    "IRONFLET", size=11, weight=ft.FontWeight.W_900, color=ACCENT
                                ),
                                ft.Container(width=8),
                                self._lang_toggle(),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(today_display(), size=22, weight=ft.FontWeight.W_900, color=TEXT),
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            profile_btn,
                            card(
                                ft.Text("🔥", size=18, text_align=ft.TextAlign.CENTER),
                                ft.Text(
                                    str(streak),
                                    size=20,
                                    weight=ft.FontWeight.W_900,
                                    color=ACCENT,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Text(
                                    t("days"),
                                    size=9,
                                    weight=ft.FontWeight.W_700,
                                    color=MUTED,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                padding=ft.padding.symmetric(horizontal=14, vertical=8),
                                alignment=ft.alignment.center,
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        stats_row = ft.Row(
            [
                self._stat_card(str(stats["sessions"]), t("Sessions")),
                self._stat_card(str(stats["sets"]), t("Sets")),
                self._stat_card(vol_str, t("Vol (kg)")),
            ],
            spacing=8,
        )

        nav = self.page.data["navigate_to"]
        start_btn = primary_button(
            t("Start Routine"),
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            on_click=lambda _: nav(2),
            expand=True,
        )

        if today:
            today_block: ft.Control = ft.Column(
                [self._today_item(w) for w in today],
                spacing=0,
                tight=True,
            )
        else:
            today_block = ft.Container(
                content=ft.Column(
                    [
                        ft.Text("💤", size=28, text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            t("No records"), size=12, color="#666", text_align=ft.TextAlign.CENTER
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                bgcolor=CARD_BG,
                border=ft.border.all(1, BORDER),
                border_radius=14,
                padding=24,
                alignment=ft.alignment.center,
            )

        return ft.Column(
            [
                header,
                ft.Container(height=14),
                stats_row,
                ft.Container(height=14),
                ft.Row([start_btn]),
                ft.Container(height=14),
                section_title(t("Today")),
                ft.Container(height=4),
                today_block,
                ft.Container(height=18),
                section_title(t("Guides")),
                ft.Container(height=4),
                self._guides_row(),
                ft.Container(height=14),
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=0,
            expand=True,
        )

    def _guides_row(self) -> ft.Control:
        from guides import guide_icon, guide_ids, guide_title_key
        from views.guide_dialog import open_guide

        def card_link(gid: str) -> ft.Container:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            guide_icon(gid),
                            size=22,
                            color="#ffffff",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            t(guide_title_key(gid)),
                            size=11,
                            color="#cccccc",
                            weight=ft.FontWeight.W_700,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=4,
                ),
                bgcolor=CARD_BG,
                border=ft.border.all(1, BORDER),
                border_radius=14,
                padding=ft.padding.symmetric(horizontal=8, vertical=10),
                on_click=lambda _, g=gid: open_guide(self.page, g),
                ink=True,
                expand=True,
                height=72,
            )

        return ft.Row([card_link(gid) for gid in guide_ids()], spacing=8)
