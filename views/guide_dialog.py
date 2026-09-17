"""In-app dialog that shows a guide (training / nutrition).

Guides are pure prose — a heading and a paragraph, several times over — so this
is the dialog with the least excuse for a fixed width, and it had four of them
(300 for the heading, 300 for the body, 320 for the card, 340 for the column)
plus a 600 px height. Every one of them is now the window's, via
`shared_ui.dialog_width/height`.
"""

from __future__ import annotations

import flet as ft

from guides import guide_icon, guide_tips, guide_title_key
from theme import C
from views.shared_ui import dialog_height, dialog_width

#: Ceiling for the body, not a size: `dialog_height` cuts it to the window.
_PREFERRED_H = 560


def build_guide_dialog(page, guide_id: str) -> ft.AlertDialog:
    """The guide as a dialog, without opening it — buildable by a test."""
    tips = guide_tips(guide_id)
    icon = guide_icon(guide_id)
    title = guide_title_key(guide_id)

    def tip_card(heading: str, body_text: str) -> ft.Container:
        # No width on the card and none on the two lines inside it. The body
        # Column is STRETCH, so the card is exactly as wide as the dialog and
        # the paragraph wraps inside it instead of running past the border.
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(heading, size=13, color=C.accent, weight=ft.FontWeight.W_800),
                    ft.Text(body_text, size=11, color=C.text),
                ],
                spacing=6,
            ),
            bgcolor=C.bg_surface,
            border_radius=10,
            padding=12,
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
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    dialog = ft.AlertDialog(
        modal=False,
        bgcolor=C.bg_surface,
        title=ft.Text(title, size=18, weight=ft.FontWeight.W_900, color=C.text),
        content=ft.Container(
            content=body,
            width=dialog_width(page),
            height=dialog_height(page, _PREFERRED_H),
            alignment=ft.alignment.top_left,
        ),
        actions=[
            ft.TextButton(
                "Cerrar",
                on_click=lambda _: page.close(dialog),
                style=ft.ButtonStyle(color=C.accent),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dialog


def open_guide(page: ft.Page, guide_id: str) -> None:
    page.open(build_guide_dialog(page, guide_id))
