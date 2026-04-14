"""History: exercise list + detail with progression."""

from __future__ import annotations

import flet as ft

from components.charts import bar_chart
from i18n import t, t_exercise
from storage import Storage
from theme import (
    ACCENT,
    BORDER,
    CARD_BG,
    DIM,
    MUTED,
    TEXT,
    card,
    chip,
    section_title,
)


class HistoryView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.selected: str | None = None

    def on_show(self):
        pass

    def handle_back(self) -> bool:
        if self.selected is not None:
            self.selected = None
            self.page.data["refresh_current"]()
            return True
        return False

    def _select(self, name: str):
        self.selected = name
        self.page.data["refresh_current"]()

    def _back_to_list(self, _=None):
        self.selected = None
        self.page.data["refresh_current"]()

    def _list(self) -> ft.Control:
        summary = self.store.get_exercise_summary()
        if not summary:
            return ft.Column(
                [
                    ft.Text(
                        t("History & Progress"), size=22, weight=ft.FontWeight.W_900, color=TEXT
                    ),
                    ft.Text(t("Tap an exercise to see your progress"), size=11, color=MUTED),
                    ft.Container(height=20),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text("📭", size=28, text_align=ft.TextAlign.CENTER),
                                ft.Text(
                                    t("Start training to see your progress"),
                                    size=12,
                                    color="#666",
                                    text_align=ft.TextAlign.CENTER,
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
                    ),
                ],
                expand=True,
                spacing=0,
                tight=True,
            )

        items = []
        for ex in summary:
            items.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        t_exercise(ex["name"]),
                                        size=13,
                                        weight=ft.FontWeight.W_700,
                                        color=TEXT,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    ft.Text(
                                        f"{ex['count']} {t('sessions')} · {ex['last_date']}",
                                        size=10,
                                        color=DIM,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        f"{ex['max_weight']:g}",
                                        size=16,
                                        color=ACCENT,
                                        weight=ft.FontWeight.W_900,
                                    ),
                                    ft.Text(t("max kg"), size=9, color="#666"),
                                ],
                                spacing=0,
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    bgcolor=CARD_BG,
                    border=ft.border.all(1, BORDER),
                    border_radius=12,
                    padding=12,
                    margin=ft.margin.only(bottom=6),
                    on_click=lambda _, n=ex["name"]: self._select(n),
                    ink=True,
                )
            )
        return ft.Column(
            [
                ft.Text(t("History & Progress"), size=22, weight=ft.FontWeight.W_900, color=TEXT),
                ft.Text(t("Tap an exercise to see your progress"), size=11, color=MUTED),
                ft.Container(height=10),
                *items,
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            tight=True,
            spacing=0,
        )

    def _detail(self) -> ft.Control:
        name = self.selected
        assert name
        hist = self.store.get_exercise_history(name)
        max_weights = [max((s["weight"] for s in h.sets), default=0) for h in hist]
        volumes = [sum(s["weight"] * s["reps"] for s in h.sets) for h in hist]
        labels = [h.date[5:] for h in hist]  # MM-DD
        pr = max(max_weights) if max_weights else 0

        sessions_cards = []
        for h in reversed(hist):
            set_chips = []
            for s in h.sets:
                is_pr = s["weight"] == pr and pr > 0
                text = f"{'🏆 ' if is_pr else ''}{s['weight']:g}kg × {s['reps']}"
                set_chips.append(chip(text, color=ACCENT))
            sessions_cards.append(
                card(
                    ft.Row(
                        [
                            ft.Text(h.date, size=11, color=ACCENT, weight=ft.FontWeight.W_700),
                            ft.Text(t(h.muscle_group), size=10, color=DIM),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(set_chips, wrap=True, spacing=6, run_spacing=4),
                    padding=12,
                    margin=ft.margin.only(bottom=6),
                )
            )

        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ARROW_BACK, color=ACCENT, size=16),
                            ft.Text(
                                t("Exercises"), color=ACCENT, size=12, weight=ft.FontWeight.W_700
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=self._back_to_list,
                    padding=ft.padding.symmetric(vertical=6),
                    ink=True,
                ),
                ft.Text(
                    t_exercise(name), size=20, weight=ft.FontWeight.W_900, color=TEXT, max_lines=2
                ),
                ft.Text(f"{len(hist)} {t('sessions')} · {t('PR')} {pr:g}kg", size=12, color=MUTED),
                ft.Container(height=12),
                section_title(t("Max weight")),
                ft.Container(height=6),
                ft.Container(
                    content=bar_chart(max_weights, labels, color=ACCENT, height=110),
                    bgcolor=CARD_BG,
                    border=ft.border.all(1, BORDER),
                    border_radius=12,
                    padding=12,
                ),
                ft.Container(height=14),
                section_title(t("Total volume")),
                ft.Container(height=6),
                ft.Container(
                    content=bar_chart(volumes, labels, color="#4ECDC4", height=110),
                    bgcolor=CARD_BG,
                    border=ft.border.all(1, BORDER),
                    border_radius=12,
                    padding=12,
                ),
                ft.Container(height=14),
                section_title(t("Session detail")),
                ft.Container(height=6),
                *sessions_cards,
            ],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            tight=True,
            spacing=0,
        )

    def build(self) -> ft.Control:
        if self.selected is None:
            return self._list()
        return self._detail()
