"""Nutrition node: run the embedded nutrition graph on the brief and map its output to a Proposal
(with the sub-agent's profile overrides, persisted only if the athlete approves).

A regenerate brief (set by apply after planning moved sessions) skips the sub-agent: the graph's
targets entry rebuilds the horizon from the stored plan, and the result comes back to the coach
as a "[follow-on]" message, since no tool call is waiting for it."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langgraph.errors import GraphBubbleUp

from tri_coach.graph.nodes.planning import result_message
from tri_coach.graph.state import CoachState
from tri_coach.models import Proposal
from tri_core.harness.messages import last_ai_text
from tri_nutrition.prompts.checkin import BRIEF_PREFIX

FOLLOW_ON = "[follow-on]"


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


def proposal_from_regenerate(out: dict[str, Any], pid: str) -> Proposal:
    """No sub-agent ran, so there is never a question: changes, or nothing, or violations."""
    error = out.get("last_error")
    return Proposal(
        id=pid,
        domain="nutrition",
        summary=out.get("pending_summary") or error or "",
        changes=list(out.get("pending_changes") or []),
        violations=[error] if error else [],
    )


def regeneration_failed(exc: Exception, pid: str) -> Proposal:
    error = (
        f"regeneration failed: {type(exc).__name__}: {exc}; targets may not reflect the moved "
        "sessions; consult nutrition to regenerate"
    )
    return Proposal(id=pid, domain="nutrition", summary=error, violations=[error])


def follow_on_message(proposal: Proposal) -> HumanMessage:
    if proposal.changes:
        ask = f"Narrate the consequence and call propose_changes with {proposal.id}."
    elif proposal.violations:
        ask = "Nothing can be written: state the violations and stop."
    else:
        ask = "It made no changes: say the nutrition targets stand and stop."
    return HumanMessage(
        f"{FOLLOW_ON} The approved plan change moved sessions, so nutrition was regenerated "
        f"from the stored plan.\n{proposal.render()}\n{ask}"
    )


def make_nutrition_node(graph: Any) -> Any:
    async def nutrition(state: CoachState, config: RunnableConfig) -> dict[str, Any]:
        brief = state.get("brief")
        assert brief is not None and brief.domain == "nutrition", (
            "nutrition node needs a nutrition brief"
        )
        cfg = merge_configs(config, {"tags": ["domain:nutrition"]})
        proposals = list(state.get("proposals") or [])
        pid = f"p{len(proposals) + 1}"
        if brief.regenerate:
            # apply's step is already committed; a failure here must not strand the thread
            try:
                out = await graph.ainvoke(
                    {"targets_requested": True, "regenerate_from": "checkin"}, cfg
                )
            except GraphBubbleUp:
                raise
            except Exception as exc:  # noqa: BLE001 - returned to the coach as a violation
                proposal = regeneration_failed(exc, pid)
            else:
                proposal = proposal_from_regenerate(out, pid)
            return {
                "brief": None,
                "regenerate_after_apply": False,
                "proposals": [*proposals, proposal],
                "messages": [follow_on_message(proposal)],
            }
        out = await graph.ainvoke(
            {"messages": [HumanMessage(f"{BRIEF_PREFIX} {brief.instruction}")]}, cfg
        )
        proposal = proposal_from_nutrition(out, pid)
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "messages": [result_message(brief, proposal)],
        }

    return nutrition
