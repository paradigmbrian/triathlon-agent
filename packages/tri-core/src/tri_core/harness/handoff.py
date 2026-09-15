"""Handoffs: leaving a create_agent sub-agent for another node of the parent graph.

A tool inside create_agent that returns Command(graph=Command.PARENT) unwinds the agent before
its model step is committed, so the AIMessage that made the call would be lost and the parent's
history would hold a tool result with no tool use. A handoff therefore re-emits the turn's
messages (ids intact; add_messages upserts), a result for every sibling call the unwinding cut
off, and its own acknowledgement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.types import Command


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


def handoff(
    goto: str,
    *,
    tool_call_id: str,
    messages: Sequence[AnyMessage],
    ack: ToolMessage,
    update: Mapping[str, Any] | None = None,
) -> Command[str]:
    """Jump to `goto` in the parent graph, carrying `update` and the turn's messages."""
    turn = turn_messages(messages)
    return Command(
        goto=goto,
        graph=Command.PARENT,
        update={**(update or {}), "messages": [*turn, *undelivered(turn, tool_call_id), ack]},
    )
