from datetime import date, timedelta

import pytest

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition import energy, targets
from tri_nutrition.nutrition.models import NutritionProfile, PlanContext, Session

MONDAY = date(2026, 9, 14)


def profile(**over) -> NutritionProfile:
    base = dict(
        height_cm=180,
        weight_kg=80,
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


def session(day=MONDAY, **over) -> Session:
    base = dict(day=day, sport="bike", duration_min=60, intensity="endurance")
    base.update(over)
    return Session(**base)


def ctx(**over) -> PlanContext:
    base = dict(source="plan")
    base.update(over)
    return PlanContext(**base)


# --- macro_grams ---


def test_macro_rest_day_bottom_of_range():
    c, p, f, total, floor = targets.macro_grams("rest", 0, 2500, 80)
    assert c == round(3.0 * 80) and p == round(1.8 * 80)
    assert f == round((2500 - 4 * c - 4 * p) / 9)
    assert total == 4 * c + 4 * p + 9 * f
    assert floor is False


def test_macro_position_scales_with_session_kcal():
    lo, *_ = targets.macro_grams("moderate", 0, 3000, 80)
    mid, *_ = targets.macro_grams("moderate", C.SESSION_KCAL_FULL_RANGE / 2, 3000, 80)
    hi, *_ = targets.macro_grams("moderate", C.SESSION_KCAL_FULL_RANGE * 2, 3000, 80)
    assert lo == round(5.0 * 80) and mid == round(5.5 * 80) and hi == round(6.0 * 80)


@pytest.mark.parametrize(
    "day_type,carbs_lo,protein,fat_min",
    [
        ("rest", 3.0, 1.8, 0.8),
        ("easy", 3.0, 1.8, 0.8),
        ("moderate", 5.0, 1.8, 0.8),
        ("hard", 7.0, 2.0, 0.8),
        ("long", 7.0, 2.0, 0.8),
        ("carb_load", 10.0, 1.6, 0.6),
        ("race", 8.0, 1.6, 0.6),
    ],
)
def test_macro_table_rows(day_type, carbs_lo, protein, fat_min):
    c, p, f, total, _ = targets.macro_grams(day_type, 0, 6000, 80)
    assert c == round(carbs_lo * 80) and p == round(protein * 80)
    assert f >= round(fat_min * 80)
    assert total == 4 * c + 4 * p + 9 * f


def test_macro_fat_floor_raises_total():
    # 1800 kcal cannot hold 240 g carbs + 144 g protein + 64 g fat
    c, p, f, total, floor = targets.macro_grams("rest", 0, 1800, 80)
    assert floor is True
    assert f == round(0.8 * 80)
    assert total == 4 * c + 4 * p + 9 * f and total > 1800


# --- goal_adjust ---


def test_maintain_no_adjust():
    assert targets.goal_adjust(profile(), "easy", "base") == (0, [])


def test_lose_deficit_on_easy_days_capped():
    p = profile(goal="lose", target_weight_kg=75, max_weekly_change_pct=0.5)
    budget = 0.5 / 100 * 80 * C.KCAL_PER_KG_BODY_MASS  # 3080/week
    adj, notes = targets.goal_adjust(p, "easy", "base")
    assert adj == -round(budget / 7) and notes == [C.NOTE_DEFICIT]
    big = profile(goal="lose", target_weight_kg=75, max_weekly_change_pct=1.0)
    adj, _ = targets.goal_adjust(big, "rest", "build")
    assert adj == -C.MAX_DEFICIT_KCAL_PER_DAY  # 6160/7 = 880 > 500


@pytest.mark.parametrize("day_type", ["hard", "long", "carb_load", "race"])
def test_lose_paused_on_hard_days(day_type):
    p = profile(goal="lose", target_weight_kg=75)
    assert targets.goal_adjust(p, day_type, "base") == (0, [C.NOTE_DEFICIT_PAUSED_DAY])


@pytest.mark.parametrize("phase", ["peak", "taper", "race", "recovery"])
def test_lose_paused_in_late_phases(phase):
    p = profile(goal="lose", target_weight_kg=75)
    assert targets.goal_adjust(p, "easy", phase) == (0, [C.NOTE_DEFICIT_PAUSED_PHASE])


def test_lose_applies_when_phase_unknown():
    p = profile(goal="lose", target_weight_kg=75)
    adj, _ = targets.goal_adjust(p, "easy", None)
    assert adj < 0


def test_gain_surplus_on_hard_and_long_only():
    p = profile(goal="gain_lean")
    for dt in ("hard", "long"):
        adj, notes = targets.goal_adjust(p, dt, "build")
        assert C.SURPLUS_KCAL_MIN <= adj <= C.SURPLUS_KCAL_MAX and notes == [C.NOTE_SURPLUS]
    assert targets.goal_adjust(p, "easy", "build") == (0, [])
    assert targets.goal_adjust(p, "rest", "build") == (0, [])


# --- fluids ---


def test_fluid_baseline_without_sweat_rate():
    ml = targets.fluid_baseline_ml(profile(), [session(duration_min=90)])
    assert ml == 35 * 80 + round(1.5 * C.FLUID_ML_PER_TRAINING_H)


def test_fluid_baseline_with_sweat_rate():
    p = profile(known_sweat_rate_l_per_h=1.2)
    assert targets.fluid_baseline_ml(p, [session(duration_min=90)]) == 35 * 80 + round(1.5 * 1200)


def test_fluid_baseline_rest_day():
    assert targets.fluid_baseline_ml(profile(), []) == 35 * 80


# --- build ---


def test_build_one_target_per_day_in_order():
    out = targets.build(profile(), [], ctx(), MONDAY, 14)
    assert [t.day for t in out] == [MONDAY + timedelta(days=i) for i in range(14)]
    assert all(t.day_type == "rest" and t.source == "plan" for t in out)


def test_build_maintain_rest_day_equals_non_exercise_kcal():
    p = profile()
    t = targets.build(p, [], ctx(), MONDAY, 1)[0]
    c, pr, f, total, _ = targets.macro_grams("rest", 0, energy.non_exercise_kcal(p), 80)
    assert (t.carbs_g, t.protein_g, t.fat_g, t.total_kcal) == (c, pr, f, total)
    assert t.session_kcal == 0 and t.goal_adjust_kcal == 0


def test_build_session_day_adds_session_kcal_and_types_day():
    p = profile()
    s = session(duration_min=180, planned_tss=180)
    t = targets.build(p, [s], ctx(ftp_watts=250), MONDAY, 1)[0]
    assert t.day_type == "long"
    assert t.session_kcal == round(180 * 250 * 36 / 1000)
    maintenance = energy.non_exercise_kcal(p) + t.session_kcal
    assert abs(t.total_kcal - maintenance) <= 9  # macro rounding only; no goal adjust
    assert t.fluid_baseline_ml == 35 * 80 + round(3 * C.FLUID_ML_PER_TRAINING_H)


def test_build_deficit_lowers_total_and_records_adjust():
    p = profile(goal="lose", target_weight_kg=75)
    t = targets.build(p, [], ctx(), MONDAY, 1)[0]
    assert t.goal_adjust_kcal < 0 and C.NOTE_DEFICIT in t.notes
    maintenance = energy.non_exercise_kcal(p)
    assert t.total_kcal < maintenance


def test_build_phase_from_week_monday_and_pause():
    p = profile(goal="lose", target_weight_kg=75)
    phases = {MONDAY: "build", MONDAY + timedelta(days=7): "taper"}
    out = targets.build(p, [], ctx(phases=phases), MONDAY + timedelta(days=5), 4)
    assert [t.plan_phase for t in out] == ["build", "build", "taper", "taper"]
    assert out[0].goal_adjust_kcal < 0 and out[2].goal_adjust_kcal == 0
    assert C.NOTE_DEFICIT_PAUSED_PHASE in out[2].notes


def test_build_race_and_carb_load_days():
    c = ctx(event_date=MONDAY + timedelta(days=6), event_priority="A")
    out = targets.build(profile(), [], c, MONDAY, 7)
    expected = ["rest", "rest", "rest", "rest", "carb_load", "carb_load", "race"]
    assert [t.day_type for t in out] == expected
    assert out[4].carbs_g == round(10 * 80)


def test_build_fat_floor_note():
    small = profile(
        weight_kg=60, body_fat_pct=None, activity_factor=1.2, goal="lose", target_weight_kg=55
    )
    t = targets.build(small, [], ctx(), MONDAY, 1)[0]
    assert C.NOTE_FAT_FLOOR in t.notes
    assert t.total_kcal == 4 * t.carbs_g + 4 * t.protein_g + 9 * t.fat_g


def test_build_profile_hours_fallback_spreads_goal_hours():
    c = ctx(source="profile_hours", weekly_hours=7)
    out = targets.build(profile(), [], c, MONDAY, 7)
    assert all(t.source == "profile_hours" and C.NOTE_PROFILE_HOURS in t.notes for t in out)
    assert all(t.day_type == "moderate" for t in out)  # 60 min endurance per day
    assert all(t.session_kcal > 0 for t in out)


def test_build_profile_hours_without_goal_is_rest():
    c = ctx(source="profile_hours")
    out = targets.build(profile(), [], c, MONDAY, 2)
    assert all(t.day_type == "rest" and C.NOTE_NO_SESSIONS in t.notes for t in out)


def test_build_ignores_sessions_outside_horizon():
    far = session(day=MONDAY + timedelta(days=30), duration_min=200)
    out = targets.build(profile(), [far], ctx(), MONDAY, 7)
    assert all(t.day_type == "rest" for t in out)
