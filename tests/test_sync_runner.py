from contextlib import asynccontextmanager
from datetime import date, datetime

import pytest

from tri_analyze.config import Settings
from tri_analyze.db import repo
from tri_analyze.db.models import SyncState
from tri_analyze.sync.runner import (
    GARMIN_FIRST_RUN_DAYS,
    TP_FIRST_RUN_DAYS,
    resolve_window,
    run_sync,
)

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
    monkeypatch.setattr("tri_analyze.sync.runner.connect", lambda url: _NoClose(db))

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
    monkeypatch.setattr("tri_analyze.sync.runner.connect", lambda url: _NoClose(db))

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
