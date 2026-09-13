"""The athlete context: thresholds, the last seven days of load and recovery, and the workouts
one week either side of today. Passed to every analyst run as its runtime context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from tri_core.db.repo import Conn


@dataclass
class AthleteContext:
    today: date
    profile: dict[str, Any] | None
    recent_days: list[dict[str, Any]] = field(default_factory=list)
    recent_workouts: list[dict[str, Any]] = field(default_factory=list)


def load_athlete_context(conn: Conn, today: date) -> AthleteContext:
    profile = conn.execute(
        "select ftp_watts, run_threshold_pace_sec_per_km, swim_css_sec_per_100m, lthr_bpm, "
        "max_hr_bpm, weight_kg from athlete_profile where id = 1"
    ).fetchone()
    days_rows = conn.execute(
        "select metric_date, tss_day, ctl, atl, tsb, sleep_score, hrv_overnight_avg, "
        "resting_hr, training_readiness from daily_metrics "
        "where metric_date between %s and %s order by metric_date",
        (today - timedelta(days=7), today),
    ).fetchall()
    workouts_rows = conn.execute(
        "select workout_date, sport, title, completed, planned_tss, actual_tss, "
        "planned_duration_sec, actual_duration_sec from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
        (today - timedelta(days=7), today + timedelta(days=7)),
    ).fetchall()

    def _to_native(d: dict[str, Any]) -> dict[str, Any]:
        """Convert Decimal values to float."""
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in d.items()}

    days = [_to_native(d) for d in days_rows] if days_rows else []
    workouts = [_to_native(w) for w in workouts_rows] if workouts_rows else []

    return AthleteContext(today=today, profile=profile, recent_days=days, recent_workouts=workouts)
