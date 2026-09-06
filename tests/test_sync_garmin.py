import json
from datetime import date, datetime
from pathlib import Path

import pytest

from tri_analyze.db.models import DailyMetricsRow
from tri_analyze.sync.garmin import (
    GarminSnapshot,
    fetch_garmin,
    merge_daily,
    parse_activity_list,
    parse_readiness,
    parse_sleep_range,
    parse_stats,
)

FIX = Path("tests/fixtures/mcp")


def test_parse_sleep_range():
    out = parse_sleep_range(
        {
            "nights": [
                {
                    "date": "2026-09-01",
                    "sleep_seconds": 25000,
                    "sleep_score": 81,
                    "avg_overnight_hrv": 52,
                    "resting_heart_rate_bpm": 47,
                },
                {"date": "2026-09-02", "sleep_seconds": 21000},
            ]
        }
    )
    assert set(out) == {date(2026, 9, 1), date(2026, 9, 2)}
    r = out[date(2026, 9, 1)]
    assert (r.sleep_seconds, r.sleep_score, r.hrv_overnight_avg, r.resting_hr) == (
        25000,
        81,
        52,
        47,
    )
    assert out[date(2026, 9, 2)].sleep_score is None


def test_parse_sleep_range_tolerates_other_list_key():
    out = parse_sleep_range({"summaries": [{"date": "2026-09-01", "sleep_seconds": 1}]})
    assert out[date(2026, 9, 1)].sleep_seconds == 1


def test_parse_stats():
    r = parse_stats(
        {
            "date": "2026-09-01",
            "resting_heart_rate_bpm": 46,
            "avg_stress_level": 31,
            "body_battery_highest": 92,
            "body_battery_lowest": 20,
        }
    )
    assert r.metric_date == date(2026, 9, 1)
    assert (r.resting_hr, r.stress_avg, r.body_battery_high, r.body_battery_low) == (46, 31, 92, 20)


def test_parse_readiness_picks_highest_score():
    assert parse_readiness(
        [{"date": "2026-09-01", "score": 55}, {"date": "2026-09-01", "score": 68}]
    ) == (date(2026, 9, 1), 68)
    assert parse_readiness([]) is None
    assert parse_readiness({"date": "2026-09-01", "score": 70}) == (date(2026, 9, 1), 70)


def test_parse_activity_list():
    acts = parse_activity_list(
        {
            "activities": [
                {
                    "id": 111,
                    "name": "Morning Ride",
                    "type": "cycling",
                    "start_time": "2026-09-01 06:12:00",
                    "distance_meters": 45100.0,
                    "duration_seconds": 5580.2,
                    "avg_hr_bpm": 140,
                },
                {"id": 112, "type": "lap_swimming", "start_time": "2026-09-02 05:30:00"},
            ]
        }
    )
    assert acts[0].id == "111" and acts[0].sport == "bike"
    assert acts[0].start_time_local == datetime(2026, 9, 1, 6, 12)
    assert acts[0].duration_sec == 5580.2
    assert acts[1].sport == "swim" and acts[1].distance_m is None


def test_merge_daily_later_wins_and_raw_collects():
    d = date(2026, 9, 1)
    sleep = {
        d: DailyMetricsRow(
            metric_date=d, sleep_seconds=100, resting_hr=50, garmin_raw={"sleep": {"a": 1}}
        )
    }
    stats = {
        d: DailyMetricsRow(
            metric_date=d, resting_hr=48, stress_avg=30, garmin_raw={"stats": {"b": 2}}
        )
    }
    rows = merge_daily(sleep, stats)
    assert len(rows) == 1
    r = rows[0]
    assert r.sleep_seconds == 100 and r.resting_hr == 48 and r.stress_avg == 30
    assert r.garmin_raw == {"sleep": {"a": 1}, "stats": {"b": 2}}


@pytest.mark.skipif(
    not (FIX / "get_sleep_summary_range.json").exists(), reason="fixture not recorded"
)
def test_parse_recorded_sleep_range():
    payload = json.loads((FIX / "get_sleep_summary_range.json").read_text())["result"]
    out = parse_sleep_range(payload)
    assert out
    first = next(iter(out.values()))
    assert first.sleep_seconds and first.sleep_seconds > 3600


@pytest.mark.skipif(
    not (FIX / "get_activities_by_date.json").exists(), reason="fixture not recorded"
)
def test_parse_recorded_activities():
    payload = json.loads((FIX / "get_activities_by_date.json").read_text())["result"]
    acts = parse_activity_list(payload)
    assert acts and all(
        a.sport in ("swim", "bike", "run", "strength", "brick", "other") for a in acts
    )


class _FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def call_json(self, tool, args=None):
        self.calls.append((tool, args or {}))
        a = self.answers[tool]
        return a(args or {}) if callable(a) else a


async def test_fetch_garmin_paginates_and_walks_days():
    pages = {
        0: {
            "activities": [{"id": 1, "type": "running", "start_time": "2026-09-01 07:00:00"}],
            "has_more": True,
            "next_page": 1,
        },
        1: {
            "activities": [{"id": 2, "type": "cycling", "start_time": "2026-09-02 07:00:00"}],
            "has_more": False,
        },
    }
    client = _FakeClient(
        {
            "get_sleep_summary_range": lambda a: {
                "nights": [{"date": a["start_date"], "sleep_seconds": 1}]
            },
            "get_stats": lambda a: {"date": a["date"], "resting_heart_rate_bpm": 50},
            "get_training_readiness": lambda a: [{"date": a["date"], "score": 60}],
            "get_activities_by_date": lambda a: pages[a["page"]],
        }
    )
    snap = await fetch_garmin(client, date(2026, 9, 1), date(2026, 9, 3), log=lambda m: None)
    assert isinstance(snap, GarminSnapshot)
    assert [a.id for a in snap.activities] == ["1", "2"]
    assert len([c for c in client.calls if c[0] == "get_stats"]) == 3
    assert len([c for c in client.calls if c[0] == "get_training_readiness"]) == 3
    by_date = {r.metric_date: r for r in snap.daily}
    assert by_date[date(2026, 9, 2)].resting_hr == 50
    assert by_date[date(2026, 9, 2)].training_readiness == 60


async def test_fetch_garmin_tolerates_empty_days():
    client = _FakeClient(
        {
            "get_sleep_summary_range": None,
            "get_stats": None,
            "get_training_readiness": None,
            "get_activities_by_date": {"activities": [], "has_more": False},
        }
    )
    snap = await fetch_garmin(client, date(2026, 9, 1), date(2026, 9, 1), log=lambda m: None)
    assert snap.daily == [] and snap.activities == []
