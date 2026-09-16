"""Graph state. One reducer: messages accumulate; every other key is last-write-wins."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision

# Pydantic models that live in NutritionState. Registering them keeps the checkpointer from
# warning (and, in strict mode, refusing) when it deserializes them.
STATE_TYPES: tuple[type, ...] = (NutritionChange, ReviewDecision)


class NutritionState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    has_profile: bool  # set by the route node from the Store each run
    profile_saved: bool  # set by intake/checkin when save_nutrition_profile succeeded this run
    targets_requested: bool  # set by checkin when propose_target_changes succeeded this run
    profile_overrides: dict[str, Any] | None  # from propose_target_changes; persisted on approve
    regenerate_from: Literal["intake", "checkin"] | None
    pending_changes: list[NutritionChange]
    pending_summary: str | None
    review_decision: ReviewDecision | None
    last_error: str | None
