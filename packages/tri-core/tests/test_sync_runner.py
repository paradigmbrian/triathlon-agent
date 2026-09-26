from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

import pytest

from tri_core.config import Settings
from tri_core.db import repo
from tri_core.db.models import SyncState
from tri_core.sync.runner import (
    GARMIN_FIRST_RUN_DAYS,
    SYNC_AHEAD_DAYS,
    TP_FIRST_RUN_DAYS,
    resolve_window,
    run_sync,
)
from tri_core.sync.trainingpeaks import fetch_trainingpeaks

TODAY = date(2026, 9, 6)


def test_resolve_window_first_run():
    assert resolve_window(None, None, False, TODAY, TP_FIRST_RUN_DAYS) == (date(2025, 9, 6), TODAY)
    assert resolve_window(None, None, False, TODAY, GARMIN_FIRST_RUN_DAYS) == (
        date(2026, 7, 8),
        TODAY,
    )


def test_resolve_window_incremental_with_overlap():
    st = SyncState("garmin", date(2026, 9, 1), datetime(2026, 9, 1), "ok", None)
    assert resolve_window(st, None, False, TODAY, 60) == (date(2026, 8, 29), TODAY)


def test_resolve_window_since_and_full_override():
    st = SyncState("garmin", date(2026, 9, 1), datetime(2026, 9, 1), "ok", None)
    assert resolve_window(st, date(2026, 6, 1), False, TODAY, 60) == (date(2026, 6, 1), TODAY)
    assert resolve_window(st, None, True, TODAY, 60) == (date(2026, 7, 8), TODAY)


class _Fake:
    def __init__(self, answers, fail=False):
        self.answers = answers
        self.fail = fail

    async def call_json(self, tool, args=None):
        if self.fail:
            raise RuntimeError("server down")
        a = self.answers[tool]
        return a(args or {}) if callable(a) else a


def _tp_answers():
    detail = {
        "id": "w1",
        "date": "2026-09-01",
        "sport": "Bike",
        "metrics": {"duration_actual": 1.0, "tss_actual": 50},
        "completed": True,
    }
    return {
        "tp_get_athlete_settings": {"settings": {"athleteId": 9}},
        "tp_get_workouts": {
            "workouts": [{"id": "w1", "date": "2026-09-01", "type": "completed", "sport": "Bike"}]
        },
        "tp_get_workout": detail,
        "tp_get_fitness": {
            "daily_data": [{"date": "2026-09-01", "tss": 50, "ctl": 40, "atl": 45, "tsb": -5}]
        },
    }


def _garmin_answers():
    return {
        "get_sleep_summary_range": {"nights": [{"date": "2026-09-01", "sleep_seconds": 27000}]},
        "get_stats": lambda a: {"date": a["date"], "resting_heart_rate_bpm": 49},
        "get_training_readiness": lambda a: [{"date": a["date"], "score": 71}],
        "get_activities_by_date": {
            "activities": [
                {
                    "id": 555,
                    "type": "cycling",
                    "start_time": "2026-09-01 06:00:00",
                    "duration_seconds": 3610.0,
                }
            ],
            "has_more": False,
        },
    }


def _factory(fake):
    @asynccontextmanager
    async def _open():
        yield fake

    return _open


class _NoClose:
    """Wraps the test connection so the runner's `with connect(...)` and commit()
    don't end the test transaction."""

    def __init__(self, conn):
        self._c = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        pass

    def rollback(self):
        pass

    def __getattr__(self, name):
        return getattr(self._c, name)


@pytest.mark.db
async def test_run_sync_end_to_end(db, monkeypatch):
    settings = Settings(_env_file=None)
    settings.database_url = settings.test_database_url
    monkeypatch.setattr("tri_core.sync.runner.connect", lambda url: _NoClose(db))

    report = await run_sync(
        settings,
        since=date(2026, 8, 30),
        log=lambda m: None,
        open_tp=_factory(_Fake(_tp_answers())),
        open_garmin=_factory(_Fake(_garmin_answers())),
    )
    assert report.ok, report
    statuses = {r.source: r.status for r in report.results}
    assert statuses == {"trainingpeaks": "ok", "garmin": "ok"}

    w = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert w["garmin_activity_id"] == "555"
    assert w["start_time_local"] == datetime(2026, 9, 1, 6, 0)
    dm = db.execute(
        "select * from daily_metrics where metric_date = %s", (date(2026, 9, 1),)
    ).fetchone()
    assert dm["sleep_seconds"] == 27000 and dm["training_readiness"] == 71
    assert float(dm["ctl"]) == 40
    assert repo.get_sync_state(db, "garmin").last_status == "ok"
    profile = db.execute("select ftp_watts, tp_athlete_id from athlete_profile").fetchone()
    assert profile["tp_athlete_id"] == "9"


@pytest.mark.db
async def test_run_sync_isolates_source_failure(db, monkeypatch):
    settings = Settings(_env_file=None)
    settings.database_url = settings.test_database_url
    monkeypatch.setattr("tri_core.sync.runner.connect", lambda url: _NoClose(db))

    report = await run_sync(
        settings,
        since=date(2026, 8, 30),
        log=lambda m: None,
        open_tp=_factory(_Fake(_tp_answers())),
        open_garmin=_factory(_Fake({}, fail=True)),
    )
    assert not report.ok
    statuses = {r.source: r.status for r in report.results}
    assert statuses == {"trainingpeaks": "ok", "garmin": "error"}
    assert repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))
    st = repo.get_sync_state(db, "garmin")
    assert st.last_status == "error" and "server down" in (st.last_error or "")


class _DeadConn:
    """A connection whose writes fail after the source did; connect() returns it."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        pass

    def rollback(self):
        pass


async def test_a_failing_state_write_is_reported_with_the_source_error(monkeypatch):
    settings = Settings(_env_file=None)
    monkeypatch.setattr("tri_core.sync.runner.connect", lambda url: _DeadConn())
    monkeypatch.setattr(repo, "get_sync_state", lambda conn, source: None)

    def dead_write(conn, source, last, status, error):
        raise RuntimeError("the connection is closed")

    monkeypatch.setattr(repo, "set_sync_state", dead_write)
    lines: list[str] = []
    report = await run_sync(
        settings,
        since=date(2026, 8, 30),
        sources=("garmin",),
        log=lines.append,
        open_garmin=_factory(_Fake({}, fail=True)),
    )
    assert not report.ok
    (result,) = report.results
    assert result.source == "garmin" and result.status == "error"
    assert "server down" in (result.error or "") and "the connection is closed" in (
        result.error or ""
    )
    assert any("could not record the error state" in line for line in lines)


def test_resolve_window_reaches_ahead():
    st = SyncState("trainingpeaks", date(2026, 9, 1), datetime(2026, 9, 1), "ok", None)
    ahead = date(2026, 10, 4)  # TODAY + 28
    assert SYNC_AHEAD_DAYS == 28
    assert resolve_window(st, None, False, TODAY, 365, ahead_days=28) == (date(2026, 8, 29), ahead)
    assert resolve_window(None, None, False, TODAY, 365, ahead_days=28) == (date(2025, 9, 6), ahead)
    assert resolve_window(st, date(2026, 6, 1), False, TODAY, 365, ahead_days=28) == (
        date(2026, 6, 1),
        ahead,
    )


def _detail(wid, day):
    return {
        "id": wid,
        "date": day,
        "sport": "Bike",
        "title": f"ride {wid}",
        "metrics": {"tss_planned": 50},
    }


def _tp_calendar(listing):
    """TrainingPeaks answers whose listing is the `listing` dict, so a test can change it."""
    days = {"w1": "2026-09-01", "w2": "2026-09-02"}
    return {
        "tp_get_athlete_settings": {"settings": {"athleteId": 9}},
        "tp_get_workouts": listing,
        "tp_get_workout": lambda a: _detail(a["workout_id"], days[a["workout_id"]]),
        "tp_get_fitness": {"daily_data": []},
    }


async def test_fetch_records_listed_ids_and_completeness():
    listing = {"workouts": [{"id": "w1", "date": "2026-09-01"}, {"id": "w2", "date": "2026-09-02"}]}
    snap = await fetch_trainingpeaks(
        _Fake(_tp_calendar(listing)), date(2026, 8, 30), date(2026, 9, 3), log=lambda m: None
    )
    assert snap.listed_ids == {"w1", "w2"} and snap.listing_complete is True
    broken = await fetch_trainingpeaks(
        _Fake(_tp_calendar(None)), date(2026, 8, 30), date(2026, 9, 3), log=lambda m: None
    )
    assert broken.listed_ids == set() and broken.listing_complete is False


async def _tp_sync(db, monkeypatch, answers, lines):
    settings = Settings(_env_file=None)
    settings.database_url = settings.test_database_url
    monkeypatch.setattr("tri_core.sync.runner.connect", lambda url: _NoClose(db))
    return await run_sync(
        settings,
        since=date(2026, 8, 30),
        sources=("trainingpeaks",),
        log=lines.append,
        open_tp=_factory(_Fake(answers)),
    )


@pytest.mark.db
async def test_a_workout_removed_from_tp_is_tombstoned_then_restored(db, monkeypatch):
    both = [{"id": "w1", "date": "2026-09-01"}, {"id": "w2", "date": "2026-09-02"}]
    listing = {"workouts": list(both)}
    answers = _tp_calendar(listing)
    d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
    lines: list[str] = []

    assert (await _tp_sync(db, monkeypatch, answers, lines)).ok
    assert [w["tp_workout_id"] for w in repo.list_workouts_between(db, d1, d2)] == ["w1", "w2"]

    listing["workouts"] = both[:1]  # w2 deleted in TrainingPeaks
    lines.clear()
    assert (await _tp_sync(db, monkeypatch, answers, lines)).ok
    assert [w["tp_workout_id"] for w in repo.list_workouts_between(db, d1, d2)] == ["w1"]
    every = repo.list_workouts_between(db, d1, d2, include_deleted=True)
    assert [w["deleted_at"] is not None for w in every] == [False, True]
    assert any("1 deleted, 0 restored" in line for line in lines)

    listing["workouts"] = list(both)  # w2 back
    lines.clear()
    assert (await _tp_sync(db, monkeypatch, answers, lines)).ok
    assert [w["tp_workout_id"] for w in repo.list_workouts_between(db, d1, d2)] == ["w1", "w2"]
    assert any("0 deleted, 1 restored" in line for line in lines)


@pytest.mark.db
async def test_a_failed_listing_deletes_nothing(db, monkeypatch):
    listing = {"workouts": [{"id": "w1", "date": "2026-09-01"}, {"id": "w2", "date": "2026-09-02"}]}
    lines: list[str] = []
    assert (await _tp_sync(db, monkeypatch, _tp_calendar(listing), lines)).ok
    lines.clear()
    assert (await _tp_sync(db, monkeypatch, _tp_calendar(None), lines)).ok
    live = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 2))
    assert [w["tp_workout_id"] for w in live] == ["w1", "w2"]
    assert any("deletions not reconciled" in line for line in lines)


@pytest.mark.db
async def test_tp_lands_future_workouts_and_the_watermark_stops_at_today(db, monkeypatch):
    ahead = (date.today() + timedelta(days=20)).isoformat()
    answers = _tp_calendar({"workouts": [{"id": "w9", "date": ahead}]})
    answers["tp_get_workout"] = lambda a: _detail("w9", ahead)
    assert (await _tp_sync(db, monkeypatch, answers, [])).ok
    day = date.fromisoformat(ahead)
    assert [w["tp_workout_id"] for w in repo.list_workouts_between(db, day, day)] == ["w9"]
    assert repo.get_sync_state(db, "trainingpeaks").last_synced_date == date.today()


@pytest.mark.db
async def test_future_fitness_is_not_stored(db, monkeypatch):
    future = date.today() + timedelta(days=5)
    answers = _tp_calendar({"workouts": []})
    answers["tp_get_fitness"] = {
        "daily_data": [
            {"date": "2026-09-01", "tss": 50, "ctl": 40, "atl": 45, "tsb": -5},
            {"date": future.isoformat(), "tss": 0, "ctl": 55, "atl": 30, "tsb": 25},
        ]
    }
    assert (await _tp_sync(db, monkeypatch, answers, [])).ok
    got = db.execute(
        "select metric_date from daily_metrics where metric_date in (%s, %s) order by 1",
        (date(2026, 9, 1), future),
    ).fetchall()
    assert [r["metric_date"] for r in got] == [date(2026, 9, 1)]


@pytest.mark.db
async def test_garmin_keeps_every_activity_and_a_brick_gets_both_legs(db, monkeypatch):
    settings = Settings(_env_file=None)
    settings.database_url = settings.test_database_url
    monkeypatch.setattr("tri_core.sync.runner.connect", lambda url: _NoClose(db))
    brick = {
        "id": "w1",
        "date": "2026-09-01",
        "sport": "Brick",
        "metrics": {"duration_actual": 4800 / 3600},
        "completed": True,
    }
    tp = _tp_answers()
    tp["tp_get_workout"] = brick
    garmin = _garmin_answers()
    garmin["get_activities_by_date"] = {
        "activities": [
            {
                "id": 1,
                "type": "cycling",
                "start_time": "2026-09-01 06:00:00",
                "duration_seconds": 3600.0,
            },
            {
                "id": 2,
                "type": "running",
                "start_time": "2026-09-01 07:05:00",
                "duration_seconds": 1200.0,
            },
            {
                "id": 3,
                "type": "walking",
                "start_time": "2026-09-01 18:00:00",
                "duration_seconds": 900.0,
            },
        ],
        "has_more": False,
    }
    report = await run_sync(
        settings,
        since=date(2026, 8, 30),
        log=lambda m: None,
        open_tp=_factory(_Fake(tp)),
        open_garmin=_factory(_Fake(garmin)),
    )
    assert report.ok, report
    rows = db.execute(
        "select id, tp_workout_id from garmin_activities where id in ('1', '2', '3') order by id"
    ).fetchall()
    assert [(r["id"], r["tp_workout_id"]) for r in rows] == [("1", "w1"), ("2", "w1"), ("3", None)]
    w = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert w["garmin_activity_id"] == "1"
