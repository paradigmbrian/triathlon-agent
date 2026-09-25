from datetime import date, timedelta

import pytest

from tri_nutrition.nutrition import bounds, energy
from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import (
    DayTarget,
    FuelLogEntry,
    NutritionProfile,
    Product,
    RaceFuelPlan,
    RaceFuelStep,
    SessionFuel,
)

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
        caffeine_mg_per_day=200,
    )
    base.update(over)
    return NutritionProfile(**base)


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
        goal_adjust_kcal=0,
        plan_phase="base",
        source="plan",
    )
    base.update(over)
    return DayTarget(**base)


LIB = [
    Product(name="Gel", form="gel", carbs_g=25, sodium_mg=50, caffeine_mg=0),
    Product(name="Mix", form="drink", carbs_g=40, sodium_mg=400, caffeine_mg=0),
]


def fuel(**over) -> SessionFuel:
    base = dict(
        tp_workout_id="w1",
        day=MONDAY,
        pre="toast",
        carbs_g_per_h=60,
        fluid_ml_per_h=600,
        sodium_mg_per_h=500,
        caffeine_mg=None,
        products=["Gel", "Mix"],
        post="shake",
        gut_training=False,
        note_text="",
    )
    base.update(over)
    return SessionFuel(**base)


def log(carbs: int, outcome: str = "ok") -> FuelLogEntry:
    return FuelLogEntry(
        day=MONDAY - timedelta(days=7),
        sport="bike",
        duration_min=120,
        carbs_g_per_h=carbs,
        outcome=outcome,
    )


def vf(f: SessionFuel, p: NutritionProfile | None = None, log_entries=(), other=0) -> list[str]:
    return bounds.validate_fuel(f, p or profile(), LIB, list(log_entries), other)


# --- validate_targets ---


def test_targets_valid():
    assert bounds.validate_targets([target()], profile()) == []


def test_targets_energy_availability():
    p = profile()
    # EA = (total - session) / ffm < 30
    low = round(30 * energy.ffm(p)) - 50
    t = target(total_kcal=low, session_kcal=0, protein_g=150, carbs_g=100, fat_g=50)
    assert any("energy availability" in v for v in bounds.validate_targets([t], p))


def test_targets_below_rmr():
    p = profile()
    t = target(total_kcal=round(energy.rmr(p)) - 1, session_kcal=0)
    assert any("below RMR" in v for v in bounds.validate_targets([t], p))


def test_targets_protein_floor():
    t = target(protein_g=round(1.5 * 80))
    assert any("protein" in v for v in bounds.validate_targets([t], profile()))


@pytest.mark.parametrize("day_type", ["hard", "long"])
def test_targets_hard_day_carbs(day_type):
    t = target(day_type=day_type, carbs_g=round(5.9 * 80), total_kcal=4000, session_kcal=1000)
    assert any("carbs" in v for v in bounds.validate_targets([t], profile()))
    ok = target(day_type=day_type, carbs_g=round(6.0 * 80), total_kcal=4000, session_kcal=1000)
    assert bounds.validate_targets([ok], profile()) == []


def test_targets_seven_day_deficit_bound():
    p = profile(goal="lose", target_weight_kg=75, max_weekly_change_pct=0.5)
    budget = 0.5 / 100 * 80 * C.KCAL_PER_KG_BODY_MASS  # 3080
    per_day = -round(budget / 7)
    ok = [target(day=MONDAY + timedelta(days=i), goal_adjust_kcal=per_day) for i in range(7)]
    assert bounds.validate_targets(ok, p) == []
    bad = [target(day=MONDAY + timedelta(days=i), goal_adjust_kcal=per_day - 20) for i in range(7)]
    assert any("seven-day deficit" in v for v in bounds.validate_targets(bad, p))


def test_targets_deficit_in_forbidden_phase():
    p = profile(goal="lose", target_weight_kg=75)
    for phase in ("peak", "taper", "race"):
        t = target(goal_adjust_kcal=-300, plan_phase=phase)
        assert any("deficit" in v and phase in v for v in bounds.validate_targets([t], p))
    ok = target(goal_adjust_kcal=-300, plan_phase="recovery")
    assert bounds.validate_targets([ok], p) == []  # pause is the builder's job; not forbidden


# --- validate_fuel ---


def test_fuel_valid():
    assert vf(fuel()) == []


def test_carbs_evidence():
    assert bounds.carbs_evidence([]) == 0
    assert bounds.carbs_evidence([log(70), log(95, "gi_upset"), log(65)]) == 70


def test_fuel_carbs_tiers():
    assert any("60" in v for v in vf(fuel(carbs_g_per_h=61)))
    assert vf(fuel(carbs_g_per_h=90), log_entries=[log(60)]) == []
    assert any("90" in v for v in vf(fuel(carbs_g_per_h=91), log_entries=[log(60)]))
    assert vf(fuel(carbs_g_per_h=120), log_entries=[log(90)]) == []
    assert any("120" in v for v in vf(fuel(carbs_g_per_h=121), log_entries=[log(130)]))


def test_fuel_gi_upset_is_not_evidence():
    assert any("60" in v for v in vf(fuel(carbs_g_per_h=70), log_entries=[log(70, "gi_upset")]))


def test_fuel_fluid_and_sodium():
    assert any("fluid" in v for v in vf(fuel(fluid_ml_per_h=1001)))
    assert any("sodium" in v for v in vf(fuel(sodium_mg_per_h=299)))
    assert any("sodium" in v for v in vf(fuel(sodium_mg_per_h=1501)))


def test_fuel_sodium_zero_means_none_and_is_valid():
    # a 40-minute endurance run: nothing during the session is a valid plan
    assert vf(fuel(sodium_mg_per_h=0, fluid_ml_per_h=0)) == []
    assert any("sodium" in v for v in vf(fuel(sodium_mg_per_h=100)))
    assert vf(fuel(sodium_mg_per_h=300)) == []


def test_fuel_caffeine_rules():
    assert any("caffeine" in v for v in vf(fuel(caffeine_mg=50), profile(caffeine_mg_per_day=0)))
    assert vf(fuel(caffeine_mg=100)) == []
    # 6 mg/kg * 80 = 480; 300 in this session + 200 elsewhere today = 500
    assert any("caffeine" in v for v in vf(fuel(caffeine_mg=300), other=200))
    assert vf(fuel(caffeine_mg=300), profile(caffeine_mg_per_day=None)) == []


def test_fuel_unknown_product():
    assert any("Mystery" in v for v in vf(fuel(products=["Gel", "Mystery"])))


# --- validate_race ---


def step(offset: int, leg: str, **over) -> RaceFuelStep:
    base = dict(offset_min=offset, leg=leg, what="x", carbs_g=25, fluid_ml=0, sodium_mg=0)
    base.update(over)
    return RaceFuelStep(**base)


TOTALS_OK = {
    "bike_carbs": 80,
    "run_carbs": 60,
    "bike_fluid": 700,
    "run_fluid": 500,
    "bike_sodium": 600,
    "run_sodium": 400,
}
TOTALS_LOW = {"bike_carbs": 60, "run_carbs": 60}


def race(**over) -> RaceFuelPlan:
    base = dict(
        event_date=MONDAY,
        timeline=[
            step(
                -180, "pre", what="oats", carbs_g=120, fluid_ml=500, sodium_mg=300, caffeine_mg=100
            ),
            step(30, "bike", fluid_ml=250, sodium_mg=200, products=["Gel"]),
            step(150, "run", fluid_ml=200, sodium_mg=150, products=["Gel"]),
        ],
        totals_per_h=TOTALS_OK,
        contingencies=["if GI: drop to water and gels"],
        note_text="",
    )
    base.update(over)
    return RaceFuelPlan(**base)


def vr(plan: RaceFuelPlan, log_entries=()) -> list[str]:
    return bounds.validate_race(plan, profile(), LIB, list(log_entries))


def test_race_valid_with_evidence():
    assert vr(race(), [log(80)]) == []


def test_race_leg_carbs_need_evidence():
    assert any("bike" in v and "60" in v for v in vr(race()))


def test_race_leg_fluid_and_sodium_bounds():
    totals = {
        **TOTALS_LOW,
        "bike_fluid": 1100,
        "run_fluid": 500,
        "bike_sodium": 600,
        "run_sodium": 200,
    }
    out = vr(race(totals_per_h=totals))
    assert any("bike" in v and "fluid" in v for v in out)
    assert any("run" in v and "sodium" in v for v in out)


def test_race_pre_step_window():
    early = race(timeline=[step(-300, "pre")], totals_per_h=TOTALS_LOW)
    assert any("pre-race" in v for v in vr(early))
    late = race(timeline=[step(-60, "pre")], totals_per_h=TOTALS_LOW)
    assert any("pre-race" in v for v in vr(late))
    missing = race(timeline=[], totals_per_h=TOTALS_LOW)
    assert any("pre-race" in v for v in vr(missing))


def test_race_total_caffeine():
    steps = [step(-180, "pre", caffeine_mg=300), step(60, "bike", caffeine_mg=200)]
    t = race(timeline=steps, totals_per_h=TOTALS_LOW)
    assert any("caffeine" in v for v in vr(t))  # 500 > 480


def test_race_unknown_product():
    steps = [step(-180, "pre"), step(60, "bike", products=["Nope"])]
    t = race(timeline=steps, totals_per_h=TOTALS_LOW)
    assert any("Nope" in v for v in vr(t))
