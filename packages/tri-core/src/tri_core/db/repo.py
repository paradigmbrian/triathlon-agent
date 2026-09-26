"""SQL access. Every function takes an open connection; callers commit."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from tri_core.db.models import (
    AthleteProfileRow,
    DailyMetricsRow,
    GarminActivityRow,
    SyncState,
    WorkoutRow,
)

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
    # A workout back in the listing is live again.
    sql = (
        f"insert into workouts ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (tp_workout_id) do update set {updates}, deleted_at = null, "
        "synced_at = now()"
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


_ACTIVITY_COLS = [
    "id",
    "type_key",
    "sport",
    "start_time_local",
    "duration_sec",
    "distance_m",
    "avg_hr",
    "name",
    "raw",
]


def upsert_garmin_activities(conn: Conn, rows: Iterable[GarminActivityRow]) -> int:
    """Every fetched activity, matched or not. `tp_workout_id` is not in the column list, so a
    re-sync keeps the link."""
    cols = ", ".join(_ACTIVITY_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _ACTIVITY_COLS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _ACTIVITY_COLS if c != "id")
    sql = (
        f"insert into garmin_activities ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (id) do update set {updates}, synced_at = now()"
    )
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, _params(row))
            n += 1
    return n


def _num(v: Any) -> float | None:
    return float(v) if v is not None else None


def linked_activities(conn: Conn, start: date, end: date) -> dict[str, list[GarminActivityRow]]:
    rows = conn.execute(
        f"select tp_workout_id, {', '.join(_ACTIVITY_COLS)} from garmin_activities "
        "where tp_workout_id is not null and start_time_local::date between %s and %s "
        "order by start_time_local, id",
        (start, end),
    ).fetchall()
    out: dict[str, list[GarminActivityRow]] = {}
    for r in rows:
        out.setdefault(r["tp_workout_id"], []).append(
            GarminActivityRow(
                id=r["id"],
                type_key=r["type_key"],
                sport=r["sport"],
                start_time_local=r["start_time_local"],
                duration_sec=_num(r["duration_sec"]),
                distance_m=_num(r["distance_m"]),
                avg_hr=r["avg_hr"],
                name=r["name"],
                raw=r["raw"],
            )
        )
    return out


def link_activity(conn: Conn, activity_id: str, tp_workout_id: str) -> None:
    """Link one activity to its workout. The workout's own `garmin_activity_id` is the first
    linked leg and is never replaced, so `get_activity_splits` readers keep working."""
    conn.execute(
        "update garmin_activities set tp_workout_id = %s where id = %s",
        (tp_workout_id, activity_id),
    )
    conn.execute(
        "update workouts w set garmin_activity_id = a.id, start_time_local = a.start_time_local "
        "from garmin_activities a "
        "where a.id = %s and w.tp_workout_id = %s and w.garmin_activity_id is null",
        (activity_id, tp_workout_id),
    )


def list_workouts_between(
    conn: Conn, start: date, end: date, *, include_deleted: bool = False
) -> list[dict[str, Any]]:
    live = "" if include_deleted else "and deleted_at is null "
    return conn.execute(
        f"select * from workouts where workout_date between %s and %s {live}"
        "order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()


def mark_missing_deleted(conn: Conn, start: date, end: date, seen_ids: Collection[str]) -> int:
    """Tombstone live workouts dated in [start, end] that the TrainingPeaks listing for that
    window did not return. Rows outside the window are never touched. A tombstoned workout lets
    go of its Garmin activities (a soft delete never fires the foreign key), so the next Garmin
    sync can match them to the workout that replaced it."""
    row = conn.execute(
        "with gone as ("
        "  update workouts set deleted_at = now(), garmin_activity_id = null, "
        "  start_time_local = null "
        "  where workout_date between %s and %s and deleted_at is null "
        "  and tp_workout_id <> all(%s) returning tp_workout_id"
        "), released as ("
        "  update garmin_activities a set tp_workout_id = null from gone "
        "  where a.tp_workout_id = gone.tp_workout_id"
        ") select count(*) as n from gone",
        (start, end, list(seen_ids)),
    ).fetchone()
    return int(row["n"]) if row else 0


def count_deleted(conn: Conn, ids: Collection[str]) -> int:
    row = conn.execute(
        "select count(*) as n from workouts where deleted_at is not null "
        "and tp_workout_id = any(%s)",
        (list(ids),),
    ).fetchone()
    return int(row["n"]) if row else 0


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
