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
from tri_coach.graph.llm import make_subagent
from tri_coach.graph.state import CoachState
from tri_coach.prompts.coach import render_system_prompt
from tri_coach.tools.analyst import make_analyst_tool
from tri_coach.tools.handoff import make_handoff_tools
from tri_coach.tools.memory import make_memory_tools


def make_coach_node(deps: CoachDeps) -> Any:
    analyst = make_analyst_tool(deps.analyst_model, deps.analyst_tools, deps.connect, deps.today)
    tools = [analyst, *make_handoff_tools(), *make_memory_tools(deps.today)]

    async def coach(
        state: CoachState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        with deps.connect() as conn:
            ctx = await load_context(conn, store, deps.today(), state.get("pending"))
        entries = await M.get_entries(store)
        prompt = render_system_prompt(ctx, entries, max_consults=deps.max_consults)
        agent = make_subagent(deps.model, tools, prompt)
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        return {"messages": result["messages"][len(before) :]}

    return coach
