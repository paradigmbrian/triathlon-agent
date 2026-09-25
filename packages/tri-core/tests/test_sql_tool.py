import json

import pytest

from tri_core.config import Settings
from tri_core.db.sql_tool import (
    SCHEMA_DOC,
    make_query_tool,
    run_readonly_query,
    validate_select,
)


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("select 1", "select 1"),
        ("  SELECT 1;  ", "SELECT 1"),
        ("with x as (select 1) select * from x", "with x as (select 1) select * from x"),
    ],
)
def test_validate_select_accepts(sql, expected):
    assert validate_select(sql) == expected


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "delete from workouts",
        "update workouts set title='x'",
        "select 1; drop table x",
        "insert into workouts values (1)",
        "explain select 1",
        "-- comment\nselect 1",
    ],
)
def test_validate_select_rejects(sql):
    with pytest.raises(ValueError):
        validate_select(sql)


def test_schema_doc_mentions_every_table():
    for t in ("athlete_profile", "workouts", "daily_metrics", "sync_state"):
        assert t in SCHEMA_DOC
    assert "garmin_activity_id" in SCHEMA_DOC


@pytest.fixture
def url(db):
    # `db` proves the test database is reachable; the tool opens its own connection.
    return Settings().test_database_url


@pytest.mark.db
def test_run_query_returns_columns_and_rows(url):
    # a fixed date, not current_date: the container runs on UTC and disagrees with local
    # time in the evening
    out = run_readonly_query(url, "select 1 as one, 'a' as letter, date '2026-01-02' as today")
    assert out["columns"] == ["one", "letter", "today"]
    assert out["rows"][0][:2] == [1, "a"]
    assert out["rows"][0][2] == "2026-01-02"  # JSON-safe
    assert out["row_count"] == 1 and out["truncated"] is False


@pytest.mark.db
def test_run_query_caps_rows(url):
    out = run_readonly_query(url, "select generate_series(1, 500) as n", max_rows=10)
    assert out["row_count"] == 10 and out["truncated"] is True


@pytest.mark.db
def test_run_query_rejects_write_even_inside_cte(url):
    sql = (
        "with w as (insert into sync_state values ('x', current_date, now(), 'ok', null) "
        "returning *) select * from w"
    )
    out = run_readonly_query(url, sql)
    assert "error" in out and "read-only" in out["error"].lower()


@pytest.mark.db
def test_run_query_times_out(url):
    out = run_readonly_query(url, "select pg_sleep(2)", timeout_ms=100)
    assert "error" in out and "timeout" in out["error"].lower()


@pytest.mark.db
def test_run_query_reports_sql_errors(url):
    out = run_readonly_query(url, "select * from no_such_table")
    assert "error" in out and "no_such_table" in out["error"]


@pytest.mark.db
def test_tool_wraps_query_as_json_text(url):
    tool = make_query_tool(url)
    assert tool.name == "query_training_db"
    assert "workouts" in tool.description
    text = tool.invoke({"sql": "select count(*) as n from sync_state"})
    data = json.loads(text)
    assert data["columns"] == ["n"]


def test_make_query_tool_extra_doc_is_appended():
    from tri_core.db.sql_tool import SCHEMA_DOC, make_query_tool

    plain = make_query_tool("postgresql://x/y")
    assert plain.description.endswith(SCHEMA_DOC)
    extended = make_query_tool("postgresql://x/y", extra_doc="lab_panels: id, drawn_on")
    assert extended.description.endswith("lab_panels: id, drawn_on")
    assert SCHEMA_DOC in extended.description


@pytest.mark.db
def test_run_query_returns_numeric_as_float(url):
    out = run_readonly_query(url, "select 1.5::numeric as x, 2::numeric as n, 40.0::numeric as ctl")
    assert out["rows"][0] == [1.5, 2.0, 40.0]
    assert all(isinstance(v, float) for v in out["rows"][0])
