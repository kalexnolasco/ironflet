"""Food catalogue, servings and daily intake log.

Until now the app knew about energy only in the abstract: `health.py` computes a
BMR and a TDEE, `guides.py` explains what to eat. Nothing recorded what was
actually eaten. This module is that missing half.

Four tables, all on `storage.Base` so `Storage()` creates them together with the
training ones (and so the Telegram coach sees them once it declares the same
models in `../agente/entrenador/modelos.py`):

- `foods`             — the catalogue, everything per 100 g.
- `servings`          — named portions ("1 medium banana" = 120 g), because
                        nobody puts a banana on a scale.
- `food_log`          — what was actually eaten, with **frozen** macros.
- `nutrition_targets` — daily targets, versioned by start date.

Two decisions worth stating up front:

**Macros in `food_log` are frozen at insert time.** The row stores the kcal,
protein, fat, carbs and fibre of *that portion*, not a pointer to whatever the
catalogue says today. Correct the entry for chicken next month and Tuesday's
lunch keeps the numbers it was logged with. A diary is a record of what
happened, not a view that re-derives the past from present opinion — otherwise
a single typo fix silently rewrites every weekly average behind it. The cost is
denormalisation (the food name is copied in too, so an entry survives its food
being deleted); the benefit is that history is immutable and summing a day is a
plain `SUM`, no joins.

**Targets are versioned, not overwritten.** The plan says that if the waist
grows 1 cm the intake drops by 150 kcal, so targets change *during* the plan.
A single mutable row would make last month's adherence look wrong the moment
today's target moved. Each change is a new row keyed by the date it starts
applying; `targets_for(day)` picks the newest row that had already started.

Everything per 100 g follows the **European label convention**: `carbs` are
available carbohydrate with fibre *excluded* and listed separately. USDA tables
publish "carbohydrate, by difference", which includes fibre — subtract the fibre
before copying a USDA number in here or every carb total comes out ~10 % high.
"""

from __future__ import annotations

import os
import re
import weakref
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from storage import DEFAULT_URL, Base

# ── meals ────────────────────────────────────────────────────
# Five fixed slots. They are an ordered tuple, not a set: every report shows the
# day in eating order, and the DB stores the slug, never the label or the index.
MEALS: tuple[str, ...] = ("breakfast", "snack1", "lunch", "snack2", "dinner")

MEAL_LABELS: dict[str, str] = {
    "breakfast": "Breakfast",
    "snack1": "Mid-morning",
    "lunch": "Lunch",
    "snack2": "Afternoon snack",
    "dinner": "Dinner",
}

# Clock times from the plan. Handy for sorting a partially logged day and for
# the bot to know which meal it is nagging about.
MEAL_TIMES: dict[str, str] = {
    "breakfast": "06:45",
    "snack1": "10:30",
    "lunch": "13:00",
    "snack2": "17:00",
    "dinner": "20:30",
}


class UnknownMeal(ValueError):
    pass


class UnknownFood(ValueError):
    pass


def _check_meal(meal: str) -> str:
    if meal not in MEALS:
        raise UnknownMeal(f"{meal!r} is not one of {', '.join(MEALS)}")
    return meal


def _as_date(value: str | date | None) -> date:
    if value is None:
        return date.today()
    return date.fromisoformat(value) if isinstance(value, str) else value


def _now() -> datetime:
    return datetime.now().astimezone()


# ── models ───────────────────────────────────────────────────
class Food(Base):
    """A catalogue entry. All figures are per 100 g of raw, edible product.

    The primary key is a surrogate integer because `food_log` points at it and
    an integer FK is the cheap thing to index. The *natural* key is `slug`: a
    stable ASCII identifier chosen once and never translated. Seeding, the bot
    and any future import all match on the slug, so re-running the seed cannot
    duplicate "Chicken breast" just because someone renamed it.
    """

    __tablename__ = "foods"
    __table_args__ = (
        # Favourites first, then alphabetical — the exact order of the picker's
        # default listing, so it comes straight off the index.
        Index("ix_foods_favourite_name", "is_favourite", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    kcal: Mapped[float] = mapped_column(Float, default=0.0)
    protein: Mapped[float] = mapped_column(Float, default=0.0)
    fat: Mapped[float] = mapped_column(Float, default=0.0)
    carbs: Mapped[float] = mapped_column(Float, default=0.0)
    # Optional: plenty of labels simply do not print fibre, and 0.0 would be a
    # lie for meat and oil alike. None means "not known", 0.0 means "none".
    fiber: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_favourite: Mapped[bool] = mapped_column(Boolean, default=False)
    # Where the numbers came from. Kept in the row rather than in a comment so
    # a value can be audited three months from now without opening this file.
    source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Serving(Base):
    """A named portion of a food, expressed in grams.

    "1 medium banana" is 120 g. The point is that the log still stores grams —
    servings are an input convenience, never a second unit system. Nothing
    downstream has to know that servings exist.
    """

    __tablename__ = "servings"
    __table_args__ = (UniqueConstraint("food_id", "name", name="uq_serving_food_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    grams: Mapped[float] = mapped_column(Float)
    # The portion pre-selected in the picker. Not enforced as unique per food:
    # a bad seed would then fail at insert instead of just looking odd.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class FoodLogEntry(Base):
    """One intake: a food, a day, a meal, an amount — and its macros, frozen.

    `kcal`/`protein`/`fat`/`carbs`/`fiber` are the totals **for the grams eaten**,
    not per 100 g, so a day is one `SUM` with no arithmetic and no join. They are
    written once from the catalogue and never recomputed; see the module
    docstring for why.

    `food_id` goes NULL if the food is deleted, which is why `food_name` is
    copied in. An entry is meant to outlive its catalogue row.
    """

    __tablename__ = "food_log"
    __table_args__ = (
        # The hot query is "everything for this day", usually grouped by meal.
        # Date first: it is the selective column and the only one ever ranged.
        Index("ix_food_log_day_meal", "log_date", "meal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No index of its own: it leads ix_food_log_day_meal, which Postgres uses
    # for date-only lookups and ranges just as well. A second one would only
    # cost writes.
    log_date: Mapped[date] = mapped_column(Date)
    meal: Mapped[str] = mapped_column(String(20))
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("foods.id", ondelete="SET NULL"), nullable=True, index=True
    )
    food_name: Mapped[str] = mapped_column(String(120))
    grams: Mapped[float] = mapped_column(Float)
    kcal: Mapped[float] = mapped_column(Float, default=0.0)
    protein: Mapped[float] = mapped_column(Float, default=0.0)
    fat: Mapped[float] = mapped_column(Float, default=0.0)
    carbs: Mapped[float] = mapped_column(Float, default=0.0)
    fiber: Mapped[float] = mapped_column(Float, default=0.0)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NutritionTarget(Base):
    """Daily macro target, effective from `starts_on` until the next row.

    The date is the primary key: two targets cannot start the same day, and the
    newest row that has already started wins. Editing today's target is an
    upsert on today; cutting 150 kcal next Monday is an insert on Monday, and
    everything logged before it keeps being judged against the old numbers.
    """

    __tablename__ = "nutrition_targets"

    starts_on: Mapped[date] = mapped_column(Date, primary_key=True)
    kcal: Mapped[float] = mapped_column(Float)
    protein: Mapped[float] = mapped_column(Float)
    fat: Mapped[float] = mapped_column(Float)
    carbs: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── value object ─────────────────────────────────────────────
@dataclass(frozen=True)
class Macros:
    """An immutable macro bundle. Adds, scales and subtracts like a vector."""

    kcal: float = 0.0
    protein: float = 0.0
    fat: float = 0.0
    carbs: float = 0.0
    fiber: float = 0.0

    def __add__(self, other: Macros) -> Macros:
        return Macros(
            self.kcal + other.kcal,
            self.protein + other.protein,
            self.fat + other.fat,
            self.carbs + other.carbs,
            self.fiber + other.fiber,
        )

    def __sub__(self, other: Macros) -> Macros:
        return Macros(
            self.kcal - other.kcal,
            self.protein - other.protein,
            self.fat - other.fat,
            self.carbs - other.carbs,
            self.fiber - other.fiber,
        )

    def scaled(self, factor: float) -> Macros:
        return Macros(
            self.kcal * factor,
            self.protein * factor,
            self.fat * factor,
            self.carbs * factor,
            self.fiber * factor,
        )

    def rounded(self, digits: int = 1) -> Macros:
        return Macros(*(round(v, digits) for v in self.as_tuple()))

    def as_tuple(self) -> tuple[float, float, float, float, float]:
        return (self.kcal, self.protein, self.fat, self.carbs, self.fiber)

    def as_dict(self) -> dict[str, float]:
        return {
            "kcal": self.kcal,
            "protein": self.protein,
            "fat": self.fat,
            "carbs": self.carbs,
            "fiber": self.fiber,
        }

    @classmethod
    def sum(cls, items) -> Macros:
        total = cls()
        for item in items:
            total = total + item
        return total


# Alex's plan, section 4. Protein 115 g is a floor, not a ceiling.
PLAN_TARGET = Macros(kcal=2550.0, protein=115.0, fat=70.0, carbs=365.0)
PLAN_TARGET_NOTE = "Recomposition plan v1 — 2550 kcal, P115/F70/C365"
# The date the plan's targets start applying. `targets_for()` also falls back to
# the earliest row, so a day logged before this still gets sensible numbers.
PLAN_TARGET_START = date(2026, 8, 1)


# ── seed catalogue ───────────────────────────────────────────
@dataclass(frozen=True)
class _SeedFood:
    slug: str
    name: str
    kcal: float
    protein: float
    fat: float
    carbs: float
    fiber: float | None
    source: str
    servings: tuple[tuple[str, float, bool], ...] = ()


# The eighteen foods of the plan's template menu, per 100 g of raw edible
# product, carbs excluding fibre (EU label convention — see module docstring).
#
# Values are the rounded consensus of the two tables this household would check:
# USDA FoodData Central (SR Legacy / Foundation) for whole foods, and BEDCA
# (Base de Datos Española de Composición de Alimentos) plus typical Spanish
# retail labels for the processed ones, where the local product differs from the
# US one — semi-skimmed milk is 1.6 % fat here and 2 % there, deli turkey and
# skyr have no meaningful USDA equivalent. They are hardcoded on purpose: the
# brief rules out Open Food Facts and any other network lookup, because a food
# log that needs internet to add a banana is a food log nobody fills in.
#
# Sanity check on every row: Atwater (4/9/4 kcal per g of protein/fat/carb, plus
# 2 per g of fibre) reproduces the stated kcal within a few percent. The
# exceptions are physiological, not typos — walnuts come out ~5 % high because
# nut fat is not fully absorbed, and cooked-protein-per-raw-gram rows sit a few
# percent low. tests/test_nutrition.py enforces a 12 % band.
SEED_FOODS: tuple[_SeedFood, ...] = (
    _SeedFood(
        "oats",
        "Rolled oats",
        372.0,
        13.5,
        7.0,
        58.7,
        10.0,
        "USDA SR Legacy 20038 / EU label",
        (("1 bowl (80 g)", 80.0, True), ("1 tbsp (15 g)", 15.0, False)),
    ),
    _SeedFood(
        "milk_semi",
        "Semi-skimmed milk",
        46.0,
        3.2,
        1.6,
        4.7,
        0.0,
        "BEDCA / Spanish retail label, 1.6 % fat",
        # Milk is 1.032 g/ml, so 250 ml is 258 g. Ignoring density here would
        # under-count breakfast by ~4 kcal a day; keeping it costs nothing.
        (("1 glass (250 ml)", 258.0, True), ("1 splash (100 ml)", 103.0, False)),
    ),
    _SeedFood(
        "banana",
        "Banana",
        89.0,
        1.1,
        0.3,
        20.0,
        2.6,
        "USDA SR Legacy 09040, edible portion",
        (("1 medium banana", 120.0, True), ("1 large banana", 150.0, False)),
    ),
    _SeedFood(
        "walnuts",
        "Walnuts",
        654.0,
        15.2,
        65.2,
        7.0,
        6.7,
        "USDA SR Legacy 12155",
        (("1 handful (15 g)", 15.0, True), ("1 half", 3.0, False)),
    ),
    _SeedFood(
        "skyr",
        "Skyr / high-protein yoghurt",
        63.0,
        11.0,
        0.2,
        4.0,
        0.0,
        "Spanish retail label, 0 % fat skyr",
        (("1 tub (250 g)", 250.0, True), ("1 tub (150 g)", 150.0, False)),
    ),
    _SeedFood(
        "bread_wholemeal",
        "Wholemeal bread",
        247.0,
        9.5,
        3.5,
        41.0,
        6.5,
        "BEDCA / Spanish retail label",
        (("1 slice (35 g)", 35.0, True), ("2 slices (70 g)", 70.0, False)),
    ),
    _SeedFood(
        "turkey_breast",
        "Turkey breast, sliced",
        104.0,
        22.0,
        1.5,
        1.0,
        0.0,
        "Spanish retail label, >90 % turkey deli slices",
        (("1 slice (20 g)", 20.0, True), ("2 slices (40 g)", 40.0, False)),
    ),
    _SeedFood(
        "apple",
        "Apple",
        52.0,
        0.3,
        0.2,
        11.4,
        2.4,
        "USDA SR Legacy 09003, with skin",
        (("1 medium apple", 180.0, True),),
    ),
    _SeedFood(
        "rice_white",
        "White rice, dry",
        358.0,
        7.0,
        0.9,
        78.0,
        1.3,
        "USDA SR Legacy 20444, uncooked",
        (("1 portion (110 g dry)", 110.0, True), ("1 cup (185 g dry)", 185.0, False)),
    ),
    _SeedFood(
        "chicken_breast",
        "Chicken breast, raw",
        120.0,
        22.5,
        2.6,
        0.0,
        0.0,
        "USDA SR Legacy 05062, skinless raw",
        (("1 fillet (150 g)", 150.0, True),),
    ),
    _SeedFood(
        "olive_oil",
        "Olive oil",
        899.0,
        0.0,
        99.9,
        0.0,
        0.0,
        "USDA SR Legacy 04053",
        # 0.916 g/ml. A tablespoon is 15 ml = 13.7 g, not 15 g: taking the
        # volume for the mass over-counts a cooking day by ~25 kcal.
        (("1 tbsp (15 ml)", 13.7, True), ("1 tsp (5 ml)", 4.6, False)),
    ),
    _SeedFood(
        "whey_protein",
        "Whey protein powder",
        383.0,
        80.0,
        6.0,
        5.0,
        0.0,
        "Typical whey concentrate label (80 % protein)",
        (("1 scoop (30 g)", 30.0, True),),
    ),
    _SeedFood(
        "honey",
        "Honey",
        321.0,
        0.3,
        0.0,
        80.0,
        0.0,
        "EU nutrition label for honey",
        (("1 tbsp (15 g)", 15.0, True), ("1 tsp (7 g)", 7.0, False)),
    ),
    _SeedFood(
        "salmon",
        "Salmon, raw",
        208.0,
        20.4,
        13.4,
        0.0,
        0.0,
        "USDA SR Legacy 15236, Atlantic farmed",
        (("1 fillet (150 g)", 150.0, True),),
    ),
    _SeedFood(
        "potato",
        "Potato, raw",
        77.0,
        2.0,
        0.1,
        15.4,
        2.1,
        "USDA SR Legacy 11352, flesh and skin",
        (("1 medium potato (200 g)", 200.0, True),),
    ),
    _SeedFood(
        "egg",
        "Egg, whole",
        143.0,
        12.6,
        9.5,
        0.7,
        0.0,
        "USDA SR Legacy 01123, raw",
        # Grams are the edible portion: an M egg weighs ~60 g with shell, ~53 g
        # without. The plan's "4 huevos M" is 212 g of egg, not 240 g.
        (("1 medium egg (53 g)", 53.0, True), ("1 large egg (60 g)", 60.0, False)),
    ),
    _SeedFood(
        "tuna_canned",
        "Tuna, canned in water",
        116.0,
        25.5,
        0.8,
        0.0,
        0.0,
        "USDA SR Legacy 15121, drained",
        (("1 tin drained (52 g)", 52.0, True),),
    ),
    _SeedFood(
        "vegetables_mixed",
        "Mixed vegetables",
        28.0,
        2.0,
        0.3,
        3.5,
        2.2,
        "Mean of USDA courgette 11477, broccoli 11090, pepper 11333",
        (("1 serving (200 g)", 200.0, True), ("1 side salad (150 g)", 150.0, False)),
    ),
)

# The plan's template day (section 4 of ../plan_recomposicion.md), in grams of
# raw product. Quantities are the plan's, converted where it wrote millilitres.
# `menu_totals()` sums it; tests/test_nutrition.py pins the result.
TEMPLATE_DAY: tuple[tuple[str, str, float], ...] = (
    ("breakfast", "oats", 80.0),
    ("breakfast", "milk_semi", 258.0),  # 250 ml
    ("breakfast", "banana", 120.0),
    ("breakfast", "walnuts", 15.0),
    ("snack1", "skyr", 250.0),
    ("snack1", "apple", 180.0),
    ("snack1", "bread_wholemeal", 40.0),
    ("snack1", "turkey_breast", 40.0),
    ("lunch", "rice_white", 110.0),
    ("lunch", "chicken_breast", 150.0),
    ("lunch", "vegetables_mixed", 200.0),
    ("lunch", "olive_oil", 13.7),  # 15 ml
    ("snack2", "whey_protein", 30.0),
    ("snack2", "bread_wholemeal", 60.0),
    ("snack2", "honey", 15.0),
    ("dinner", "salmon", 150.0),
    ("dinner", "potato", 200.0),
    ("dinner", "vegetables_mixed", 150.0),  # large salad
    ("dinner", "olive_oil", 9.2),  # 10 ml
)

# The template summed with real food-table numbers lands at ~2668 kcal, about
# 4.6 % above the 2550 target — and the plan says so itself ("Suma real del menú:
# ≈ 2.600 kcal"). The plan also names the lever: if weight climbs faster than
# +0.3 kg/week, cut the dinner oil from 10 ml to 5 ml and drop the honey, never
# the protein. That trim is this variant, and it lands within ~1 % of 2550.
TEMPLATE_DAY_TRIMMED: tuple[tuple[str, str, float], ...] = tuple(
    (meal, slug, 4.6 if (meal == "dinner" and slug == "olive_oil") else grams)
    for meal, slug, grams in TEMPLATE_DAY
    if slug != "honey"
)

_SEED_BY_SLUG: dict[str, _SeedFood] = {f.slug: f for f in SEED_FOODS}


def macros_per_100g(seed: _SeedFood) -> Macros:
    return Macros(seed.kcal, seed.protein, seed.fat, seed.carbs, seed.fiber or 0.0)


def menu_totals(menu=TEMPLATE_DAY) -> Macros:
    """Sum the template menu straight from `SEED_FOODS`. No database needed.

    Deliberately independent of the ORM so the numbers can be checked (and were
    checked) before a single row existed.
    """
    return Macros.sum(
        macros_per_100g(_SEED_BY_SLUG[slug]).scaled(grams / 100.0) for _, slug, grams in menu
    )


def menu_totals_by_meal(menu=TEMPLATE_DAY) -> dict[str, Macros]:
    out = {meal: Macros() for meal in MEALS}
    for meal, slug, grams in menu:
        out[meal] = out[meal] + macros_per_100g(_SEED_BY_SLUG[slug]).scaled(grams / 100.0)
    return out


# ── the API ──────────────────────────────────────────────────
class Nutrition:
    """Nutrition persistence, deliberately separate from `Storage`.

    Same shape as `Storage` so views can hold both, but a different object: the
    training history and the food log share a database, not a lifecycle. Pass
    `engine=` to reuse the pool `Storage` already opened, or `db_url=` to open a
    second one (fine for tests and for the bot).
    """

    def __init__(self, db_url: str | None = None, engine=None):
        if engine is not None:
            self._engine = engine
            self.db_url = str(engine.url)
        else:
            self.db_url = db_url or os.environ.get("DATABASE_URL") or DEFAULT_URL
            self._engine = create_engine(self.db_url, pool_pre_ping=True)
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._init_db()

    def _init_db(self):
        # create_all touches every table registered on the shared Base, the
        # training ones included. That is idempotent and matches what Storage
        # already does, so the two can be constructed in either order.
        Base.metadata.create_all(self._engine)
        self.seed(overwrite=False)

    # ── seeding ──────────────────────────────────────────────
    def seed(self, *, overwrite: bool = False) -> dict:
        """Insert the plan's catalogue and targets. Idempotent.

        Matching is by slug. With `overwrite=False` (the default) an existing
        food is left exactly as it is — the user may have corrected it against
        the packet in their hand, and a later app start must not undo that.
        `overwrite=True` is the "reset the catalogue" button, and even then it
        never touches `food_log`: past entries carry their own frozen macros.
        """
        counts = {"foods": 0, "servings": 0, "targets": 0}
        with self._Session() as s:
            existing = {f.slug: f for f in s.scalars(select(Food))}
            for seed in SEED_FOODS:
                food = existing.get(seed.slug)
                if food is None:
                    food = Food(
                        slug=seed.slug,
                        name=seed.name,
                        kcal=seed.kcal,
                        protein=seed.protein,
                        fat=seed.fat,
                        carbs=seed.carbs,
                        fiber=seed.fiber,
                        is_favourite=False,
                        source=seed.source,
                        created=_now(),
                    )
                    s.add(food)
                    s.flush()  # need food.id for the servings below
                    counts["foods"] += 1
                elif overwrite:
                    food.name = seed.name
                    food.kcal, food.protein = seed.kcal, seed.protein
                    food.fat, food.carbs, food.fiber = seed.fat, seed.carbs, seed.fiber
                    food.source = seed.source
                    counts["foods"] += 1

                have = {
                    row.name for row in s.scalars(select(Serving).where(Serving.food_id == food.id))
                }
                for name, grams, is_default in seed.servings:
                    if name not in have:
                        s.add(
                            Serving(
                                food_id=food.id,
                                name=name,
                                grams=grams,
                                is_default=is_default,
                            )
                        )
                        counts["servings"] += 1

            if s.scalar(select(func.count()).select_from(NutritionTarget)) == 0:
                s.add(
                    NutritionTarget(
                        starts_on=PLAN_TARGET_START,
                        kcal=PLAN_TARGET.kcal,
                        protein=PLAN_TARGET.protein,
                        fat=PLAN_TARGET.fat,
                        carbs=PLAN_TARGET.carbs,
                        note=PLAN_TARGET_NOTE,
                        created=_now(),
                    )
                )
                counts["targets"] += 1
            s.commit()
        return counts

    # ── catalogue ────────────────────────────────────────────
    def get_food(self, ref: int | str) -> dict | None:
        with self._Session() as s:
            food = self._resolve(s, ref, required=False)
            return self._food_dict(s, food) if food else None

    def list_foods(self, *, favourites_first: bool = True) -> list[dict]:
        with self._Session() as s:
            stmt = select(Food)
            stmt = (
                stmt.order_by(Food.is_favourite.desc(), Food.name)
                if favourites_first
                else stmt.order_by(Food.name)
            )
            return [self._food_dict(s, f) for f in s.scalars(stmt)]

    def search_foods(self, query: str, limit: int = 20) -> list[dict]:
        """Case-insensitive substring match on the name, favourites first.

        `ilike '%x%'` cannot use a btree index, which is fine: the catalogue is
        tens of rows, not millions, and a sequential scan over it is faster than
        the trigram index that would be needed to avoid one. Revisit if the
        catalogue ever grows past a few thousand rows.
        """
        text = (query or "").strip()
        with self._Session() as s:
            stmt = select(Food)
            if text:
                stmt = stmt.where(Food.name.ilike(f"%{text}%"))
            stmt = stmt.order_by(Food.is_favourite.desc(), Food.name).limit(limit)
            return [self._food_dict(s, f) for f in s.scalars(stmt)]

    def frequent_foods(self, meal: str | None = None, days: int = 30, limit: int = 6) -> list[dict]:
        """Foods logged most often lately, optionally only in one meal.

        What the quick-add row falls back to before anything has been starred.
        Counts entries, not grams: "how often do I reach for this" is the
        question, and one 300 g portion is not three habits.
        """
        since = date.today() - timedelta(days=days)
        with self._Session() as s:
            stmt = (
                select(FoodLogEntry.food_id, func.count().label("n"))
                .where(FoodLogEntry.food_id.is_not(None), FoodLogEntry.log_date >= since)
                .group_by(FoodLogEntry.food_id)
                .order_by(func.count().desc())
                .limit(limit)
            )
            if meal:
                stmt = stmt.where(FoodLogEntry.meal == meal)
            ids = [row[0] for row in s.execute(stmt).all()]
            found = (
                {f.id: f for f in s.scalars(select(Food).where(Food.id.in_(ids)))} if ids else {}
            )
            # Re-order by frequency; the IN query comes back in table order.
            return [self._food_dict(s, found[i]) for i in ids if i in found]

    def add_food(
        self,
        slug: str,
        name: str,
        kcal: float,
        protein: float,
        fat: float,
        carbs: float,
        fiber: float | None = None,
        source: str | None = None,
        servings: tuple[tuple[str, float], ...] = (),
    ) -> int:
        with self._Session() as s:
            food = Food(
                slug=slug,
                name=name,
                kcal=float(kcal),
                protein=float(protein),
                fat=float(fat),
                carbs=float(carbs),
                fiber=None if fiber is None else float(fiber),
                is_favourite=False,
                source=source,
                created=_now(),
            )
            s.add(food)
            s.flush()
            for serving_name, grams in servings:
                s.add(Serving(food_id=food.id, name=serving_name, grams=float(grams)))
            s.commit()
            return food.id

    def update_food(self, ref: int | str, **fields) -> None:
        """Correct a catalogue entry. Past `food_log` rows are untouched."""
        allowed = {"name", "kcal", "protein", "fat", "carbs", "fiber", "source", "is_favourite"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown food fields: {', '.join(sorted(unknown))}")
        with self._Session() as s:
            food = self._resolve(s, ref)
            for key, value in fields.items():
                setattr(food, key, value)
            s.commit()

    def delete_food(self, ref: int | str) -> None:
        """Remove a catalogue entry. Its servings go with it; its log does not.

        The FK is ON DELETE SET NULL, and each entry kept a copy of the name, so
        the diary still reads correctly with the food gone.
        """
        with self._Session() as s:
            food = self._resolve(s, ref)
            s.delete(food)
            s.commit()

    def set_favourite(self, ref: int | str, value: bool = True) -> None:
        with self._Session() as s:
            self._resolve(s, ref).is_favourite = bool(value)
            s.commit()

    def toggle_favourite(self, ref: int | str) -> bool:
        with self._Session() as s:
            food = self._resolve(s, ref)
            food.is_favourite = not food.is_favourite
            s.commit()
            return food.is_favourite

    def favourites(self) -> list[dict]:
        with self._Session() as s:
            stmt = select(Food).where(Food.is_favourite.is_(True)).order_by(Food.name)
            return [self._food_dict(s, f) for f in s.scalars(stmt)]

    # ── servings ─────────────────────────────────────────────
    def add_serving(self, ref: int | str, name: str, grams: float, is_default: bool = False) -> int:
        with self._Session() as s:
            food = self._resolve(s, ref)
            row = Serving(
                food_id=food.id, name=name, grams=float(grams), is_default=bool(is_default)
            )
            s.add(row)
            s.commit()
            return row.id

    def servings_for(self, ref: int | str) -> list[dict]:
        with self._Session() as s:
            food = self._resolve(s, ref)
            return self._servings(s, food.id)

    # ── the log ──────────────────────────────────────────────
    def log_food(
        self,
        food: int | str,
        grams: float | None = None,
        *,
        meal: str = "breakfast",
        day: str | date | None = None,
        serving: str | None = None,
        quantity: float = 1.0,
    ) -> int:
        """Record an intake and freeze its macros.

        Amount comes either from `grams` or from `serving` × `quantity`; passing
        neither is an error, because a silent default of 100 g is the kind of
        thing that quietly ruins a week of data.
        """
        _check_meal(meal)
        when = _as_date(day)
        with self._Session() as s:
            row = self._resolve(s, food)
            amount = self._grams_for(s, row, grams, serving, quantity)
            frozen = self._macros_of(row).scaled(amount / 100.0)
            entry = FoodLogEntry(
                log_date=when,
                meal=meal,
                food_id=row.id,
                food_name=row.name,
                grams=amount,
                kcal=frozen.kcal,
                protein=frozen.protein,
                fat=frozen.fat,
                carbs=frozen.carbs,
                fiber=frozen.fiber,
                created=_now(),
            )
            s.add(entry)
            s.commit()
            return entry.id

    def delete_entry(self, entry_id: int) -> bool:
        with self._Session() as s:
            entry = s.get(FoodLogEntry, int(entry_id))
            if entry is None:
                return False
            s.delete(entry)
            s.commit()
            return True

    def update_entry_grams(self, entry_id: int, grams: float) -> bool:
        """Fix the amount without re-reading the catalogue.

        Macros are linear in grams, so the frozen values are rescaled from what
        the row already holds. Correcting "I ate 200 g not 150 g" therefore does
        not import today's possibly-different catalogue numbers into a past day.
        """
        with self._Session() as s:
            entry = s.get(FoodLogEntry, int(entry_id))
            if entry is None:
                return False
            if entry.grams <= 0:
                raise ValueError("cannot rescale an entry logged with 0 g")
            factor = float(grams) / entry.grams
            entry.kcal *= factor
            entry.protein *= factor
            entry.fat *= factor
            entry.carbs *= factor
            entry.fiber *= factor
            entry.grams = float(grams)
            s.commit()
            return True

    def clear_day(self, day: str | date | None = None) -> int:
        when = _as_date(day)
        with self._Session() as s:
            result = s.execute(delete(FoodLogEntry).where(FoodLogEntry.log_date == when))
            s.commit()
            return result.rowcount or 0

    def day_entries(self, day: str | date | None = None) -> list[dict]:
        when = _as_date(day)
        with self._Session() as s:
            rows = s.scalars(
                select(FoodLogEntry).where(FoodLogEntry.log_date == when).order_by(FoodLogEntry.id)
            )
            return [self._entry_dict(r) for r in rows]

    def meal_entries(self, meal: str, day: str | date | None = None) -> list[dict]:
        _check_meal(meal)
        return [e for e in self.day_entries(day) if e["meal"] == meal]

    # ── totals ───────────────────────────────────────────────
    def day_totals(self, day: str | date | None = None) -> Macros:
        when = _as_date(day)
        with self._Session() as s:
            row = s.execute(
                select(
                    func.coalesce(func.sum(FoodLogEntry.kcal), 0.0),
                    func.coalesce(func.sum(FoodLogEntry.protein), 0.0),
                    func.coalesce(func.sum(FoodLogEntry.fat), 0.0),
                    func.coalesce(func.sum(FoodLogEntry.carbs), 0.0),
                    func.coalesce(func.sum(FoodLogEntry.fiber), 0.0),
                ).where(FoodLogEntry.log_date == when)
            ).one()
        return Macros(*(float(v) for v in row))

    def day_totals_by_meal(self, day: str | date | None = None) -> dict[str, Macros]:
        """Per-meal totals, always all five keys, in eating order.

        Empty meals come back as a zero `Macros` rather than being absent: the
        day view renders five rows whether or not lunch was logged, and a caller
        that has to guard every lookup will eventually forget to.
        """
        when = _as_date(day)
        out: dict[str, Macros] = {meal: Macros() for meal in MEALS}
        with self._Session() as s:
            rows = s.execute(
                select(
                    FoodLogEntry.meal,
                    func.sum(FoodLogEntry.kcal),
                    func.sum(FoodLogEntry.protein),
                    func.sum(FoodLogEntry.fat),
                    func.sum(FoodLogEntry.carbs),
                    func.sum(FoodLogEntry.fiber),
                )
                .where(FoodLogEntry.log_date == when)
                .group_by(FoodLogEntry.meal)
            ).all()
        for meal, *values in rows:
            # A meal slug retired from MEALS would otherwise vanish from the
            # totals it still contributes to. Keep it visible.
            out[meal] = Macros(*(float(v or 0.0) for v in values))
        return out

    def range_totals(self, start: str | date, end: str | date | None = None) -> dict[str, Macros]:
        """Totals per day between two dates, inclusive. Days with no log are absent."""
        first, last = _as_date(start), _as_date(end)
        with self._Session() as s:
            rows = s.execute(
                select(
                    FoodLogEntry.log_date,
                    func.sum(FoodLogEntry.kcal),
                    func.sum(FoodLogEntry.protein),
                    func.sum(FoodLogEntry.fat),
                    func.sum(FoodLogEntry.carbs),
                    func.sum(FoodLogEntry.fiber),
                )
                .where(FoodLogEntry.log_date >= first, FoodLogEntry.log_date <= last)
                .group_by(FoodLogEntry.log_date)
                .order_by(FoodLogEntry.log_date)
            ).all()
        return {d.isoformat(): Macros(*(float(v or 0.0) for v in vals)) for d, *vals in rows}

    # ── targets ──────────────────────────────────────────────
    def set_targets(
        self,
        kcal: float,
        protein: float,
        fat: float,
        carbs: float,
        starts_on: str | date | None = None,
        note: str = "",
    ) -> date:
        when = _as_date(starts_on)
        with self._Session() as s:
            row = s.get(NutritionTarget, when)
            if row is None:
                row = NutritionTarget(starts_on=when, created=_now())
                s.add(row)
            row.kcal, row.protein = float(kcal), float(protein)
            row.fat, row.carbs = float(fat), float(carbs)
            row.note = note or None
            s.commit()
        return when

    def targets_for(self, day: str | date | None = None) -> dict | None:
        """The target in force on `day`: newest row with `starts_on <= day`.

        Falls back to the earliest row when `day` predates every version — a day
        logged before the plan started should be judged against the plan, not
        against nothing.
        """
        when = _as_date(day)
        with self._Session() as s:
            row = s.scalar(
                select(NutritionTarget)
                .where(NutritionTarget.starts_on <= when)
                .order_by(NutritionTarget.starts_on.desc())
                .limit(1)
            )
            if row is None:
                row = s.scalar(select(NutritionTarget).order_by(NutritionTarget.starts_on).limit(1))
            if row is None:
                return None
            return {
                "starts_on": row.starts_on.isoformat(),
                "macros": Macros(row.kcal, row.protein, row.fat, row.carbs),
                "note": row.note or "",
            }

    def target_history(self) -> list[dict]:
        with self._Session() as s:
            rows = s.scalars(select(NutritionTarget).order_by(NutritionTarget.starts_on))
            return [
                {
                    "starts_on": r.starts_on.isoformat(),
                    "macros": Macros(r.kcal, r.protein, r.fat, r.carbs),
                    "note": r.note or "",
                }
                for r in rows
            ]

    def compare_to_target(self, day: str | date | None = None) -> dict:
        """Consumed vs target for a day.

        `remaining` can go negative on purpose — "230 kcal over" is the number
        that changes behaviour, and clamping it at zero hides exactly the days
        worth looking at. `pct` is None-free only when a target exists.
        """
        when = _as_date(day)
        consumed = self.day_totals(when)
        target = self.targets_for(when)
        if target is None:
            return {
                "date": when.isoformat(),
                "consumed": consumed,
                "target": None,
                "remaining": None,
                "pct": {},
            }
        goal: Macros = target["macros"]
        pct = {
            key: (getattr(consumed, key) / getattr(goal, key) * 100.0)
            for key in ("kcal", "protein", "fat", "carbs")
            if getattr(goal, key)
        }
        # Fibre is left at 0: the plan sets no fibre target, and reporting
        # "-31 g of fibre remaining" would read as a deficit that does not exist.
        remaining = Macros(
            goal.kcal - consumed.kcal,
            goal.protein - consumed.protein,
            goal.fat - consumed.fat,
            goal.carbs - consumed.carbs,
        )
        return {
            "date": when.isoformat(),
            "consumed": consumed,
            "target": goal,
            "target_starts_on": target["starts_on"],
            "remaining": remaining,
            "pct": pct,
        }

    # ── bulk day operations ──────────────────────────────────
    def copy_day(
        self,
        source: str | date,
        target: str | date | None = None,
        *,
        replace_target: bool = False,
    ) -> int:
        """Re-log every entry of `source` onto `target`. Returns rows created.

        Macros are re-read from the catalogue, not copied from the source rows:
        this is a *new* intake happening today, so it is valued with what the
        catalogue says today. Only entries whose food has since been deleted
        fall back to their frozen numbers, rescaled.

        Appends by default; `replace_target=True` wipes the target day first.
        """
        src, dst = _as_date(source), _as_date(target)
        if src == dst:
            raise ValueError("source and target are the same day")
        with self._Session() as s:
            if replace_target:
                s.execute(delete(FoodLogEntry).where(FoodLogEntry.log_date == dst))
            rows = list(
                s.scalars(
                    select(FoodLogEntry)
                    .where(FoodLogEntry.log_date == src)
                    .order_by(FoodLogEntry.id)
                )
            )
            made = 0
            for old in rows:
                food = s.get(Food, old.food_id) if old.food_id else None
                if food is not None:
                    fresh = self._macros_of(food).scaled(old.grams / 100.0)
                    name = food.name
                else:
                    fresh = Macros(old.kcal, old.protein, old.fat, old.carbs, old.fiber)
                    name = old.food_name
                s.add(
                    FoodLogEntry(
                        log_date=dst,
                        meal=old.meal,
                        food_id=old.food_id,
                        food_name=name,
                        grams=old.grams,
                        kcal=fresh.kcal,
                        protein=fresh.protein,
                        fat=fresh.fat,
                        carbs=fresh.carbs,
                        fiber=fresh.fiber,
                        created=_now(),
                    )
                )
                made += 1
            s.commit()
            return made

    def copy_previous_day(self, day: str | date | None = None, **kw) -> int:
        """Copy yesterday onto `day`. The plan is a template; most days repeat."""
        when = _as_date(day)
        return self.copy_day(when - timedelta(days=1), when, **kw)

    def log_template_day(
        self, day: str | date | None = None, *, replace_target: bool = False
    ) -> int:
        """Log the plan's whole template menu onto a day. Returns rows created."""
        when = _as_date(day)
        if replace_target:
            self.clear_day(when)
        made = 0
        for meal, slug, grams in TEMPLATE_DAY:
            self.log_food(slug, grams, meal=meal, day=when)
            made += 1
        return made

    # ── internals ────────────────────────────────────────────
    @staticmethod
    def _macros_of(food: Food) -> Macros:
        return Macros(food.kcal, food.protein, food.fat, food.carbs, food.fiber or 0.0)

    @staticmethod
    def _resolve(session, ref: int | str, *, required: bool = True) -> Food | None:
        """Accept an id, a slug or a Food. Views hold slugs; the log holds ids."""
        if isinstance(ref, Food):
            return ref
        food = (
            session.get(Food, int(ref))
            if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit())
            else session.scalar(select(Food).where(Food.slug == ref))
        )
        if food is None and required:
            raise UnknownFood(f"no food matches {ref!r}")
        return food

    @staticmethod
    def _grams_for(session, food: Food, grams, serving, quantity) -> float:
        if grams is not None:
            return float(grams)
        if serving is None:
            raise ValueError("pass grams= or serving=; there is no sensible default amount")
        row = session.scalar(
            select(Serving).where(Serving.food_id == food.id, Serving.name == serving)
        )
        if row is None:
            raise ValueError(f"{food.name} has no serving named {serving!r}")
        return row.grams * float(quantity)

    @staticmethod
    def _servings(session, food_id: int) -> list[dict]:
        rows = session.scalars(
            select(Serving).where(Serving.food_id == food_id).order_by(Serving.grams)
        )
        return [
            {"id": r.id, "name": r.name, "grams": r.grams, "is_default": r.is_default} for r in rows
        ]

    @classmethod
    def _food_dict(cls, session, food: Food) -> dict:
        return {
            "id": food.id,
            "slug": food.slug,
            "name": food.name,
            "per_100g": cls._macros_of(food),
            "kcal": food.kcal,
            "protein": food.protein,
            "fat": food.fat,
            "carbs": food.carbs,
            "fiber": food.fiber,
            "is_favourite": food.is_favourite,
            "source": food.source or "",
            "servings": cls._servings(session, food.id),
        }

    @staticmethod
    def _entry_dict(entry: FoodLogEntry) -> dict:
        return {
            "id": entry.id,
            "date": entry.log_date.isoformat(),
            "meal": entry.meal,
            "food_id": entry.food_id,
            "food_name": entry.food_name,
            "grams": entry.grams,
            "macros": Macros(entry.kcal, entry.protein, entry.fat, entry.carbs, entry.fiber),
            "timestamp": entry.created.timestamp(),
        }


# ── the view-facing façade ───────────────────────────────────
# `views/nutrition_view.py` was written in parallel with this file, against an
# agreed contract rather than against the code: module-level functions taking
# the `Storage` as first argument, dates as ISO strings, and plain dicts of
# numbers in and out. The class above is the better shape for the bot and for
# tests; this layer is what the screen imports.
#
# It is a translation layer and nothing else — no rules live down here. Two
# translations it does perform, because only the caller's shape needs them:
#
#   * grams. The view speaks in portions ("1 medium banana"), the log speaks in
#     grams. A quick-add with no portion means one *default* serving, falling
#     back to 100 g for a food that has none.
#   * per-serving macros. A picker row shows what one portion costs, not what
#     100 g costs; nobody adds a spoon of olive oil thinking "899 kcal".


def _nutrition_for(store) -> Nutrition:
    """The `Nutrition` bound to whatever the caller is holding, cached.

    Accepts a `Nutrition` (returned as is), a `Storage` (reuses its engine, so
    the two share one connection pool), or None (falls back to DATABASE_URL).
    Cached weakly so a discarded Storage does not keep an engine alive.
    """
    if isinstance(store, Nutrition):
        return store
    cache = globals().setdefault("_NUT_CACHE", weakref.WeakKeyDictionary())
    try:
        cached = cache.get(store)
    except TypeError:  # unhashable stand-in (a MagicMock in a test, say)
        cached = None
        cache = None
    if cached is not None:
        return cached

    engine = getattr(store, "_engine", None)
    if engine is not None:
        made = Nutrition(engine=engine)
    else:
        made = Nutrition(getattr(store, "db_url", None))
    if cache is not None:
        cache[store] = made
    return made


# Matches the amount inside a hand-written portion label ("80 g", "1,5 ml").
_GRAMS_RE = re.compile(r"([\d]+(?:[.,]\d+)?)\s*(?:g|ml)\b", re.I)


def _round(value: float, digits: int = 1) -> float:
    return round(float(value or 0.0), digits)


def _default_serving(food: dict) -> dict | None:
    servings = food.get("servings") or []
    for row in servings:
        if row.get("is_default"):
            return row
    return servings[0] if servings else None


def _view_food(food: dict) -> dict:
    """A catalogue row in the shape the picker reads.

    Macros are for one default serving, not per 100 g — see the section note.
    `id` carries the slug rather than the integer key so the view can round-trip
    it through a widget without caring that the database has both.
    """
    serving = _default_serving(food)
    grams = float(serving["grams"]) if serving else 100.0
    per_serving = food["per_100g"].scaled(grams / 100.0)
    return {
        "id": food["slug"],
        "key": food["slug"],
        "name": food["name"],
        "serving": serving["name"] if serving else "100 g",
        "grams": grams,
        "kcal": _round(per_serving.kcal, 0),
        "protein": _round(per_serving.protein),
        "fat": _round(per_serving.fat),
        "carbs": _round(per_serving.carbs),
        "fiber": _round(per_serving.fiber),
        "is_favourite": food["is_favourite"],
        "portions": [
            {"label": row["name"], "grams": row["grams"]} for row in (food.get("servings") or [])
        ],
        "per_100g": food["per_100g"].as_dict(),
    }


def _view_entry(entry: dict) -> dict:
    macros: Macros = entry["macros"]
    return {
        "id": entry["id"],
        "meal": entry["meal"],
        "name": entry["food_name"],
        # The log stores grams, not the portion name that produced them, so the
        # caption is rebuilt from the amount. "150 g" is what the user weighed.
        "serving": f"{entry['grams']:g} g",
        "grams": entry["grams"],
        "kcal": _round(macros.kcal, 0),
        "protein": _round(macros.protein),
        "fat": _round(macros.fat),
        "carbs": _round(macros.carbs),
        "fiber": _round(macros.fiber),
    }


def _grams_from_portion(nut: Nutrition, food: dict, portion: str | None, qty: float) -> float:
    """Portion label × quantity → grams.

    The label normally comes straight from `portions`, so the lookup hits. The
    "80 g" fallback is for a label typed by hand or carried over from an older
    build; guessing 100 g instead would silently mis-log the entry.
    """
    servings = {row["name"]: row["grams"] for row in (food.get("servings") or [])}
    if portion and portion in servings:
        return servings[portion] * qty
    if portion:
        match = _GRAMS_RE.search(portion)
        if match:
            return float(match.group(1).replace(",", ".")) * qty
        raise ValueError(f"{food['name']} has no portion named {portion!r}")
    serving = _default_serving(food)
    return (float(serving["grams"]) if serving else 100.0) * qty


def _food_ref(food) -> str | int:
    """The view hands back whatever it was given: a dict, a slug or an id."""
    if isinstance(food, dict):
        ref = food.get("id") or food.get("key") or food.get("slug")
        if ref is None:
            raise UnknownFood(f"food dict without an id: {food!r}")
        return ref
    return food


def search_foods(store, query: str, limit: int = 25) -> list[dict]:
    return [_view_food(f) for f in _nutrition_for(store).search_foods(query, limit=limit)]


def favourite_foods(store, meal: str | None = None, limit: int = 6) -> list[dict]:
    """Quick-add candidates: starred first, then habit, then the plan's menu.

    An empty quick-add row on day one would be the worst possible first
    impression, so the tiers degrade instead of returning nothing. Order within
    a tier is meaningful; duplicates across tiers are dropped.
    """
    nut = _nutrition_for(store)
    picked: dict[str, dict] = {}
    for tier in (nut.favourites(), nut.frequent_foods(meal=meal, limit=limit), nut.list_foods()):
        for food in tier:
            if len(picked) >= limit:
                break
            picked.setdefault(food["slug"], food)
        if len(picked) >= limit:
            break
    return [_view_food(f) for f in list(picked.values())[:limit]]


def log_food(store, day, meal: str, food, qty: float = 1.0, portion: str | None = None) -> dict:
    """Log one portion. Returns the created entry in view shape."""
    nut = _nutrition_for(store)
    ref = _food_ref(food)
    full = nut.get_food(ref)
    if full is None:
        raise UnknownFood(f"no food matches {ref!r}")
    grams = _grams_from_portion(nut, full, portion, float(qty))
    entry_id = nut.log_food(full["id"], grams, meal=meal, day=day)
    return _view_entry(next(e for e in nut.day_entries(day) if e["id"] == entry_id))


def delete_entry(store, entry_id) -> bool:
    return _nutrition_for(store).delete_entry(int(entry_id))


def day_entries(store, day) -> list[dict]:
    return [_view_entry(e) for e in _nutrition_for(store).day_entries(day)]


def day_totals(store, day) -> dict:
    """Flat day totals plus `by_meal`, each block carrying its own `entries`.

    One call, everything the screen draws: the view renders five meal cards and
    a ring, and making it fetch entries separately would mean six round trips
    for one screen.
    """
    nut = _nutrition_for(store)
    total = nut.day_totals(day)
    entries = [_view_entry(e) for e in nut.day_entries(day)]
    by_meal_macros = nut.day_totals_by_meal(day)
    by_meal = {}
    for meal, macros in by_meal_macros.items():
        by_meal[meal] = {
            "kcal": _round(macros.kcal, 0),
            "protein": _round(macros.protein),
            "fat": _round(macros.fat),
            "carbs": _round(macros.carbs),
            "entries": [e for e in entries if e["meal"] == meal],
        }
    return {
        "kcal": _round(total.kcal, 0),
        "protein": _round(total.protein),
        "fat": _round(total.fat),
        "carbs": _round(total.carbs),
        "fiber": _round(total.fiber),
        "by_meal": by_meal,
    }


def targets_for(store, day) -> dict | None:
    """The day's target, flattened.

    Note the shape differs from `Nutrition.targets_for`, which returns the row
    (`starts_on`, `macros`, `note`). The view wants four numbers; the class
    keeps the provenance. Same name, same question, two audiences.
    """
    row = _nutrition_for(store).targets_for(day)
    if row is None:
        return None
    macros: Macros = row["macros"]
    return {
        "kcal": macros.kcal,
        "protein": macros.protein,
        "fat": macros.fat,
        "carbs": macros.carbs,
        "starts_on": row["starts_on"],
        "note": row["note"],
    }


def copy_previous_day(store, day) -> int:
    return _nutrition_for(store).copy_previous_day(day)
