import pytest

pytestmark = pytest.mark.db


def test_tables_exist(db):
    rows = db.execute(
        "select table_name from information_schema.tables where table_schema='public' order by 1"
    ).fetchall()
    names = {r["table_name"] for r in rows}
    assert {"athlete_profile", "workouts", "daily_metrics", "sync_state"} <= names


def test_rows_are_dicts(db):
    row = db.execute("select 1 as one").fetchone()
    assert row == {"one": 1}
