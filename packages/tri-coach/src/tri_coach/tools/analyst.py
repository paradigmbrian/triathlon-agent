"""ask_analyst: the tri-analyze agent as a tool. Each call runs the analyst on a throwaway
in-memory thread with the coach's read-only tools and returns its final text, or the failure as
text (spec 9)."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from tri_analyze.agent import build_agent
from tri_analyze.repo import load_athlete_context
from tri_core.db.repo import Conn
from tri_core.harness.agent_tool import Invocation, agent_tool

ANALYST_RECURSION_LIMIT = 40

ASK_ANALYST_DESCRIPTION = inspect.cleandoc(
    """Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,
    logged intake against nutrition targets, or how training compares to plan. It reads the
    database and the devices; it changes nothing. Ask one specific question at a time."""
)


def make_analyst_tool(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    connect: Callable[[], AbstractContextManager[Conn]],
    today: Callable[[], date],
) -> BaseTool:
    def prepare() -> Invocation:
        with connect() as conn:
            ctx = load_athlete_context(conn, today())
        return Invocation(build_agent(model, tools, InMemorySaver()), context=ctx)

    return agent_tool(
        name="ask_analyst",
        description=ASK_ANALYST_DESCRIPTION,
        prepare=prepare,
        thread_prefix="analyst",
        recursion_limit=ANALYST_RECURSION_LIMIT,
        failure="The analyst failed ({error}); do not guess at the data it could not read.",
        empty="The analyst returned no answer; ask a narrower question.",
    )
