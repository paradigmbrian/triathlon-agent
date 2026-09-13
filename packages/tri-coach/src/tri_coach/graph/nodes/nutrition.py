"""Nutrition node: run the embedded nutrition graph on the brief and map its output to a Proposal
(with the sub-agent's profile overrides, persisted only if the athlete approves)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from tri_coach.graph.nodes.planning import last_ai_text, result_message
from tri_coach.graph.state import CoachState
from tri_coach.models import Proposal
from tri_nutrition.prompts.checkin import BRIEF_PREFIX


def proposal_from_nutrition(out: dict[str, Any], pid: str) -> Proposal:
    changes = list(out.get("pending_changes") or [])
    violations = [out["last_error"]] if out.get("last_error") else []
    overrides = out.get("profile_overrides") or None
    if not changes:
        return Proposal(
            id=pid,
            domain="nutrition",
            summary=out.get("pending_summary") or "",
            violations=violations,
            question=last_ai_text(out.get("messages", [])) or "no answer",
        )
    return Proposal(
        id=pid,
        domain="nutrition",
        summary=out.get("pending_summary") or "",
        changes=changes,
        violations=violations,
        overrides=overrides,
    )


def make_nutrition_node(graph: Any) -> Any:
    async def nutrition(state: CoachState, config: RunnableConfig) -> dict[str, Any]:
        brief = state.get("brief")
        assert brief is not None and brief.domain == "nutrition", (
            "nutrition node needs a nutrition brief"
        )
        out = await graph.ainvoke(
            {"messages": [HumanMessage(f"{BRIEF_PREFIX} {brief.instruction}")]}, config
        )
        proposals = list(state.get("proposals") or [])
        proposal = proposal_from_nutrition(out, f"p{len(proposals) + 1}")
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "messages": [result_message(brief, proposal)],
        }

    return nutrition
