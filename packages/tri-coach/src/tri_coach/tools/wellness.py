"""ask_wellness: the tri-wellness chat agent as a tool. Each call runs the lab interpreter on a
throwaway in-memory thread with wellness's own prompt and read-only tools and returns its final
text. The coach never writes a wellness row: ingest and report stay athlete-driven commands."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphBubbleUp

from tri_coach.text import last_ai_text
from tri_core.db.repo import Conn
from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.agents import build_chat_agent
from tri_wellness import repo
from tri_wellness.prompts.chat import render_chat_prompt
from tri_wellness.ranges.registry import MarkerRegistry
from tri_wellness.report import athlete_profile
from tri_wellness.tools.findings import WELLNESS_SCHEMA_DOC, make_findings_tools

ConnectFactory = Callable[[], AbstractContextManager[Conn]]

WELLNESS_RECURSION_LIMIT = 40


def wellness_tools(
    connect: ConnectFactory, db_url: str, registry: MarkerRegistry
) -> list[BaseTool]:
    """What tri-wellness chat binds: the SQL read tool with the lab schema doc and the three
    findings tools. None of them writes."""
    return [make_query_tool(db_url, WELLNESS_SCHEMA_DOC), *make_findings_tools(connect, registry)]


def make_wellness_tool(
    model: BaseChatModel,
    connect: ConnectFactory,
    db_url: str,
    registry: MarkerRegistry,
    today: Callable[[], date],
) -> BaseTool:
    tools = wellness_tools(connect, db_url, registry)
    names = [t.name for t in tools]

    async def ask_wellness(question: str) -> str:
        """Ask the lab interpreter about the athlete's lab panels: a marker's value against its
        functional range, what is outside optimal and why, the retest plan, supplements, or
        whether a symptom could be lab-related. It reads stored panels and reports; it changes
        nothing. Ask one specific question at a time."""
        try:
            with connect() as conn:
                profile = athlete_profile(conn)
                panels = repo.list_panels(conn)
                latest = repo.latest_panel_id(conn)
                latest_report = repo.latest_report_for_panel(conn, latest) if latest else None
            prompt = render_chat_prompt(
                profile, registry.sex, panels, latest_report, today(), names
            )
            agent = build_chat_agent(
                model, tools, system_prompt=prompt, checkpointer=InMemorySaver()
            )
            out = await agent.ainvoke(
                {"messages": [HumanMessage(question)]},
                {
                    "configurable": {"thread_id": f"wellness-{uuid4()}"},
                    "recursion_limit": WELLNESS_RECURSION_LIMIT,
                },
            )
        except GraphBubbleUp:
            raise  # interrupts and other langgraph control flow must keep propagating
        except Exception as exc:
            return (
                f"The lab interpreter failed ({type(exc).__name__}: {exc}); "
                "answer without lab data."
            )
        return last_ai_text(out["messages"]) or (
            "The lab interpreter returned no answer; ask a narrower question."
        )

    return StructuredTool.from_function(
        coroutine=ask_wellness,
        name="ask_wellness",
        description=inspect.cleandoc(ask_wellness.__doc__ or ""),
    )
