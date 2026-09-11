"""Test doubles and SQL seeds for the wellness package. Imported by tests only."""

from __future__ import annotations

from typing import Any

from tri_core.db.models import DailyMetricsRow, WorkoutRow
from tri_core.db.repo import Conn, upsert_daily_metrics, upsert_workouts


def seed_workouts(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with tp_workout_id, workout_date, sport, and optional title,
    actual_duration_sec, actual_tss, completed (default True)."""
    out: list[WorkoutRow] = []
    for r in rows:
        out.append(
            WorkoutRow(
                tp_workout_id=r["tp_workout_id"],
                workout_date=r["workout_date"],
                sport=r["sport"],
                sport_raw=None,
                title=r.get("title", ""),
                description=None,
                completed=bool(r.get("completed", True)),
                planned_duration_sec=r.get("planned_duration_sec"),
                planned_distance_m=None,
                planned_tss=r.get("planned_tss"),
                planned_if=None,
                actual_duration_sec=r.get("actual_duration_sec"),
                actual_distance_m=None,
                actual_tss=r.get("actual_tss"),
                actual_if=None,
                normalized_power=None,
                avg_power=None,
                avg_hr=None,
                avg_cadence=None,
                elevation_gain_m=None,
                calories=None,
                feeling=None,
                rpe=None,
                comments=None,
                structure=None,
                raw={},
            )
        )
    upsert_workouts(conn, out)


def seed_daily_metrics(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with metric_date and any other DailyMetricsRow field."""
    upsert_daily_metrics(conn, [DailyMetricsRow(**r) for r in rows])
