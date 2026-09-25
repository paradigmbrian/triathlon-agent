"""Review node: pause the graph until the athlete decides.

`interrupt(value)` stops the run with the value exposed to the caller as `__interrupt__` and the
checkpoint records where we are. On `Command(resume=x)` the node runs again from the top and
`interrupt()` returns x. Nothing before the interrupt may have side effects.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import ReviewDecision


def review_node(state: NutritionState) -> dict[str, Any]:
    changes = state.get("pending_changes") or []
    if not changes:
        return {"review_decision": None, "messages": [AIMessage("No nutrition changes to review.")]}
    raw = interrupt(
        {
            "summary": state.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in changes],
            "violations": state.get("pending_violations") or {},
            "last_error": state.get("last_error"),
        }
    )
    decision = ReviewDecision.model_validate(raw)
    update: dict[str, Any] = {"review_decision": decision}
    if decision.action == "reject":
        note = decision.note or "no note given"
        update["messages"] = [HumanMessage(f"Targets review rejected: {note}")]
        update["pending_changes"] = []
        update["pending_violations"] = {}
        update["pending_summary"] = None
        update["profile_overrides"] = None
    elif decision.action == "edit" and decision.changes is not None:
        update["pending_changes"] = decision.changes
    return update
