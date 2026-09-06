"""SQL access. Every function takes an open connection; callers commit."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from tri_analyze.db.models import AthleteProfileRow, DailyMetricsRow, SyncState, WorkoutRow

Conn = psycopg.Connection[dict[str, Any]]

_JSON_COLS = {
    "raw",
    "hr_zones",
    "power_zones",
    "pace_zones",
    "comments",
    "structure",
    "garmin_raw",
    "tp_raw",
}


def _params(row: Any) -> dict[str, Any]:
    d = asdict(row)
    for k in _JSON_COLS & d.keys():
        d[k] = Jsonb(d[k]) if d[k] is not None else None
    return d


def upsert_athlete_profile(conn: Conn, row: AthleteProfileRow) -> None:
    conn.execute(
        """
        insert into athlete_profile (id, tp_athlete_id, ftp_watts, run_threshold_pace_sec_per_km,
            swim_css_sec_per_100m, lthr_bpm, max_hr_bpm, hr_zones, power_zones, pace_zones,
            weight_kg, raw, updated_at)
        values (1, %(tp_athlete_id)s, %(ftp_watts)s, %(run_threshold_pace_sec_per_km)s,
            %(swim_css_sec_per_100m)s, %(lthr_bpm)s, %(max_hr_bpm)s, %(hr_zones)s, %(power_zones)s,
            %(pace_zones)s, %(weight_kg)s, %(raw)s, now())
        on conflict (id) do update set
            tp_athlete_id = excluded.tp_athlete_id,
            ftp_watts = excluded.ftp_watts,
            run_threshold_pace_sec_per_km = excluded.run_threshold_pace_sec_per_km,
            swim_css_sec_per_100m = excluded.swim_css_sec_per_100m,
            lthr_bpm = excluded.lthr_bpm,
            max_hr_bpm = excluded.max_hr_bpm,
            hr_zones = excluded.hr_zones,
            power_zones = excluded.power_zones,
            pace_zones = excluded.pace_zones,
            weight_kg = excluded.weight_kg,
            raw = excluded.raw,
            updated_at = now()
        """,
        _params(row),
    )


_WORKOUT_COLS = [
    "tp_workout_id",
    "workout_date",
    "sport",
    "sport_raw",
    "title",
    "description",
    "completed",
    "planned_duration_sec",
    "planned_distance_m",
    "planned_tss",
    "planned_if",
    "actual_duration_sec",
    "actual_distance_m",
    "actual_tss",
    "actual_if",
    "normalized_power",
    "avg_power",
    "avg_hr",
    "avg_cadence",
    "elevation_gain_m",
    "calories",
    "feeling",
    "rpe",
    "comments",
    "structure",
    "raw",
]


def upsert_workouts(conn: Conn, rows: Iterable[WorkoutRow]) -> int:
    cols = ", ".join(_WORKOUT_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _WORKOUT_COLS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _WORKOUT_COLS if c != "tp_workout_id")
    sql = (
        f"insert into workouts ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (tp_workout_id) do update set {updates}, synced_at = now()"
    )
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, _params(row))
            n += 1
    return n


_DAILY_COLS = [
    "metric_date",
    "sleep_seconds",
    "sleep_score",
    "hrv_overnight_avg",
    "resting_hr",
    "body_battery_high",
    "body_battery_low",
    "stress_avg",
    "training_readiness",
    "garmin_raw",
    "ctl",
    "atl",
    "tsb",
    "tss_day",
    "tp_raw",
]


def upsert_daily_metrics(conn: Conn, rows: Iterable[DailyMetricsRow]) -> int:
    cols = ", ".join(_DAILY_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _DAILY_COLS)
    updates = ", ".join(
        f"{c} = coalesce(excluded.{c}, daily_metrics.{c})"
        for c in _DAILY_COLS
        if c != "metric_date"
    )
    sql = (
        f"insert into daily_metrics ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (metric_date) do update set {updates}, synced_at = now()"
    )
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, _params(row))
            n += 1
    return n


def set_garmin_match(
    conn: Conn, tp_workout_id: str, garmin_activity_id: str, start_time_local: datetime
) -> None:
    conn.execute(
        "update workouts set garmin_activity_id = %s, start_time_local = %s "
        "where tp_workout_id = %s",
        (garmin_activity_id, start_time_local, tp_workout_id),
    )


def list_workouts_between(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select * from workouts where workout_date between %s and %s "
        "order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()


def get_sync_state(conn: Conn, source: str) -> SyncState | None:
    row = conn.execute("select * from sync_state where source = %s", (source,)).fetchone()
    return SyncState(**row) if row else None


def set_sync_state(
    conn: Conn, source: str, last_synced_date: date, status: str, error: str | None
) -> None:
    conn.execute(
        """
        insert into sync_state (source, last_synced_date, last_run_at, last_status, last_error)
        values (%s, %s, now(), %s, %s)
        on conflict (source) do update set
            last_synced_date = excluded.last_synced_date,
            last_run_at = now(),
            last_status = excluded.last_status,
            last_error = excluded.last_error
        """,
        (source, last_synced_date, status, error),
    )
