"""Read-only SQL access for the agent.

A tool is a typed function plus a docstring. The docstring and the
description are the only API the model sees, so the schema lives here, not in code the
model can't read.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import psycopg
from langchain_core.tools import BaseTool, tool
from psycopg import errors
from psycopg.rows import tuple_row

SCHEMA_DOC = """\
Tables (Postgres). All dates are the athlete's local calendar day.

athlete_profile (single row): ftp_watts, run_threshold_pace_sec_per_km, swim_css_sec_per_100m,
  lthr_bpm, max_hr_bpm, hr_zones jsonb, power_zones jsonb, pace_zones jsonb, weight_kg.

workouts (one row per TrainingPeaks workout; planned and actual on the same row):
  tp_workout_id text PK, workout_date date, sport text ('swim','bike','run','brick','strength',
  'race','rest','other'), sport_raw text, title, description (coach's plan text),
  completed bool,
  planned_duration_sec, planned_distance_m, planned_tss, planned_if,
  actual_duration_sec, actual_distance_m, actual_tss, actual_if,
  normalized_power, avg_power, avg_hr, avg_cadence, elevation_gain_m, calories,
  feeling int (0-10), rpe int (0-10), comments jsonb (athlete/coach comments),
  structure jsonb (planned intervals, may be null),
  garmin_activity_id text (use with get_activity_splits / get_activity for lap detail),
  start_time_local timestamp (from Garmin), raw jsonb (full TP payload).

daily_metrics (one row per day):
  metric_date date PK, sleep_seconds, sleep_score, hrv_overnight_avg, resting_hr,
  body_battery_high, body_battery_low, stress_avg, training_readiness (Garmin 0-100),
  ctl, atl, tsb, tss_day (TrainingPeaks fitness curve), garmin_raw jsonb, tp_raw jsonb.

sync_state: source, last_synced_date, last_run_at, last_status, last_error.

training_goals (planning agent): id, goal_type, event_name, event_date, duration_weeks,
  priority, weekly_hours_min, weekly_hours_max, available_days jsonb, constraints jsonb, status.
training_plans: id, goal_id, source ('generated'|'tp_plan'), start_date, end_date,
  targets jsonb, status.
plan_weeks: plan_id, week_start (Monday), phase, target_tss, target_hours, designed jsonb,
  written_to_tp.
plan_changes: plan_id, thread_id, operation, tp_workout_id, workout_date, payload jsonb,
  result jsonb, reason, applied_at  (audit of every calendar write; a workout is
  agent-authored iff its id is here).

Examples:
  -- yesterday's completed sessions
  select workout_date, sport, title, actual_duration_sec, actual_tss, avg_hr, garmin_activity_id
  from workouts where completed and workout_date = current_date - 1;
  -- planned vs actual this week
  select workout_date, sport, title, planned_tss, actual_tss, planned_duration_sec,
         actual_duration_sec
  from workouts where workout_date >= date_trunc('week', current_date) order by 1;
  -- weekly run volume for the last 12 weeks
  select date_trunc('week', workout_date)::date as wk, round(sum(actual_distance_m)/1000, 1) as km,
         sum(actual_duration_sec)/3600.0 as hours
  from workouts where sport='run' and completed and workout_date >= current_date - 84
  group by 1 order by 1;
  -- load and recovery, last 14 days
  select metric_date, tss_day, ctl, atl, tsb, sleep_score, hrv_overnight_avg, training_readiness
  from daily_metrics where metric_date >= current_date - 14 order by 1;
  -- the active plan's week targets
  select week_start, phase, target_tss from plan_weeks order by 1;
"""

_ALLOWED_HEADS = ("select", "with")
MAX_CHARS = 8000  # of the rows' JSON; whole rows only, so a wide result is cut early


def validate_select(sql: str) -> str:
    """Return the statement if it is a single SELECT/WITH query, else raise ValueError."""
    stmt = sql.strip()
    if stmt.endswith(";"):
        stmt = stmt[:-1].rstrip()
    if not stmt:
        raise ValueError("empty query")
    if ";" in stmt:
        raise ValueError("only one statement is allowed")
    head = stmt.split(None, 1)[0].lower()
    if head not in _ALLOWED_HEADS:
        raise ValueError("only SELECT queries are allowed (start with SELECT or WITH)")
    return stmt


def _json_safe(v: Any) -> Any:
    if isinstance(v, int | float | str | bool) or v is None:
        return v
    if isinstance(v, Decimal):
        return float(v)  # numeric columns (ctl, atl, tsb) are numbers to the model, not text
    if isinstance(v, list | dict):
        return json.loads(json.dumps(v, default=str))
    return str(v)


def run_readonly_query(
    url: str, sql: str, *, max_rows: int = 200, timeout_ms: int = 5000
) -> dict[str, Any]:
    """Run one SELECT on a fresh read-only connection. Never raises for SQL problems."""
    try:
        stmt = validate_select(sql)
    except ValueError as exc:
        return {"error": f"rejected: {exc}"}
    try:
        with psycopg.connect(url, row_factory=tuple_row, autocommit=False) as conn:
            conn.read_only = True
            with conn.transaction():
                conn.execute(f"set local statement_timeout = {int(timeout_ms)}")
                cur = conn.execute(stmt)
                columns = [d.name for d in cur.description] if cur.description else []
                fetched = cur.fetchmany(max_rows + 1)
            conn.rollback()
    except errors.ReadOnlySqlTransaction as exc:
        return {"error": f"rejected by read-only transaction: {exc}".strip()}
    except errors.QueryCanceled:
        return {"error": f"statement timeout after {timeout_ms} ms; narrow the query"}
    except psycopg.Error as exc:
        return {"error": f"sql error: {exc}".strip()}
    rows = [[_json_safe(v) for v in r] for r in fetched[:max_rows]]
    kept: list[list[Any]] = []
    size = 2  # the enclosing brackets
    for row in rows:
        size += len(json.dumps(row, default=str)) + 1
        if size > MAX_CHARS:
            break
        kept.append(row)
    truncated = len(fetched) > max_rows or len(kept) < len(rows)
    out: dict[str, Any] = {
        "columns": columns,
        "rows": kept,
        "row_count": len(kept),
        "truncated": truncated,
    }
    if truncated:
        out["note"] = (
            f"result cut at {len(kept)} rows (caps: {max_rows} rows, {MAX_CHARS} characters); "
            "narrow the query: fewer columns, a shorter window, or aggregate"
        )
    return out


def make_query_tool(url: str, extra_doc: str = "") -> BaseTool:
    """The read-only SQL tool. `extra_doc` documents tables an agent adds (appended after
    SCHEMA_DOC)."""

    @tool("query_training_db")
    def query_training_db(sql: str) -> str:
        """Run one read-only SQL SELECT against the athlete's training database and return JSON.

        Use this for anything about past workouts, planned vs actual, weekly volume, training
        load (CTL/ATL/TSB), sleep, HRV, readiness, and the athlete's zones and thresholds.
        Do arithmetic in SQL (sums, averages, group by week), not in your head.
        Rows are capped at 200 and the result at 8,000 characters, cut at whole rows; a cut
        result has "truncated": true and a note. Pick columns, aggregate, or shorten the window
        rather than listing raw rows for long windows.
        """
        return json.dumps(run_readonly_query(url, sql), default=str)

    doc = SCHEMA_DOC + ("\n" + extra_doc if extra_doc else "")
    query_training_db.description = (query_training_db.description or "") + "\n" + doc
    return query_training_db
