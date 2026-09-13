"""Planning node: run the embedded planning graph on the brief and map its output to a Proposal.
The result replaces the handoff ToolMessage (same id), so the coach's history reads as one tool
call and its result."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from tri_coach.graph.state import CoachState
from tri_coach.models import Brief, Proposal
from tri_planning.prompts.adjust import BRIEF_PREFIX


def last_ai_text(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            content = msg.content
            if isinstance(content, str):
                return content
            return "".join(
                str(b.get("text", ""))
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
    return ""


def proposal_from_planning(out: dict[str, Any], pid: str) -> Proposal:
    changes = list(out.get("pending_changes") or [])
    violations = [out["last_error"]] if out.get("last_error") else []
    if not changes:
        return Proposal(
            id=pid,
            domain="planning",
            summary=out.get("pending_summary") or "",
            violations=violations,
            question=last_ai_text(out.get("messages", [])) or "no answer",
        )
    return Proposal(
        id=pid,
        domain="planning",
        summary=out.get("pending_summary") or "",
        changes=changes,
        violations=violations,
    )


def result_message(brief: Brief, proposal: Proposal) -> ToolMessage:
    return ToolMessage(
        content=proposal.render(),
        tool_call_id=brief.tool_call_id,
        name=f"consult_{brief.domain}",
        id=brief.message_id,
    )


def make_planning_node(graph: Any) -> Any:
    async def planning(state: CoachState, config: RunnableConfig) -> dict[str, Any]:
        brief = state.get("brief")
        assert brief is not None and brief.domain == "planning", (
            "planning node needs a planning brief"
        )
        out = await graph.ainvoke(
            {"messages": [HumanMessage(f"{BRIEF_PREFIX} {brief.instruction}")]}, config
        )
        proposals = list(state.get("proposals") or [])
        proposal = proposal_from_planning(out, f"p{len(proposals) + 1}")
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "messages": [result_message(brief, proposal)],
        }

    return planning
