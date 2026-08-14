"""Nutrition: the food diary.

Logging a meal has to cost fewer taps than skipping it, or the diary stops
being filled in by Wednesday. So the fast paths come first and the search box
last: the favourites strip logs into the meal the clock is nearest to in a
single tap, every meal card carries its own favourites, and an empty day can be
filled from yesterday with one button. Search is the fallback, not the default.

This file only draws. Everything it knows comes from `nutrition.py`, written
against a contract that pins down `day_totals` and `targets_for` and leaves the
rest to good faith — so every call into that module goes through the "nutrition
bridge" section below, optional arguments are offered rather than assumed (see
`_accepts`), and returned dicts are read with `.get`. One module changes, one
section here changes with it.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta

import flet as ft

from dates import day_name, month_name
from nutrition import (
    MEALS,
    copy_previous_day,
    day_totals,
    delete_entry,
    favourite_foods,
    log_food,
    search_foods,
    targets_for,
)
from storage import Storage
from theme import (
    C,
    Radius,
    Space,
    card,
    chip,
    ghost_button,
    muted_text,
    primary_button,
    section_title,
)

# Labels and clock hints come from the plan's five-meal menu (plan_recomposicion
# §4), so the screen reads like the sheet on the fridge. Unknown keys — should
# nutrition.MEALS ever grow a sixth — degrade to a title-cased label instead of
# raising.
MEAL_LABELS = {
    "breakfast": "Breakfast",
    "snack1": "Mid-morning",
    "lunch": "Lunch",
    "snack2": "Afternoon",
    "dinner": "Dinner",
}
MEAL_ICONS = {
    "breakfast": "🥣",
    "snack1": "🍎",
    "lunch": "🍚",
    "snack2": "🥤",
    "dinner": "🐟",
}
# Decimal hours, not strings: they are compared against the wall clock.
MEAL_HOURS = {"breakfast": 6.75, "snack1": 10.5, "lunch": 13.0, "snack2": 17.0, "dinner": 20.5}

# How early a meal may be picked as "the one being eaten now". Nobody opens the
# diary at 12:59 to log breakfast.
MEAL_LOOKAHEAD_H = 1.0

# (totals key, label, index into C.phase)
#
# The four macros need four colours that stay apart. The palette's only
# guaranteed-distinct set is `phase`, whose hues the theme tests keep both
# mutually different and dark enough to carry white text — that is exactly the
# property a chart palette needs, and no hex may be written here.
MACROS = (("protein", "Protein", 0), ("fat", "Fat", 3), ("carbs", "Carbs", 2))

QUICK_ADD_MAX = 6
SEARCH_RESULTS_MAX = 25


# ── pure helpers (tested directly) ───────────────────────────


def bar_flex(current: float, target: float) -> tuple[int, int, int]:
    """Flex weights for (eaten, remaining, over), summing to 100.

    Flet has no width-percentage, so a bar is a Row of containers with integer
    `expand` weights. Past the target the whole bar still represents the target
    plus the overshoot, which keeps two bars at 110% and 200% visibly different
    instead of both being "full".
    """
    if target <= 0:
        return (0, 100, 0)
    ratio = current / target
    if ratio <= 0:
        return (0, 100, 0)
    if ratio <= 1:
        eaten = int(round(ratio * 100))
        return (eaten, 100 - eaten, 0)
    within = max(1, int(round(100 / ratio)))
    return (within, 0, 100 - within)


def meal_for_hour(hour: float, meals: list[str] | tuple[str, ...] = tuple(MEALS)) -> str:
    """The meal a tap should default to at this time of day."""
    chosen = meals[0] if meals else ""
    for key in meals:
        start = MEAL_HOURS.get(key)
        if start is not None and start <= hour + MEAL_LOOKAHEAD_H:
            chosen = key
    return chosen


def meal_label(key: str) -> str:
    return MEAL_LABELS.get(key) or key.replace("_", " ").title()


def meal_icon(key: str) -> str:
    return MEAL_ICONS.get(key, "🍽")


def meal_time_hint(key: str) -> str:
    hour = MEAL_HOURS.get(key)
    if hour is None:
        return ""
    h, m = int(hour), int(round((hour - int(hour)) * 60))
    return f"{h:02d}:{m:02d}"


def _n(value, decimals: int = 0) -> str:
    """Thousands-separated number; the diary is full of 2,550s."""
    try:
        return f"{float(value or 0):,.{decimals}f}"
    except (TypeError, ValueError):
        return "0"


def _accepts(fn, name: str) -> bool:
    """True when `fn` declares a parameter called `name`, or takes **kwargs.

    nutrition.py is written by another pair of hands against a contract that
    spells out two signatures out of eight. Optional arguments are therefore
    offered, not assumed: a `log_food` without `portion` gets called without it
    rather than raising TypeError under the user's finger.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # builtins, C functions, mocks
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _entry_id(value):
    """The id of whatever `log_food` handed back, or None if it said nothing."""
    if isinstance(value, dict):
        return value.get("id")
    if isinstance(value, (int, str)):
        return value
    return getattr(value, "id", None)


class NutritionView:
    def __init__(self, page: ft.Page, store: Storage):
        self.page = page
        self.store = store
        self.day: date = date.today()
        # Open the meal that is due; the other four stay folded with just their
        # subtotal, which is what makes five meals fit on one phone screen.
        self.expanded: set[str] = {meal_for_hour(self._now_hour())}

        # Search sheet state. It survives a rebuild because logging from the
        # sheet refreshes the page behind it and leaves it open.
        self._dialog: ft.AlertDialog | None = None
        self._search_meal: str = ""
        self._query: str = ""
        self._portions_open: str | None = None
        self._results: ft.Column | None = None

    # ── view contract ────────────────────────────────────────
    def on_show(self):
        """Deliberately empty.

        `refresh_current()` routes through `navigate_to`, which calls `on_show`
        on *every* redraw — so anything resetting state here (snapping back to
        today, for one) would undo the user's own tap a frame later.
        """

    def handle_back(self) -> bool:
        if self._dialog is not None:
            self._close_dialog()
            return True
        if self.day != date.today():
            self.day = date.today()
            self._refresh()
            return True
        return False

    def build(self) -> ft.Control:
        totals = self._day_totals()
        targets = self._targets()
        entries_by_meal = {m: self._meal_entries(totals, m) for m in MEALS}
        empty = not any(entries_by_meal.values())

        blocks: list[ft.Control] = [
            self._day_header(),
            ft.Container(height=Space.x3),
            self._macros_card(totals, targets),
            ft.Container(height=Space.x4),
        ]
        if empty:
            blocks += [self._empty_state(targets), ft.Container(height=Space.x4)]
        else:
            blocks += [self._quick_add(), ft.Container(height=Space.x4)]

        blocks.append(section_title("Meals"))
        blocks.append(ft.Container(height=Space.x2))
        blocks += [self._meal_card(m, totals, entries_by_meal[m]) for m in MEALS]
        blocks.append(ft.Container(height=Space.x4))

        return ft.Column(
            blocks,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
            spacing=0,
            tight=True,
        )

    # ── nutrition bridge ─────────────────────────────────────
    # Every call into nutrition.py lives here. Dates travel as ISO strings, the
    # convention the rest of the app already uses (`WorkoutEntry.date`,
    # `save_weight(date_iso=...)`).

    def _day_arg(self) -> str:
        return self.day.isoformat()

    def _day_totals(self) -> dict:
        return day_totals(self.store, self._day_arg()) or {}

    def _targets(self) -> dict:
        return targets_for(self.store, self._day_arg()) or {}

    def _meal_entries(self, totals: dict, meal: str) -> list[dict]:
        """The lines shown under a meal.

        The contract only promises `by_meal[meal]` is a dict of numbers, so the
        entries are looked for inside it first and fetched from the optional
        `nutrition.day_entries(store, date)` otherwise. If neither exists the
        meal renders as empty rather than failing.
        """
        block = (totals.get("by_meal") or {}).get(meal) or {}
        entries = block.get("entries")
        if entries is not None:
            return list(entries)
        return [e for e in self._all_entries() if e.get("meal") == meal]

    def _all_entries(self) -> list[dict]:
        try:
            from nutrition import day_entries
        except ImportError:
            return []
        return list(day_entries(self.store, self._day_arg()) or [])

    def _favourites(self, meal: str | None = None, limit: int = QUICK_ADD_MAX) -> list[dict]:
        kw = {}
        if meal and _accepts(favourite_foods, "meal"):
            kw["meal"] = meal
        if _accepts(favourite_foods, "limit"):
            kw["limit"] = limit
        return list(favourite_foods(self.store, **kw) or [])[:limit]

    def _search(self, query: str) -> list[dict]:
        kw = {}
        if _accepts(search_foods, "limit"):
            kw["limit"] = SEARCH_RESULTS_MAX
        return list(search_foods(self.store, query, **kw) or [])[:SEARCH_RESULTS_MAX]

    def _log(self, meal: str, food: dict, portion: str | None = None, qty: float = 1.0):
        kw = {}
        if portion and _accepts(log_food, "portion"):
            kw["portion"] = portion
        if qty != 1.0 and _accepts(log_food, "qty"):
            kw["qty"] = qty
        saved = log_food(self.store, self._day_arg(), meal, food, **kw)
        name = (food or {}).get("name") or "Food"
        self._toast(f"{name} → {meal_label(meal)}", undo_id=_entry_id(saved))
        self._portions_open = None
        self._refresh()

    def _delete(self, entry_id):
        delete_entry(self.store, entry_id)
        self._refresh()

    def _copy_yesterday(self, _=None):
        copied = copy_previous_day(self.store, self._day_arg())
        count = copied if isinstance(copied, int) else len(copied or [])
        self._toast(f"Copied {count} items from yesterday" if count else "Yesterday was empty too")
        self._refresh()

    # ── plumbing ─────────────────────────────────────────────
    def _refresh(self):
        self.page.data["refresh_current"]()

    def _now_hour(self) -> float:
        now = datetime.now()
        return now.hour + now.minute / 60

    def _toast(self, message: str, undo_id=None):
        bar = ft.SnackBar(
            content=ft.Text(message, size=12, color=C.text),
            bgcolor=C.bg_surface,
        )
        if undo_id is not None:
            bar.action = "Undo"
            bar.action_color = C.accent
            bar.on_action = lambda _, i=undo_id: self._delete(i)
        self.page.open(bar)

    def _shift_day(self, days: int):
        target = self.day + timedelta(days=days)
        # Forward stops at today: there is nothing to log in the future, and a
        # date that drifts past it makes "Today" unreachable by tapping.
        if target > date.today():
            return
        self.day = target
        self._refresh()

    def _toggle_meal(self, meal: str):
        self.expanded.symmetric_difference_update({meal})
        self._refresh()

    # ── day header ───────────────────────────────────────────
    def _day_title(self) -> str:
        today = date.today()
        if self.day == today:
            return "Today"
        if self.day == today - timedelta(days=1):
            return "Yesterday"
        return self._full_date()

    def _full_date(self) -> str:
        return f"{day_name(self.day.weekday())}, {self.day.day} {month_name(self.day.month - 1)}"

    def _day_subtitle(self) -> str:
        gap = (date.today() - self.day).days
        return self._full_date() if gap <= 1 else f"{gap} days ago"

    def _arrow(self, icon: str, days: int, enabled: bool) -> ft.Control:
        return ft.Container(
            content=ft.Icon(icon, size=18, color=C.accent if enabled else C.border),
            width=36,
            height=36,
            alignment=ft.alignment.center,
            bgcolor=C.bg_surface,
            border=ft.border.all(1, C.border),
            border_radius=Radius.md,
            on_click=(lambda _: self._shift_day(days)) if enabled else None,
            ink=enabled,
        )

    def _day_header(self) -> ft.Control:
        return ft.Row(
            [
                self._arrow(ft.Icons.CHEVRON_LEFT, -1, True),
                ft.Column(
                    [
                        ft.Text(
                            self._day_title(),
                            size=20,
                            weight=ft.FontWeight.W_900,
                            color=C.text,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            self._day_subtitle(),
                            size=11,
                            color=C.text_muted,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    spacing=1,
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._arrow(ft.Icons.CHEVRON_RIGHT, 1, self.day < date.today()),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # ── macro summary ────────────────────────────────────────
    def _bar(self, current: float, target: float, color: str) -> ft.Control:
        eaten, rest, over = bar_flex(current, target)
        segments: list[ft.Control] = []
        if eaten:
            segments.append(ft.Container(bgcolor=color, expand=eaten))
        if rest:
            segments.append(ft.Container(bgcolor=C.bg_sunken, expand=rest))
        if over:
            segments.append(ft.Container(bgcolor=C.danger, expand=over))
        return ft.Container(
            content=ft.Row(segments, spacing=0),
            height=8,
            bgcolor=C.bg_sunken,
            border_radius=Radius.pill,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    def _macro_row(self, key: str, label: str, phase_idx: int, totals: dict, targets: dict):
        current = float(totals.get(key) or 0)
        target = float(targets.get(key) or 0)
        left = target - current
        if left >= 0:
            remaining = ft.Text(f"{_n(left)} left", size=10, color=C.text_muted)
        else:
            remaining = ft.Text(
                f"{_n(-left)} over", size=10, color=C.danger, weight=ft.FontWeight.W_700
            )
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(label, size=11, weight=ft.FontWeight.W_700, color=C.text_secondary),
                        ft.Row(
                            [
                                ft.Text(f"{_n(current)}/{_n(target)} g", size=11, color=C.text),
                                remaining,
                            ],
                            spacing=6,
                            tight=True,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                self._bar(current, target, C.phase[phase_idx % len(C.phase)]),
            ],
            spacing=3,
            tight=True,
        )

    def _kcal_ring(self, totals: dict, targets: dict) -> ft.Control:
        eaten = float(totals.get("kcal") or 0)
        target = float(targets.get("kcal") or 0)
        left = target - eaten
        ratio = (eaten / target) if target > 0 else 0.0
        over = left < 0
        ring_color = C.warning if over else C.accent
        size = 78

        centre = ft.Column(
            [
                ft.Text(
                    _n(abs(left)),
                    size=18,
                    weight=ft.FontWeight.W_900,
                    color=C.warning if over else C.text,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    "over" if over else "left",
                    size=9,
                    color=C.text_muted,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        return ft.Column(
            [
                ft.Stack(
                    [
                        ft.ProgressRing(
                            value=min(1.0, max(0.0, ratio)),
                            stroke_width=8,
                            color=ring_color,
                            bgcolor=C.bg_sunken,
                            width=size,
                            height=size,
                        ),
                        ft.Container(
                            content=centre,
                            width=size,
                            height=size,
                            alignment=ft.alignment.center,
                        ),
                    ],
                    width=size,
                    height=size,
                ),
                ft.Text(
                    f"{_n(eaten)} / {_n(target)}",
                    size=10,
                    color=C.text_muted,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        )

    def _macros_card(self, totals: dict, targets: dict) -> ft.Control:
        return card(
            ft.Row(
                [
                    self._kcal_ring(totals, targets),
                    ft.Column(
                        [self._macro_row(k, lbl, idx, totals, targets) for k, lbl, idx in MACROS],
                        spacing=Space.x2,
                        expand=True,
                        tight=True,
                    ),
                ],
                spacing=Space.x4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
        )

    # ── empty state ──────────────────────────────────────────
    def _empty_state(self, targets: dict) -> ft.Control:
        plan = (
            f"{_n(targets.get('kcal'))} kcal · "
            f"{_n(targets.get('protein'))}P / {_n(targets.get('fat'))}F / "
            f"{_n(targets.get('carbs'))}C"
        )
        viewing_today = self.day == date.today()
        return card(
            ft.Text("🍽", size=26, text_align=ft.TextAlign.CENTER),
            ft.Text(
                "Nothing logged yet",
                size=13,
                weight=ft.FontWeight.W_700,
                color=C.text,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                f"Today's plan: {plan}",
                size=11,
                color=C.text_muted,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Container(height=Space.x2),
            primary_button(
                "Copy yesterday",
                icon=ft.Icons.CONTENT_COPY,
                on_click=self._copy_yesterday,
                expand=True,
            )
            if viewing_today
            else ghost_button("Copy previous day", on_click=self._copy_yesterday, expand=True),
            ft.Container(height=Space.x1),
            ghost_button(
                "Search food",
                on_click=lambda _: self._open_search(meal_for_hour(self._now_hour())),
                expand=True,
            ),
            padding=18,
        )

    # ── quick add ────────────────────────────────────────────
    def _quick_add(self) -> ft.Control:
        target_meal = meal_for_hour(self._now_hour())
        favourites = self._favourites(target_meal)
        header = ft.Row(
            [
                section_title(f"Quick add · {meal_label(target_meal)}"),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.CONTENT_COPY, size=13, color=C.text_secondary),
                            ft.Text(
                                "Copy yesterday",
                                size=11,
                                weight=ft.FontWeight.W_700,
                                color=C.text_secondary,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=self._copy_yesterday,
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                    border=ft.border.all(1, C.border),
                    border_radius=Radius.sm,
                    ink=True,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        if not favourites:
            body: ft.Control = muted_text("Log a few foods and your regulars show up here.")
        else:
            body = ft.Row(
                [self._favourite_chip(f, target_meal) for f in favourites],
                wrap=True,
                spacing=6,
                run_spacing=6,
            )
        return ft.Column([header, ft.Container(height=Space.x2), body], spacing=0, tight=True)

    def _favourite_chip(self, food: dict, meal: str) -> ft.Control:
        name = food.get("name") or "?"
        serving = food.get("serving") or ""
        label = f"+ {name}" + (f" · {serving}" if serving else "")
        c = chip(label, color=C.accent, bg=C.accent_soft)
        c.on_click = lambda _, f=food, m=meal: self._log(m, f)
        c.ink = True
        c.tooltip = f"{_n(food.get('kcal'))} kcal → {meal_label(meal)}"
        return c

    # ── meal cards ───────────────────────────────────────────
    def _meal_card(self, meal: str, totals: dict, entries: list[dict]) -> ft.Control:
        block = (totals.get("by_meal") or {}).get(meal) or {}
        # `by_meal` is the authority on the subtotal; adding up the rows is only
        # for a nutrition.py that reports entries without per-meal sums.
        raw_kcal = block.get("kcal")
        if raw_kcal is None:
            raw_kcal = sum(float(e.get("kcal") or 0) for e in entries)
        kcal = float(raw_kcal or 0)
        is_open = meal in self.expanded

        subtitle = meal_time_hint(meal)
        if entries:
            subtitle = f"{subtitle} · {len(entries)} item{'s' if len(entries) != 1 else ''}"

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Text(meal_icon(meal), size=16),
                    ft.Column(
                        [
                            ft.Text(
                                meal_label(meal),
                                size=13,
                                weight=ft.FontWeight.W_700,
                                color=C.text,
                            ),
                            ft.Text(subtitle, size=10, color=C.text_muted),
                        ],
                        spacing=1,
                        expand=True,
                        tight=True,
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                _n(kcal) if (entries or kcal) else "—",
                                size=14,
                                weight=ft.FontWeight.W_800,
                                color=C.accent if (entries or kcal) else C.text_muted,
                            ),
                            ft.Text("kcal", size=9, color=C.text_muted),
                        ],
                        spacing=0,
                        horizontal_alignment=ft.CrossAxisAlignment.END,
                        tight=True,
                    ),
                    ft.Icon(
                        ft.Icons.KEYBOARD_ARROW_UP if is_open else ft.Icons.KEYBOARD_ARROW_DOWN,
                        size=18,
                        color=C.text_muted,
                    ),
                ],
                spacing=Space.x2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=lambda _, m=meal: self._toggle_meal(m),
            ink=True,
        )

        children: list[ft.Control] = [header]
        if is_open:
            children.append(ft.Container(height=Space.x2))
            children.append(ft.Divider(height=1, thickness=1, color=C.border))
            children.append(ft.Container(height=Space.x1))
            if entries:
                children += [self._entry_row(e) for e in entries]
                children.append(self._meal_macros(block, entries))
            else:
                children.append(muted_text("Nothing here yet"))
            favourites = self._favourites(meal, limit=4)
            if favourites:
                children.append(ft.Container(height=Space.x2))
                children.append(
                    ft.Row(
                        [self._favourite_chip(f, meal) for f in favourites],
                        wrap=True,
                        spacing=6,
                        run_spacing=6,
                    )
                )
            children.append(ft.Container(height=Space.x2))
            children.append(
                ghost_button(
                    "Add food",
                    on_click=lambda _, m=meal: self._open_search(m),
                    expand=True,
                )
            )

        return card(*children, padding=12, margin=ft.margin.only(bottom=6))

    def _meal_macros(self, block: dict, entries: list[dict]) -> ft.Control:
        def total(key: str) -> float:
            if block.get(key) is not None:
                return float(block.get(key) or 0)
            return sum(float(e.get(key) or 0) for e in entries)

        return ft.Container(
            content=ft.Text(
                f"P {_n(total('protein'))} · F {_n(total('fat'))} · C {_n(total('carbs'))}",
                size=10,
                color=C.text_muted,
                weight=ft.FontWeight.W_700,
            ),
            padding=ft.padding.only(top=2),
        )

    def _entry_row(self, entry: dict) -> ft.Control:
        entry_id = entry.get("id")
        caption_bits = []
        portion = entry.get("serving") or entry.get("portion")
        qty = entry.get("qty")
        if portion:
            caption_bits.append(str(portion))
        if qty not in (None, "", 1, 1.0):
            caption_bits.append(f"×{qty:g}" if isinstance(qty, (int, float)) else f"×{qty}")
        caption_bits.append(
            f"P{_n(entry.get('protein'))} F{_n(entry.get('fat'))} C{_n(entry.get('carbs'))}"
        )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(
                                entry.get("name") or "?",
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=C.text,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(" · ".join(caption_bits), size=10, color=C.text_muted),
                        ],
                        spacing=1,
                        expand=True,
                        tight=True,
                    ),
                    ft.Text(
                        _n(entry.get("kcal")),
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color=C.text_secondary,
                    ),
                    ft.Container(
                        content=ft.Icon(ft.Icons.CLOSE, size=14, color=C.text_muted),
                        width=28,
                        height=28,
                        alignment=ft.alignment.center,
                        border_radius=Radius.sm,
                        on_click=lambda _, i=entry_id: self._delete(i),
                        ink=True,
                        tooltip="Remove",
                    ),
                ],
                spacing=Space.x2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(vertical=3),
        )

    # ── search sheet ─────────────────────────────────────────
    def _open_search(self, meal: str):
        self._search_meal = meal
        self._query = ""
        self._portions_open = None

        field = ft.TextField(
            hint_text="Search food",
            autofocus=True,
            dense=True,
            bgcolor=C.bg_sunken,
            border_color=C.border,
            focused_border_color=C.accent,
            color=C.text,
            text_size=14,
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._on_query,
        )
        self._results = ft.Column([], spacing=0, scroll=ft.ScrollMode.AUTO, expand=True, tight=True)
        self._fill_results()

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=C.bg_surface,
            title=ft.Text(
                f"Add to {meal_label(meal)}",
                size=16,
                weight=ft.FontWeight.W_900,
                color=C.text,
            ),
            content=ft.Container(
                content=ft.Column(
                    [field, ft.Container(height=Space.x2), self._results],
                    spacing=0,
                    tight=False,
                ),
                width=340,
                height=420,
            ),
            actions=[
                ft.TextButton(
                    "Done",
                    on_click=lambda _: self._close_dialog(),
                    style=ft.ButtonStyle(color=C.accent),
                )
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            # Tapping outside also closes it, and `handle_back` must not then
            # swallow the next back press trying to close a dialog that is gone.
            on_dismiss=self._forget_dialog,
        )
        self._dialog = dlg
        self.page.open(dlg)

    def _forget_dialog(self, _=None):
        self._dialog = None
        self._results = None

    def _close_dialog(self):
        if self._dialog is not None:
            self.page.close(self._dialog)
        self._forget_dialog()

    def _on_query(self, e):
        self._query = e.control.value or ""
        self._portions_open = None
        self._fill_results()
        self.page.update()

    def _fill_results(self):
        """Repaints the result list in place — the sheet stays open while you add.

        Closing on every tap is what makes logging a five-item breakfast feel
        like work; here each tap logs, toasts, and leaves the list where it was.
        """
        if self._results is None:
            return
        query = self._query.strip()
        foods = self._search(query) if query else self._favourites(self._search_meal, limit=12)
        header = "Results" if query else "Favourites"

        rows: list[ft.Control] = [
            ft.Text(
                header.upper(),
                size=9,
                weight=ft.FontWeight.W_700,
                color=C.text_muted,
            ),
            ft.Container(height=Space.x1),
        ]
        if not foods:
            rows.append(
                ft.Text(
                    f'No match for "{query}"' if query else "No favourites yet",
                    size=12,
                    color=C.text_muted,
                )
            )
        else:
            rows += [self._food_row(f) for f in foods]
        self._results.controls = rows

    def _food_key(self, food: dict) -> str:
        return str(food.get("id") or food.get("key") or food.get("name") or "")

    def _food_row(self, food: dict) -> ft.Control:
        meal = self._search_meal
        portions = list(food.get("portions") or [])
        key = self._food_key(food)
        showing_portions = self._portions_open == key

        caption = " · ".join(
            bit
            for bit in (
                food.get("serving") or "",
                f"P{_n(food.get('protein'))} F{_n(food.get('fat'))} C{_n(food.get('carbs'))}",
            )
            if bit
        )

        def toggle_portions(_):
            self._portions_open = None if showing_portions else key
            self._fill_results()
            self.page.update()

        row = ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(
                                food.get("name") or "?",
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=C.text,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(caption, size=10, color=C.text_muted),
                        ],
                        spacing=1,
                        expand=True,
                        tight=True,
                    ),
                    ft.Text(
                        _n(food.get("kcal")),
                        size=12,
                        weight=ft.FontWeight.W_800,
                        color=C.accent,
                    ),
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.EXPAND_LESS if showing_portions else ft.Icons.TUNE,
                            size=15,
                            color=C.text_muted,
                        ),
                        width=28,
                        height=28,
                        alignment=ft.alignment.center,
                        border_radius=Radius.sm,
                        on_click=toggle_portions,
                        ink=True,
                        tooltip="Other portions",
                    )
                    if portions
                    else ft.Container(width=28),
                ],
                spacing=Space.x2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            # The row itself is the one-tap path: it logs the default serving.
            # The tune icon is the escape hatch for the other portions.
            on_click=lambda _, f=food: self._log(meal, f),
            ink=True,
            padding=ft.padding.symmetric(vertical=6, horizontal=4),
            border_radius=Radius.sm,
        )

        if not showing_portions:
            return row

        chips = []
        for portion in portions:
            label = portion.get("label") if isinstance(portion, dict) else str(portion)
            if not label:
                continue
            c = chip(label, color=C.accent, bg=C.accent_soft)
            c.on_click = lambda _, f=food, p=label: self._log(meal, f, portion=p)
            c.ink = True
            chips.append(c)
        return ft.Column(
            [
                row,
                ft.Container(
                    content=ft.Row(chips, wrap=True, spacing=6, run_spacing=6),
                    padding=ft.padding.only(left=4, bottom=8),
                ),
            ],
            spacing=0,
            tight=True,
        )
