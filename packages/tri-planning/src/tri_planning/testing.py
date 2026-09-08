"""Test doubles for the planning graph: a fake TrainingPeaks caller, a no-commit connection
wrapper, and canned goal/week payloads. Imported by tests only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tri_core.mcp.client import McpToolError

MONDAY = date(2026, 9, 14)
ALL_DAYS = {d: "any" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}

GOAL_ARGS: dict[str, Any] = {
    "goal_type": "olympic",
    "event_name": "City Tri",
    "event_date": (MONDAY + timedelta(weeks=13, days=6)).isoformat(),
    "priority": "A",
    "weekly_hours_min": 4,
    "weekly_hours_max": 12,
    "available_days": ALL_DAYS,
    "constraints": ["pool closed Fridays"],
    "create_tp_event": False,
}


def week_json(
    week_start: date, target_tss: float, *, hard_on_consecutive_days: bool = False
) -> dict[str, Any]:
    """A PlannedWeek as the model would return it (JSON-safe). Three sessions summing to target."""
    a = round(target_tss * 0.4)
    b = round(target_tss * 0.3)
    c = target_tss - a - b
    d2 = 3 if hard_on_consecutive_days else 2  # Thu run + Fri swim are consecutive hard days
    return {
        "week_start": week_start.isoformat(),
        "coach_note": "steady aerobic week",
        "sessions": [
            {
                "date": week_start.isoformat(),
                "sport": "bike",
                "title": "Endurance ride",
                "description": "z2",
                "duration_minutes": 90,
                "tss_planned": a,
                "intensity": "endurance",
            },
            {
                "date": (week_start + timedelta(days=d2)).isoformat(),
                "sport": "run",
                "title": "Threshold run",
                "description": "4x6",
                "duration_minutes": 60,
                "tss_planned": b,
                "intensity": "threshold",
            },
            {
                "date": (week_start + timedelta(days=4)).isoformat(),
                "sport": "swim",
                "title": "CSS swim",
                "description": "10x100",
                "duration_minutes": 45,
                "tss_planned": c,
                "intensity": "threshold" if hard_on_consecutive_days else "endurance",
            },
        ],
    }


class FakeTp:
    """Records every call; answers like the real server. `fail_on_call` raises on the nth call."""

    def __init__(
        self, *, responses: dict[str, Any] | None = None, fail_on_call: int | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        self.calls.append((tool, dict(args or {})))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise McpToolError(tool, "API_ERROR: boom")
        if tool in self.responses:
            return self.responses[tool]
        if tool == "tp_create_workout":
            return {
                "success": True,
                "workout_id": 1000 + len(self.calls),
                "title": args["title"] if args else "",
            }
        if tool == "tp_update_workout":
            return {"success": True, "workout_id": (args or {})["workout_id"]}
        if tool == "tp_delete_workout":
            return {"success": True, "message": "deleted"}
        if tool == "tp_create_event":
            return {"success": True, "event_id": 77, "name": (args or {}).get("name")}
        if tool == "tp_apply_training_plan":
            return {"success": True, "created": 3, "failed": 0, "skipped_periods": 0, "total": 3}
        if tool == "tp_get_workouts":
            return {"workouts": [], "count": 0}
        if tool == "tp_list_training_plans":
            return {"plans": [{"id": "p1", "name": "12 week olympic"}]}
        return {}


class NoCommit:
    """The rolled-back test connection; commit/close are no-ops so nodes can call them."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> NoCommit:
        return self

    def __exit__(self, *exc: object) -> None:
        return None
