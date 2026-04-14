"""Shared exercise detail dialog — used by Plan and Browse views."""

from __future__ import annotations

import flet as ft

from exercise_details import details_for
from exercise_details_es import instructions_es
from exercise_images import EXERCISE_IMAGE, image_for
from i18n import get_language, t, t_exercise
from theme import ACCENT, BORDER_2, CARD_BG, DARK_BG, DIM, MUTED, TEXT


def open_exercise_detail(page: ft.Page, key: str) -> None:
    det = details_for(key)
    if not det:
        return
    img_src = image_for(key)
    lang_is_es = get_language() == "es"

    def chip_item(label: str, value: str) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(label.upper(), size=9, color=MUTED,
                            weight=ft.FontWeight.W_700),
                    ft.Text(value, size=12, color=TEXT,
                            weight=ft.FontWeight.W_700),
                ],
                spacing=1,
                tight=True,
            ),
            bgcolor=DARK_BG,
            border=ft.border.all(1, BORDER_2),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
        )

    muscles_primary = ", ".join(t(m) for m in det["primary"]) or "—"
    muscles_secondary = ", ".join(t(m) for m in det["secondary"]) or "—"

    chips_row = ft.Row(
        [
            chip_item(t("Equipment"), t(det["equipment"]) or "—"),
            chip_item(t("Level"), t(det["level"]) or "—"),
            chip_item(t("Type"), t(det["mechanic"]) or "—"),
        ],
        spacing=6,
        wrap=True,
        run_spacing=6,
    )

    instructions_header = t("How to do it")
    slug = EXERCISE_IMAGE.get(key)
    instructions_list = det.get("instructions") or []
    if lang_is_es and slug:
        es_steps = instructions_es(slug)
        if es_steps:
            instructions_list = es_steps
        else:
            instructions_header += f"  ·  {t('Instructions in English').lower()}"

    body = ft.Column(
        [
            ft.Container(
                content=ft.Image(src=img_src, fit=ft.ImageFit.COVER,
                                 width=float("inf"), height=180),
                bgcolor="#0f0f11",
                border_radius=10,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ) if img_src else ft.Container(),
            ft.Container(height=10),
            chips_row,
            ft.Container(height=10),
            ft.Text(f"{t('Primary')}: ", size=11, color=ACCENT,
                    weight=ft.FontWeight.W_700,
                    spans=[ft.TextSpan(muscles_primary,
                                       ft.TextStyle(color=TEXT,
                                                    weight=ft.FontWeight.W_400))]),
            ft.Text(f"{t('Secondary')}: ", size=11, color=DIM,
                    weight=ft.FontWeight.W_700,
                    spans=[ft.TextSpan(muscles_secondary,
                                       ft.TextStyle(color="#aaa",
                                                    weight=ft.FontWeight.W_400))]),
            ft.Container(height=12),
            ft.Text(instructions_header, size=12, color=ACCENT,
                    weight=ft.FontWeight.W_800),
            ft.Container(height=6),
            ft.Text(
                "\n\n".join(f"{i + 1}.  {s}" for i, s in
                            enumerate(instructions_list)),
                size=11,
                color="#ffffff",
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
        title=ft.Text(t_exercise(key), size=16,
                      weight=ft.FontWeight.W_900, color=TEXT),
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
