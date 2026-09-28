import json
from datetime import date
from pathlib import Path

import pytest

from tri_analyze.repo import AthleteContext, load_athlete_context
from tri_analyze.testing import TODAY, athlete_context, seed_daily_metrics, seed_workouts
from tri_core.db import repo
from tri_core.db.models import AthleteProfileRow
from tri_core.testing import workout_row


def test_athlete_context_fixture_and_overrides():
    ctx = athlete_context()
    assert isinstance(ctx, AthleteContext) and ctx.today == TODAY == date(2026, 9, 6)
    assert ctx.profile and ctx.profile["ftp_watts"] == 230 and ctx.profile["lthr_bpm"] == 180
    assert ctx.profile["run_threshold_pace_sec_per_km"] == 270
    assert ctx.profile["swim_css_sec_per_100m"] == 104
    assert len(ctx.recent_days) == 1 and len(ctx.recent_workouts) == 1
    assert ctx.recent_workouts[0]["title"] == "Z2 ride" and ctx.recent_workouts[0]["completed"]
    later = athlete_context(today=date(2026, 9, 7), profile=None)
    assert later.today == date(2026, 9, 7) and later.profile is None
    assert AthleteContext(today=TODAY, profile=None).recent_days == []


def _seed_profile(db):
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
            weight_kg=70.5,
            raw={},
        ),
    )


@pytest.mark.db
def test_load_athlete_context_reads_profile_and_windows(db):
    _seed_profile(db)
    seed_daily_metrics(
        db,
        [
            {"metric_date": date(2026, 8, 29), "ctl": 10.0},  # 8 days back: out
            {"metric_date": date(2026, 8, 30), "ctl": 12.0},  # 7 days back: in
            {"metric_date": date(2026, 9, 5), "ctl": 15.2, "atl": 19.6, "tsb": -7.3},
            {"metric_date": date(2026, 9, 6), "ctl": 15.5},  # today: in
            {"metric_date": date(2026, 9, 7), "ctl": 16.0},  # tomorrow: out
        ],
    )
    seed_workouts(
        db,
        [
            {
                "tp_workout_id": "w1",
                "workout_date": date(2026, 8, 29),
                "sport": "bike",
                "title": "too old",
            },
            {
                "tp_workout_id": "w2",
                "workout_date": date(2026, 8, 30),
                "sport": "bike",
                "title": "edge back",
            },
            {
                "tp_workout_id": "w9",
                "workout_date": date(2026, 9, 8),
                "sport": "run",
                "title": "Tempo",
                "completed": False,
                "planned_tss": 70,
            },
            {
                "tp_workout_id": "a0",
                "workout_date": date(2026, 9, 8),
                "sport": "swim",
                "title": "same day, lower id",
                "completed": False,
            },
            {
                "tp_workout_id": "w3",
                "workout_date": date(2026, 9, 13),
                "sport": "swim",
                "title": "edge forward",
                "completed": False,
            },
            {
                "tp_workout_id": "w4",
                "workout_date": date(2026, 9, 14),
                "sport": "swim",
                "title": "too far",
                "completed": False,
            },
        ],
    )
    ctx = load_athlete_context(db, TODAY)
    assert ctx.today == TODAY
    assert ctx.profile and ctx.profile["ftp_watts"] == 230
    assert ctx.profile["weight_kg"] == 70.5 and isinstance(ctx.profile["weight_kg"], float)
    assert [d["metric_date"] for d in ctx.recent_days] == [
        date(2026, 8, 30),
        date(2026, 9, 5),
        date(2026, 9, 6),
    ]
    assert ctx.recent_days[1]["tsb"] == -7.3
    assert [(w["workout_date"], w["title"]) for w in ctx.recent_workouts] == [
        (date(2026, 8, 30), "edge back"),
        (date(2026, 9, 8), "same day, lower id"),  # ordered by date, then tp_workout_id
        (date(2026, 9, 8), "Tempo"),
        (date(2026, 9, 13), "edge forward"),
    ]
    assert (
        ctx.recent_workouts[2]["planned_tss"] == 70 and ctx.recent_workouts[2]["completed"] is False
    )


@pytest.mark.db
def test_load_athlete_context_with_empty_tables(db):
    ctx = load_athlete_context(db, TODAY)
    assert ctx.profile is None and ctx.recent_days == [] and ctx.recent_workouts == []


@pytest.mark.db
def test_context_skips_deleted_workouts(db):
    repo.upsert_workouts(db, [workout_row("keep", TODAY), workout_row("gone", TODAY)])
    repo.mark_missing_deleted(db, TODAY, TODAY, {"keep"})
    ctx = load_athlete_context(db, TODAY)
    assert [w["title"] for w in ctx.recent_workouts] == ["ride keep"]


@pytest.mark.db
def test_load_athlete_context_reads_the_zone_groups(db):
    settings = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "tri-core/tests/fixtures/mcp/tp_get_athlete_settings.json"
        ).read_text()
    )["result"]["settings"]
    repo.upsert_athlete_profile(
        db,
        AthleteProfileRow(
            tp_athlete_id="1",
            ftp_watts=230,
            run_threshold_pace_sec_per_km=270,
            swim_css_sec_per_100m=104,
            lthr_bpm=180,
            max_hr_bpm=182,
            hr_zones=settings["heartRateZones"],
            power_zones=settings["powerZones"],
            pace_zones=settings["speedZones"],
            weight_kg=70.5,
            raw={},
        ),
    )
    profile = load_athlete_context(db, TODAY).profile
    assert profile is not None
    assert profile["hr_zones"] == settings["heartRateZones"]
    assert profile["power_zones"] == settings["powerZones"]
    assert profile["pace_zones"] == settings["speedZones"]
