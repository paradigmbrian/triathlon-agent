"""read_training_plan: the horizon's sessions, phases and event, as the sub-agents see them."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from tri_nutrition import plan_loader
from tri_nutrition.graph.deps import ConnectFactory


class NoArgs(BaseModel):
    pass


def make_plan_tool(
    connect: ConnectFactory, today: Callable[[], date], horizon_days: int
) -> BaseTool:
    async def read_training_plan() -> str:
        """The planned sessions for the coming days (day, sport, minutes, intensity, TSS), the
        plan phase per week, the goal event date and priority, FTP, and where the sessions came
        from: plan (the planning agent's designed weeks), tp_calendar (TrainingPeaks workouts),
        or profile_hours (nothing planned; the goal's weekly hours)."""
        with connect() as conn:
            sessions, ctx = plan_loader.load_horizon(conn, today(), horizon_days)
        return json.dumps(plan_loader.describe(sessions, ctx))

    return StructuredTool.from_function(
        coroutine=read_training_plan,
        name="read_training_plan",
        description=read_training_plan.__doc__ or "",
        args_schema=NoArgs,
    )
