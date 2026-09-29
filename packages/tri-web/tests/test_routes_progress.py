"""GET /api/progress over the rolled-back test database."""

from datetime import date

import pytest

pytestmark = pytest.mark.db

TODAY = date(2026, 9, 16)


def workout(conn, wid, day, sport, *, completed=True, deleted=False, **cols):
    base = {
        "actual_duration_sec": None,
        "actual_distance_m": None,
        "actual_tss": None,
        "elevation_gain_m": None,
        "calories": None,
        "planned_duration_sec": None,
    }
    base.update(cols)
    conn.execute(
        "insert into workouts (tp_workout_id, workout_date, sport, completed, "
        "actual_duration_sec, actual_distance_m, actual_tss, elevation_gain_m, calories, "
        "planned_duration_sec, raw, deleted_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', %s)",
        (
            wid,
            day,
            sport,
            completed,
            base["actual_duration_sec"],
            base["actual_distance_m"],
            base["actual_tss"],
            base["elevation_gain_m"],
            base["calories"],
            base["planned_duration_sec"],
            "2026-09-10T00:00:00Z" if deleted else None,
        ),
    )


async def test_default_range_returns_the_view(runtime, client, nocommit):
    workout(
        nocommit, "w1", date(2026, 9, 14), "bike", actual_duration_sec=3600, actual_distance_m=30000
    )
    nocommit.execute(
        "insert into daily_metrics (metric_date, ctl, atl, tsb) values (%s, 40, 44, -4)", (TODAY,)
    )
    async with client(runtime(today=TODAY)) as c:
        r = await c.get("/api/progress")
    assert r.status_code == 200
    body = r.json()
    assert body["range"] == "12m" and body["end"] == "2026-09-16"
    assert body["as_of"] == "2026-09-16"
    assert body["weeks"][-1]["partial"] is True
    assert body["weeks"][-1]["by_sport"]["bike"]["duration_sec"] == 3600
    assert body["pmc"][-1] == {
        "date": "2026-09-16",
        "ctl": 40.0,
        "atl": 44.0,
        "tsb": -4.0,
        "tss": None,
    }


@pytest.mark.parametrize("value", ["6w", "6m", "12m", "all"])
async def test_every_range_is_accepted(runtime, client, value):
    async with client(runtime(today=TODAY)) as c:
        r = await c.get("/api/progress", params={"range": value})
    assert r.status_code == 200 and r.json()["range"] == value


async def test_an_invalid_range_is_a_422(runtime, client):
    async with client(runtime(today=TODAY)) as c:
        r = await c.get("/api/progress", params={"range": "3d"})
    assert r.status_code == 422


async def test_deleted_workouts_and_old_rows_are_left_out(runtime, client, nocommit):
    workout(nocommit, "gone", date(2026, 9, 15), "run", deleted=True, actual_duration_sec=999)
    workout(nocommit, "old", date(2025, 1, 6), "run", actual_duration_sec=888)
    async with client(runtime(today=TODAY)) as c:
        six = (await c.get("/api/progress", params={"range": "6w"})).json()
        everything = (await c.get("/api/progress", params={"range": "all"})).json()
    assert six["share"]["completed"]["duration_sec"] == {}
    assert everything["share"]["completed"]["duration_sec"] == {"run": 888.0}


async def test_an_empty_database_still_answers(runtime, client):
    async with client(runtime(today=TODAY)) as c:
        r = await c.get("/api/progress")
    body = r.json()
    assert r.status_code == 200 and body["as_of"] is None
    assert all(p["ctl"] is None for p in body["pmc"])


async def test_the_365_day_ramp_survives_a_curve_that_lags_today(runtime, client, nocommit):
    lag = date(2026, 9, 14)  # two days behind today
    for d, ctl in ((lag, 40), (date(2025, 9, 14), 30)):
        nocommit.execute("insert into daily_metrics (metric_date, ctl) values (%s, %s)", (d, ctl))
    async with client(runtime(today=TODAY)) as c:
        body = (await c.get("/api/progress", params={"range": "6w"})).json()
    ramp = {r["days"]: r for r in body["ramp"]}
    assert body["as_of"] == "2026-09-14" and ramp[365]["delta"] == 10.0
