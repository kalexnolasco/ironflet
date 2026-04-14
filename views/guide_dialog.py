"""In-app dialog that shows a guide (training / nutrition / women fitness)."""

from __future__ import annotations

import flet as ft

from guides import guide_icon, guide_tips, guide_title_key
from i18n import get_language, t
from theme import ACCENT, CARD_BG, DIM, TEXT


def open_guide(page: ft.Page, guide_id: str) -> None:
    tips = guide_tips(guide_id, get_language())
    icon = guide_icon(guide_id)
    title = t(guide_title_key(guide_id))

    def tip_card(heading: str, body_text: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(heading, size=13, color=ACCENT,
                            weight=ft.FontWeight.W_800, width=300),
                    ft.Text(body_text, size=11, color="#ffffff", width=300),
                ],
                spacing=6,
            ),
            bgcolor="#141416",
            border_radius=10,
            padding=12,
            width=320,
        )

    body = ft.Column(
        [
            ft.Text(icon, size=36, text_align=ft.TextAlign.CENTER),
            ft.Container(height=4),
            *[tip_card(h, b) for h, b in tips],
            ft.Container(height=6),
        ],
        scroll=ft.ScrollMode.AUTO,
        spacing=8,
        width=340,
    )

    dialog = ft.AlertDialog(
        modal=False,
        bgcolor=CARD_BG,
        title=ft.Text(title, size=18, weight=ft.FontWeight.W_900, color=TEXT),
        content=ft.Container(content=body, width=340, height=600,
                             alignment=ft.alignment.top_left),
        actions=[
            ft.TextButton(
                t("Close"),
                on_click=lambda _: page.close(dialog),
                style=ft.ButtonStyle(color=ACCENT),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.open(dialog)
