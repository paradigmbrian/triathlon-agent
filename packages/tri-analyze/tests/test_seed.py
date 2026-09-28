"""The eval's seeded history: pure checks, then a round trip through the test database."""

import json
from collections import defaultdict
from datetime import date

import psycopg
import pytest

from tri_analyze.evals import seed
from tri_analyze.evals.cases import TODAY, WEEK_DAYS
from tri_core.config import Settings, reader_url
from tri_core.db.connection import connect
from tri_core.db.sql_tool import run_readonly_query


def test_the_history_is_one_consistent_athlete():
    ws = seed.workouts()
    ids = [w["tp_workout_id"] for w in ws]
    assert len(ids) == len(set(ids)) and all(i.startswith("eval-") for i in ids)
    # June is a run block: no bike, so "average weekly bike TSS in June" has no data
    assert not [w for w in ws if w["sport"] == "bike" and w["workout_date"] < date(2026, 7, 1)]
    by_title = {(w["workout_date"], w["title"]) for w in ws}
    for d, title in [
        (date(2026, 9, 9), "Threshold 3x10"),
        (date(2026, 9, 13), "Brick: 2h ride + 20 min run"),
        (date(2026, 9, 14), "Z2 ride"),
        (date(2026, 9, 15), "Intervals 6x800"),
        (date(2026, 9, 19), "Long ride"),
    ]:
        assert (d, title) in by_title
    # tss_day is the day's completed load, and the cases' own days are unchanged
    load: dict[date, float] = defaultdict(float)
    for w in ws:
        if w["completed"] and w.get("actual_tss") is not None:
            load[w["workout_date"]] += float(w["actual_tss"])
    days = seed.daily_metrics(ws)
    assert all(abs(float(d["tss_day"]) - load[d["metric_date"]]) < 0.01 for d in days)
    assert [d for d in days if d["metric_date"] >= date(2026, 9, 9)] == WEEK_DAYS
    assert max(d["metric_date"] for d in days) < TODAY

    # the recovery week carries less load than the week before it
    def week(monday):
        return sum(load[d] for d in load if monday <= d < date.fromordinal(monday.toordinal() + 7))

    assert week(date(2026, 8, 10)) < 0.8 * week(date(2026, 8, 3))


def _url() -> str:
    url = Settings().test_database_url
    try:
        psycopg.connect(url).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable at {url}: {exc}")
    return url


@pytest.mark.db
def test_the_seeded_rows_are_readable_through_the_real_sql_tool():
    url = _url()
    try:
        seed.seed_database(url)
        out = run_readonly_query(
            reader_url(url),
            "select title, rpe, comments from workouts where workout_date = date '2026-09-09'",
        )
        assert out["rows"][0][0] == "Threshold 3x10" and out["rows"][0][1] == 9
        assert "Legs were dead" in json.dumps(out["rows"][0][2])
        legs = run_readonly_query(
            reader_url(url),
            "select count(*) from garmin_activities where tp_workout_id = 'eval-brick'",
        )
        assert legs["rows"][0][0] == 2
    finally:
        seed.clear_database(url)
    with connect(url) as conn:
        assert conn.execute("select count(*) as n from workouts").fetchone()["n"] == 0


@pytest.mark.db
def test_seeding_twice_replaces_the_first_run():
    url = _url()
    try:
        seed.seed_database(url)
        seed.seed_database(url)  # a killed run's rows are the eval's own: replaced, not refused
        with connect(url) as conn:
            n = conn.execute("select count(*) as n from workouts").fetchone()["n"]
        assert n == len(seed.workouts())
    finally:
        seed.clear_database(url)


@pytest.mark.db
def test_seeding_refuses_a_database_with_rows_it_did_not_write():
    url = _url()
    with connect(url) as conn:
        conn.execute(
            "insert into workouts (tp_workout_id, workout_date, sport, raw) "
            "values ('real-1', '2026-09-01', 'run', '{}')"
        )
        conn.commit()
    try:
        with pytest.raises(seed.EvalDatabaseInUse):
            seed.seed_database(url)
        with pytest.raises(seed.EvalDatabaseInUse):
            seed.clear_database(url)
    finally:
        with connect(url) as conn:
            conn.execute("delete from workouts where tp_workout_id = 'real-1'")
            conn.commit()


@pytest.mark.db
def test_seeding_refuses_a_database_with_a_foreign_garmin_activity():
    url = _url()
    with connect(url) as conn:
        conn.execute(
            "insert into garmin_activities (id, sport, start_time_local, raw) "
            "values ('real-activity', 'run', '2026-09-01 07:00', '{}')"
        )
        conn.commit()
    try:
        with pytest.raises(seed.EvalDatabaseInUse):
            seed.seed_database(url)
        with pytest.raises(seed.EvalDatabaseInUse):
            seed.clear_database(url)
    finally:
        with connect(url) as conn:
            conn.execute("delete from garmin_activities where id = 'real-activity'")
            conn.commit()


@pytest.mark.db
def test_seeding_refuses_a_database_with_daily_metrics_and_no_eval_profile():
    url = _url()
    with connect(url) as conn:
        conn.execute("insert into daily_metrics (metric_date, tss_day) values ('2026-09-01', 50)")
        conn.commit()
    try:
        with pytest.raises(seed.EvalDatabaseInUse):
            seed.seed_database(url)
        with pytest.raises(seed.EvalDatabaseInUse):
            seed.clear_database(url)
    finally:
        with connect(url) as conn:
            conn.execute("delete from daily_metrics where metric_date = '2026-09-01'")
            conn.commit()


@pytest.mark.db
def test_verify_readable_passes_once_seeded():
    url = _url()
    try:
        seed.seed_database(url)
        seed.verify_readable(url)  # tri_reader sees exactly the seeded workouts; does not raise
    finally:
        seed.clear_database(url)


def test_the_build_weeks_differ_in_load():
    # a flat series gives trend questions nothing to find and derived arithmetic nothing to do
    weekly: dict[date, float] = defaultdict(float)
    for w in seed.workouts():
        d = w["workout_date"]
        if w["completed"] and w.get("actual_tss") is not None and d < seed.CASE_WEEK:
            weekly[date.fromordinal(d.toordinal() - d.weekday())] += float(w["actual_tss"])
    build = [t for m, t in weekly.items() if m >= seed.BUILD_START and m != seed.RECOVERY_WEEK]
    assert len(build) >= 6 and len(set(build)) > 1


class _Recording:
    """A stand-in connection: records every statement, reports no foreign rows."""

    def __init__(self) -> None:
        self.sql: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)
        return self

    def fetchone(self):
        return {"n": 0}

    def commit(self):
        pass


def test_clearing_locks_the_tables_before_the_guard_reads_them(monkeypatch):
    conn = _Recording()
    monkeypatch.setattr(seed, "connect", lambda url: conn)
    seed.clear_database("postgresql://u@h/evaldb")
    lock = next(i for i, s in enumerate(conn.sql) if s.startswith("lock table"))
    guard = next(i for i, s in enumerate(conn.sql) if "count(*)" in s)
    truncate = next(i for i, s in enumerate(conn.sql) if s.startswith("truncate"))
    assert lock < guard < truncate
    assert all(t in conn.sql[lock] for t in seed.SEEDED_TABLES)
    assert conn.sql[lock].endswith("in access exclusive mode")
