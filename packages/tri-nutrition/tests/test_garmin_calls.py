from datetime import date, timedelta

import pytest

from tri_nutrition.nutrition.garmin_calls import (
    consistent_calorie_goal,
    day_target_change,
    targets_needing_write,
    to_garmin_call,
)
from tri_nutrition.nutrition.models import DayTarget, NutritionChange, StoredDayTarget

MONDAY = date(2026, 9, 14)


def target(day=MONDAY, **over) -> DayTarget:
    base = dict(
        day=day,
        day_type="easy",
        session_kcal=0,
        total_kcal=2800,
        carbs_g=280,
        protein_g=150,
        fat_g=120,
        fluid_baseline_ml=2800,
        source="plan",
    )
    base.update(over)
    return DayTarget(**base)


def test_consistent_calorie_goal():
    assert consistent_calorie_goal(280, 150, 120, 2800) == 2800  # exact
    assert consistent_calorie_goal(280, 150, 120, 2815) == 2815  # within 20
    assert consistent_calorie_goal(280, 150, 120, 2900) == 2800  # off by 100: recomputed


def test_day_target_change_and_call():
    c = day_target_change(target())
    assert c.op == "set_day_targets" and c.target_key == "2026-09-14" and c.day == MONDAY
    assert c.payload == {
        "calorie_goal": 2800,
        "carbs_grams": 280,
        "protein_grams": 150,
        "fat_grams": 120,
    }
    name, args = to_garmin_call(c)
    assert name == "set_nutrition_daily_settings"
    assert args == {"date": "2026-09-14", **c.payload}


def test_to_garmin_call_fixes_inconsistent_goal_and_rejects_other_ops():
    c = day_target_change(target())
    c = c.model_copy(update={"payload": {**c.payload, "calorie_goal": 3000}})
    assert to_garmin_call(c)[1]["calorie_goal"] == 2800
    other = NutritionChange(op="set_race_note", target_key="", day=MONDAY, payload={}, reason="")
    with pytest.raises(ValueError):
        to_garmin_call(other)


def test_targets_needing_write():
    d2 = MONDAY + timedelta(days=1)
    d3 = MONDAY + timedelta(days=2)
    new = [target(), target(d2, total_kcal=3000, fat_g=142), target(d3)]
    existing = [
        StoredDayTarget(target=target(), written_to_garmin=True),  # unchanged, written: skip
        StoredDayTarget(target=target(d2), written_to_garmin=True),  # changed: write
        StoredDayTarget(target=target(d3), written_to_garmin=False),  # never written: write
    ]
    assert [t.day for t in targets_needing_write(new, existing)] == [d2, d3]
    assert [t.day for t in targets_needing_write(new, [])] == [MONDAY, d2, d3]
