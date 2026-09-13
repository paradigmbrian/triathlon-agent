"""Handoffs: tools that move the run from the coach to a sub-graph node.

A tool inside create_agent that returns Command(graph=Command.PARENT) unwinds the agent before
its model step is committed, so the AIMessage that made the call would be lost and the parent's
history would hold a tool result with no tool use. Each handoff therefore re-emits the turn's
messages (ids intact; add_messages upserts) together with its own ToolMessage. The sub-graph
node later replaces that ToolMessage's content (same id) with its result."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from tri_coach.models import Brief, Domain, ProposalRequest


def turn_messages(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Everything after the last HumanMessage: the messages this turn produced so far."""
    last = -1
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            last = i
    return list(messages[last + 1 :])


NOT_DELIVERED = "not delivered: this step ended with a handoff; call again if still needed"


def undelivered(turn: Sequence[AnyMessage], handoff_call_id: str) -> list[ToolMessage]:
    """A result for every sibling call of the handoff that the tools node will never answer.

    The sub-agent unwinds the moment a handoff tool returns, so a call made alongside it in the
    same step loses its result. Anthropic rejects a persisted history that holds a tool_use with
    no tool_result, which would break every later turn on the thread."""
    last_ai = next((m for m in reversed(turn) if isinstance(m, AIMessage)), None)
    if last_ai is None:
        return []
    answered = {m.tool_call_id for m in turn if isinstance(m, ToolMessage)} | {handoff_call_id}
    return [
        ToolMessage(content=NOT_DELIVERED, tool_call_id=tc["id"], name=tc["name"], id=str(uuid4()))
        for tc in last_ai.tool_calls
        if tc["id"] and tc["id"] not in answered
    ]


def _consult(
    domain: Domain, instruction: str, tool_call_id: str, messages: Sequence[AnyMessage]
) -> Command[str]:
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
    turn = turn_messages(messages)
    return Command(
        goto=domain,
        graph=Command.PARENT,
        update={"brief": brief, "messages": [*turn, *undelivered(turn, tool_call_id), ack]},
    )


def make_handoff_tools() -> list[BaseTool]:
    @tool
    def consult_planning(
        instruction: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str]:
        """Brief the planning agent to change the calendar, the goal or the horizon. The
        instruction must name the signal, the lever and the constraint. The result (a proposal
        id with its summary, or the agent's question) comes back as this call's result."""
        return _consult("planning", instruction, tool_call_id, messages)

    @tool
    def consult_nutrition(
        instruction: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str]:
        """Brief the nutrition agent to change daily targets, fueling notes, the profile or the
        race plan. The instruction must name the signal, the lever and the constraint. The
        result comes back as this call's result."""
        return _consult("nutrition", instruction, tool_call_id, messages)

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
        turn = turn_messages(messages)
        return Command(
            goto="review",
            graph=Command.PARENT,
            update={
                "proposal_request": ProposalRequest(narration=narration, ids=list(proposal_ids)),
                "messages": [*turn, *undelivered(turn, tool_call_id), ack],
            },
        )

    return [consult_planning, consult_nutrition, propose_changes]
