"""CalendarChange -> (TrainingPeaks MCP tool name, arguments). Pure."""

from __future__ import annotations

from typing import Any

from tri_planning.planning.models import CalendarChange, PlannedSession, Sport, TrainingGoal

TP_SPORT: dict[Sport, str] = {
    "swim": "Swim",
    "bike": "Bike",
    "run": "Run",
    "brick": "Brick",
    "strength": "Strength",
    "rest": "DayOff",
}


def _workout_args(w: PlannedSession) -> dict[str, Any]:
    args: dict[str, Any] = {
        "sport": TP_SPORT[w.sport],
        "title": w.title,
        "duration_minutes": w.duration_minutes,
        "description": w.description,
        "tss_planned": w.tss_planned,
    }
    if w.structure is not None:
        args["structure"] = w.structure
    return args


def to_tp_call(change: CalendarChange) -> tuple[str, dict[str, Any]]:
    op = change.op
    if op == "create":
        if change.workout is None:
            raise ValueError("create needs a workout")
        return "tp_create_workout", {
            "date": change.workout.date.isoformat(),
            **_workout_args(change.workout),
        }
    if op == "update":
        if change.tp_workout_id is None or change.workout is None:
            raise ValueError("update needs tp_workout_id and a workout")
        return "tp_update_workout", {
            "workout_id": change.tp_workout_id,
            **_workout_args(change.workout),
        }
    if op == "move":
        if change.tp_workout_id is None or change.new_date is None:
            raise ValueError("move needs tp_workout_id and new_date")
        return "tp_update_workout", {
            "workout_id": change.tp_workout_id,
            "date": change.new_date.isoformat(),
        }
    if op == "delete":
        if change.tp_workout_id is None:
            raise ValueError("delete needs tp_workout_id")
        return "tp_delete_workout", {"workout_id": change.tp_workout_id}
    if op == "apply_plan":
        payload = change.payload
        if not payload or "plan_id" not in payload or "start_date" not in payload:
            raise ValueError("apply_plan needs payload with plan_id and start_date")
        return "tp_apply_training_plan", {
            "plan_id": payload["plan_id"],
            "start_date": payload["start_date"],
        }
    if op == "create_event":
        if not change.payload or "name" not in change.payload or "date" not in change.payload:
            raise ValueError("create_event needs payload with name and date")
        return "tp_create_event", dict(change.payload)
    raise ValueError(f"unknown op {op}")


def result_workout_id(change: CalendarChange, result: Any) -> str | None:
    if change.op == "create":
        wid = result.get("workout_id") if isinstance(result, dict) else None
        return str(wid) if wid is not None else None
    if change.op in ("update", "move", "delete"):
        return change.tp_workout_id
    return None


def event_change(goal: TrainingGoal) -> CalendarChange:
    if goal.event_date is None:
        raise ValueError("goal has no event_date")
    return CalendarChange(
        op="create_event",
        workout_date=goal.event_date,
        payload={
            "name": goal.event_name or goal.goal_type,
            "date": goal.event_date.isoformat(),
            "event_type": "MultisportTriathlon",
            "priority": goal.priority or "A",
        },
        reason=f"race day: {goal.event_name or goal.goal_type} on {goal.event_date}",
    )
