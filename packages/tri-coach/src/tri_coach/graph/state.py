"""Graph state. `messages` accumulates; every other key is last-write-wins and the `start` node
clears the per-turn ones."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from tri_coach.models import (
    ApplyReport,
    Brief,
    ChangeSet,
    Proposal,
    ProposalRequest,
    ReviewDecision,
)


class CoachState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    brief: Brief | None  # set by a handoff tool, consumed by planning/nutrition
    proposals: list[Proposal]  # accumulated this turn
    proposal_request: ProposalRequest | None  # set by propose_changes, consumed by review
    pending: ChangeSet | None  # what review shows; remainder after a partial apply
    carried: list[Proposal]  # held proposals the change set did not name; review -> apply
    regenerate_after_apply: bool  # set by apply when planning moved sessions; routes to nutrition
    review_decision: ReviewDecision | None
    reports: list[ApplyReport]
    last_error: str | None
