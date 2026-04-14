"""Health metric calculators — age, BMI, BMR, TDEE, protein target.

All inputs are optional; helpers return None when inputs are missing/invalid.
"""

from __future__ import annotations

from datetime import date


ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


def age_years(birthdate_iso: str) -> int | None:
    try:
        b = date.fromisoformat(birthdate_iso)
    except (ValueError, TypeError):
        return None
    t = date.today()
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    return max(0, years)


def bmi(weight_kg: float | None, height_cm: float | None) -> float | None:
    if not weight_kg or not height_cm:
        return None
    h = height_cm / 100.0
    return weight_kg / (h * h)


def bmi_category(bmi_value: float | None) -> str | None:
    if bmi_value is None:
        return None
    if bmi_value < 18.5:
        return "underweight"
    if bmi_value < 25:
        return "normal"
    if bmi_value < 30:
        return "overweight"
    return "obese"


def bmr_mifflin(weight_kg: float | None, height_cm: float | None,
                age: int | None, sex: str) -> float | None:
    """Mifflin-St Jeor BMR in kcal/day."""
    if not (weight_kg and height_cm and age is not None):
        return None
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    if sex == "M":
        return base + 5.0
    if sex == "F":
        return base - 161.0
    return base - 78.0  # average for unspecified


def tdee(bmr_value: float | None, activity: str) -> float | None:
    if bmr_value is None:
        return None
    factor = ACTIVITY_FACTORS.get(activity, 1.2)
    return bmr_value * factor


def protein_target_range(weight_kg: float | None) -> tuple[float, float] | None:
    """Returns (low, high) daily protein target in grams (1.6–2.2 g/kg)."""
    if not weight_kg:
        return None
    return (round(weight_kg * 1.6, 1), round(weight_kg * 2.2, 1))


def water_target_l(weight_kg: float | None) -> float | None:
    """~35 ml per kg of bodyweight, in litres."""
    if not weight_kg:
        return None
    return round(weight_kg * 0.035, 1)
