"""Placeholder until Plan 4 replaces it with the adjust sub-agent."""

from typing import Any

from langchain_core.messages import AIMessage

from tri_planning.graph.state import PlanningState


def adjust_node(state: PlanningState) -> dict[str, Any]:
    return {
        "messages": [
            AIMessage("The plan is active. Adjustments and check-in arrive in milestone 4.")
        ]
    }
