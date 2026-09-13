"""Review node: build the change set from the coach's proposal request, pause until the athlete
decides. On resume the node runs again from the top, so everything before interrupt() is a pure
function of state.

Held proposals (a partial apply's remainder in `pending`) that the request does not name are
`carried`: apply holds them again after an approve, and a reject leaves them pending."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from tri_coach.graph.state import CoachState
from tri_coach.models import ChangeSet, ReviewDecision


def _refusal(text: str) -> dict[str, Any]:
    return {"proposal_request": None, "messages": [HumanMessage(f"[review] {text}")]}


def review_node(state: CoachState) -> dict[str, Any]:
    request = state.get("proposal_request")
    held = state.get("pending")
    held_proposals = list(held.proposals) if held else []
    proposals = {p.id: p for p in held_proposals}
    proposals.update({p.id: p for p in state.get("proposals") or []})
    if request is None:
        return {
            "messages": [
                HumanMessage("[review] nothing to review; call propose_changes with proposal ids")
            ]
        }
    missing = [i for i in request.ids if i not in proposals]
    if missing or not request.ids:
        what = ", ".join(missing) if missing else "none given"
        return _refusal(
            f"unknown proposal ids {what}; propose again with ids from this "
            "turn or a held id from the context block"
        )
    empty = [i for i in request.ids if not proposals[i].changes]
    if empty:
        return _refusal(
            f"{', '.join(empty)} carry no changes (a question, or nothing to write); answer the "
            "question or consult again, and propose only proposals with changes"
        )
    pending = ChangeSet(narration=request.narration, proposals=[proposals[i] for i in request.ids])
    carried = [p for p in held_proposals if p.id not in request.ids]
    raw = interrupt(
        {
            "narration": pending.narration,
            "proposals": [p.model_dump(mode="json") for p in pending.proposals],
        }
    )
    decision = ReviewDecision.model_validate(raw)
    update: dict[str, Any] = {
        "pending": pending,
        "carried": carried,
        "proposal_request": None,
        "review_decision": decision,
    }
    if decision.action == "reject":
        note = decision.note or "no note given"
        # What was rejected is dropped; held proposals the request did not name stay pending.
        update["pending"] = (
            ChangeSet(narration=held.narration, proposals=carried) if held and carried else None
        )
        update["carried"] = []
        update["messages"] = [HumanMessage(f"Review rejected: {note}")]
    elif decision.action == "edit" and decision.proposals is not None:
        update["pending"] = ChangeSet(narration=pending.narration, proposals=decision.proposals)
    return update
