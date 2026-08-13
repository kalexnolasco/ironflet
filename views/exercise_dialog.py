"""Shared exercise detail dialog — used by Plan and Browse views."""

from __future__ import annotations

import flet as ft

from exercise_details import details_for
from exercise_images import image_for
from theme import ACCENT, BORDER_2, CARD_BG, DARK_BG, DIM, MUTED, TEXT, C


def open_exercise_detail(page: ft.Page, key: str) -> None:
    det = details_for(key)
    if not det:
        return
    img_src = image_for(key)

    def chip_item(label: str, value: str) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(label.upper(), size=9, color=MUTED, weight=ft.FontWeight.W_700),
                    ft.Text(value, size=12, color=TEXT, weight=ft.FontWeight.W_700),
                ],
                spacing=1,
                tight=True,
            ),
            bgcolor=DARK_BG,
            border=ft.border.all(1, BORDER_2),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
        )

    muscles_primary = ", ".join(m for m in det["primary"]) or "—"
    muscles_secondary = ", ".join(m for m in det["secondary"]) or "—"

    chips_row = ft.Row(
        [
            chip_item("Equipment", det["equipment"] or "—"),
            chip_item("Level", det["level"] or "—"),
            chip_item("Type", det["mechanic"] or "—"),
        ],
        spacing=6,
        wrap=True,
        run_spacing=6,
    )

    instructions_header = "How to do it"
    instructions_list = det.get("instructions") or []

    body = ft.Column(
        [
            ft.Container(
                content=ft.Image(
                    src=img_src, fit=ft.ImageFit.COVER, width=float("inf"), height=180
                ),
                bgcolor=C.bg_sunken,
                border_radius=10,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
            if img_src
            else ft.Container(),
            ft.Container(height=10),
            chips_row,
            ft.Container(height=10),
            ft.Text(
                "Primary: ",
                size=11,
                color=ACCENT,
                weight=ft.FontWeight.W_700,
                spans=[
                    ft.TextSpan(
                        muscles_primary, ft.TextStyle(color=TEXT, weight=ft.FontWeight.W_400)
                    )
                ],
            ),
            ft.Text(
                "Secondary: ",
                size=11,
                color=DIM,
                weight=ft.FontWeight.W_700,
                spans=[
                    ft.TextSpan(
                        muscles_secondary,
                        ft.TextStyle(color=C.text_secondary, weight=ft.FontWeight.W_400),
                    )
                ],
            ),
            ft.Container(height=12),
            ft.Text(instructions_header, size=12, color=ACCENT, weight=ft.FontWeight.W_800),
            ft.Container(height=6),
            ft.Text(
                "\n\n".join(f"{i + 1}.  {s}" for i, s in enumerate(instructions_list)),
                size=11,
                color=C.text,
                width=320,
            ),
            ft.Container(height=6),
        ],
        scroll=ft.ScrollMode.AUTO,
        spacing=4,
        width=340,
    )

    dialog = ft.AlertDialog(
        modal=False,
        bgcolor=CARD_BG,
        title=ft.Text(key, size=16, weight=ft.FontWeight.W_900, color=TEXT),
        content=ft.Container(content=body, width=340, height=600, alignment=ft.alignment.top_left),
        actions=[
            ft.TextButton(
                "Close",
                on_click=lambda _: page.close(dialog),
                style=ft.ButtonStyle(color=ACCENT),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.open(dialog)
