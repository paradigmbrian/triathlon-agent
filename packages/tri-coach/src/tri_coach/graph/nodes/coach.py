"""Coach node: a create_agent sub-agent rebuilt every turn with a fresh system prompt (rules,
context block, memory). Its handoff tools leave through Command.PARENT; a turn that ends in
conversation returns the new messages."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_coach import memory as M
from tri_coach.context import load_context
from tri_coach.graph.deps import CoachDeps
from tri_coach.graph.state import CoachState
from tri_coach.prompts.coach import render_system_prompt
from tri_coach.tools.analyst import make_analyst_tool
from tri_coach.tools.handoff import make_handoff_tools
from tri_coach.tools.memory import make_memory_tools
from tri_coach.tools.wellness import make_wellness_tool
from tri_core.harness.agents import make_subagent, one_tool_call_at_a_time


def make_coach_node(deps: CoachDeps) -> Any:
    analyst = make_analyst_tool(deps.analyst_model, deps.analyst_tools, deps.connect, deps.today)
    labs_enabled = deps.wellness_registry is not None
    wellness = (
        [
            make_wellness_tool(
                deps.wellness_model, deps.connect, deps.db_url, deps.wellness_registry, deps.today
            )
        ]
        if deps.wellness_registry is not None
        else []
    )
    tools = [analyst, *wellness, *make_handoff_tools(), *make_memory_tools(deps.today)]

    async def coach(
        state: CoachState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        with deps.connect() as conn:
            ctx = await load_context(
                conn, store, deps.today(), state.get("pending"), labs_enabled=labs_enabled
            )
        entries = await M.get_entries(store)
        prompt = render_system_prompt(ctx, entries, max_consults=deps.max_consults)
        agent = make_subagent(deps.model, tools, prompt, middleware=[one_tool_call_at_a_time])
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        return {"messages": result["messages"][len(before) :]}

    return coach
