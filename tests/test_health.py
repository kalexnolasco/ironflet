"""Basic tests for pure-function health calculators."""

from __future__ import annotations

from health import bmi, bmi_category, bmr_mifflin, protein_target_range, tdee, water_target_l


def test_bmi_none_on_missing_input():
    assert bmi(None, 170) is None
    assert bmi(70, None) is None
    assert bmi(0, 170) is None


def test_bmi_value():
    # 70 kg, 1.75 m → 22.86
    assert round(bmi(70, 175), 2) == 22.86


def test_bmi_category_boundaries():
    assert bmi_category(17) == "underweight"
    assert bmi_category(18.5) == "normal"
    assert bmi_category(24.9) == "normal"
    assert bmi_category(25) == "overweight"
    assert bmi_category(29.9) == "overweight"
    assert bmi_category(30) == "obese"


def test_bmr_mifflin_male():
    # 80 kg, 180 cm, 30 yrs, M
    # = 10*80 + 6.25*180 - 5*30 + 5 = 800 + 1125 - 150 + 5 = 1780
    assert bmr_mifflin(80, 180, 30, "M") == 1780


def test_bmr_mifflin_female():
    # 60 kg, 165 cm, 28 yrs, F
    # = 10*60 + 6.25*165 - 5*28 - 161 = 600 + 1031.25 - 140 - 161 = 1330.25
    assert bmr_mifflin(60, 165, 28, "F") == 1330.25


def test_tdee_uses_activity_factor():
    assert tdee(2000, "sedentary") == 2400
    assert tdee(2000, "moderate") == 3100
    assert tdee(None, "moderate") is None


def test_protein_target_range():
    low, high = protein_target_range(75)
    assert low == 120.0
    assert high == 165.0
    assert protein_target_range(0) is None


def test_water_target():
    # 80 kg → 2.8 L
    assert water_target_l(80) == 2.8
