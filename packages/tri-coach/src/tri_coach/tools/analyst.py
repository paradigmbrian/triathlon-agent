"""ask_analyst: the tri-analyze agent as a tool. Each call runs the analyst on a throwaway
in-memory thread with the coach's read-only tools and returns its final text, or the failure as
text (spec 9)."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphBubbleUp

from tri_analyze._old_agent.agent import build_agent
from tri_analyze._old_agent.prompt import load_athlete_context, render_system_prompt
from tri_coach.text import last_ai_text
from tri_core.db.repo import Conn

ANALYST_RECURSION_LIMIT = 40


def make_analyst_tool(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    connect: Callable[[], AbstractContextManager[Conn]],
    today: Callable[[], date],
) -> BaseTool:
    live = [t.name for t in tools if t.name != "query_training_db"]

    async def ask_analyst(question: str) -> str:
        """Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,
        logged intake against nutrition targets, or how training compares to plan. It reads the
        database and the devices; it changes nothing. Ask one specific question at a time."""
        try:
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
        except GraphBubbleUp:
            raise  # interrupts and other langgraph control flow must keep propagating
        except Exception as exc:
            return (
                f"The analyst failed ({type(exc).__name__}: {exc}); "
                "do not guess at the data it could not read."
            )
        return last_ai_text(out["messages"]) or (
            "The analyst returned no answer; ask a narrower question."
        )

    return StructuredTool.from_function(
        coroutine=ask_analyst,
        name="ask_analyst",
        description=inspect.cleandoc(ask_analyst.__doc__ or ""),
    )
