"""Planning node: run the embedded planning graph on the brief and map its output to a Proposal.
The result replaces the handoff ToolMessage (same id), so the coach's history reads as one tool
call and its result."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from tri_coach.graph.state import CoachState
from tri_coach.models import Brief, Proposal
from tri_core.harness.messages import last_ai_text
from tri_planning.prompts.adjust import BRIEF_PREFIX


def keyed_violations(
    out: dict[str, Any], where: Callable[[str], str]
) -> tuple[list[str], dict[str, list[str]]]:
    """A sub-graph run's violations: `last_error`, then one line per `pending_violations` entry
    (`where` names its key), for the coach and the review; and the entries themselves, which
    check-in --yes uses to leave the flagged changes out."""
    raw: dict[str, list[str]] = out.get("pending_violations") or {}
    keyed = {k: list(v) for k, v in raw.items() if v}
    lines = [out["last_error"]] if out.get("last_error") else []
    lines += [f"{where(k)}: " + "; ".join(keyed[k]) for k in sorted(keyed)]
    return lines, keyed


def proposal_from_planning(out: dict[str, Any], pid: str) -> Proposal:
    changes = list(out.get("pending_changes") or [])
    violations, keyed = keyed_violations(out, lambda week: f"week of {week}")
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
        pending_violations=keyed,
    )


def result_message(brief: Brief, proposal: Proposal) -> ToolMessage:
    assert brief.tool_call_id is not None and brief.message_id is not None, (
        "only a consultation brief has a tool call to answer"
    )
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
            {"messages": [HumanMessage(f"{BRIEF_PREFIX} {brief.instruction}")]},
            merge_configs(config, {"tags": ["domain:planning"]}),
        )
        proposals = list(state.get("proposals") or [])
        n = state.get("next_proposal_id") or 1
        proposal = proposal_from_planning(out, f"p{n}")
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "next_proposal_id": n + 1,
            "messages": [result_message(brief, proposal)],
        }

    return planning
