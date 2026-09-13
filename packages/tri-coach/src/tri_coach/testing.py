"""Test doubles for the coach graph: deps over the rolled-back connection with a scripted model
per level, and canned rows. Imported by tests only."""

from __future__ import annotations

import contextlib
from datetime import date, timedelta
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from tri_coach.graph.deps import CoachDeps
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition.graph.deps import GraphDeps as NutritionDeps
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps as PlanningDeps
from tri_planning.planning.models import CalendarChange, PlannedSession, TrainingGoal, WeekTarget
from tri_planning.testing import GOAL_ARGS, MONDAY
from tri_wellness.ranges.registry import MarkerRegistry

CFG: dict[str, Any] = {"configurable": {"thread_id": "coach"}, "recursion_limit": 60}


def make_test_deps(
    nocommit: Any,
    *,
    coach: BaseChatModel,
    planning: BaseChatModel,
    nutrition: BaseChatModel,
    analyst: BaseChatModel,
    wellness: BaseChatModel | None = None,
    registry: MarkerRegistry | None = None,
    tp: Any = None,
    garmin: Any = None,
    today: date = MONDAY,
    max_consults: int = 2,
) -> CoachDeps:
    url = Settings().test_database_url
    connect = lambda: contextlib.nullcontext(nocommit)  # noqa: E731
    return CoachDeps(
        model=coach,
        analyst_model=analyst,
        connect=connect,
        db_url=url,
        planning_deps=PlanningDeps(
            model=planning,
            connect=connect,
            db_url=url,
            tp=tp,
            horizon_weeks=3,
            today=lambda: today,
        ),
        nutrition_deps=NutritionDeps(
            model=nutrition,
            connect=connect,
            db_url=url,
            garmin=garmin,
            tp=tp,
            horizon_days=3,
            today=lambda: today,
        ),
        analyst_tools=[],
        wellness_model=wellness or ScriptedChatModel(script=[]),
        wellness_registry=registry,
        max_consults=max_consults,
        today=lambda: today,
    )


def seed_active_plan(conn: Any) -> tuple[int, int]:
    """An active goal and plan with one week on the calendar and one owned workout w1."""
    gid = repo.insert_goal(conn, TrainingGoal(**GOAL_ARGS))
    targets = [
        WeekTarget(
            week_start=MONDAY + timedelta(weeks=i),
            phase="build",
            target_tss=300,
            target_hours=6,
        )
        for i in range(3)
    ]
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    s = PlannedSession(
        date=MONDAY + timedelta(days=2),
        sport="run",
        title="Tempo",
        description="",
        duration_minutes=60,
        tss_planned=60,
        intensity="tempo",
    )
    repo.insert_change(
        conn,
        pid,
        "planning",
        CalendarChange(op="create", workout_date=s.date, workout=s, reason="r"),
        tp_workout_id="w1",
        result={},
    )
    repo.mark_weeks_written(conn, pid, [MONDAY])
    return gid, pid


def move_call(call_id: str = "c1") -> AIMessage:
    """The planning sub-agent proposing to move w1 to Friday."""
    return tool_call(
        "propose_calendar_changes",
        {
            "summary": "move it",
            "changes": [
                {
                    "op": "move",
                    "tp_workout_id": "w1",
                    "new_date": (MONDAY + timedelta(days=4)).isoformat(),
                    "reason": "rest day",
                }
            ],
        },
        call_id,
    )


def consult(domain: str, instruction: str, call_id: str = "c1") -> AIMessage:
    return tool_call(f"consult_{domain}", {"instruction": instruction}, call_id)


def propose(narration: str, ids: list[str], call_id: str = "c9") -> AIMessage:
    return tool_call("propose_changes", {"narration": narration, "proposal_ids": ids}, call_id)
