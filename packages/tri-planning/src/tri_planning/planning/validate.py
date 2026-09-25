"""Judge a designed week against its target and the athlete's constraints. Pure."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from tri_planning.planning.models import (
    HARD_INTENSITIES,
    WEEKDAYS,
    PlannedWeek,
    Sport,
    TrainingGoal,
    WeekTarget,
)

TSS_TOLERANCE = 0.10
STRUCTURE_TOLERANCE_MIN = 5


def structure_seconds(structure: dict[str, Any]) -> int | None:
    """Seconds the steps add up to, or None when a step has no duration_seconds (a distance
    step, or a malformed one)."""
    total = 0
    for step in structure.get("steps", []):
        if step.get("type") == "repetition":
            inner = [s.get("duration_seconds") for s in step.get("steps", [])]
            if any(d is None for d in inner):
                return None
            total += int(step.get("reps", 1)) * sum(int(d) for d in inner)
        elif step.get("duration_seconds") is None:
            return None
        else:
            total += int(step["duration_seconds"])
    return total


def sport_allowed(sport: Sport, allowed: list[Sport] | Literal["any"]) -> bool:
    if sport == "rest" or allowed == "any":
        return True
    if sport == "brick":
        return "brick" in allowed or ("bike" in allowed and "run" in allowed)
    return sport in allowed


def week(planned: PlannedWeek, target: WeekTarget, goal: TrainingGoal) -> list[str]:
    out: list[str] = []
    week_end = target.week_start + timedelta(days=6)
    if planned.week_start != target.week_start:
        out.append(
            f"week_start {planned.week_start} does not match the target week {target.week_start}"
        )

    total = planned.total_tss
    if target.target_tss and abs(total - target.target_tss) > TSS_TOLERANCE * target.target_tss:
        out.append(f"total TSS {total:.0f} is more than 10% from target {target.target_tss:.0f}")

    for s in planned.sessions:
        if not target.week_start <= s.date <= week_end:
            out.append(f"{s.date} {s.sport}: outside the week starting {target.week_start}")
            continue
        day = WEEKDAYS[s.date.weekday()]
        allowed = goal.available_days[day]
        if allowed != "any" and not allowed and s.sport != "rest":
            out.append(f"{s.date} ({day}) is unavailable but has {s.sport}")
        elif not sport_allowed(s.sport, allowed):
            out.append(f"{s.date} ({day}) does not allow {s.sport}; allowed: {allowed}")
        if s.structure is not None:
            secs = structure_seconds(s.structure)
            if secs is None:
                out.append(f"{s.date} {s.title}: structure has a step without duration_seconds")
            elif abs(secs / 60 - s.duration_minutes) > STRUCTURE_TOLERANCE_MIN:
                out.append(
                    f"{s.date} {s.title}: structure sums to {secs // 60} min but duration is "
                    f"{s.duration_minutes} min"
                )

    hard_days = sorted({s.date for s in planned.sessions if s.intensity in HARD_INTENSITIES})
    for a, b in zip(hard_days, hard_days[1:], strict=False):
        if (b - a).days == 1:
            out.append(f"hard sessions on consecutive days {a} and {b}")

    hours = planned.total_hours
    if hours > goal.weekly_hours_max:
        out.append(f"total hours {hours:.1f} exceed weekly max {goal.weekly_hours_max:g}")
    return out
