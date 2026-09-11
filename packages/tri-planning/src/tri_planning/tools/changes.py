"""The adjust sub-agent's only way to change the calendar: a proposal the athlete reviews."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, ValidationError

from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.planning.tp_calls import to_tp_call


class ProposedChange(BaseModel):
    """One calendar change the model may propose: the reviewable subset of `CalendarChange`.

    Activating a bought plan and adding a race event belong to intake, so those ops and the
    raw TrainingPeaks body they carry are not part of this vocabulary.
    """

    op: Literal["create", "update", "move", "delete"] = Field(
        description="create (workout required), update (tp_workout_id and workout), "
        "move (tp_workout_id and new_date), delete (tp_workout_id)"
    )
    workout_date: date | None = Field(
        default=None, description="The day the workout sits on, for create"
    )
    tp_workout_id: str | None = Field(
        default=None, description="The TrainingPeaks workout id, for update, move and delete"
    )
    workout: PlannedSession | None = Field(
        default=None, description="The full session, for create and update"
    )
    new_date: date | None = Field(default=None, description="The day to move the workout to")
    reason: str = Field(description="One line: why this change")
    athlete_requested: bool = Field(
        default=False,
        description="True only when the athlete explicitly asked to change a workout that is "
        "not agent-authored",
    )


class ProposeArgs(BaseModel):
    summary: str = Field(
        description="Two or three sentences: what you found and what the changes do"
    )
    changes: list[ProposedChange] = Field(description="Every change, each with a one-line reason")


DESCRIPTION = """\
Propose calendar changes for the athlete to approve. Ops: create (workout required), update
(tp_workout_id and workout), move (tp_workout_id and new_date), delete (tp_workout_id). Only
agent-authored workouts may be updated, moved or deleted unless athlete_requested is true. Call
it once, at the end, with the complete set. Nothing is written until the athlete approves."""


def _error_json(exc: ValidationError) -> str:
    return json.dumps({"error": str(exc)})


def make_change_tool() -> BaseTool:
    def propose_calendar_changes(summary: str, changes: list[ProposedChange]) -> str:
        converted = [CalendarChange(**c.model_dump()) for c in changes]
        errors = []
        for c in converted:
            try:
                to_tp_call(c)
            except ValueError as exc:
                errors.append(f"{c.op}: {exc}")
        if errors:
            return json.dumps({"error": errors})
        return json.dumps(
            {"summary": summary, "changes": [c.model_dump(mode="json") for c in converted]}
        )

    return StructuredTool.from_function(
        func=propose_calendar_changes,
        name="propose_calendar_changes",
        description=DESCRIPTION,
        args_schema=ProposeArgs,
        # LangChain validates against args_schema before calling the function; return that
        # error as text too, so the model can read it and fix the inputs.
        handle_validation_error=_error_json,
    )
