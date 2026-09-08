"""Intake tools: commit a TrainingGoal; list the athlete's bought TrainingPeaks plans."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import ValidationError

from tri_core.sync import ToolCaller
from tri_planning import repo
from tri_planning.graph.deps import ConnectFactory
from tri_planning.planning import periodization as P
from tri_planning.planning.models import TrainingGoal
from tri_planning.planning.targets import allocate_phases, count_weeks, next_monday

SET_GOAL_DESCRIPTION = """\
Commit the athlete's training goal once every field is established and confirmed. Fields:
goal_type (sprint | olympic | half_ironman | ironman | maintenance | build | recovery);
event_name and event_date (YYYY-MM-DD) for race goals; duration_weeks for non-race goals;
priority (A | B | C); weekly_hours_min and weekly_hours_max; available_days, a mapping of
mon..sun to a list of sports (swim, bike, run, brick, strength) or the string "any" (a missing
day or an empty list means unavailable); constraints, a list of short strings; tp_plan_id if the
athlete wants a bought TrainingPeaks plan activated instead of a generated one; create_tp_event
true to add the race to the TrainingPeaks calendar. Returns JSON with goal_id and the number of
weeks, or an error explaining what to fix. Do not call it more than once per goal."""


def _error_json(exc: ValidationError) -> str:
    return json.dumps({"error": str(exc)})


def make_goal_tools(
    connect: ConnectFactory, tp: ToolCaller | None, today: Callable[[], date]
) -> list[BaseTool]:
    def set_training_goal(**kwargs: Any) -> str:
        try:
            goal = TrainingGoal(**kwargs)
        except ValidationError as exc:
            return json.dumps({"error": str(exc)})
        start = next_monday(today())
        try:
            weeks = count_weeks(goal, start)
            _, compressed = allocate_phases(goal.goal_type, weeks)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        minimum = P.PHASE_TABLE[goal.goal_type].minimum_weeks
        warning = (
            f"only {weeks} weeks until the event; {goal.goal_type} normally needs {minimum}. "
            "Base is dropped and build shortened; the plan is flagged compressed."
            if compressed
            else None
        )
        with connect() as conn:
            goal_id = repo.insert_goal(conn, goal)
            conn.commit()
        return json.dumps(
            {"goal_id": goal_id, "weeks": weeks, "compressed": compressed, "warning": warning}
        )

    async def list_tp_training_plans() -> str:
        """List the bought TrainingPeaks training plans in the athlete's library (id and name)."""
        if tp is None:
            return json.dumps({"error": "TrainingPeaks server unavailable this session"})
        return json.dumps(await tp.call_json("tp_list_training_plans"), default=str)

    set_goal_tool = StructuredTool.from_function(
        func=set_training_goal,
        name="set_training_goal",
        description=SET_GOAL_DESCRIPTION,
        args_schema=TrainingGoal,
        # LangChain validates against args_schema before calling the function; return that
        # error as text too, so the model can read it and fix the inputs.
        handle_validation_error=_error_json,
    )
    list_tool = StructuredTool.from_function(
        coroutine=list_tp_training_plans,
        name="list_tp_training_plans",
        description=list_tp_training_plans.__doc__ or "",
    )
    return [set_goal_tool, list_tool]
