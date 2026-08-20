"""Shared exercise detail dialog — used by Plan and Browse views.

This is the dialog with the most text in the app: three chips, two muscle lines
and a numbered how-to that runs to eight steps for a squat. It was also the one
pinned hardest — a 340 px box with a 320 px paragraph inside it and a 600 px
height — so on any phone narrower than the 420 px it was designed for, the
instructions were cut off mid-word and the Close button sat below the fold.

Nothing here carries a width any more. The box comes from
`shared_ui.dialog_width/height`, which read the real window, and every line
inside takes whatever the box has.
"""

from __future__ import annotations

import flet as ft

from exercise_details import details_for
from exercise_images import image_props
from theme import C
from views.shared_ui import dialog_height, dialog_width

#: Ceiling for the body, not a size: `dialog_height` cuts it to the window.
_PREFERRED_H = 560
#: The photo's height. Width is the parent's, whatever that turns out to be.
_IMAGE_H = 180


def build_exercise_detail(page, key: str) -> ft.AlertDialog | None:
    """The dialog for `key`, or None when there is nothing to show.

    Split out from `open_exercise_detail` so it can be built and measured
    without a running app — the same shape `views/help_dialog.py` uses.
    """
    det = details_for(key)
    if not det:
        return None
    # `image_props`, not `image_for`: on the phone an assets-relative URL
    # resolves to nothing and the photo is a silent grey box. See the delivery
    # note in exercise_images.py.
    img_props = image_props(key)

    def chip_item(label: str, value: str) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(label.upper(), size=9, color=C.text_muted, weight=ft.FontWeight.W_700),
                    ft.Text(value, size=12, color=C.text, weight=ft.FontWeight.W_700),
                ],
                spacing=1,
                tight=True,
            ),
            bgcolor=C.bg_page,
            border=ft.border.all(1, C.border_strong),
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
                # `float("inf")` is Flet's "fill the parent", which is the
                # opposite of a pinned width: the photo follows the dialog.
                content=ft.Image(
                    **img_props,
                    fit=ft.ImageFit.COVER,
                    width=float("inf"),
                    height=_IMAGE_H,
                    # DECODE SMALL: the source is an 850×567 photo and `height`
                    # only scales the drawing. No `cache_width` — the width is
                    # the dialog's and is not known here.
                    cache_height=_IMAGE_H * 2,
                    error_content=ft.Icon(ft.Icons.FITNESS_CENTER, color=C.text_muted, size=28),
                ),
                bgcolor=C.bg_sunken,
                border_radius=10,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
            if img_props
            else ft.Container(),
            ft.Container(height=10),
            chips_row,
            ft.Container(height=10),
            ft.Text(
                "Primary: ",
                size=11,
                color=C.accent,
                weight=ft.FontWeight.W_700,
                spans=[
                    ft.TextSpan(
                        muscles_primary, ft.TextStyle(color=C.text, weight=ft.FontWeight.W_400)
                    )
                ],
            ),
            ft.Text(
                "Secondary: ",
                size=11,
                color=C.text_secondary,
                weight=ft.FontWeight.W_700,
                spans=[
                    ft.TextSpan(
                        muscles_secondary,
                        ft.TextStyle(color=C.text_secondary, weight=ft.FontWeight.W_400),
                    )
                ],
            ),
            ft.Container(height=12),
            ft.Text(instructions_header, size=12, color=C.accent, weight=ft.FontWeight.W_800),
            ft.Container(height=6),
            # No width: the steps are the longest text in the app and a pinned
            # one is what cut them off. The Column bounds them.
            ft.Text(
                "\n\n".join(f"{i + 1}.  {s}" for i, s in enumerate(instructions_list)),
                size=11,
                color=C.text,
            ),
            ft.Container(height=6),
        ],
        scroll=ft.ScrollMode.AUTO,
        spacing=4,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    dialog = ft.AlertDialog(
        modal=False,
        bgcolor=C.bg_surface,
        title=ft.Text(key, size=16, weight=ft.FontWeight.W_900, color=C.text),
        content=ft.Container(
            content=body,
            width=dialog_width(page),
            height=dialog_height(page, _PREFERRED_H),
            alignment=ft.alignment.top_left,
        ),
        actions=[
            ft.TextButton(
                "Close",
                on_click=lambda _: page.close(dialog),
                style=ft.ButtonStyle(color=C.accent),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dialog


def open_exercise_detail(page: ft.Page, key: str) -> None:
    dialog = build_exercise_detail(page, key)
    if dialog is not None:
        page.open(dialog)
