"""Paleta y helpers visuales compartidos."""

import flet as ft

DARK_BG = "#0A0A0B"
CARD_BG = "#111114"
NAV_BG = "#101012"
BORDER = "#1a1a1d"
BORDER_2 = "#242428"
ACCENT = "#FF6B35"
ACCENT2 = "#FF3366"
MUTED = "#999999"
TEXT = "#FFFFFF"
DIM = "#aaaaaa"
CHIP_TEXT = "#dddddd"


def card(*controls, padding=16, margin=None, border_color=BORDER, **kw) -> ft.Container:
    return ft.Container(
        content=ft.Column(list(controls), spacing=6, tight=True),
        bgcolor=kw.pop("bgcolor", CARD_BG),
        border=ft.border.all(1, border_color),
        border_radius=14,
        padding=padding,
        margin=margin,
        **kw,
    )


def chip(text: str, color: str = CHIP_TEXT, bg: str = "#252528") -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=10, weight=ft.FontWeight.W_700, color=color),
        bgcolor=bg,
        border_radius=6,
        padding=ft.padding.symmetric(horizontal=8, vertical=2),
    )


def primary_button(text: str, on_click=None, expand=False, icon: str | None = None) -> ft.Container:
    children: list[ft.Control] = []
    if icon:
        children.append(ft.Icon(icon, color=TEXT, size=16))
    children.append(ft.Text(text, color=TEXT, size=14, weight=ft.FontWeight.W_800))
    return ft.Container(
        content=ft.Row(children, alignment=ft.MainAxisAlignment.CENTER, spacing=6, tight=True),
        gradient=ft.LinearGradient(
            begin=ft.alignment.top_left,
            end=ft.alignment.bottom_right,
            colors=[ACCENT, ACCENT2],
        ),
        border_radius=12,
        padding=ft.padding.symmetric(horizontal=20, vertical=14),
        on_click=on_click,
        ink=True,
        expand=expand,
        alignment=ft.alignment.center,
    )


def ghost_button(text: str, on_click=None, expand=False) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, color=MUTED, size=13, weight=ft.FontWeight.W_700),
        bgcolor=BORDER,
        border=ft.border.all(1, BORDER_2),
        border_radius=10,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        on_click=on_click,
        ink=True,
        expand=expand,
        alignment=ft.alignment.center,
    )


def section_title(text: str) -> ft.Text:
    return ft.Text(text, size=16, weight=ft.FontWeight.W_800, color=TEXT)


def muted_text(text: str, size: int = 11) -> ft.Text:
    return ft.Text(text, color=MUTED, size=size)
