from datetime import date, timedelta

import pytest

from tri_wellness.labs.training_context import load_training_context
from tri_wellness.testing import seed_daily_metrics, seed_workouts

pytestmark = pytest.mark.db

D = date(2031, 1, 15)  # far from any synced data


def day(n: int) -> date:
    return D + timedelta(days=n)


def seed_quiet_month(db, sleep=27000, hrv=60):
    seed_daily_metrics(
        db,
        [
            {
                "metric_date": day(-n),
                "sleep_seconds": sleep,
                "hrv_overnight_avg": hrv,
                "ctl": 60.0 + n,
                "atl": 62.0 + n,
                "tsb": -2.0,
                "tss_day": 50.0,
            }
            for n in range(0, 31)
        ],
    )


def test_empty_database_gives_nones(db):
    t = load_training_context(db, D)
    assert t.drawn_on == D
    assert t.ctl is None and t.atl is None and t.tsb is None and t.tss_7d is None
    assert t.last_sessions == []
    assert t.sleep_2n_avg_sec is None and t.hrv_30d_avg is None


def test_sessions_window_hardest_first_completed_only(db):
    seed_workouts(
        db,
        [
            {
                "tp_workout_id": "w-ride",
                "workout_date": day(-2),
                "sport": "bike",
                "title": "long ride",
                "actual_duration_sec": 10800,
                "actual_tss": 200,
            },
            {
                "tp_workout_id": "w-run",
                "workout_date": day(-1),
                "sport": "run",
                "title": "easy",
                "actual_duration_sec": 2700,
                "actual_tss": 40,
            },
            {
                "tp_workout_id": "w-swim",
                "workout_date": day(-3),
                "sport": "swim",
                "title": "swim",
                "actual_duration_sec": 3600,
                "actual_tss": 60,
            },
            {
                "tp_workout_id": "w-planned",
                "workout_date": day(-2),
                "sport": "run",
                "title": "skipped",
                "completed": False,
                "planned_tss": 300,
            },
            {
                "tp_workout_id": "w-drawday",
                "workout_date": day(0),
                "sport": "bike",
                "title": "same day",
                "actual_duration_sec": 7200,
                "actual_tss": 180,
            },
            {
                "tp_workout_id": "w-old",
                "workout_date": day(-4),
                "sport": "run",
                "title": "too old",
                "actual_duration_sec": 9000,
                "actual_tss": 220,
            },
            {
                "tp_workout_id": "w-notss",
                "workout_date": day(-1),
                "sport": "strength",
                "title": "gym",
                "actual_duration_sec": 1800,
                "actual_tss": None,
            },
        ],
    )
    t = load_training_context(db, D)
    assert [s["title"] for s in t.last_sessions] == ["long ride", "swim", "easy"]
    assert t.last_sessions[0] == {
        "date": day(-2).isoformat(),
        "sport": "bike",
        "duration_min": 180,
        "tss": 200.0,
        "title": "long ride",
    }


def test_load_from_draw_day_row_and_seven_day_tss(db):
    seed_quiet_month(db)
    t = load_training_context(db, D)
    assert (t.ctl, t.atl, t.tsb) == (60.0, 62.0, -2.0)
    assert t.tss_7d == 350.0  # seven days before the draw, not the draw day


def test_load_falls_back_to_most_recent_row_in_seven_days(db):
    seed_daily_metrics(db, [{"metric_date": day(-3), "ctl": 55.0, "atl": 70.0, "tsb": -15.0}])
    seed_daily_metrics(db, [{"metric_date": day(-9), "ctl": 40.0, "atl": 40.0, "tsb": 0.0}])
    t = load_training_context(db, D)
    assert (t.ctl, t.atl, t.tsb) == (55.0, 70.0, -15.0)
    assert load_training_context(db, day(-10)).ctl is None  # both rows are after that draw


def test_sleep_and_hrv_two_nights_versus_thirty_days(db):
    seed_quiet_month(db)
    seed_daily_metrics(
        db,
        [
            {"metric_date": day(-1), "sleep_seconds": 21600, "hrv_overnight_avg": 50},
            {"metric_date": day(0), "sleep_seconds": 18000, "hrv_overnight_avg": 40},
        ],
    )
    t = load_training_context(db, D)
    assert t.sleep_2n_avg_sec == 19800  # mean of the two nights ending on the draw morning
    assert t.hrv_2n_avg == 45
    # the baseline is the 30 days before the draw day; day(-1) is in it, day(0) is not
    assert t.sleep_30d_avg_sec == round((29 * 27000 + 21600) / 30)
    assert t.hrv_30d_avg == round((29 * 60 + 50) / 30)


def test_null_nights_are_skipped(db):
    seed_daily_metrics(
        db,
        [
            {"metric_date": day(-1), "sleep_seconds": None, "hrv_overnight_avg": None},
            {"metric_date": day(0), "sleep_seconds": 25200, "hrv_overnight_avg": 55},
        ],
    )
    t = load_training_context(db, D)
    assert t.sleep_2n_avg_sec == 25200 and t.hrv_2n_avg == 55
    assert t.sleep_30d_avg_sec is None
