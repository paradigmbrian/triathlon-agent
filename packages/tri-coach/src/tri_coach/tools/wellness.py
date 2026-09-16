"""ask_wellness: the tri-wellness chat agent as a tool. Each call runs the lab interpreter on a
throwaway in-memory thread with wellness's own prompt and read-only tools and returns its final
text. The coach never writes a wellness row: ingest and report stay athlete-driven commands."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from tri_core.db.repo import Conn
from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.agent_tool import Invocation, agent_tool
from tri_core.harness.agents import build_chat_agent
from tri_wellness import repo
from tri_wellness.prompts.chat import render_chat_prompt
from tri_wellness.ranges.registry import MarkerRegistry
from tri_wellness.report import athlete_profile
from tri_wellness.tools.findings import WELLNESS_SCHEMA_DOC, make_findings_tools

ConnectFactory = Callable[[], AbstractContextManager[Conn]]

WELLNESS_RECURSION_LIMIT = 40

ASK_WELLNESS_DESCRIPTION = inspect.cleandoc(
    """Ask the lab interpreter about the athlete's lab panels: a marker's value against its
    functional range, what is outside optimal and why, the retest plan, supplements, or
    whether a symptom could be lab-related. It reads stored panels and reports; it changes
    nothing. Ask one specific question at a time."""
)


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

    def prepare() -> Invocation:
        with connect() as conn:
            profile = athlete_profile(conn)
            panels = repo.list_panels(conn)
            latest = repo.latest_panel_id(conn)
            latest_report = repo.latest_report_for_panel(conn, latest) if latest else None
        prompt = render_chat_prompt(profile, registry.sex, panels, latest_report, today(), names)
        agent = build_chat_agent(model, tools, system_prompt=prompt, checkpointer=InMemorySaver())
        return Invocation(agent)

    return agent_tool(
        name="ask_wellness",
        description=ASK_WELLNESS_DESCRIPTION,
        prepare=prepare,
        thread_prefix="wellness",
        recursion_limit=WELLNESS_RECURSION_LIMIT,
        failure="The lab interpreter failed ({error}); answer without lab data.",
        empty="The lab interpreter returned no answer; ask a narrower question.",
    )
