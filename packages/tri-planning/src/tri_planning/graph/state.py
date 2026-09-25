"""Graph state. One reducer: messages accumulate; every other key is last-write-wins."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from tri_planning.planning.models import CalendarChange, GraphPhase, PlannedSession, ReviewDecision

# Pydantic models that live in PlanningState. Registering them keeps the checkpointer from
# warning (and, in strict mode, refusing) when it deserializes them.
STATE_TYPES: tuple[type, ...] = (CalendarChange, PlannedSession, ReviewDecision)


class PlanningState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    phase: GraphPhase
    goal_id: int | None
    plan_id: int | None
    pending_changes: list[CalendarChange]
    pending_summary: str | None
    pending_violations: dict[str, list[str]]  # week_start ISO -> validator violations
    review_decision: ReviewDecision | None
    last_error: str | None
    changes_from: Literal["targets", "design", "adjust"] | None
    tp_plan_applied: bool
