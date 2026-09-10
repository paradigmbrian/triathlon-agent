from datetime import date

import pytest
from pydantic import ValidationError

from tri_nutrition.nutrition.models import (
    DayTarget,
    NutritionChange,
    NutritionProfile,
    PlanContext,
    Product,
    RaceFuelPlan,
    RaceFuelStep,
    ReviewDecision,
    Session,
    SessionFuel,
)


def profile(**over) -> NutritionProfile:
    base = dict(
        height_cm=180,
        weight_kg=75,
        body_fat_pct=15,
        sex="m",
        age=40,
        goal="maintain",
        pattern="omnivore",
        meals_per_day=3,
        cooks=True,
        tracks_food=True,
        scale_days_per_week=3,
        unit_preference="metric",
    )
    base.update(over)
    return NutritionProfile(**base)


def test_profile_defaults_and_lists():
    p = profile()
    assert p.activity_factor == 1.35
    assert p.max_weekly_change_pct == 0.5
    assert p.restrictions == [] and p.tested_products == [] and p.medical_flags == []
    assert p.target_weight_kg is None and p.caffeine_mg_per_day is None


@pytest.mark.parametrize("field,value", [("activity_factor", 1.1), ("activity_factor", 1.6)])
def test_activity_factor_bounded(field, value):
    with pytest.raises(ValidationError):
        profile(**{field: value})


def test_max_weekly_change_pct_bounded():
    with pytest.raises(ValidationError):
        profile(max_weekly_change_pct=1.5)
    assert profile(max_weekly_change_pct=1.0).max_weekly_change_pct == 1.0


def test_lose_goal_needs_target_weight_below_current():
    with pytest.raises(ValidationError):
        profile(goal="lose", target_weight_kg=80)
    assert profile(goal="lose", target_weight_kg=70).goal == "lose"


def test_product_defaults():
    p = Product(name="Gel", form="gel", carbs_g=25)
    assert p.sodium_mg == 0 and p.caffeine_mg == 0 and p.tested is True


def test_session_hours_and_brick_legs():
    bike = Session(day=date(2026, 9, 14), sport="bike", duration_min=90, intensity="endurance")
    run = Session(day=date(2026, 9, 14), sport="run", duration_min=30, intensity="endurance")
    brick = Session(
        day=date(2026, 9, 14),
        sport="brick",
        duration_min=120,
        intensity="endurance",
        legs=[bike, run],
    )
    assert bike.hours == 1.5
    assert brick.legs is not None and len(brick.legs) == 2
    with pytest.raises(ValidationError):
        Session(
            day=date(2026, 9, 14), sport="bike", duration_min=60, intensity="endurance", legs=[run]
        )


def test_plan_context_defaults():
    ctx = PlanContext(source="plan")
    assert ctx.ftp_watts is None and ctx.event_date is None and ctx.phases == {}
    assert ctx.weekly_hours is None


def test_day_target_json_roundtrip():
    t = DayTarget(
        day=date(2026, 9, 14),
        day_type="easy",
        session_kcal=300,
        total_kcal=2500,
        carbs_g=260,
        protein_g=135,
        fat_g=100,
        fluid_baseline_ml=3000,
        goal_adjust_kcal=-300,
        plan_phase="base",
        source="plan",
        notes=["deficit"],
    )
    assert DayTarget.model_validate(t.model_dump(mode="json")) == t


def test_session_fuel_and_race_plan_shapes():
    sf = SessionFuel(
        tp_workout_id="w1",
        day=date(2026, 9, 14),
        pre="toast",
        carbs_g_per_h=60,
        fluid_ml_per_h=600,
        sodium_mg_per_h=500,
        caffeine_mg=None,
        products=["Gel"],
        post="shake",
        gut_training=False,
        note_text="60 g/h",
    )
    assert sf.caffeine_mg is None
    step = RaceFuelStep(
        offset_min=-180,
        leg="pre",
        what="oats",
        carbs_g=100,
        fluid_ml=500,
        sodium_mg=300,
        caffeine_mg=0,
    )
    assert step.products == []
    plan = RaceFuelPlan(
        event_date=date(2026, 10, 4),
        timeline=[step],
        totals_per_h={"bike_carbs": 80, "run_carbs": 60},
        contingencies=[],
        note_text="x",
    )
    assert plan.timeline[0].leg == "pre"


def test_change_and_decision():
    c = NutritionChange(
        op="set_day_targets",
        target_key="2026-09-14",
        day=date(2026, 9, 14),
        payload={"calorie_goal": 2500},
        reason="new targets",
    )
    d = ReviewDecision(action="edit", note=None, changes=[c])
    assert d.changes is not None and d.changes[0].op == "set_day_targets"
    with pytest.raises(ValidationError):
        NutritionChange(op="nope", target_key="", day=date(2026, 9, 14), payload={}, reason="")
