"""An agent run as a tool: each call prepares the agent, runs it on a throwaway thread and returns
its final text, or the failure as text. Interrupts and other graph control flow propagate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphBubbleUp

from tri_core.harness.messages import last_ai_text


@dataclass(frozen=True)
class Invocation:
    agent: Any
    context: Any = None  # passed to ainvoke as context= only when set


def agent_tool(
    *,
    name: str,
    description: str,
    prepare: Callable[[], Invocation],
    thread_prefix: str,
    recursion_limit: int,
    failure: str,
    empty: str,
) -> BaseTool:
    async def run(question: str) -> str:
        try:
            invocation = prepare()
            kwargs: dict[str, Any] = {}
            if invocation.context is not None:
                kwargs["context"] = invocation.context
            out = await invocation.agent.ainvoke(
                {"messages": [HumanMessage(question)]},
                {
                    "configurable": {"thread_id": f"{thread_prefix}-{uuid4()}"},
                    "recursion_limit": recursion_limit,
                },
                **kwargs,
            )
        except GraphBubbleUp:
            raise  # interrupts and other langgraph control flow must keep propagating
        except Exception as exc:
            return failure.format(error=f"{type(exc).__name__}: {exc}")
        return last_ai_text(out["messages"]) or empty

    # gives args_schema the same top-level description as tool_call_schema
    run.__doc__ = description
    return StructuredTool.from_function(coroutine=run, name=name, description=description)
