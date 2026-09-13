"""ask_analyst: the tri-analyze agent as a tool. Each call runs the analyst on a throwaway
in-memory thread with the coach's read-only tools and returns its final text."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from tri_analyze.agent.agent import build_agent
from tri_analyze.agent.prompt import load_athlete_context, render_system_prompt
from tri_core.db.repo import Conn

ANALYST_RECURSION_LIMIT = 40


def _text(msg: AIMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    return "".join(
        str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
    )


def make_analyst_tool(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    connect: Callable[[], AbstractContextManager[Conn]],
    today: Callable[[], date],
) -> BaseTool:
    live = [t.name for t in tools if t.name != "query_training_db"]

    async def ask_analyst(question: str) -> str:
        """Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition
        or how training compares to plan. It reads the database and the devices; it changes
        nothing. Ask one specific question at a time."""
        with connect() as conn:
            ctx = load_athlete_context(conn, today())
        agent = build_agent(model, tools, render_system_prompt(ctx, live), InMemorySaver())
        out = await agent.ainvoke(
            {"messages": [HumanMessage(question)]},
            {
                "configurable": {"thread_id": f"analyst-{uuid4()}"},
                "recursion_limit": ANALYST_RECURSION_LIMIT,
            },
        )
        for msg in reversed(out["messages"]):
            if isinstance(msg, AIMessage) and not msg.tool_calls:
                text = _text(msg)
                if text:
                    return text
        return "The analyst returned no answer; ask a narrower question."

    return StructuredTool.from_function(
        coroutine=ask_analyst, name="ask_analyst", description=ask_analyst.__doc__
    )
