from datetime import date

import pytest

from tri_analyze.agent.prompt import AthleteContext, load_athlete_context, render_system_prompt
from tri_core.db import repo
from tri_core.db.models import AthleteProfileRow, DailyMetricsRow, WorkoutRow

TODAY = date(2026, 9, 6)


def _ctx(**over):
    base = dict(
        today=TODAY,
        profile={
            "ftp_watts": 230,
            "lthr_bpm": 180,
            "run_threshold_pace_sec_per_km": 270,
            "swim_css_sec_per_100m": 104,
            "max_hr_bpm": 182,
        },
        recent_days=[
            {
                "metric_date": date(2026, 9, 5),
                "tss_day": 55,
                "ctl": 15.2,
                "atl": 19.6,
                "tsb": -7.3,
                "sleep_score": 79,
                "hrv_overnight_avg": 71,
                "training_readiness": 51,
            }
        ],
        recent_workouts=[
            {
                "workout_date": date(2026, 9, 5),
                "sport": "bike",
                "title": "Z2 ride",
                "completed": True,
                "planned_tss": 60,
                "actual_tss": 55,
            }
        ],
    )
    base.update(over)
    return AthleteContext(**base)


def test_render_includes_profile_and_load():
    text = render_system_prompt(_ctx(), live_tools=["get_activity_splits"])
    assert "2026-09-06" in text
    assert "230" in text and "4:30" in text  # FTP and run threshold pace formatted mm:ss/km
    assert "1:44" in text  # swim CSS per 100 m
    assert "CTL 15.2" in text and "TSB -7.3" in text
    assert "Z2 ride" in text
    assert "get_activity_splits" in text
    assert "query_training_db" in text


def test_render_without_profile_or_data():
    text = render_system_prompt(
        _ctx(profile=None, recent_days=[], recent_workouts=[]), live_tools=[]
    )
    assert "not available" in text.lower()
    assert "no live tools" in text.lower()


def test_render_feedback_rules_present():
    text = render_system_prompt(_ctx(), live_tools=[])
    for phrase in ("planned vs", "zones", "CTL/ATL/TSB", "takeaway", "SQL"):
        assert phrase.lower() in text.lower(), phrase


def test_render_is_deterministic():
    assert render_system_prompt(_ctx(), []) == render_system_prompt(_ctx(), [])


@pytest.mark.db
def test_load_athlete_context_reads_tables(db):
    repo.upsert_athlete_profile(
        db,
        AthleteProfileRow(
            tp_athlete_id="1",
            ftp_watts=230,
            run_threshold_pace_sec_per_km=270,
            swim_css_sec_per_100m=104,
            lthr_bpm=180,
            max_hr_bpm=182,
            hr_zones=None,
            power_zones=None,
            pace_zones=None,
            weight_kg=None,
            raw={},
        ),
    )
    repo.upsert_daily_metrics(
        db, [DailyMetricsRow(metric_date=date(2026, 9, 5), ctl=15.2, atl=19.6, tsb=-7.3)]
    )
    repo.upsert_workouts(
        db,
        [
            WorkoutRow(
                tp_workout_id="w9",
                workout_date=date(2026, 9, 8),
                sport="run",
                sport_raw="Run",
                title="Tempo",
                description=None,
                completed=False,
                planned_duration_sec=3600,
                planned_distance_m=None,
                planned_tss=70,
                planned_if=None,
                actual_duration_sec=None,
                actual_distance_m=None,
                actual_tss=None,
                actual_if=None,
                normalized_power=None,
                avg_power=None,
                avg_hr=None,
                avg_cadence=None,
                elevation_gain_m=None,
                calories=None,
                feeling=None,
                rpe=None,
                comments=None,
                structure=None,
                raw={},
            )
        ],
    )
    ctx = load_athlete_context(db, TODAY)
    assert ctx.profile and ctx.profile["ftp_watts"] == 230
    assert any(d["metric_date"] == date(2026, 9, 5) for d in ctx.recent_days)
    assert any(w["title"] == "Tempo" for w in ctx.recent_workouts)  # upcoming plan included
