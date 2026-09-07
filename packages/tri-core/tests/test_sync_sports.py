import pytest

from tri_core.sync.sports import normalize_garmin_sport, normalize_tp_sport


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Swim", "swim"),
        ("Bike", "bike"),
        ("MtnBike", "bike"),
        ("Run", "run"),
        ("Brick", "brick"),
        ("Strength", "strength"),
        ("Race", "race"),
        ("DayOff", "rest"),
        ("Crosstrain", "other"),
        ("Walk", "other"),
        (None, "other"),
        ("bike", "bike"),
    ],
)
def test_tp(label, expected):
    assert normalize_tp_sport(label) == expected


@pytest.mark.parametrize(
    "key,expected",
    [
        ("running", "run"),
        ("trail_running", "run"),
        ("treadmill_running", "run"),
        ("cycling", "bike"),
        ("road_biking", "bike"),
        ("indoor_cycling", "bike"),
        ("virtual_ride", "bike"),
        ("lap_swimming", "swim"),
        ("open_water_swimming", "swim"),
        ("strength_training", "strength"),
        ("multi_sport", "brick"),
        ("triathlon", "brick"),
        ("yoga", "other"),
        (None, "other"),
    ],
)
def test_garmin(key, expected):
    assert normalize_garmin_sport(key) == expected
