"""Checkin node (Plan 2 version): a sub-agent that answers questions and edits the profile.
Plan 4 replaces the prompt and adds the food-log tools and propose_target_changes."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.llm import make_subagent
from tri_nutrition.graph.nodes.intake import profile_saved_from_messages
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.prompts.checkin import render_checkin_prompt
from tri_nutrition.tools.plan import make_plan_tool
from tri_nutrition.tools.profile import make_profile_tools


def make_checkin_node(deps: GraphDeps) -> Any:
    tools = [
        make_query_tool(deps.db_url),
        make_plan_tool(deps.connect, deps.today, deps.horizon_days),
        *make_profile_tools(),
    ]
    agent = make_subagent(deps.model, tools, render_checkin_prompt(deps.today()))

    async def checkin(state: NutritionState, config: RunnableConfig) -> dict[str, Any]:
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        new = result["messages"][len(before) :]
        update: dict[str, Any] = {"messages": new}
        if profile_saved_from_messages(new):
            update["profile_saved"] = True
            update["regenerate_from"] = "checkin"
        return update

    return checkin
