"""Contrast is a correctness property, not taste.

The palette that shipped before this had label text at 1.94:1 against its card
background — the language toggle looked like an empty button because the letters
were there and unreadable. Nobody noticed until someone screenshotted the app.

These tests recompute every foreground/background pair against WCAG AA, so a
prettier shade cannot quietly drop below the line again.
"""

from __future__ import annotations

import pytest

from theme import DARK, LIGHT, Palette

# WCAG 2.1 AA
MIN_TEXTO = 4.5  # body text
MIN_GRANDE = 3.0  # 18pt+, or bold 14pt+, and UI component edges


def luminancia(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)

    def canal(v: str) -> float:
        x = int(v, 16) / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = canal(h[0:2]), canal(h[2:4]), canal(h[4:6])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = luminancia(a), luminancia(b)
    claro, oscuro = max(la, lb), min(la, lb)
    return (claro + 0.05) / (oscuro + 0.05)


def pares_de_texto(p: Palette) -> list[tuple[str, str, str, float]]:
    """(descripción, primer plano, fondo, mínimo exigido)."""
    pares = []
    for fondo_nombre, fondo in (
        ("page", p.bg_page),
        ("surface", p.bg_surface),
        ("sunken", p.bg_sunken),
        ("nav", p.bg_nav),
    ):
        for texto_nombre, texto, minimo in (
            ("text", p.text, MIN_TEXTO),
            ("text_secondary", p.text_secondary, MIN_TEXTO),
            ("text_muted", p.text_muted, MIN_TEXTO),
            ("accent", p.accent, MIN_TEXTO),
        ):
            pares.append((f"{texto_nombre} on {fondo_nombre}", texto, fondo, minimo))
    # Texto sobre relleno de color.
    pares.append(("on_accent on accent", p.on_accent, p.accent, MIN_TEXTO))
    pares.append(("on_accent on accent_2", p.on_accent, p.accent_2, MIN_TEXTO))
    pares.append(("accent on accent_soft", p.accent, p.accent_soft, MIN_TEXTO))
    # Semánticos sobre tarjeta.
    for nombre, color in (("success", p.success), ("warning", p.warning), ("danger", p.danger)):
        pares.append((f"{nombre} on surface", color, p.bg_surface, MIN_TEXTO))
    # Bordes interactivos y barras: umbral de componente.
    pares.append(("border_strong on surface", p.border_strong, p.bg_surface, MIN_GRANDE))
    pares.append(("chart_bar on surface", p.chart_bar, p.bg_surface, MIN_GRANDE))
    # Colores de fase: llevan texto on_accent encima.
    for i, fase in enumerate(p.phase, 1):
        pares.append((f"on_accent on phase {i}", p.on_accent, fase, MIN_TEXTO))
    return pares


@pytest.mark.parametrize("paleta", [LIGHT, DARK], ids=lambda p: p.name)
def test_todo_el_texto_cumple_aa(paleta):
    fallos = []
    for descripcion, fg, bg, minimo in pares_de_texto(paleta):
        ratio = contraste(fg, bg)
        if ratio < minimo:
            fallos.append(f"{descripcion}: {ratio:.2f}:1 (mínimo {minimo})")
    assert not fallos, f"{paleta.name} — {len(fallos)} pares ilegibles:\n" + "\n".join(fallos)


@pytest.mark.parametrize("paleta", [LIGHT, DARK], ids=lambda p: p.name)
def test_las_fases_se_distinguen_entre_si(paleta):
    """Siete fases del mismo naranja no sirven de nada como código de color."""
    assert len(paleta.phase) == 7
    for i, a in enumerate(paleta.phase):
        for b in paleta.phase[i + 1 :]:
            assert a != b, f"{paleta.name}: dos fases con el mismo color {a}"


def test_el_tema_claro_es_realmente_claro():
    assert luminancia(LIGHT.bg_page) > 0.7
    assert luminancia(LIGHT.text) < 0.1
    assert luminancia(DARK.bg_page) < 0.1


def test_el_proxy_sigue_a_la_paleta_activa():
    """Las vistas importan C una vez; cambiar de paleta debe alcanzarlas."""
    from theme import C, set_palette

    try:
        set_palette(LIGHT)
        assert C.bg_page == LIGHT.bg_page
        set_palette(DARK)
        assert C.bg_page == DARK.bg_page
    finally:
        set_palette(LIGHT)


def test_los_helpers_no_congelan_el_color_en_el_default():
    """`def card(border_color=BORDER)` evaluaría el color al importar."""
    import inspect

    from theme import card, chip

    for funcion in (card, chip):
        for nombre, parametro in inspect.signature(funcion).parameters.items():
            if nombre in ("border_color", "bg", "color"):
                assert parametro.default is None, (
                    f"{funcion.__name__}({nombre}=...) fija el color en el `def`: "
                    "se quedaría con la paleta que estuviera activa al importar"
                )
