"""Design prompt: the model plans one week's sessions inside Python-set bounds."""

from __future__ import annotations

import json
from typing import Any

from tri_planning.planning.models import WEEKDAYS, PlannedWeek, TrainingGoal, WeekTarget

PROMPT_VERSION = "2"  # bump when DESIGN_SYSTEM changes; names the eval experiment design-v<N>

DESIGN_SYSTEM = """\
You are a triathlon coach writing one week of sessions for one self-coached athlete. You return a
DesignedWeek: week_start, coach_note (two sentences on the week's intent), and sessions. Each
session has date (YYYY-MM-DD inside the week), sport (swim | bike | run | brick | strength | rest),
title (short, specific), description (what to do, in the athlete's language, with targets in the
athlete's zones), duration_minutes, intensity (recovery | endurance | tempo | threshold | vo2 |
race) and optionally structure.

The planner computes each session's load from its duration and intensity, then scales every
duration together (by at most a quarter) to meet the week's load target. You do not estimate
load: choose the sessions, their intensities and durations that fit the hours target and the
phase. If the planner cannot reach the target, it asks you for more or fewer sessions.

structure is TrainingPeaks' simplified format: {"primaryIntensityMetric": "percentOfFtp" for
bike, "percentOfThresholdPace" for run and swim, "percentOfThresholdHr" if no pace or power
threshold exists, "steps": [ {"name", "duration_seconds", "intensity_min", "intensity_max",
"intensityClass": "warmUp" | "active" | "rest" | "coolDown"} or {"type": "repetition", "reps",
"steps": [...]} ]}. Step durations must sum to duration_minutes within 5 minutes. Only add
structure to interval sessions; leave it out for steady endurance and swims described in text.

Hard rules (a validator rejects the week otherwise):
- No session on an unavailable day; only the day's allowed sports. Brick is allowed when the
  day lists brick, or both bike and run.
- Sessions with intensity threshold, vo2 or race are never on consecutive days.
- Total duration must not exceed the weekly hours max, and must reach 80 % of the target hours
  except in recovery, taper and race weeks.
- No session longer than 6 hours; no vo2 session longer than 90 minutes.
Do not include rest days as sessions."""


def _availability_block(goal: TrainingGoal) -> str:
    rows = []
    for d in WEEKDAYS:
        allowed = goal.available_days.get(d, [])
        label = "any sport" if allowed == "any" else (", ".join(allowed) or "unavailable")
        rows.append(f"  {d}: {label}")
    return "\n".join(rows)


def _previous_block(prev: PlannedWeek | None) -> str:
    if prev is None:
        return "Previous week: none (first designed week)."
    lines = [f"Previous week ({prev.week_start}, {prev.total_tss:.0f} TSS):"]
    for s in prev.sessions:
        lines.append(f"  {s.date} {s.sport} {s.intensity} {s.duration_minutes} min: {s.title}")
    return "\n".join(lines)


def render_design_prompt(
    goal: TrainingGoal,
    target: WeekTarget,
    thresholds: dict[str, Any] | None,
    previous: PlannedWeek | None,
    athlete_note: str | None,
    violations: list[str] | None,
    previous_attempt: PlannedWeek | None,
) -> str:
    recovery = " (recovery week)" if target.is_recovery else ""
    event = f", {goal.event_name} on {goal.event_date}" if goal.event_date else ""
    parts = [
        f"Design the week starting {target.week_start} (Monday). Phase: {target.phase}{recovery}. "
        f"Target about {target.target_hours:.1f} hours; the planner scales durations to "
        f"{target.target_tss:.0f} TSS. The athlete's range is {goal.weekly_hours_min:g} to "
        f"{goal.weekly_hours_max:g} hours.",
        f"Phase guidance: {target.sport_hint}",
        f"Goal: {goal.goal_type}{event}",
        "Availability:\n" + _availability_block(goal),
        "Constraints: " + ("; ".join(goal.constraints) if goal.constraints else "none"),
        "Athlete thresholds and zones: " + json.dumps(thresholds or {}, default=str),
        _previous_block(previous),
    ]
    if athlete_note:
        parts.append(
            f"The athlete rejected the last proposal with this note; honor it: {athlete_note}"
        )
    if violations and previous_attempt is not None:
        parts.append(
            "Your previous attempt was rejected by the validator:\n- "
            + "\n- ".join(violations)
            + "\nPrevious attempt: "
            + previous_attempt.model_dump_json()
            + "\nFix every violation and return the whole week again."
        )
    return "\n\n".join(parts)
