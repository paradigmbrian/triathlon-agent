"""Row builders for tests that seed `workouts` directly."""

from __future__ import annotations

from datetime import date
from typing import Any

from tri_core.db.models import WorkoutRow


def workout_row(tp_workout_id: str, workout_date: date, **over: Any) -> WorkoutRow:
    """A completed one-hour bike, 50 TSS, planned and actual alike; override any field."""
    base: dict[str, Any] = dict(
        tp_workout_id=tp_workout_id,
        workout_date=workout_date,
        sport="bike",
        sport_raw="Bike",
        title=f"ride {tp_workout_id}",
        description=None,
        completed=True,
        planned_duration_sec=3600,
        planned_distance_m=None,
        planned_tss=50.0,
        planned_if=None,
        actual_duration_sec=3600,
        actual_distance_m=None,
        actual_tss=50.0,
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
    base.update(over)
    return WorkoutRow(**base)
