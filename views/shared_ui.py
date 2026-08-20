"""The three things every screen needs and none of them should own.

Each one is here because it shipped broken more than once, in more than one
file, and a fix applied to a single call site did not stop the next one:

* **`plural()`** — "3 warm-up" and "Copied 1 items from yesterday" both reached
  the screen. Agreement is one line of code, which is exactly why it gets
  retyped by hand and why one of the copies is always wrong.

* **`dialog_width()` / `dialog_height()`** — every dialog in the app was pinned
  to 340 px because "the phone is 420 px wide". It is not: the APK runs at
  whatever the device reports and the web build at whatever the window is. On a
  narrower screen the pinned box clipped the text; on a wider one it wasted half
  the room. These read `page` at build time and clamp instead of guessing, and
  they fall back to the old numbers when the page cannot say — which is what
  keeps a dialog built by a test (or before the first frame) the size it was.

* **`db_error_card()`** — `views/data_view.py` already caught a dead database
  and said so. Everywhere else the exception came straight out of `build()` and
  the screen rendered as nothing at all. A blank screen in a gym is
  indistinguishable from a crash, and it does not say the obvious reassuring
  thing: the data is in Postgres, it is not lost, the phone just cannot reach it.

No colour is stored at module level — same rule as everywhere else, `C` is read
inside the call so the palette can change under it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from theme import C, Radius, Space, ghost_button

# ── plurals ──────────────────────────────────────────────────


def _count_str(count: float | int) -> str:
    """The number as it should read: `3`, `1.5`, `0` — never `3.0`."""
    if isinstance(count, float) and count.is_integer():
        return str(int(count))
    if isinstance(count, float):
        return f"{count:g}"
    return str(count)


def plural(count: float | int, singular: str, plural_form: str | None = None) -> str:
    """`1 set`, `3 sets`, `0 sets` — the number and its noun, agreed.

    Pass `plural_form` for anything English does not pluralise with a bare `s`
    (`plural(n, "entry", "entries")`). A fractional count is never singular:
    half a set is "0.5 sets", and only an exact 1 takes the singular.
    """
    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{_count_str(count)} {word}"


# ── dialog geometry ──────────────────────────────────────────

#: Room the window keeps for itself: the AlertDialog's own inset plus a margin
#: so the card never touches the screen edge.
DIALOG_MARGIN = 80
#: A 320 px phone still has to be readable, so the box never shrinks past this
#: even if it means the dialog touches the edges.
DIALOG_MIN_W = 280
#: Past ~560 px a line of 11 px text is too long to scan; a dialog on a desktop
#: window should stop growing, not stretch to 1400 px.
DIALOG_MAX_W = 560
#: What to assume when `page` cannot say — the phone the app was designed on.
#: These are the numbers that keep an untested/pre-first-frame dialog at the
#: 340 px it has always been.
FALLBACK_PAGE_W = 420
FALLBACK_PAGE_H = 780
#: Chrome above and below a dialog (title row, action row, status bar).
DIALOG_CHROME_H = 200
#: A dialog shorter than this is not worth scrolling; better to overflow the
#: window than to show three lines through a letterbox.
DIALOG_MIN_H = 240


def _finite(value: Any) -> float | None:
    """`value` as a usable positive number, or None.

    Deliberately paranoid: `page` is `ft.Page` in production, a `MagicMock` in
    tests, and a page whose first frame has not landed reports `None`. A
    MagicMock attribute is truthy and arithmetic on it silently returns another
    MagicMock, so a plain `page.width or 420` would hand a mock straight into a
    layout and fail somewhere unrelated.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")) or number <= 0:
        return None
    return number


def dialog_width(page: Any, minimum: int = DIALOG_MIN_W, maximum: int = DIALOG_MAX_W) -> float:
    """How wide a dialog's content box may be on *this* window."""
    available = _finite(getattr(page, "width", None)) or FALLBACK_PAGE_W
    return max(minimum, min(maximum, available - DIALOG_MARGIN))


def dialog_height(page: Any, preferred: float, minimum: int = DIALOG_MIN_H) -> float:
    """How tall a scrolling dialog body may be before the window runs out.

    A scrolling Column needs a bounded box, so this returns a number rather than
    None — but never a number taller than the window, which is how a 600 px
    dialog ended up with its Close button below the fold.
    """
    available = _finite(getattr(page, "height", None)) or FALLBACK_PAGE_H
    return max(minimum, min(preferred, available - DIALOG_CHROME_H))


# ── the database is down ─────────────────────────────────────

#: Exception module prefixes that mean "the database", not "this screen has a
#: bug". Matched on the module name rather than by importing SQLAlchemy so this
#: module stays a pure view helper — and so a driver swap does not need a code
#: change here to keep the message right.
_DB_MODULES = ("sqlalchemy", "psycopg", "asyncpg")


def is_db_error(exc: BaseException) -> bool:
    module = type(exc).__module__ or ""
    if any(module.startswith(prefix) for prefix in _DB_MODULES):
        return True
    # A dead container shows up as a plain socket error before any driver
    # exception wraps it.
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def describe_db_error(exc: BaseException) -> tuple[str, str]:
    """(headline, body) for a failure that reached a `build()`.

    Two different sentences on purpose. "Cannot reach the database" is a fact
    Alex can act on — the container is down, the phone is off the network — and
    it comes with the reassurance that matters: nothing he logged is gone. A
    non-database exception is a bug in the app, and saying "database" about it
    would send him to restart Postgres for no reason.
    """
    if is_db_error(exc):
        return (
            "Can't reach the database",
            "Your training and food are stored in the database, and it is not "
            "answering right now. Nothing you logged is lost — check that the "
            "server is up and try again.",
        )
    return (
        "This screen could not load",
        "Something went wrong building this screen. The details are below; your data is untouched.",
    )


def _technical_detail(exc: BaseException) -> str:
    """The exception, trimmed. Long enough to search for, short enough to read."""
    text = f"{type(exc).__name__}: {exc}".strip()
    return text if len(text) <= 220 else text[:217] + "…"


def db_error_card(exc: BaseException, on_retry: Callable[[], None] | None = None) -> ft.Control:
    """The card a screen renders instead of nothing when its data will not load.

    Modelled on `views/data_view.py`, which is the one screen that already got
    this right: say what happened in a sentence, keep the technical text but put
    it last and small, and offer the one action there is.
    """
    headline, body = describe_db_error(exc)
    children: list[ft.Control] = [
        ft.Row(
            [
                ft.Icon(ft.Icons.CLOUD_OFF, color=C.danger, size=20),
                ft.Text(headline, size=15, weight=ft.FontWeight.W_900, color=C.text, expand=True),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Container(height=Space.x1),
        ft.Text(body, size=12, color=C.text_secondary),
    ]
    if on_retry is not None:
        children += [
            ft.Container(height=Space.x2),
            ghost_button("Try again", on_click=lambda _: on_retry(), expand=True),
        ]
    children += [
        ft.Container(height=Space.x2),
        ft.Container(
            content=ft.Text(_technical_detail(exc), size=10, color=C.text_muted, selectable=True),
            bgcolor=C.bg_sunken,
            border_radius=Radius.sm,
            padding=8,
        ),
    ]
    return ft.Container(
        content=ft.Column(children, spacing=0, tight=True),
        bgcolor=C.bg_surface,
        border=ft.border.all(1, C.danger),
        border_radius=Radius.lg,
        padding=16,
    )


def db_error_screen(
    title: str, exc: BaseException, on_retry: Callable[[], None] | None = None
) -> ft.Control:
    """`db_error_card` as a whole screen, keeping the view's own heading.

    The heading stays so the failure reads as "this screen has no data" rather
    than "the app replaced itself", which is what a bare card floating on an
    empty page looks like.
    """
    return ft.Column(
        [
            ft.Text(title, size=22, weight=ft.FontWeight.W_900, color=C.text),
            ft.Container(height=Space.x4),
            db_error_card(exc, on_retry),
        ],
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        expand=True,
        spacing=0,
        tight=True,
    )
