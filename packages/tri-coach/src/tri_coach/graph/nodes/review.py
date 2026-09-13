"""Review node: build the change set from the coach's proposal request, pause until the athlete
decides. On resume the node runs again from the top, so everything before interrupt() is a pure
function of state."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from tri_coach.graph.state import CoachState
from tri_coach.models import ChangeSet, ReviewDecision


def review_node(state: CoachState) -> dict[str, Any]:
    request = state.get("proposal_request")
    proposals = {p.id: p for p in state.get("proposals") or []}
    if request is None:
        return {
            "messages": [
                HumanMessage("[review] nothing to review; call propose_changes with proposal ids")
            ]
        }
    missing = [i for i in request.ids if i not in proposals]
    if missing or not request.ids:
        what = ", ".join(missing) if missing else "none given"
        return {
            "proposal_request": None,
            "messages": [
                HumanMessage(
                    f"[review] unknown proposal ids {what}; propose again with ids from this turn"
                )
            ],
        }
    pending = ChangeSet(narration=request.narration, proposals=[proposals[i] for i in request.ids])
    raw = interrupt(
        {
            "narration": pending.narration,
            "proposals": [p.model_dump(mode="json") for p in pending.proposals],
        }
    )
    decision = ReviewDecision.model_validate(raw)
    update: dict[str, Any] = {
        "pending": pending,
        "proposal_request": None,
        "review_decision": decision,
    }
    if decision.action == "reject":
        note = decision.note or "no note given"
        update["pending"] = None
        update["messages"] = [HumanMessage(f"Review rejected: {note}")]
    elif decision.action == "edit" and decision.proposals is not None:
        update["pending"] = ChangeSet(narration=pending.narration, proposals=decision.proposals)
    return update
