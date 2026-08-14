"""In-app dialog that shows a guide (training / nutrition / women fitness)."""

from __future__ import annotations

import flet as ft

from guides import guide_icon, guide_tips, guide_title_key
from theme import C


def open_guide(page: ft.Page, guide_id: str) -> None:
    tips = guide_tips(guide_id)
    icon = guide_icon(guide_id)
    title = guide_title_key(guide_id)

    def tip_card(heading: str, body_text: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        heading, size=13, color=C.accent, weight=ft.FontWeight.W_800, width=300
                    ),
                    ft.Text(body_text, size=11, color=C.text, width=300),
                ],
                spacing=6,
            ),
            bgcolor=C.bg_surface,
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
        bgcolor=C.bg_surface,
        title=ft.Text(title, size=18, weight=ft.FontWeight.W_900, color=C.text),
        content=ft.Container(content=body, width=340, height=600, alignment=ft.alignment.top_left),
        actions=[
            ft.TextButton(
                "Close",
                on_click=lambda _: page.close(dialog),
                style=ft.ButtonStyle(color=C.accent),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.open(dialog)
