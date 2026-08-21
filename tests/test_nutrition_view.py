"""The food diary is judged in taps, so that is what these tests count.

`views/nutrition_view.py` imports `nutrition.py`, which is written separately.
Every test here installs a fake `nutrition` module in `sys.modules` *before*
importing the view, so the screen is exercised against the contract it was
written to and not against whatever that module happens to contain today. The
fake is a real module with real functions — not a MagicMock — because the view
inspects signatures to decide which optional arguments it may pass.

No database is needed: the view never touches Storage, it only hands it through.
"""

from __future__ import annotations

import importlib
import inspect
import os
import re
import sys
import types
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import flet as ft
import pytest

MEALS = ["breakfast", "snack1", "lunch", "snack2", "dinner"]

FOODS = [
    {
        "id": "oats",
        "name": "Oats",
        "serving": "80 g",
        "kcal": 300,
        "protein": 11,
        "fat": 6,
        "carbs": 50,
        "portions": [{"label": "40 g"}, {"label": "120 g"}],
    },
    {
        "id": "skyr",
        "name": "Skyr",
        "serving": "250 g",
        "kcal": 160,
        "protein": 28,
        "fat": 1,
        "carbs": 10,
    },
    {
        "id": "chicken",
        "name": "Chicken breast",
        "serving": "150 g",
        "kcal": 248,
        "protein": 46,
        "fat": 5,
        "carbs": 0,
    },
]

MACRO_KEYS = ("kcal", "protein", "fat", "carbs")


class FakeNutrition:
    """A believable nutrition.py: keeps a day → entries dict in memory."""

    def __init__(self):
        self.by_day: dict[str, list[dict]] = {}
        self.logged: list[dict] = []
        self.deleted: list = []
        self.copied: list[str] = []
        self._next_id = 1

    # ── the contract ─────────────────────────────────────────
    def day_totals(self, store, day):
        entries = self.by_day.get(day, [])
        by_meal = {}
        for meal in MEALS:
            rows = [e for e in entries if e["meal"] == meal]
            block = {k: sum(float(r.get(k) or 0) for r in rows) for k in MACRO_KEYS}
            block["entries"] = rows
            by_meal[meal] = block
        totals = {k: sum(float(e.get(k) or 0) for e in entries) for k in MACRO_KEYS}
        totals["by_meal"] = by_meal
        return totals

    def targets_for(self, store, day):
        return {"kcal": 2550, "protein": 115, "fat": 70, "carbs": 365}

    def target_note(self, store, day=None):
        # El plan semanal del coach; None = sin nota, la vista pinta la línea
        # simple. Un test concreto lo sobreescribe para ver el desplegable.
        return None

    def log_food(self, store, day, meal, food, qty=1.0, portion=None):
        entry = {
            "id": self._next_id,
            "meal": meal,
            "name": food["name"],
            "serving": portion or food.get("serving"),
            "qty": qty,
            **{k: float(food.get(k) or 0) * qty for k in MACRO_KEYS},
        }
        self._next_id += 1
        self.by_day.setdefault(day, []).append(entry)
        self.logged.append({"day": day, "meal": meal, "food": food, "portion": portion, "qty": qty})
        return entry

    def delete_entry(self, store, entry_id):
        self.deleted.append(entry_id)
        for rows in self.by_day.values():
            rows[:] = [r for r in rows if r["id"] != entry_id]

    def search_foods(self, store, query, limit=25):
        q = (query or "").lower()
        return [f for f in FOODS if q in f["name"].lower()][:limit]

    def favourite_foods(self, store, meal=None, limit=6):
        return FOODS[:limit]

    def copy_previous_day(self, store, day):
        self.copied.append(day)
        return 4


def _fake_module(fake: FakeNutrition) -> types.ModuleType:
    mod = types.ModuleType("nutrition")
    mod.MEALS = MEALS
    for name in (
        "day_totals",
        "targets_for",
        "target_note",
        "log_food",
        "delete_entry",
        "search_foods",
        "favourite_foods",
        "copy_previous_day",
    ):
        setattr(mod, name, getattr(fake, name))
    return mod


@pytest.fixture
def nutrition_view(monkeypatch):
    """(fake nutrition, freshly imported view module) with the stub installed."""
    fake = FakeNutrition()
    monkeypatch.setitem(sys.modules, "nutrition", _fake_module(fake))
    # Force a re-import so the module-level `from nutrition import ...` binds to
    # the stub, and drop it again afterwards so no other test file inherits it.
    sys.modules.pop("views.nutrition_view", None)
    module = importlib.import_module("views.nutrition_view")
    try:
        yield fake, module
    finally:
        sys.modules.pop("views.nutrition_view", None)


@pytest.fixture
def view(nutrition_view):
    fake, module = nutrition_view
    page = MagicMock()
    refreshes = []
    page.data = {
        "refresh_current": lambda: refreshes.append(1),
        "navigate_to": lambda i, **k: None,
        "store": MagicMock(),
    }
    v = module.NutritionView(page, page.data["store"])
    v.test_refreshes = refreshes
    v.test_fake = fake
    v.test_module = module
    return v


# ── control-tree helpers ─────────────────────────────────────


def walk(control):
    """Every control in the subtree, once."""
    out, stack, seen = [], [control], set()
    while stack:
        c = stack.pop()
        if c is None or id(c) in seen:
            continue
        seen.add(id(c))
        out.append(c)
        for attr in ("controls", "actions"):
            kids = getattr(c, attr, None)
            if isinstance(kids, list):
                stack.extend(kids)
        for attr in ("content", "title"):
            kid = getattr(c, attr, None)
            if isinstance(kid, ft.Control):
                stack.append(kid)
    return out


def texts(control) -> list[str]:
    return [str(c.value) for c in walk(control) if isinstance(c, ft.Text) and c.value]


def joined(control) -> str:
    return " | ".join(texts(control))


def clickable_with(root, fragment: str):
    """The tightest clickable control whose subtree contains `fragment`."""
    hits = [
        c
        for c in walk(root)
        if getattr(c, "on_click", None) and any(fragment in t for t in texts(c))
    ]
    assert hits, f"no clickable containing {fragment!r} in: {joined(root)}"
    return min(hits, key=lambda c: len(texts(c)))


def clickable_with_tooltip(root, tooltip: str):
    hits = [c for c in walk(root) if getattr(c, "on_click", None) and c.tooltip == tooltip]
    assert hits, f"no clickable with tooltip {tooltip!r}"
    return hits[0]


def containers_with_icon(root, icon):
    return [
        c
        for c in walk(root)
        if isinstance(c, ft.Container)
        and any(isinstance(k, ft.Icon) and k.name == icon for k in walk(c))
    ]


# ── pure helpers ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        (0, 2550, (0, 100, 0)),
        (1275, 2550, (50, 50, 0)),
        (2550, 2550, (100, 0, 0)),
        (5100, 2550, (50, 0, 50)),  # double the target: half the bar is overshoot
        (100, 0, (0, 100, 0)),  # no target set — never divide by zero
    ],
)
def test_bar_flex(nutrition_view, current, target, expected):
    _, module = nutrition_view
    assert module.bar_flex(current, target) == expected


def test_bar_flex_always_sums_to_one_bar(nutrition_view):
    _, module = nutrition_view
    for current in (0, 1, 37, 114, 115, 200, 999):
        assert sum(module.bar_flex(current, 115)) == 100


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (5.0, "breakfast"),  # before anything: the day starts at breakfast
        (8.0, "breakfast"),
        (9.9, "snack1"),  # the lookahead lets you log just before eating
        (13.5, "lunch"),
        (18.0, "snack2"),
        (22.0, "dinner"),
    ],
)
def test_meal_for_hour(nutrition_view, hour, expected):
    _, module = nutrition_view
    assert module.meal_for_hour(hour) == expected


def test_meal_labels_survive_an_unknown_key(nutrition_view):
    """nutrition.MEALS is not ours; a sixth meal must not raise."""
    _, module = nutrition_view
    assert module.meal_label("second_dinner") == "Second Dinner"
    assert module.meal_icon("second_dinner")
    assert module.meal_time_hint("second_dinner") == ""


# ── the screen ───────────────────────────────────────────────


def test_view_contract(view):
    assert callable(view.build) and callable(view.on_show) and callable(view.handle_back)
    view.on_show()
    assert view.build() is not None


def _seed_yesterday(fake, food=FOODS[0]):
    """One entry on the day before today, so "copy yesterday" has a source."""
    fake.log_food(None, (date.today() - timedelta(days=1)).isoformat(), "lunch", food)


def test_empty_day_is_an_invitation_not_an_error(view):
    _seed_yesterday(view.test_fake)
    tree = view.build()
    blob = joined(tree)
    assert "Nada registrado todavía" in blob
    assert "Copiar ayer" in blob
    assert "2,550 kcal" in blob  # the plan is restated, so the day has a shape
    assert not re.search(r"error|failed|none", blob, re.I)


def test_empty_state_does_not_offer_a_copy_of_an_empty_yesterday(view):
    """Day one: yesterday is empty too, so copying it is a tap that does nothing.

    This was the primary action on a fresh install — the biggest button on the
    screen, wired to a no-op that toasted about itself. Search is the action
    that always works, so on this day search is the primary one.
    """
    blob = joined(view.build())
    assert "Nada registrado todavía" in blob
    assert "Copiar ayer" not in blob
    # And it says why, rather than silently dropping the button the reader saw
    # yesterday.
    assert "nada que copiar" in blob.lower()
    assert "Buscar alimento" in blob


def test_empty_state_names_the_day_it_would_copy_from(view):
    """Three days back, "yesterday" is not the day it reads from."""
    fake = view.test_fake
    view.day = date.today() - timedelta(days=3)
    fake.log_food(None, (view.day - timedelta(days=1)).isoformat(), "lunch", FOODS[0])
    blob = joined(view.build())
    assert "Copiar el día anterior" in blob
    assert "Copiar ayer" not in blob


def test_empty_state_does_not_invent_targets(view, monkeypatch):
    """No targets row means no plan, not a plan of zeroes.

    Nothing in this app writes `nutrition_targets` — they come from the coach's
    side of the shared database — so "not set yet" is an ordinary first-run
    state. It used to render as "Today's plan: 0 kcal · 0P / 0F / 0C", which is
    a plan nobody wrote.
    """
    monkeypatch.setattr(view.test_module, "targets_for", lambda *a, **k: None)
    blob = joined(view.build())
    assert "0 kcal ·" not in blob
    assert "Aún no hay objetivos diarios" in blob


def test_all_five_meals_are_always_listed(view):
    blob = joined(view.build())
    for label in ("Desayuno", "Media mañana", "Comida", "Merienda", "Cena"):
        assert label in blob


def test_macros_show_what_is_left(view):
    fake = view.test_fake
    fake.log_food(None, date.today().isoformat(), "lunch", FOODS[2])  # 248 kcal, 46P 5F 0C
    blob = joined(view.build())
    assert "2,302" in blob  # 2550 - 248 kcal left, in the ring
    assert "46/115 g" in blob and "quedan 69" in blob  # protein bar
    assert "248 / 2,550" in blob  # eaten / target caption


def test_going_over_target_is_flagged_not_hidden(view):
    fake = view.test_fake
    today = date.today().isoformat()
    for _ in range(20):
        fake.log_food(None, today, "dinner", FOODS[0])  # 20 × 50 g carbs = 1000 g
    blob = joined(view.build())
    assert "de más" in blob
    assert "635 de más" in blob  # carbs: 1000 eaten against a 365 target


def test_meal_subtotal_is_visible_while_collapsed(view):
    fake = view.test_fake
    fake.log_food(None, date.today().isoformat(), "dinner", FOODS[2])
    view.expanded = set()  # everything folded
    # An exact-match text, not a substring: "248 / 2,550" in the ring caption
    # would otherwise pass this test with every meal card broken.
    assert "248" in texts(view.build())


def test_expanding_a_meal_lists_its_entries(view):
    fake = view.test_fake
    fake.log_food(None, date.today().isoformat(), "lunch", FOODS[2])
    view.expanded = {"lunch"}
    labels = texts(view.build())
    # Exact matches: "+ Chicken breast · 150 g" is the favourites chip, a
    # different control that must not be mistaken for the logged row.
    assert "Chicken breast" in labels
    assert "150 g · P46 F5 C0" in labels


def test_quick_add_logs_in_one_tap(view):
    fake = view.test_fake
    fake.log_food(None, date.today().isoformat(), "breakfast", FOODS[1])  # day not empty
    tree = view.build()
    clickable_with(tree, "+ Oats").on_click(None)
    assert fake.logged[-1]["food"]["name"] == "Oats"
    assert fake.logged[-1]["meal"] in MEALS
    assert view.test_refreshes  # the screen redraws itself after logging


def test_removing_an_entry_calls_delete(view):
    fake = view.test_fake
    entry = fake.log_food(None, date.today().isoformat(), "lunch", FOODS[0])
    view.expanded = {"lunch"}
    clickable_with_tooltip(view.build(), "Quitar").on_click(None)
    assert fake.deleted == [entry["id"]]


def test_copy_yesterday_from_the_empty_state(view):
    _seed_yesterday(view.test_fake)
    clickable_with(view.build(), "Copiar ayer").on_click(None)
    assert view.test_fake.copied == [date.today().isoformat()]


def test_copy_yesterday_is_still_reachable_on_a_used_day(view):
    fake = view.test_fake
    fake.log_food(None, date.today().isoformat(), "lunch", FOODS[0])
    clickable_with(view.build(), "Copiar ayer").on_click(None)
    assert fake.copied


# ── day navigation ───────────────────────────────────────────


def test_day_navigation_moves_back_and_forward(view):
    today = date.today()
    containers_with_icon(view.build(), ft.Icons.CHEVRON_LEFT)[0].on_click(None)
    assert view.day == today - timedelta(days=1)
    assert "Ayer" in joined(view.build())

    containers_with_icon(view.build(), ft.Icons.CHEVRON_RIGHT)[0].on_click(None)
    assert view.day == today


def test_the_future_is_not_loggable(view):
    forward = containers_with_icon(view.build(), ft.Icons.CHEVRON_RIGHT)[0]
    assert forward.on_click is None, "the next-day arrow must be dead on today"


def test_totals_follow_the_selected_day(view):
    fake = view.test_fake
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    fake.log_food(None, yesterday, "lunch", FOODS[2])

    # Exact matches again: the favourites chips name every food on every day.
    assert "Chicken breast" not in texts(view.build())
    view.day = date.today() - timedelta(days=1)
    view.expanded = {"lunch"}
    assert "Chicken breast" in texts(view.build())


def test_back_returns_to_today_then_gives_up(view):
    view.day = date.today() - timedelta(days=3)
    assert view.handle_back() is True
    assert view.day == date.today()
    assert view.handle_back() is False  # main.py falls back to Home


def test_on_show_does_not_fight_the_user(view):
    """on_show runs on every refresh — it must not snap the day back."""
    view.day = date.today() - timedelta(days=2)
    view.on_show()
    assert view.day == date.today() - timedelta(days=2)


# ── search sheet ─────────────────────────────────────────────


def test_search_starts_on_favourites(view):
    view._open_search("lunch")
    assert view.page.open.called
    blob = joined(view._results)
    assert "FAVORITOS" in blob
    assert "Oats" in blob


def test_search_filters_and_logs_without_closing(view):
    fake = view.test_fake
    view._open_search("dinner")
    view._on_query(MagicMock(control=MagicMock(value="chick")))

    blob = joined(view._results)
    assert "Chicken breast" in blob and "Oats" not in blob

    clickable_with(view._results, "Chicken breast").on_click(None)
    assert fake.logged[-1]["meal"] == "dinner"
    assert view._dialog is not None, "the sheet stays open so a second item is one tap away"


def test_named_portions_instead_of_grams(view):
    fake = view.test_fake
    view._open_search("breakfast")
    # The tune icon opens the alternatives; the row itself logs the default.
    clickable_with_tooltip(view._results, "Otras raciones").on_click(None)
    clickable_with(view._results, "120 g").on_click(None)
    assert fake.logged[-1]["portion"] == "120 g"


def test_no_match_says_so_politely(view):
    view._open_search("lunch")
    view._on_query(MagicMock(control=MagicMock(value="zzz")))
    assert 'Nada que encaje con "zzz"' in joined(view._results)


def test_back_closes_the_sheet_first(view):
    view._open_search("lunch")
    assert view.handle_back() is True
    assert view._dialog is None
    assert view.page.close.called


# ── house rules ──────────────────────────────────────────────


def test_no_hardcoded_colours():
    """Colours come from theme.C; a hex here would dodge the contrast tests."""
    source = Path(__file__).resolve().parent.parent / "views" / "nutrition_view.py"
    offenders = re.findall(r"#[0-9A-Fa-f]{3,8}\b", source.read_text(encoding="utf-8"))
    assert not offenders, f"hardcoded colours: {offenders}"


def test_optional_arguments_are_offered_not_assumed_stub(nutrition_view):
    """A nutrition.py without `portion` must not crash under the user's finger."""
    fake, module = nutrition_view
    calls = []

    def log_food(store, day, meal, food):  # the minimal signature
        calls.append((meal, food["name"]))

    module.log_food = log_food
    page = MagicMock()
    page.data = {"refresh_current": lambda: None}
    v = module.NutritionView(page, MagicMock())
    v._log("lunch", FOODS[0], portion="120 g")
    assert calls == [("lunch", "Oats")]


# ── against the real nutrition.py ────────────────────────────
# The stub above proves the screen behaves; these prove the contract it was
# written to is the one the other half actually shipped. They need the database
# — the real module is SQLAlchemy all the way down — and skip without it.


def _test_db_url() -> str:
    from sqlalchemy.engine import make_url

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ.get("DATABASE_URL")
        if not base:
            pytest.skip("sin DATABASE_URL: no hay base de datos contra la que probar")
        url = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)
    return url


@pytest.fixture
def real_view():
    """The view bound to the real nutrition module, on a scratch day."""
    url = _test_db_url()
    import nutrition
    from storage import Storage

    store = Storage(url)
    # Import fresh so the module-level `from nutrition import ...` binds to the
    # real module and not to a stub left behind by the tests above.
    sys.modules.pop("views.nutrition_view", None)
    module = importlib.import_module("views.nutrition_view")

    page = MagicMock()
    page.data = {"refresh_current": lambda: None, "store": store}
    view = module.NutritionView(page, store)
    model = nutrition.Nutrition(url)
    model.clear_day(view.day)
    try:
        yield view, nutrition, store
    finally:
        model.clear_day(view.day)
        sys.modules.pop("views.nutrition_view", None)


def test_the_real_module_exports_the_contract():
    """Guards the seam between this screen and nutrition.py.

    Both were written at the same time against a written contract. If that
    façade ever drifts — a renamed argument, a method that stopped being
    module-level — this fails here instead of under the user's finger.
    """
    import nutrition

    signatures = {
        "day_totals": ["store", "day"],
        "targets_for": ["store", "day"],
        "search_foods": ["store", "query"],
        "favourite_foods": ["store"],
        "log_food": ["store", "day", "meal", "food"],
        "delete_entry": ["store", "entry_id"],
        "copy_previous_day": ["store", "day"],
    }
    for name, expected in signatures.items():
        fn = getattr(nutrition, name, None)
        assert callable(fn), f"nutrition.{name} is missing or not callable"
        params = list(inspect.signature(fn).parameters)
        assert params[: len(expected)] == expected, f"nutrition.{name}{tuple(params)}"
    assert list(nutrition.MEALS) == MEALS


def test_renders_a_real_logged_day(real_view):
    view, nutrition, store = real_view
    day = view.day.isoformat()
    entry = nutrition.log_food(store, day, "breakfast", {"id": "oats"})

    view.expanded = {"breakfast"}
    labels = texts(view.build())
    assert entry["name"] in labels
    assert entry["serving"] in " | ".join(labels)
    # The plan's target is seeded, so the ring has something to count down from.
    assert any("quedan" in t for t in labels)


def test_removing_a_real_entry_empties_the_day(real_view):
    view, nutrition, store = real_view
    day = view.day.isoformat()
    nutrition.log_food(store, day, "lunch", {"id": "chicken_breast"})
    view.expanded = {"lunch"}

    clickable_with_tooltip(view.build(), "Quitar").on_click(None)
    assert nutrition.day_totals(store, day)["kcal"] == 0


def test_a_real_portion_is_logged_by_name(real_view):
    view, nutrition, store = real_view
    day = view.day.isoformat()
    oats = next(f for f in nutrition.search_foods(store, "avena") if f["id"] == "oats")
    assert oats["portions"], "the picker needs named portions, not grams"
    # A portion that is *not* the default, so the assertion cannot pass by
    # accident when the tap falls through to the one-tap path.
    alt = next(p for p in oats["portions"] if p["grams"] != oats["grams"])

    view._open_search("breakfast")
    view._on_query(MagicMock(control=MagicMock(value="avena")))
    clickable_with_tooltip(view._results, "Otras raciones").on_click(None)
    clickable_with(view._results, alt["label"]).on_click(None)

    logged = nutrition.day_entries(store, day)
    assert len(logged) == 1
    assert logged[0]["grams"] == alt["grams"]
