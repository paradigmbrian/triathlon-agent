"""Row dataclasses shared by sync parsers and the repository."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class AthleteProfileRow:
    tp_athlete_id: str | None
    ftp_watts: int | None
    run_threshold_pace_sec_per_km: int | None
    swim_css_sec_per_100m: int | None
    lthr_bpm: int | None
    max_hr_bpm: int | None
    hr_zones: Any
    power_zones: Any
    pace_zones: Any
    weight_kg: float | None
    raw: dict[str, Any]


@dataclass(slots=True)
class WorkoutRow:
    tp_workout_id: str
    workout_date: date
    sport: str
    sport_raw: str | None
    title: str | None
    description: str | None
    completed: bool
    planned_duration_sec: int | None
    planned_distance_m: float | None
    planned_tss: float | None
    planned_if: float | None
    actual_duration_sec: int | None
    actual_distance_m: float | None
    actual_tss: float | None
    actual_if: float | None
    normalized_power: int | None
    avg_power: int | None
    avg_hr: int | None
    avg_cadence: float | None
    elevation_gain_m: float | None
    calories: int | None
    feeling: int | None
    rpe: int | None
    comments: Any
    structure: Any
    raw: dict[str, Any]


@dataclass(slots=True)
class DailyMetricsRow:
    metric_date: date
    sleep_seconds: int | None = None
    sleep_score: int | None = None
    hrv_overnight_avg: int | None = None
    resting_hr: int | None = None
    body_battery_high: int | None = None
    body_battery_low: int | None = None
    stress_avg: int | None = None
    training_readiness: int | None = None
    garmin_raw: Any = None
    ctl: float | None = None
    atl: float | None = None
    tsb: float | None = None
    tss_day: float | None = None
    tp_raw: Any = None


@dataclass(slots=True)
class SyncState:
    source: str
    last_synced_date: date
    last_run_at: datetime
    last_status: str
    last_error: str | None = field(default=None)
