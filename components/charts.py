"""Gráficos simples con ft.Container (sin dependencias externas)."""

from __future__ import annotations

import flet as ft


def bar_chart(
    values: list[float],
    labels: list[str] | None = None,
    color: str = "#FF6B35",
    height: int = 120,
) -> ft.Control:
    if not values:
        return ft.Container(
            content=ft.Text("Sin datos", color="#555", size=11, italic=True),
            alignment=ft.alignment.center,
            height=height,
        )
    labels = labels or []
    max_val = max(values) or 1
    bars = []
    for i, v in enumerate(values):
        bar_h = max(2, int((v / max_val) * height))
        lbl = labels[i] if i < len(labels) else ""
        bars.append(
            ft.Column(
                [
                    ft.Container(height=height - bar_h),
                    ft.Container(
                        height=bar_h,
                        width=16,
                        bgcolor=color,
                        border_radius=ft.border_radius.only(top_left=4, top_right=4),
                        tooltip=f"{v:g}",
                    ),
                    ft.Text(f"{v:g}", size=8, color=color, weight=ft.FontWeight.W_700),
                    ft.Text(lbl, size=7, color="#555"),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=1,
            )
        )
    return ft.Row(
        bars,
        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
        spacing=2,
        scroll=ft.ScrollMode.AUTO,
    )
