from datetime import date, datetime

import pytest

from tri_core.db import repo
from tri_core.db.models import AthleteProfileRow, DailyMetricsRow, WorkoutRow

pytestmark = pytest.mark.db


def _workout(**over):
    base = dict(
        tp_workout_id="w1",
        workout_date=date(2026, 9, 1),
        sport="bike",
        sport_raw="Bike",
        title="Endurance",
        description=None,
        completed=True,
        planned_duration_sec=5400,
        planned_distance_m=None,
        planned_tss=80.0,
        planned_if=0.7,
        actual_duration_sec=5500,
        actual_distance_m=45000.0,
        actual_tss=84.2,
        actual_if=0.72,
        normalized_power=210,
        avg_power=200,
        avg_hr=140,
        avg_cadence=88.0,
        elevation_gain_m=300.0,
        calories=1200,
        feeling=7,
        rpe=5,
        comments=[],
        structure=None,
        raw={"id": "w1"},
    )
    base.update(over)
    return WorkoutRow(**base)


def test_upsert_workouts_is_idempotent(db):
    assert repo.upsert_workouts(db, [_workout()]) == 1
    assert repo.upsert_workouts(db, [_workout(title="Renamed")]) == 1
    rows = repo.list_workouts_between(db, date(2026, 8, 31), date(2026, 9, 2))
    assert len(rows) == 1
    assert rows[0]["title"] == "Renamed"
    assert rows[0]["completed"] is True


def test_set_garmin_match(db):
    repo.upsert_workouts(db, [_workout()])
    repo.set_garmin_match(db, "w1", "g123", datetime(2026, 9, 1, 6, 30))
    row = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert row["garmin_activity_id"] == "g123"
    assert row["start_time_local"] == datetime(2026, 9, 1, 6, 30)


def test_upsert_workouts_preserves_garmin_match(db):
    repo.upsert_workouts(db, [_workout()])
    repo.set_garmin_match(db, "w1", "g123", datetime(2026, 9, 1, 6, 30))
    repo.upsert_workouts(db, [_workout(title="Again")])
    row = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert row["garmin_activity_id"] == "g123"


def test_daily_metrics_merge_partial_rows(db):
    d = date(2026, 9, 1)
    repo.upsert_daily_metrics(
        db, [DailyMetricsRow(metric_date=d, sleep_seconds=25000, resting_hr=48)]
    )
    repo.upsert_daily_metrics(
        db, [DailyMetricsRow(metric_date=d, ctl=60.5, atl=70.1, tsb=-9.6, tss_day=85)]
    )
    row = db.execute("select * from daily_metrics where metric_date=%s", (d,)).fetchone()
    assert row["sleep_seconds"] == 25000
    assert row["resting_hr"] == 48
    assert float(row["ctl"]) == 60.5
    assert float(row["tss_day"]) == 85


def test_athlete_profile_single_row(db):
    repo.upsert_athlete_profile(
        db,
        AthleteProfileRow(
            tp_athlete_id="a1",
            ftp_watts=250,
            run_threshold_pace_sec_per_km=270,
            swim_css_sec_per_100m=95,
            lthr_bpm=165,
            max_hr_bpm=185,
            hr_zones=[{"z": 1}],
            power_zones=None,
            pace_zones=None,
            weight_kg=72.5,
            raw={"x": 1},
        ),
    )
    repo.upsert_athlete_profile(
        db,
        AthleteProfileRow(
            tp_athlete_id="a1",
            ftp_watts=255,
            run_threshold_pace_sec_per_km=None,
            swim_css_sec_per_100m=None,
            lthr_bpm=None,
            max_hr_bpm=None,
            hr_zones=None,
            power_zones=None,
            pace_zones=None,
            weight_kg=None,
            raw={"x": 2},
        ),
    )
    rows = db.execute("select * from athlete_profile").fetchall()
    assert len(rows) == 1
    assert rows[0]["ftp_watts"] == 255


def test_sync_state_roundtrip(db):
    assert repo.get_sync_state(db, "garmin") is None
    repo.set_sync_state(db, "garmin", date(2026, 9, 1), "ok", None)
    st = repo.get_sync_state(db, "garmin")
    assert st is not None and st.last_synced_date == date(2026, 9, 1) and st.last_status == "ok"
    repo.set_sync_state(db, "garmin", date(2026, 9, 2), "error", "boom")
    st = repo.get_sync_state(db, "garmin")
    assert st is not None and st.last_error == "boom" and st.last_synced_date == date(2026, 9, 2)
