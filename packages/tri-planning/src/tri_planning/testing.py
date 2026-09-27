"""Test doubles for the planning graph: a fake TrainingPeaks caller, a no-commit connection
wrapper, and canned goal/week payloads. Imported by tests only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tri_core.mcp.client import McpToolError
from tri_planning.planning.models import Intensity, Sport
from tri_planning.planning.tss import INTENSITY_IF, ROUND_MIN, session_tss

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
    """A week as the designer would return it (JSON-safe): three sessions whose durations put
    the week within a few percent of `target_tss`, so scaling leaves it alone. Each session
    also carries its `tss_planned`, so the dict validates as a PlannedWeek too; DesignedWeek
    ignores the field."""
    d2 = 3 if hard_on_consecutive_days else 2  # Thu run + Fri swim are consecutive hard days
    swim: Intensity = "threshold" if hard_on_consecutive_days else "endurance"
    rows: list[tuple[int, Sport, str, str, Intensity, float]] = [
        (0, "bike", "Endurance ride", "z2", "endurance", 0.4),
        (d2, "run", "Threshold run", "4x6", "threshold", 0.3),
        (4, "swim", "CSS swim", "10x100", swim, 0.3),
    ]
    sessions = []
    for day, sport, title, description, intensity, share in rows:
        per_hour = INTENSITY_IF[intensity] ** 2 * 100
        steps = int(target_tss * share / per_hour * 60 / ROUND_MIN + 0.5)  # half rounds up
        minutes = max(ROUND_MIN, steps * ROUND_MIN)
        sessions.append(
            {
                "date": (week_start + timedelta(days=day)).isoformat(),
                "sport": sport,
                "title": title,
                "description": description,
                "duration_minutes": minutes,
                "tss_planned": session_tss(minutes, intensity),
                "intensity": intensity,
            }
        )
    return {
        "week_start": week_start.isoformat(),
        "coach_note": "steady aerobic week",
        "sessions": sessions,
    }


class FakeTp:
    """Records every call; answers like the real server. `fail_on_call` raises on the nth call."""

    def __init__(
        self,
        *,
        responses: dict[str, Any] | None = None,
        fail_on_call: int | None = None,
        listings: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call
        # successive tp_get_workouts answers, one list of workouts per call
        self.listings = list(listings) if listings is not None else None

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
            if self.listings:
                workouts = self.listings.pop(0)
                return {"workouts": workouts, "count": len(workouts)}
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
