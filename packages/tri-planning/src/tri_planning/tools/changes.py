"""The adjust sub-agent's only way to change the calendar: a proposal the athlete reviews."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from tri_planning.planning.models import CalendarChange
from tri_planning.planning.tp_calls import to_tp_call


class ProposeArgs(BaseModel):
    summary: str = Field(
        description="Two or three sentences: what you found and what the changes do"
    )
    changes: list[CalendarChange] = Field(description="Every change, each with a one-line reason")


DESCRIPTION = """\
Propose calendar changes for the athlete to approve. Ops: create (workout required), update
(tp_workout_id and workout), move (tp_workout_id and new_date), delete (tp_workout_id). Only
agent-authored workouts may be updated, moved or deleted unless athlete_requested is true. Call
it once, at the end, with the complete set. Nothing is written until the athlete approves."""


def make_change_tool() -> BaseTool:
    def propose_calendar_changes(summary: str, changes: list[CalendarChange]) -> str:
        errors = []
        for c in changes:
            try:
                to_tp_call(c)
            except ValueError as exc:
                errors.append(f"{c.op}: {exc}")
        if errors:
            return json.dumps({"error": errors})
        return json.dumps(
            {"summary": summary, "changes": [c.model_dump(mode="json") for c in changes]}
        )

    return StructuredTool.from_function(
        func=propose_calendar_changes,
        name="propose_calendar_changes",
        description=DESCRIPTION,
        args_schema=ProposeArgs,
    )
