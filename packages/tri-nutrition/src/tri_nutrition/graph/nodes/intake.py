"""Intake node: a create_agent sub-agent that ends the phase by calling save_nutrition_profile."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_nutrition.allowlist import INTAKE_READ_TOOLS
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.llm import make_subagent
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.prompts.intake import render_intake_prompt
from tri_nutrition.tools.garmin import make_garmin_read_tools
from tri_nutrition.tools.plan import make_plan_tool
from tri_nutrition.tools.profile import make_profile_tools


def profile_saved_from_messages(messages: Sequence[AnyMessage]) -> bool:
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "save_nutrition_profile":
            try:
                data = json.loads(str(msg.content))
            except json.JSONDecodeError:
                return False
            return bool(isinstance(data, dict) and data.get("saved"))
    return False


def make_intake_node(deps: GraphDeps) -> Any:
    tools = [
        make_query_tool(deps.db_url),
        make_plan_tool(deps.connect, deps.today, deps.horizon_days),
        *make_garmin_read_tools(deps.garmin, deps.today, only=INTAKE_READ_TOOLS),
        *make_profile_tools(),
    ]
    agent = make_subagent(deps.model, tools, render_intake_prompt(deps.today()))

    async def intake(state: NutritionState, config: RunnableConfig) -> dict[str, Any]:
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        new = result["messages"][len(before) :]
        update: dict[str, Any] = {"messages": new}
        if profile_saved_from_messages(new):
            update["profile_saved"] = True
            update["regenerate_from"] = "intake"
        return update

    return intake
