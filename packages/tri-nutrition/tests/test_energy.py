from datetime import date, timedelta

import pytest

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition import energy
from tri_nutrition.nutrition.models import NutritionProfile, PlanContext, Session

DAY = date(2026, 9, 14)


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


def session(**over) -> Session:
    base = dict(day=DAY, sport="bike", duration_min=60, intensity="endurance")
    base.update(over)
    return Session(**base)


def ctx(**over) -> PlanContext:
    base = dict(source="plan")
    base.update(over)
    return PlanContext(**base)


# --- RMR ---


def test_ffm_from_body_fat():
    assert energy.ffm(profile()) == pytest.approx(75 * 0.85)


def test_ffm_assumed_when_body_fat_unknown():
    m = 75 * (1 - C.ASSUMED_BODY_FAT_PCT["m"] / 100)
    f = 75 * (1 - C.ASSUMED_BODY_FAT_PCT["f"] / 100)
    assert energy.ffm(profile(body_fat_pct=None)) == pytest.approx(m)
    assert energy.ffm(profile(body_fat_pct=None, sex="f")) == pytest.approx(f)


def test_rmr_cunningham_when_body_fat_known():
    assert energy.rmr(profile()) == pytest.approx(500 + 22 * 75 * 0.85)


def test_rmr_mifflin_when_body_fat_unknown():
    # 10*75 + 6.25*180 - 5*40 + 5 = 1680
    assert energy.rmr(profile(body_fat_pct=None)) == pytest.approx(1680)
    # female: -161 instead of +5
    assert energy.rmr(profile(body_fat_pct=None, sex="f")) == pytest.approx(1514)


def test_non_exercise_kcal():
    expected = energy.rmr(profile()) * 1.4
    assert energy.non_exercise_kcal(profile(activity_factor=1.4)) == pytest.approx(expected)


# --- session kcal ---


def test_bike_from_tss_and_ftp():
    s = session(sport="bike", planned_tss=100)
    assert energy.session_kcal(s, profile(), ftp_watts=250) == pytest.approx(100 * 250 * 36 / 1000)


def test_bike_falls_back_without_tss_or_ftp():
    s = session(sport="bike", duration_min=60, intensity="endurance")
    expected = 1.0 * 75 * C.SPORT_KCAL_PER_KG_H["bike"]["endurance"]
    assert energy.session_kcal(s, profile(), ftp_watts=250) == pytest.approx(expected)
    with_tss = session(sport="bike", planned_tss=100)
    assert energy.session_kcal(with_tss, profile(), ftp_watts=None) == pytest.approx(expected)


def test_run_from_distance():
    s = session(sport="run", distance_km=12)
    assert energy.session_kcal(s, profile(), ftp_watts=None) == pytest.approx(75 * 12)


def test_run_from_duration_and_intensity():
    s = session(sport="run", duration_min=90, intensity="threshold")
    expected = 1.5 * 75 * C.SPORT_KCAL_PER_KG_H["run"]["threshold"]
    assert energy.session_kcal(s, profile(), ftp_watts=None) == pytest.approx(expected)


def test_swim_from_duration_and_intensity():
    s = session(sport="swim", duration_min=45, intensity="endurance")
    expected = 0.75 * 75 * C.SPORT_KCAL_PER_KG_H["swim"]["endurance"]
    assert energy.session_kcal(s, profile(), ftp_watts=None) == pytest.approx(expected)


def test_strength():
    s = session(sport="strength", duration_min=30, intensity="endurance")
    assert energy.session_kcal(s, profile(), ftp_watts=None) == pytest.approx(0.5 * 5 * 75)


def test_brick_sums_legs():
    bike = session(sport="bike", duration_min=90, planned_tss=90)
    run = session(sport="run", duration_min=30, distance_km=5)
    brick = session(sport="brick", duration_min=120, legs=[bike, run])
    expected = energy.session_kcal(bike, profile(), 250) + energy.session_kcal(run, profile(), 250)
    assert energy.session_kcal(brick, profile(), ftp_watts=250) == pytest.approx(expected)


def test_brick_without_legs_splits_by_fraction():
    brick = session(sport="brick", duration_min=120, intensity="tempo")
    bike_h = 2 * C.BRICK_BIKE_FRACTION
    run_h = 2 - bike_h
    expected = (
        bike_h * 75 * C.SPORT_KCAL_PER_KG_H["bike"]["tempo"]
        + run_h * 75 * C.SPORT_KCAL_PER_KG_H["run"]["tempo"]
    )
    assert energy.session_kcal(brick, profile(), ftp_watts=None) == pytest.approx(expected)


def test_brick_without_legs_shares_tss_with_the_bike_leg_only():
    brick = session(sport="brick", duration_min=150, planned_tss=180, distance_km=40)
    bike_min = round(150 * C.BRICK_BIKE_FRACTION)
    bike = 180 * C.BRICK_BIKE_FRACTION * 250 * C.BIKE_KCAL_PER_TSS_FTP
    run = (150 - bike_min) / 60 * 75 * C.SPORT_KCAL_PER_KG_H["run"]["endurance"]
    kcal = energy.session_kcal(brick, profile(), ftp_watts=250)
    assert kcal == pytest.approx(bike + run)  # 1080 + 625
    assert 1500 < kcal < 1800  # not the whole brick's TSS on the bike plus a 40 km run on top


# --- day type ---


def test_day_type_rest():
    assert energy.day_type([], DAY, ctx()) == "rest"


def test_day_type_easy_under_60_min_endurance():
    assert energy.day_type([session(duration_min=45)], DAY, ctx()) == "easy"
    assert energy.day_type([session(duration_min=59, intensity="recovery")], DAY, ctx()) == "easy"


def test_day_type_moderate_up_to_120_or_one_tempo():
    assert energy.day_type([session(duration_min=60)], DAY, ctx()) == "moderate"
    assert energy.day_type([session(duration_min=120)], DAY, ctx()) == "moderate"
    assert energy.day_type([session(duration_min=40, intensity="tempo")], DAY, ctx()) == "moderate"


@pytest.mark.parametrize("intensity", ["threshold", "vo2", "race"])
def test_day_type_hard(intensity):
    assert energy.day_type([session(duration_min=45, intensity=intensity)], DAY, ctx()) == "hard"


def test_day_type_long_single_session_150_min():
    assert energy.day_type([session(duration_min=150)], DAY, ctx()) == "long"
    # two sessions summing past 150 are not "long"; over 120 total with no hard session is moderate
    two = [session(duration_min=80), session(sport="run", duration_min=80)]
    assert energy.day_type(two, DAY, ctx()) == "moderate"


def test_day_type_long_beats_hard():
    assert energy.day_type([session(duration_min=180, intensity="threshold")], DAY, ctx()) == "long"


def test_day_type_race_and_carb_load_for_a_priority():
    c = ctx(event_date=DAY + timedelta(days=6), event_priority="A")
    race_day = DAY + timedelta(days=6)
    assert energy.day_type([session(sport="run", duration_min=30)], race_day, c) == "race"
    assert energy.day_type([session(duration_min=45)], DAY + timedelta(days=5), c) == "carb_load"
    assert energy.day_type([], DAY + timedelta(days=4), c) == "carb_load"
    assert energy.day_type([], DAY + timedelta(days=3), c) == "rest"


def test_day_type_no_carb_load_for_b_priority():
    c = ctx(event_date=DAY + timedelta(days=6), event_priority="B")
    assert energy.day_type([], DAY + timedelta(days=6), c) == "race"
    assert energy.day_type([session(duration_min=45)], DAY + timedelta(days=5), c) == "easy"
