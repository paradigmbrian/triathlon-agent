"""Pair Garmin activities with TrainingPeaks workouts on the same day. A `brick` workout takes two
legs of different sports (or one Garmin multisport activity); every other workout takes one."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tri_core.sync.garmin import GarminActivity

BRICK = "brick"


def _sport_ok(workout_sport: str, activity_sport: str) -> bool:
    return workout_sport in (BRICK, activity_sport)


def _open(w: dict[str, Any], legs: Sequence[GarminActivity]) -> bool:
    if w["sport"] == BRICK:
        return len(legs) < 2 and all(leg.sport != BRICK for leg in legs)
    return not legs and not w.get("garmin_activity_id")


def _closest_single(
    singles: list[dict[str, Any]], act: GarminActivity, tolerance_sec: int
) -> dict[str, Any] | None:
    with_dur = [
        w
        for w in singles
        if w.get("actual_duration_sec") is not None and act.duration_sec is not None
    ]
    if with_dur:
        act_dur = float(act.duration_sec or 0)
        best = min(with_dur, key=lambda w: abs(float(w["actual_duration_sec"]) - act_dur))
        return best if abs(float(best["actual_duration_sec"]) - act_dur) <= tolerance_sec else None
    return singles[0] if len(singles) == 1 else None


def _brick_gap(
    w: dict[str, Any], legs: Sequence[GarminActivity], act: GarminActivity, tolerance_sec: int
) -> float | None:
    """How far the brick's legs would fall from its actual duration with `act` added, or None
    when `act` cannot be a leg. A first leg matches on sport and day alone."""
    if any(leg.sport == act.sport for leg in legs) or (act.sport == BRICK and legs):
        return None
    total = w.get("actual_duration_sec")
    durations = [leg.duration_sec for leg in legs] + [act.duration_sec]
    if total is None or any(d is None for d in durations):
        return 0.0
    if legs or act.sport == BRICK:  # the brick is complete with this activity
        summed = sum(float(d or 0) for d in durations)
        gap = abs(float(total) - summed)
        return gap if gap <= tolerance_sec else None
    return 0.0


def match_activities(
    workouts: list[dict[str, Any]],
    activities: list[GarminActivity],
    tolerance_sec: int = 120,
    *,
    linked: Mapping[str, Sequence[GarminActivity]] | None = None,
) -> list[tuple[str, GarminActivity]]:
    """New (workout id, activity) pairs. `linked` holds each workout's activities from earlier
    syncs; they count as that workout's legs and are never assigned again."""
    legs: dict[str, list[GarminActivity]] = {k: list(v) for k, v in (linked or {}).items()}
    taken = {a.id for acts in legs.values() for a in acts}
    candidates = [w for w in workouts if w.get("completed")]
    pairs: list[tuple[str, GarminActivity]] = []

    for act in sorted(activities, key=lambda a: a.start_time_local):
        if act.id in taken:
            continue
        day = act.start_time_local.date()
        same_day = [
            w
            for w in candidates
            if w["workout_date"] == day
            and _open(w, legs.get(w["tp_workout_id"], []))
            and _sport_ok(w["sport"], act.sport)
        ]
        singles = [w for w in same_day if w["sport"] != BRICK]
        chosen = _closest_single(singles, act, tolerance_sec) if singles else None
        if chosen is None:
            fits: list[tuple[float, dict[str, Any]]] = []
            for w in same_day:
                if w["sport"] != BRICK:
                    continue
                gap = _brick_gap(w, legs.get(w["tp_workout_id"], []), act, tolerance_sec)
                if gap is not None:
                    fits.append((gap, w))
            if fits:
                chosen = min(fits, key=lambda f: f[0])[1]
        if chosen is not None:
            legs.setdefault(chosen["tp_workout_id"], []).append(act)
            taken.add(act.id)
            pairs.append((chosen["tp_workout_id"], act))
    return pairs
