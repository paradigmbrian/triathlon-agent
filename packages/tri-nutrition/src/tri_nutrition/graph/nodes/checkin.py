"""Checkin node: a sub-agent that runs the check-in, answers questions, and edits the profile.
Its tool results decide the route: a profile save or a target-change proposal sends the run to
targets; anything else ends the turn."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_nutrition.allowlist import CHECKIN_READ_TOOLS
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.llm import make_subagent
from tri_nutrition.graph.nodes.intake import profile_saved_from_messages
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.prompts.checkin import render_checkin_prompt
from tri_nutrition.tools.checkin import make_checkin_tools
from tri_nutrition.tools.garmin import make_garmin_read_tools
from tri_nutrition.tools.plan import make_plan_tool
from tri_nutrition.tools.profile import make_profile_tools


def proposal_from_messages(messages: Sequence[AnyMessage]) -> dict[str, Any] | None:
    """The overrides of the last propose_target_changes result when it succeeded (may be {})."""
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "propose_target_changes":
            try:
                data = json.loads(str(msg.content))
            except json.JSONDecodeError:
                return None
            if isinstance(data, dict) and data.get("proposed"):
                overrides = data.get("overrides")
                return dict(overrides) if isinstance(overrides, dict) else {}
            return None
    return None


def make_checkin_node(deps: GraphDeps) -> Any:
    tools = [
        make_query_tool(deps.db_url),
        make_plan_tool(deps.connect, deps.today, deps.horizon_days),
        *make_garmin_read_tools(deps.garmin, deps.today, only=CHECKIN_READ_TOOLS),
        *make_profile_tools(),
        *make_checkin_tools(deps.garmin, deps.connect, deps.today),
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
        proposal = proposal_from_messages(new)
        if proposal is not None:
            update["targets_requested"] = True
            update["profile_overrides"] = proposal or None
            update["regenerate_from"] = "checkin"
        return update

    return checkin
