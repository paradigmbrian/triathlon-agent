"""Pair Garmin activities with TrainingPeaks workouts on the same day."""

from __future__ import annotations

from typing import Any

from tri_core.sync.garmin import GarminActivity


def _sport_ok(workout_sport: str, activity_sport: str) -> bool:
    return workout_sport == "brick" or workout_sport == activity_sport


def match_activities(
    workouts: list[dict[str, Any]],
    activities: list[GarminActivity],
    tolerance_sec: int = 120,
) -> list[tuple[str, GarminActivity]]:
    candidates = [w for w in workouts if w.get("completed") and not w.get("garmin_activity_id")]
    used_workouts: set[str] = set()
    pairs: list[tuple[str, GarminActivity]] = []

    for act in sorted(activities, key=lambda a: a.start_time_local):
        day = act.start_time_local.date()
        same_day = [
            w
            for w in candidates
            if w["workout_date"] == day
            and w["tp_workout_id"] not in used_workouts
            and _sport_ok(w["sport"], act.sport)
        ]
        if not same_day:
            continue
        with_dur = [
            w
            for w in same_day
            if w.get("actual_duration_sec") is not None and act.duration_sec is not None
        ]
        chosen: dict[str, Any] | None = None
        if with_dur:
            act_dur = float(act.duration_sec or 0)
            best = min(with_dur, key=lambda w: abs(float(w["actual_duration_sec"]) - act_dur))
            if abs(float(best["actual_duration_sec"]) - act_dur) <= tolerance_sec:
                chosen = best
        elif len(same_day) == 1:
            chosen = same_day[0]
        if chosen is not None:
            used_workouts.add(chosen["tp_workout_id"])
            pairs.append((chosen["tp_workout_id"], act))
    return pairs
