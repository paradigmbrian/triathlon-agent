"""Session load from duration and intensity, and scaling a designed week to its target. Pure."""

from __future__ import annotations

import copy
from typing import Any

from tri_planning.planning.models import (
    DesignedSession,
    DesignedWeek,
    Intensity,
    PlannedSession,
    PlannedWeek,
    WeekTarget,
)
from tri_planning.planning.validate import TSS_TOLERANCE

# Assumed intensity factor per session intensity: TSS = hours * IF^2 * 100.
INTENSITY_IF: dict[Intensity, float] = {
    "recovery": 0.65,
    "endurance": 0.70,
    "tempo": 0.80,
    "threshold": 0.90,
    "vo2": 1.0,
    "race": 1.0,
}
SCALE_MIN, SCALE_MAX = 0.75, 1.25
ROUND_MIN = 5


def session_tss(duration_minutes: int, intensity: Intensity) -> float:
    return round(duration_minutes / 60 * INTENSITY_IF[intensity] ** 2 * 100, 1)


def _load(s: DesignedSession) -> float:
    return 0.0 if s.sport == "rest" else session_tss(s.duration_minutes, s.intensity)


def _scalable(s: DesignedSession) -> bool:
    return s.sport != "rest" and s.intensity != "race" and s.duration_minutes > 0


def _round(minutes: float) -> int:
    return max(ROUND_MIN, int(minutes / ROUND_MIN + 0.5) * ROUND_MIN)


def _scale_steps(steps: list[dict[str, Any]], ratio: float) -> None:
    for step in steps:
        if step.get("type") == "repetition":
            _scale_steps(step.get("steps", []), ratio)
        elif step.get("duration_seconds") is not None:
            step["duration_seconds"] = round(int(step["duration_seconds"]) * ratio)


def _scaled(s: DesignedSession, factor: float) -> DesignedSession:
    minutes = _round(s.duration_minutes * factor)
    structure = copy.deepcopy(s.structure)
    if structure is not None:
        # by the session's own rounded ratio, so the steps still sum to its duration
        _scale_steps(structure.get("steps", []), minutes / s.duration_minutes)
    return s.model_copy(update={"duration_minutes": minutes, "structure": structure})


def _off_target(total: float, target_tss: float) -> bool:
    return bool(target_tss) and abs(total - target_tss) > TSS_TOLERANCE * target_tss


def scale_to_target(week: DesignedWeek, target: WeekTarget) -> tuple[PlannedWeek, list[str]]:
    """The week with each session's TSS computed from its duration and intensity. When the
    total is more than TSS_TOLERANCE from the target, every scalable session (not rest, not
    race intensity) is scaled by one factor, clamped to [SCALE_MIN, SCALE_MAX] and rounded to
    ROUND_MIN minutes; an interval structure scales with its session. A total still off target
    is one violation, which asks the designer for more or fewer sessions."""
    sessions = list(week.sessions)
    goal = target.target_tss
    total = sum(_load(s) for s in sessions)
    scalable = sum(_load(s) for s in sessions if _scalable(s))
    if _off_target(total, goal) and scalable > 0:
        factor = min(SCALE_MAX, max(SCALE_MIN, (goal - (total - scalable)) / scalable))
        sessions = [_scaled(s, factor) if _scalable(s) else s for s in sessions]
    planned = PlannedWeek(
        week_start=week.week_start,
        sessions=[PlannedSession(**s.model_dump(), tss_planned=_load(s)) for s in sessions],
        coach_note=week.coach_note,
    )
    total = planned.total_tss
    if not _off_target(total, goal):
        return planned, []
    ask = (
        "add a session or raise an intensity"
        if total < goal
        else "remove a session or lower an intensity"
    )
    return planned, [
        f"total TSS {total:.0f} cannot reach target {goal:.0f} by scaling durations; {ask}"
    ]
