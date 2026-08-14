"""Tests for the food catalogue, the intake log and the versioned targets.

Two halves. The pure ones (`Macros`, seed data, menu arithmetic) need nothing.
The rest need PostgreSQL and run against `entrenador_test`, never production —
the fixture drops and recreates the schema on every test.
"""

from __future__ import annotations

import dataclasses
import os
from datetime import date, timedelta

import pytest

import nutrition
from nutrition import (
    MEAL_LABELS,
    MEALS,
    PLAN_TARGET,
    SEED_FOODS,
    TEMPLATE_DAY,
    TEMPLATE_DAY_TRIMMED,
    Food,
    FoodLogEntry,
    Macros,
    Nutrition,
    NutritionTarget,
    Serving,
    UnknownFood,
    UnknownMeal,
    macros_per_100g,
    menu_totals,
    menu_totals_by_meal,
)
from storage import Base

TODAY = date(2026, 8, 13)
YESTERDAY = TODAY - timedelta(days=1)


def _test_url() -> str:
    """Same resolution as tests/test_smoke.py: TEST_DATABASE_URL, else
    DATABASE_URL redirected at `entrenador_test`. Never production."""
    from sqlalchemy.engine import make_url

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ.get("DATABASE_URL")
        if not base:
            pytest.skip("no DATABASE_URL: nothing to test against")
        # render_as_string, not str(): str() masks the password.
        url = make_url(base).set(database="entrenador_test").render_as_string(hide_password=False)
    if make_url(url).database == "entrenador":
        pytest.fail("refusing to run against the production database")
    return url


# One engine for the whole module. A fresh one per test leaked a connection
# pool per test and eventually starved Postgres.
@pytest.fixture(scope="module")
def engine():
    from sqlalchemy import create_engine

    eng = create_engine(_test_url())
    yield eng
    eng.dispose()


@pytest.fixture
def nut(engine):
    """Nutrition on the test database, with only the four nutrition tables wiped.

    Deliberately *not* `Base.metadata.drop_all()`. The training tables share
    that Base, and the bot's suite and this one run against the same
    `entrenador_test`: dropping everything makes each suite flake the other for
    reasons that look nothing like the real cause. TRUNCATE ... CASCADE empties
    exactly these four and resets the identity counters, which is all a test
    actually needs.
    """
    from sqlalchemy import text

    tables = [
        Food.__table__,
        Serving.__table__,
        FoodLogEntry.__table__,
        NutritionTarget.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE food_log, servings, nutrition_targets, foods RESTART IDENTITY CASCADE")
        )
    return Nutrition(engine=engine)


# ── pure: Macros ─────────────────────────────────────────────
def test_macros_add_and_scale():
    a = Macros(100, 10, 5, 8, 2)
    b = Macros(50, 5, 1, 4, 1)
    assert (a + b).as_tuple() == (150, 15, 6, 12, 3)
    assert (a - b).as_tuple() == (50, 5, 4, 4, 1)
    assert a.scaled(0.5).as_tuple() == (50, 5, 2.5, 4, 1)
    assert Macros.sum([a, b, a]).kcal == 250


def test_macros_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Macros(1, 2, 3, 4, 5).kcal = 9


# ── pure: the seed catalogue ─────────────────────────────────
def test_seed_has_the_eighteen_plan_foods():
    assert len(SEED_FOODS) == 18
    assert len({f.slug for f in SEED_FOODS}) == 18
    assert len({f.name for f in SEED_FOODS}) == 18


def test_every_seed_food_has_at_least_one_serving():
    for food in SEED_FOODS:
        assert food.servings, f"{food.slug} has no named serving"
        assert all(grams > 0 for _, grams, _ in food.servings)


def test_seed_kcal_agree_with_atwater():
    """4/9/4 per g of protein/fat/carb plus 2 per g of fibre, within 12 %.

    Not 1 %: published kcal are measured, not derived. Walnut fat is not fully
    absorbed (+5 %) and raw-meat rows sit a few percent low. A typo — a decimal
    point in the wrong place — blows straight past 12 %.
    """
    for food in SEED_FOODS:
        atwater = food.protein * 4 + food.fat * 9 + food.carbs * 4 + (food.fiber or 0) * 2
        assert food.kcal > 0
        deviation = abs(atwater / food.kcal - 1)
        assert deviation < 0.12, f"{food.slug}: listed {food.kcal}, Atwater {atwater:.1f}"


def test_seed_carbs_exclude_fibre():
    """EU convention. A USDA "carbohydrate by difference" copied in raw would
    make carbs + fibre exceed 100 g for high-fibre foods; this catches the
    sloppier version of the same mistake."""
    for food in SEED_FOODS:
        assert food.protein + food.fat + food.carbs + (food.fiber or 0) <= 100.0


# ── pure: the template menu ──────────────────────────────────
def test_menu_covers_all_five_meals():
    assert {meal for meal, _, _ in TEMPLATE_DAY} == set(MEALS)
    assert set(MEAL_LABELS) == set(MEALS)


def test_menu_sums_close_to_the_plan_target():
    """The plan's own stated sum is ≈2600 kcal, so ≈2550 is a target the menu
    approaches from above by design. Band is ±7 %."""
    total = menu_totals()
    assert abs(total.kcal / PLAN_TARGET.kcal - 1) < 0.07, f"{total.kcal:.0f} kcal"
    assert 2400 < total.kcal < 2750


def test_menu_clears_the_protein_floor():
    """P115 is a floor, not an equality. The plan says so out loud: "la proteína
    queda muy por encima del mínimo de 115 g […] no es un problema, es margen de
    seguridad". The menu delivers ~176 g."""
    total = menu_totals()
    assert total.protein >= PLAN_TARGET.protein
    assert 150 <= total.protein <= 195, f"{total.protein:.1f} g protein"


def test_menu_fat_matches_the_plan():
    total = menu_totals()
    assert abs(total.fat - PLAN_TARGET.fat) < 12, f"{total.fat:.1f} g fat"


def test_documented_trim_lands_on_target():
    """Dinner oil 10→5 ml and no honey: the plan's own adjustment, within 2 %."""
    trimmed = menu_totals(TEMPLATE_DAY_TRIMMED)
    assert abs(trimmed.kcal / PLAN_TARGET.kcal - 1) < 0.02, f"{trimmed.kcal:.0f} kcal"
    assert trimmed.protein >= PLAN_TARGET.protein


def test_menu_by_meal_sums_to_the_whole():
    by_meal = menu_totals_by_meal()
    assert round(sum(m.kcal for m in by_meal.values()), 3) == round(menu_totals().kcal, 3)
    for meal in MEALS:
        assert by_meal[meal].kcal > 0


# ── database: catalogue ──────────────────────────────────────
def test_seed_runs_on_construction(nut):
    foods = nut.list_foods()
    assert len(foods) == 18
    banana = nut.get_food("banana")
    assert banana["name"] == "Banana"
    assert banana["per_100g"].kcal == 89.0
    assert any(s["name"] == "1 medium banana" and s["grams"] == 120.0 for s in banana["servings"])


def test_seed_is_idempotent(nut):
    before = len(nut.list_foods())
    counts = nut.seed()
    assert counts == {"foods": 0, "servings": 0, "targets": 0}
    assert len(nut.list_foods()) == before


def test_seed_does_not_clobber_user_corrections(nut):
    nut.update_food("oats", kcal=350.0)
    nut.seed()  # default overwrite=False
    assert nut.get_food("oats")["kcal"] == 350.0
    nut.seed(overwrite=True)
    assert nut.get_food("oats")["kcal"] == 372.0


def test_search_by_name(nut):
    assert [f["slug"] for f in nut.search_foods("chick")] == ["chicken_breast"]
    assert {f["slug"] for f in nut.search_foods("BREAD")} == {"bread_wholemeal"}
    assert nut.search_foods("zzz") == []
    assert len(nut.search_foods("")) == 18


def test_search_puts_favourites_first(nut):
    nut.set_favourite("tuna_canned")
    results = nut.search_foods("")
    assert results[0]["slug"] == "tuna_canned"
    assert results[0]["is_favourite"] is True


def test_toggle_favourite(nut):
    assert nut.toggle_favourite("egg") is True
    assert [f["slug"] for f in nut.favourites()] == ["egg"]
    assert nut.toggle_favourite("egg") is False
    assert nut.favourites() == []


def test_unknown_food_raises(nut):
    with pytest.raises(UnknownFood):
        nut.log_food("unicorn", 100.0, meal="lunch", day=TODAY)


def test_add_custom_food(nut):
    nut.add_food(
        "kefir", "Kefir", 55.0, 3.3, 1.5, 4.5, fiber=0.0, servings=(("1 glass (300 ml)", 309.0),)
    )
    food = nut.get_food("kefir")
    assert food["per_100g"].protein == 3.3
    assert food["servings"][0]["grams"] == 309.0


# ── database: the log ────────────────────────────────────────
def test_log_by_grams_freezes_macros(nut):
    entry_id = nut.log_food("chicken_breast", 150.0, meal="lunch", day=TODAY)
    entry = nut.day_entries(TODAY)[0]
    assert entry["id"] == entry_id
    assert entry["food_name"] == "Chicken breast, raw"
    assert entry["grams"] == 150.0
    # 120 kcal / 22.5 g protein per 100 g × 1.5
    assert entry["macros"].kcal == pytest.approx(180.0)
    assert entry["macros"].protein == pytest.approx(33.75)


def test_log_by_serving(nut):
    nut.log_food("banana", meal="breakfast", day=TODAY, serving="1 medium banana")
    entry = nut.day_entries(TODAY)[0]
    assert entry["grams"] == 120.0
    assert entry["macros"].kcal == pytest.approx(106.8)


def test_log_by_serving_with_quantity(nut):
    nut.log_food("egg", meal="dinner", day=TODAY, serving="1 medium egg (53 g)", quantity=4)
    assert nut.day_entries(TODAY)[0]["grams"] == pytest.approx(212.0)


def test_log_needs_an_amount(nut):
    with pytest.raises(ValueError):
        nut.log_food("banana", meal="breakfast", day=TODAY)


def test_log_rejects_unknown_serving(nut):
    with pytest.raises(ValueError):
        nut.log_food("banana", meal="breakfast", day=TODAY, serving="1 bunch")


def test_log_rejects_unknown_meal(nut):
    with pytest.raises(UnknownMeal):
        nut.log_food("banana", 120.0, meal="brunch", day=TODAY)


# ── database: THE frozen-macros guarantee ────────────────────
def test_frozen_macros_survive_a_later_catalogue_edit(nut):
    """The point of the whole design: correcting a food does not rewrite history."""
    nut.log_food("chicken_breast", 200.0, meal="lunch", day=YESTERDAY)
    before = nut.day_totals(YESTERDAY)
    assert before.kcal == pytest.approx(240.0)
    assert before.protein == pytest.approx(45.0)

    # "Turns out my chicken is 165 kcal and 31 g of protein per 100 g."
    nut.update_food("chicken_breast", kcal=165.0, protein=31.0)

    after = nut.day_totals(YESTERDAY)
    assert after.kcal == pytest.approx(240.0), "yesterday's lunch changed retroactively"
    assert after.protein == pytest.approx(45.0)
    assert nut.day_entries(YESTERDAY)[0]["macros"].kcal == pytest.approx(240.0)

    # ...but a *new* entry uses the corrected numbers.
    nut.log_food("chicken_breast", 200.0, meal="lunch", day=TODAY)
    assert nut.day_totals(TODAY).kcal == pytest.approx(330.0)


def test_frozen_macros_survive_renaming_and_deleting_the_food(nut):
    nut.log_food("salmon", 150.0, meal="dinner", day=TODAY)
    nut.update_food("salmon", name="Wild salmon")
    entry = nut.day_entries(TODAY)[0]
    assert entry["food_name"] == "Salmon, raw", "the logged name is a copy, not a lookup"

    nut.delete_food("salmon")
    entry = nut.day_entries(TODAY)[0]
    assert entry["food_id"] is None
    assert entry["food_name"] == "Salmon, raw"
    assert entry["macros"].kcal == pytest.approx(312.0)


def test_update_entry_grams_rescales_frozen_values(nut):
    entry_id = nut.log_food("potato", 200.0, meal="dinner", day=TODAY)
    nut.update_food("potato", kcal=999.0)  # noise the rescale must ignore
    assert nut.update_entry_grams(entry_id, 100.0) is True
    entry = nut.day_entries(TODAY)[0]
    assert entry["grams"] == 100.0
    assert entry["macros"].kcal == pytest.approx(77.0)


# ── database: totals ─────────────────────────────────────────
def test_day_totals_and_delete(nut):
    a = nut.log_food("oats", 80.0, meal="breakfast", day=TODAY)
    nut.log_food("banana", 120.0, meal="breakfast", day=TODAY)
    assert nut.day_totals(TODAY).kcal == pytest.approx(297.6 + 106.8)
    assert nut.delete_entry(a) is True
    assert nut.day_totals(TODAY).kcal == pytest.approx(106.8)
    assert nut.delete_entry(a) is False


def test_day_totals_is_zero_not_none_for_an_empty_day(nut):
    assert nut.day_totals(TODAY).as_tuple() == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_totals_by_meal_always_has_five_keys(nut):
    nut.log_food("oats", 80.0, meal="breakfast", day=TODAY)
    by_meal = nut.day_totals_by_meal(TODAY)
    assert list(by_meal) == list(MEALS)
    assert by_meal["breakfast"].kcal == pytest.approx(297.6)
    assert by_meal["lunch"].kcal == 0.0


def test_totals_by_meal_sums_to_the_day(nut):
    nut.log_template_day(TODAY)
    by_meal = nut.day_totals_by_meal(TODAY)
    assert sum(m.kcal for m in by_meal.values()) == pytest.approx(nut.day_totals(TODAY).kcal)


def test_days_do_not_leak_into_each_other(nut):
    nut.log_food("oats", 80.0, meal="breakfast", day=YESTERDAY)
    nut.log_food("banana", 120.0, meal="breakfast", day=TODAY)
    assert nut.day_totals(YESTERDAY).kcal == pytest.approx(297.6)
    assert nut.day_totals(TODAY).kcal == pytest.approx(106.8)


def test_range_totals(nut):
    nut.log_food("oats", 80.0, meal="breakfast", day=YESTERDAY)
    nut.log_food("banana", 120.0, meal="breakfast", day=TODAY)
    totals = nut.range_totals(YESTERDAY, TODAY)
    assert list(totals) == [YESTERDAY.isoformat(), TODAY.isoformat()]
    assert totals[TODAY.isoformat()].kcal == pytest.approx(106.8)


def test_logged_template_day_matches_the_pure_sum(nut):
    """Round-trip: the DB path and the no-database path must agree."""
    assert nut.log_template_day(TODAY) == len(TEMPLATE_DAY)
    assert nut.day_totals(TODAY).kcal == pytest.approx(menu_totals().kcal, rel=1e-9)
    assert nut.day_totals(TODAY).protein == pytest.approx(menu_totals().protein, rel=1e-9)


def test_clear_day(nut):
    nut.log_template_day(TODAY)
    assert nut.clear_day(TODAY) == len(TEMPLATE_DAY)
    assert nut.day_totals(TODAY).kcal == 0.0


# ── database: targets ────────────────────────────────────────
def test_targets_seeded_with_the_plan(nut):
    target = nut.targets_for(TODAY)
    assert target["macros"].as_tuple()[:4] == (2550.0, 115.0, 70.0, 365.0)


def test_targets_are_versioned_by_start_date(nut):
    cut = TODAY + timedelta(days=7)
    nut.set_targets(2400, 115, 65, 340, starts_on=cut, note="waist +1 cm → -150 kcal")

    assert nut.targets_for(TODAY)["macros"].kcal == 2550.0
    assert nut.targets_for(cut)["macros"].kcal == 2400.0
    assert nut.targets_for(cut + timedelta(days=30))["macros"].kcal == 2400.0
    assert nut.targets_for(cut)["note"].startswith("waist")
    assert len(nut.target_history()) == 2


def test_targets_fall_back_to_the_earliest_version(nut):
    """A day before the plan started is still judged against the plan."""
    assert nut.targets_for(date(2020, 1, 1))["macros"].kcal == 2550.0


def test_setting_targets_twice_on_one_day_is_an_upsert(nut):
    nut.set_targets(2400, 115, 65, 340, starts_on=TODAY)
    nut.set_targets(2300, 120, 60, 320, starts_on=TODAY)
    assert nut.targets_for(TODAY)["macros"].kcal == 2300.0
    assert len(nut.target_history()) == 2  # the seeded one plus today's


def test_compare_to_target(nut):
    nut.log_food("chicken_breast", 200.0, meal="lunch", day=TODAY)
    report = nut.compare_to_target(TODAY)
    assert report["consumed"].kcal == pytest.approx(240.0)
    assert report["target"].kcal == 2550.0
    assert report["remaining"].kcal == pytest.approx(2310.0)
    assert report["remaining"].protein == pytest.approx(70.0)
    assert report["pct"]["kcal"] == pytest.approx(240 / 2550 * 100)


def test_compare_to_target_goes_negative_when_over(nut):
    for _ in range(3):
        nut.log_template_day(TODAY)
    report = nut.compare_to_target(TODAY)
    assert report["remaining"].kcal < 0, "going over must show as a negative, not a clamp"
    assert report["pct"]["kcal"] > 100


def test_compare_uses_the_target_in_force_on_that_day(nut):
    nut.set_targets(2400, 115, 65, 340, starts_on=TODAY, note="cut")
    nut.log_food("oats", 80.0, meal="breakfast", day=YESTERDAY)
    nut.log_food("oats", 80.0, meal="breakfast", day=TODAY)
    assert nut.compare_to_target(YESTERDAY)["target"].kcal == 2550.0
    assert nut.compare_to_target(TODAY)["target"].kcal == 2400.0


# ── database: copying a day ──────────────────────────────────
def test_copy_previous_day(nut):
    nut.log_template_day(YESTERDAY)
    assert nut.copy_previous_day(TODAY) == len(TEMPLATE_DAY)
    assert nut.day_totals(TODAY).kcal == pytest.approx(nut.day_totals(YESTERDAY).kcal)
    assert nut.day_totals_by_meal(TODAY)["dinner"].kcal > 0


def test_copy_appends_by_default_and_can_replace(nut):
    nut.log_food("oats", 80.0, meal="breakfast", day=YESTERDAY)
    nut.log_food("banana", 120.0, meal="breakfast", day=TODAY)

    nut.copy_previous_day(TODAY)
    assert len(nut.day_entries(TODAY)) == 2

    nut.copy_previous_day(TODAY, replace_target=True)
    assert len(nut.day_entries(TODAY)) == 1
    assert nut.day_entries(TODAY)[0]["food_name"] == "Rolled oats"


def test_copy_revalues_with_todays_catalogue(nut):
    """A copy is a new intake, so it is priced with the catalogue as it is now —
    unlike the source row, which keeps the numbers it was frozen with."""
    nut.log_food("chicken_breast", 100.0, meal="lunch", day=YESTERDAY)
    nut.update_food("chicken_breast", kcal=165.0)
    nut.copy_previous_day(TODAY)
    assert nut.day_totals(YESTERDAY).kcal == pytest.approx(120.0)
    assert nut.day_totals(TODAY).kcal == pytest.approx(165.0)


def test_copy_of_a_deleted_food_falls_back_to_frozen_values(nut):
    nut.log_food("tuna_canned", 100.0, meal="lunch", day=YESTERDAY)
    nut.delete_food("tuna_canned")
    assert nut.copy_previous_day(TODAY) == 1
    entry = nut.day_entries(TODAY)[0]
    assert entry["food_id"] is None
    assert entry["food_name"] == "Tuna, canned in water"
    assert entry["macros"].kcal == pytest.approx(116.0)


def test_copy_onto_itself_is_refused(nut):
    with pytest.raises(ValueError):
        nut.copy_day(TODAY, TODAY)


# ── database: it really is the shared Base ───────────────────
def test_tables_live_on_the_storage_base(nut):
    for table in ("foods", "servings", "food_log", "nutrition_targets"):
        assert table in Base.metadata.tables, f"{table} is not on storage.Base"
    assert "entrenos" in Base.metadata.tables


def test_macros_per_100g_matches_what_the_db_returns(nut):
    for seed in SEED_FOODS:
        assert nut.get_food(seed.slug)["per_100g"] == macros_per_100g(seed)


# ── the view-facing façade ───────────────────────────────────
# views/nutrition_view.py imports these module-level functions by name and calls
# them with the Storage first. Its own tests run against a stub, so nothing else
# checks that the real ones match the contract. These do.
def test_facade_search_returns_picker_shaped_dicts(nut):
    results = nutrition.search_foods(nut, "banana")
    assert len(results) == 1
    banana = results[0]
    assert banana["id"] == "banana"
    assert banana["name"] == "Banana"
    assert banana["serving"] == "1 medium banana"
    # Per *serving*, not per 100 g: 89 kcal/100 g × 120 g = 107.
    assert banana["kcal"] == 107.0
    assert {p["label"] for p in banana["portions"]} == {"1 medium banana", "1 large banana"}


def test_facade_log_and_totals(nut):
    entry = nutrition.log_food(nut, TODAY.isoformat(), "breakfast", {"id": "banana"})
    assert entry["name"] == "Banana"
    assert entry["serving"] == "120 g"
    assert entry["kcal"] == 107.0

    totals = nutrition.day_totals(nut, TODAY.isoformat())
    assert totals["kcal"] == 107.0
    assert list(totals["by_meal"]) == list(MEALS)
    assert totals["by_meal"]["breakfast"]["entries"][0]["id"] == entry["id"]
    assert totals["by_meal"]["lunch"]["entries"] == []


def test_facade_log_with_portion_and_qty(nut):
    entry = nutrition.log_food(
        nut, TODAY.isoformat(), "dinner", {"id": "egg"}, qty=4, portion="1 medium egg (53 g)"
    )
    assert entry["grams"] == pytest.approx(212.0)
    assert nutrition.day_totals(nut, TODAY.isoformat())["protein"] == pytest.approx(26.7, abs=0.1)


def test_facade_falls_back_to_a_gram_count_in_the_label(nut):
    """A label the catalogue does not know must not become a silent 100 g."""
    entry = nutrition.log_food(nut, TODAY.isoformat(), "breakfast", {"id": "oats"}, portion="40 g")
    assert entry["grams"] == 40.0
    with pytest.raises(ValueError):
        nutrition.log_food(nut, TODAY.isoformat(), "breakfast", {"id": "oats"}, portion="a bowlful")


def test_facade_targets_are_flat(nut):
    target = nutrition.targets_for(nut, TODAY.isoformat())
    assert target["kcal"] == 2550.0
    assert target["protein"] == 115.0
    assert target["fat"] == 70.0
    assert target["carbs"] == 365.0


def test_facade_favourites_degrade_through_three_tiers(nut):
    # Tier 3 only: nothing starred, nothing logged — still a full quick-add row.
    assert len(nutrition.favourite_foods(nut, limit=6)) == 6

    # Tier 2: recent habit outranks the alphabet.
    for _ in range(3):
        nutrition.log_food(nut, TODAY.isoformat(), "lunch", {"id": "tuna_canned"})
    assert nutrition.favourite_foods(nut, limit=6)[0]["id"] == "tuna_canned"

    # Tier 1: a star outranks habit.
    nut.set_favourite("salmon")
    assert nutrition.favourite_foods(nut, limit=6)[0]["id"] == "salmon"


def test_facade_favourites_have_no_duplicates(nut):
    nut.set_favourite("oats")
    nutrition.log_food(nut, TODAY.isoformat(), "breakfast", {"id": "oats"})
    picks = nutrition.favourite_foods(nut, limit=6)
    assert len({f["id"] for f in picks}) == len(picks)


def test_facade_delete_and_copy(nut):
    entry = nutrition.log_food(nut, YESTERDAY.isoformat(), "lunch", {"id": "rice_white"})
    assert nutrition.copy_previous_day(nut, TODAY.isoformat()) == 1
    assert nutrition.day_totals(nut, TODAY.isoformat())["kcal"] > 0
    assert nutrition.delete_entry(nut, entry["id"]) is True
    assert nutrition.day_totals(nut, YESTERDAY.isoformat())["kcal"] == 0.0


def test_facade_accepts_a_bare_slug_as_the_food(nut):
    entry = nutrition.log_food(nut, TODAY.isoformat(), "lunch", "chicken_breast")
    assert entry["name"] == "Chicken breast, raw"
    assert entry["grams"] == 150.0


def test_facade_signature_matches_what_the_view_introspects():
    """views/nutrition_view.py calls `_accepts(fn, "portion")` before passing it.
    Rename these parameters and the view silently stops sending them."""
    import inspect

    assert set(inspect.signature(nutrition.log_food).parameters) >= {"portion", "qty"}
    assert set(inspect.signature(nutrition.favourite_foods).parameters) >= {"meal", "limit"}
    assert "limit" in inspect.signature(nutrition.search_foods).parameters
