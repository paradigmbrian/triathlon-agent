"""Intake node: a create_agent sub-agent that ends the phase by calling set_training_goal."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.llm import make_subagent
from tri_planning.graph.state import PlanningState
from tri_planning.prompts.intake import render_intake_prompt
from tri_planning.tools.goal import make_goal_tools


def goal_id_from_messages(messages: Sequence[AnyMessage]) -> int | None:
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "set_training_goal":
            try:
                data = json.loads(str(msg.content))
            except json.JSONDecodeError:
                return None
            gid = data.get("goal_id") if isinstance(data, dict) else None
            return int(gid) if gid is not None else None
    return None


def make_intake_node(deps: GraphDeps) -> Any:
    tools = [make_query_tool(deps.db_url), *make_goal_tools(deps.connect, deps.tp, deps.today)]
    agent = make_subagent(deps.model, tools, render_intake_prompt(deps.today()))

    async def intake(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        new = result["messages"][len(before) :]
        update: dict[str, Any] = {"messages": new}
        goal_id = goal_id_from_messages(new)
        if goal_id is not None:
            update["goal_id"] = goal_id
            update["phase"] = "planning"
        return update

    return intake
