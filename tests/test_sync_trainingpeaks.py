import json
from datetime import date
from pathlib import Path

import pytest

from tri_analyze.sync.trainingpeaks import (
    TPSnapshot,
    fetch_trainingpeaks,
    parse_athlete_settings,
    parse_fitness,
    parse_workout_detail,
)

FIX = Path("tests/fixtures/mcp")

DETAIL = {
    "id": "123",
    "date": "2026-09-01",
    "title": "Z2 ride",
    "sport": "Bike",
    "workout_type": 2,
    "description": "Steady",
    "rpe": 5,
    "feeling": 7,
    "metrics": {
        "duration_planned": 1.5,
        "duration_actual": 1.55,
        "tss_planned": 80.0,
        "tss_actual": 84.2,
        "if_planned": 0.7,
        "if_actual": 0.72,
        "distance_planned_km": None,
        "distance_actual_km": 45.1,
        "avg_power": 200.4,
        "normalized_power": 210.0,
        "avg_hr": 140,
        "avg_cadence": 88.2,
        "elevation_gain": 300.0,
        "calories": 1200,
    },
    "completed": True,
    "structured_workout": {"steps": []},
    "workout_comments": [{"comment": "felt good"}],
}


def test_parse_workout_detail_units():
    row = parse_workout_detail(DETAIL)
    assert row.tp_workout_id == "123"
    assert row.workout_date == date(2026, 9, 1)
    assert row.sport == "bike" and row.sport_raw == "Bike"
    assert row.planned_duration_sec == 5400
    assert row.actual_duration_sec == 5580
    assert row.actual_distance_m == 45100.0
    assert row.planned_distance_m is None
    assert row.avg_power == 200 and row.normalized_power == 210
    assert row.completed is True
    assert row.comments == [{"comment": "felt good"}]
    assert row.raw is DETAIL


def test_parse_workout_detail_planned_only():
    d = {
        **DETAIL,
        "completed": None,
        "metrics": {**DETAIL["metrics"], "duration_actual": None, "tss_actual": None},
    }
    row = parse_workout_detail(d)
    assert row.completed is False
    assert row.actual_duration_sec is None


def test_parse_workout_detail_completed_null_but_has_duration():
    # TP returns completed=null even for finished workouts; duration_actual decides.
    d = {**DETAIL, "completed": None}
    assert parse_workout_detail(d).completed is True


def test_parse_fitness():
    rows = parse_fitness(
        {
            "daily_data": [
                {"date": "2026-09-01", "tss": 85, "ctl": 60.5, "atl": 70.1, "tsb": -9.6},
                {"date": "2026-09-02", "tss": 0, "ctl": 59.1, "atl": 60.0, "tsb": -0.9},
            ]
        }
    )
    assert [r.metric_date for r in rows] == [date(2026, 9, 1), date(2026, 9, 2)]
    assert rows[0].ctl == 60.5 and rows[0].tss_day == 85
    assert rows[0].sleep_seconds is None


def test_parse_athlete_settings_minimal():
    payload = {
        "settings": {
            "athleteId": 42,
            "weight": 72.5,
            "powerZones": [
                {
                    "workoutTypeId": 2,
                    "threshold": 250,
                    "zones": [{"label": "Z1", "minimum": 0, "maximum": 137}],
                }
            ],
            "heartRateZones": [
                {
                    "workoutTypeId": 3,
                    "threshold": 165,
                    "maximumHeartRate": 185,
                    "restingHeartRate": 48,
                    "zones": [],
                }
            ],
            "speedZones": [
                {"workoutTypeId": 3, "threshold": 3.7, "zones": []},
                {"workoutTypeId": 1, "threshold": 1.05, "zones": []},
            ],
        }
    }
    row = parse_athlete_settings(payload)
    assert row.tp_athlete_id == "42"
    assert row.ftp_watts == 250
    assert row.lthr_bpm == 165 and row.max_hr_bpm == 185
    assert row.weight_kg == 72.5
    assert row.run_threshold_pace_sec_per_km == 270  # 1000 m / 3.7 m/s
    assert row.swim_css_sec_per_100m == 95  # 100 m / 1.05 m/s
    assert row.power_zones[0]["workoutTypeId"] == 2
    assert row.raw == payload["settings"]


def test_parse_athlete_settings_empty():
    row = parse_athlete_settings({"settings": {}})
    assert row.ftp_watts is None and row.raw == {}


@pytest.mark.skipif(
    not (FIX / "tp_get_workout_completed.json").exists(), reason="fixture not recorded"
)
def test_parse_recorded_completed_workout():
    payload = json.loads((FIX / "tp_get_workout_completed.json").read_text())["result"]
    row = parse_workout_detail(payload)
    assert row.completed is True
    assert row.actual_duration_sec and 60 < row.actual_duration_sec < 12 * 3600


@pytest.mark.skipif(
    not (FIX / "tp_get_athlete_settings.json").exists(), reason="fixture not recorded"
)
def test_parse_recorded_settings():
    payload = json.loads((FIX / "tp_get_athlete_settings.json").read_text())["result"]
    row = parse_athlete_settings(payload)
    assert row.tp_athlete_id
    assert row.ftp_watts and row.ftp_watts > 100
    assert row.lthr_bpm and row.lthr_bpm > 120
    assert row.run_threshold_pace_sec_per_km and 180 < row.run_threshold_pace_sec_per_km < 420


class _FakeClient:
    """Answers call_json from a dict keyed by tool name; records calls."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def call_json(self, tool, args=None):
        self.calls.append((tool, args or {}))
        a = self.answers[tool]
        return a(args or {}) if callable(a) else a


async def test_fetch_trainingpeaks_chunks_and_details():
    listed = {
        "workouts": [
            {"id": "1", "date": "2026-01-05", "type": "completed", "sport": "Run"},
            {"id": "2", "date": "2026-02-05", "type": "planned", "sport": "Bike"},
        ]
    }
    client = _FakeClient(
        {
            "tp_get_athlete_settings": {"settings": {"athleteId": 7}},
            "tp_get_workouts": listed,
            "tp_get_workout": lambda a: {**DETAIL, "id": a["workout_id"]},
            "tp_get_fitness": {
                "daily_data": [{"date": "2026-01-05", "tss": 50, "ctl": 40, "atl": 45, "tsb": -5}]
            },
        }
    )
    snap = await fetch_trainingpeaks(
        client, date(2026, 1, 1), date(2026, 6, 30), log=lambda m: None
    )
    assert isinstance(snap, TPSnapshot)
    assert snap.profile is not None and snap.profile.tp_athlete_id == "7"
    list_calls = [c for c in client.calls if c[0] == "tp_get_workouts"]
    assert len(list_calls) == 2  # 181 days -> two <=90-day chunks
    assert all(
        (date.fromisoformat(c[1]["end_date"]) - date.fromisoformat(c[1]["start_date"])).days <= 90
        for c in list_calls
    )
    detail_ids = sorted(c[1]["workout_id"] for c in client.calls if c[0] == "tp_get_workout")
    assert detail_ids == ["1", "2"]  # de-duplicated across chunks
    assert {w.tp_workout_id for w in snap.workouts} == {"1", "2"}
    fit_calls = [c for c in client.calls if c[0] == "tp_get_fitness"]
    assert len(fit_calls) == 2
    assert snap.fitness[0].ctl == 40
