"""El esquema de las cuatro tablas de comida. **Solo el esquema.**

La nutrición salió de la app en 0.21 — Alex: «quítale la nutrición, es algo
complejo… solo gym». Se fueron la pantalla, el diario, los objetivos de macros,
la compra del sábado y las herramientas del coach que las leían: unas 3.900
líneas.

Lo que queda aquí son las **cuatro tablas**, y no por nostalgia. Están vivas en
la base de datos de quien ya usaba la app, con lo que haya apuntado dentro, y
`backup.py` las exporta y las importa. Borrar estas declaraciones habría hecho
dos cosas, las dos calladas: que una copia nueva dejara de llevarse esos datos,
y que restaurar una copia vieja fallara al encontrar claves que nadie sabe leer.

Así que el esquema se queda y la lógica se fue. No hay catálogo de alimentos,
ni raciones sembradas, ni `day_totals`, ni `targets_for`, ni facade: nada de eso
se lee ya desde ninguna pantalla. Si algún día vuelve la nutrición, vuelve sobre
estas tablas y con los datos intactos.
"""

from __future__ import annotations

from datetime import date, datetime

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
)
from sqlalchemy.orm import Mapped, mapped_column

from storage import Base

#: Las cinco comidas del día del plan retirado. `backup.py` valida contra esto
#: al importar, así que sigue siendo el vocabulario de `food_log.meal`.
MEALS: tuple[str, ...] = ("breakfast", "snack1", "lunch", "snack2", "dinner")


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
