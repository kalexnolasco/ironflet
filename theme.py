"""Design tokens and shared widget factories.

Colours used to be loose module constants, which is how 51 hardcoded hex values
ended up scattered across the views and how the old dark palette shipped text at
1.94:1 contrast — invisible in practice. Everything now goes through `C`, a
proxy over the active palette, so swapping themes is one call and no view holds
a colour of its own.

Every foreground/background pair in LIGHT meets WCAG AA (4.5:1 for body text,
3:1 for large text and UI edges); the worst pair is 4.59:1. `tests/test_theme.py`
recomputes the ratios so a "nicer" shade cannot silently drop below the line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import flet as ft


@dataclass(frozen=True)
class Palette:
    """One theme. Field names describe the role, never the colour."""

    name: str
    bg_page: str  # window background
    bg_surface: str  # cards, dialogs, anything raised off the page
    bg_sunken: str  # text inputs and wells, pressed *into* the surface
    bg_nav: str
    border: str  # decorative separators
    border_strong: str  # focus rings and interactive outlines (needs 3:1)
    text: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_2: str
    accent_soft: str  # tinted background behind an active chip
    on_accent: str  # text sitting on top of accent
    success: str
    warning: str
    danger: str
    chart_bar: str
    shadow: str
    phase: tuple[str, ...] = field(default_factory=tuple)


# Light is the default: this app is used in daylight, in a gym, on a phone.
LIGHT = Palette(
    name="light",
    bg_page="#F4F6F8",
    bg_surface="#FFFFFF",
    bg_sunken="#EDF0F4",
    bg_nav="#FFFFFF",
    border="#E2E7EC",
    border_strong="#7A8492",
    text="#14181D",
    text_secondary="#454E5B",
    text_muted="#5C6673",
    accent="#C2410C",
    accent_2="#BE123C",
    accent_soft="#FFF0E6",
    on_accent="#FFFFFF",
    success="#15803D",
    warning="#A16207",
    danger="#B91C1C",
    chart_bar="#E85D1A",
    shadow="#0F172A",
    # Seven hues spread around the wheel so phases stay distinguishable, all
    # darkened enough to carry white text on a white card.
    phase=("#0F766E", "#C2410C", "#6D28D9", "#A16207", "#BE185D", "#B91C1C", "#0E7490"),
)

# Kept because the tokens make it nearly free, and fixed so it also passes AA —
# the shipped version had six failing pairs.
DARK = Palette(
    name="dark",
    bg_page="#0A0A0B",
    bg_surface="#111114",
    bg_sunken="#17171B",
    bg_nav="#101012",
    border="#232329",
    border_strong="#6E6E7C",
    text="#FFFFFF",
    text_secondary="#D5D5DC",
    text_muted="#A0A0AC",
    accent="#FF8A5C",
    accent_2="#FF6B8A",
    accent_soft="#2A1810",
    on_accent="#15100C",
    success="#4ADE80",
    warning="#FBBF24",
    danger="#F87171",
    chart_bar="#FF8A5C",
    shadow="#000000",
    phase=("#2DD4BF", "#FB923C", "#A78BFA", "#FCD34D", "#F472B6", "#FB7185", "#38BDF8"),
)


# Modelled on symmetry.club, at Alex's request, from values sampled off the live
# site rather than eyeballed: page `#121212`, surfaces `#1A1A1A`, one blue
# accent `#3781FA` used at full strength for actions and at ~10-30% alpha for
# tints and borders, `#9CA3AF` for secondary text, hairline low-alpha borders,
# **no shadows at all**, and heavy rounding — pills and 24 px.
#
# TWO DELIBERATE DEVIATIONS, both because the source fails WCAG AA and this
# repo's `tests/test_theme.py` will not let it through:
#
#   * White on `#3781FA` is **3.70:1**. Button labels are 14 px bold, which is
#     not "large text", so the bar is 4.5. And there is no way to have both: to
#     read as text on a `#121212` page the accent needs luminance >= 0.2022, to
#     carry white it needs <= 0.1833. The ranges do not overlap. So `on_accent`
#     is near-black, exactly as `DARK` already does with its light orange.
#   * Their `#6B7280` body grey is **3.60:1** on a card. It is kept, but demoted
#     to `border_strong` (a 3:1 role), and the text greys move up one step to
#     `#D1D5DB` / `#9CA3AF`, which is where the site uses them most anyway.
#
# Worst text pair: 4.71:1.
SYMMETRY = Palette(
    name="symmetry",
    bg_page="#121212",
    bg_surface="#1A1A1A",
    bg_sunken="#0E0E0E",
    bg_nav="#121212",
    # gray-700 at 50% composited over the page — the site draws depth with
    # hairline borders and background tints instead of shadows.
    border="#242A32",
    border_strong="#6B7280",
    text="#FFFFFF",
    text_secondary="#D1D5DB",
    text_muted="#9CA3AF",
    accent="#3781FA",
    # A LIGHTER blue, not a deeper one, and the constraint decided it rather
    # than taste: `primary_button` paints a gradient between the two accents and
    # the label on top is near-black, so a darker second stop drops that label
    # to 3.70:1. This is one of the site's own blues (blue-400) and keeps the
    # button reading as flat rather than as a novelty gradient.
    accent_2="#60A5FA",
    # The accent at 10% over the page. 16% looked better and dropped the accent
    # sitting on it to 4.22:1.
    accent_soft="#161D29",
    on_accent="#04101F",
    success="#4ADE80",
    warning="#FBBF24",
    danger="#F87171",
    chart_bar="#3781FA",
    shadow="#000000",
    phase=("#2DD4BF", "#60A5FA", "#A78BFA", "#FCD34D", "#F472B6", "#FB7185", "#38BDF8"),
)


#: THE DEFAULT IS NOW DARK, and that reverses a decision this file used to
#: state the other way round ("this app is used in daylight, in a gym, on a
#: phone"). Alex asked for the look of symmetry.club, which is dark, and it is
#: his app. The daylight argument did not stop being true, so `LIGHT` is intact,
#: fully tested, and one tap away in Settings → Appearance.
DEFAULT_PALETTE = SYMMETRY


class _Proxy:
    """Reads through to the active palette.

    Views do `from theme import C` at import time; the attribute lookup happens
    at render time, so `set_palette()` takes effect without reimporting anything.
    """

    _p: Palette = DEFAULT_PALETTE

    def __getattr__(self, nombre: str):
        return getattr(_Proxy._p, nombre)

    @property
    def palette(self) -> Palette:
        return _Proxy._p


C = _Proxy()


def set_palette(paleta: Palette) -> None:
    _Proxy._p = paleta


#: Every palette the app can be set to, keyed by the name stored in
#: `preferencias`. Adding one here is all it takes to reach the Settings picker.
PALETTES: dict[str, Palette] = {}


def palette_for(name: str | None) -> Palette:
    """The stored choice, or the default. Never raises on a stale name."""
    return PALETTES.get((name or "").strip().lower(), DEFAULT_PALETTE)


def apply_theme(page: ft.Page, paleta: Palette | None = None) -> None:
    """Sets the palette AND the Material scheme.

    All three assignments are needed: without an explicit ColorScheme, Flet
    derives a tonal Material 3 palette from a seed colour and every dialog,
    text field and dropdown comes out in shades that do not match anything.
    """
    paleta = paleta or DEFAULT_PALETTE
    set_palette(paleta)
    page.theme_mode = ft.ThemeMode.LIGHT if paleta.name == "light" else ft.ThemeMode.DARK
    page.bgcolor = paleta.bg_page
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=paleta.accent,
            on_primary=paleta.on_accent,
            secondary=paleta.accent_2,
            on_secondary=paleta.on_accent,
            surface=paleta.bg_surface,
            on_surface=paleta.text,
            background=paleta.bg_page,
            on_background=paleta.text,
            error=paleta.danger,
            outline=paleta.border_strong,
        )
    )


class Space:
    x1, x2, x3, x4, x5, x6, x7 = 4, 8, 12, 16, 20, 24, 32


class Radius:
    """Corner radii, sized after symmetry.club: pills and 24 px do the work.

    Sampled from the live site: `9999px` was the most common value by far (32
    uses), then `24px` (21). Everything here moved up a step to match, which
    restyles all ten screens at once — no view sets a radius of its own, the
    same reason no view sets a colour.
    """

    sm, md, lg, xl, pill = 10, 14, 20, 24, 999


# ── widget factories ─────────────────────────────────────────
# Defaults are None and resolved inside the call: a default evaluated in the
# `def` would freeze the colour of whichever palette was active at import time.


def card(*controls, padding=16, margin=None, border_color=None, **kw) -> ft.Container:
    return ft.Container(
        content=ft.Column(list(controls), spacing=6, tight=True),
        bgcolor=kw.pop("bgcolor", C.bg_surface),
        border=ft.border.all(1, border_color or C.border),
        border_radius=kw.pop("border_radius", Radius.xl),
        padding=padding,
        margin=margin,
        **kw,
    )


def chip(text: str, color=None, bg=None, size=11) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=size, color=color or C.text_secondary),
        bgcolor=bg or C.bg_sunken,
        border_radius=Radius.pill,
        padding=ft.padding.symmetric(horizontal=8, vertical=4),
    )


def primary_button(
    text: str, on_click=None, expand=False, icon: str | None = None, **kw
) -> ft.Container:
    hijos: list[ft.Control] = []
    if icon:
        hijos.append(ft.Icon(icon, color=C.on_accent, size=16))
    hijos.append(ft.Text(text, color=C.on_accent, size=14, weight=ft.FontWeight.W_800))
    return ft.Container(
        content=ft.Row(hijos, alignment=ft.MainAxisAlignment.CENTER, spacing=6, tight=True),
        gradient=ft.LinearGradient(
            begin=ft.alignment.top_left,
            end=ft.alignment.bottom_right,
            colors=[C.accent, C.accent_2],
        ),
        border_radius=Radius.pill,
        padding=ft.padding.symmetric(horizontal=20, vertical=14),
        alignment=ft.alignment.center,
        on_click=on_click,
        expand=expand,
        ink=True,
        **kw,
    )


def ghost_button(text: str, on_click=None, expand=False, **kw) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            text,
            size=13,
            weight=ft.FontWeight.W_700,
            color=C.text_secondary,
            text_align=ft.TextAlign.CENTER,
        ),
        border=ft.border.all(1, C.border_strong),
        border_radius=Radius.pill,
        padding=ft.padding.symmetric(horizontal=18, vertical=12),
        alignment=ft.alignment.center,
        on_click=on_click,
        expand=expand,
        ink=True,
        **kw,
    )


def section_title(text: str) -> ft.Text:
    return ft.Text(text, size=16, weight=ft.FontWeight.W_700, color=C.text)


def muted_text(text: str, size=11) -> ft.Text:
    return ft.Text(text, size=size, color=C.text_muted)


# The migration those aliases existed for is done: every view now reads through
# `C`. They are gone on purpose rather than left as a courtesy — being module
# constants bound to LIGHT at import time, any view that imported one silently
# stopped following the active palette, which is how two dialogs ended up
# painting a white card in dark mode.


PALETTES.update({p.name: p for p in (SYMMETRY, LIGHT, DARK)})
