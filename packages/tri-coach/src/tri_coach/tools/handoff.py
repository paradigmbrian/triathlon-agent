"""Handoffs: tools that move the run from the coach to a sub-graph node.

Each tool leaves the coach sub-agent through tri_core.harness.handoff, which re-emits the turn's
messages (ids intact; add_messages upserts) with a result for any sibling call the unwinding cut
off and this tool's own ToolMessage. The sub-graph node later replaces that ToolMessage's content
(same id) with its result."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated
from uuid import uuid4

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from tri_coach.models import Brief, Domain, ProposalRequest
from tri_core.harness.handoff import handoff

CONSULT_BUDGET_SPENT = (
    "consult budget for {domain} is spent this turn ({n} of {n}); explain what you have and "
    "stop, or ask the athlete"
)


def _consult(
    domain: Domain,
    instruction: str,
    tool_call_id: str,
    messages: Sequence[AnyMessage],
    spent: int,
    max_consults: int | None,
) -> Command[str] | ToolMessage:
    if max_consults is not None and spent >= max_consults:
        # a plain tool result: the coach stays in its loop and answers with what it has
        return ToolMessage(
            content=CONSULT_BUDGET_SPENT.format(domain=domain, n=max_consults),
            tool_call_id=tool_call_id,
            name=f"consult_{domain}",
        )
    message_id = str(uuid4())
    ack = ToolMessage(
        content=f"{domain} consulted; its answer replaces this message.",
        tool_call_id=tool_call_id,
        name=f"consult_{domain}",
        id=message_id,
    )
    brief = Brief(
        domain=domain, instruction=instruction, tool_call_id=tool_call_id, message_id=message_id
    )
    return handoff(
        domain, tool_call_id=tool_call_id, messages=messages, ack=ack, update={"brief": brief}
    )


def make_handoff_tools(
    max_consults: int | None = None, spent: Mapping[str, int] | None = None
) -> list[BaseTool]:
    """The coach's handoff tools. `spent` is this turn's consultations by domain (the coach node
    reads it from state on every entry); past `max_consults` a consult returns the budget message
    instead of handing off. With no arguments the tools are unlimited (evals, tests)."""
    used = dict(spent or {})

    @tool
    def consult_planning(
        instruction: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str] | ToolMessage:
        """Brief the planning agent to change the calendar, the goal or the horizon. The
        instruction must name the signal, the lever and the constraint. The result (a proposal
        id with its summary, or the agent's question) comes back as this call's result."""
        return _consult(
            "planning", instruction, tool_call_id, messages, used.get("planning", 0), max_consults
        )

    @tool
    def consult_nutrition(
        instruction: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str] | ToolMessage:
        """Brief the nutrition agent to change daily targets, fueling notes, the profile or the
        race plan. The instruction must name the signal, the lever and the constraint. The
        result comes back as this call's result."""
        return _consult(
            "nutrition",
            instruction,
            tool_call_id,
            messages,
            used.get("nutrition", 0),
            max_consults,
        )

    @tool
    def propose_changes(
        narration: str,
        proposal_ids: list[str],
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str]:
        """Send the kept proposals to the athlete for review, with a two or three sentence
        narration of why. Ends your turn; the athlete approves, rejects with a note, or edits."""
        ack = ToolMessage(
            content=f"change set {proposal_ids} sent to the athlete for review",
            tool_call_id=tool_call_id,
            name="propose_changes",
            id=str(uuid4()),
        )
        return handoff(
            "review",
            tool_call_id=tool_call_id,
            messages=messages,
            ack=ack,
            update={
                "proposal_request": ProposalRequest(narration=narration, ids=list(proposal_ids))
            },
        )

    return [consult_planning, consult_nutrition, propose_changes]
