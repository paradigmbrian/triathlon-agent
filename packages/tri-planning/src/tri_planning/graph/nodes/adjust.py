"""Adjust node: a create_agent sub-agent that reviews training and proposes calendar changes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.agents import make_subagent
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning.models import CalendarChange
from tri_planning.prompts.adjust import load_adjust_context, render_adjust_prompt
from tri_planning.tools.changes import make_change_tool
from tri_planning.tools.design_next_week import make_design_next_week_tool
from tri_planning.tools.tp_read import make_tp_read_tools


def _json(msg: ToolMessage) -> dict[str, Any] | None:
    try:
        data = json.loads(str(msg.content))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def changes_from_messages(
    messages: Sequence[AnyMessage],
) -> tuple[list[CalendarChange], str | None, dict[str, list[str]]]:
    """Changes from the last `propose_calendar_changes` result plus the last `design_next_week`
    result per week, in week order of first appearance; the proposal's summary, or a generated
    one when only designed weeks were added; and the validator violations of each designed
    week that has any, keyed by week_start ISO date.

    A week designed twice in one turn would otherwise be created twice, so a repeat replaces
    the earlier result (and its violations) instead of adding to it.
    """
    designed: dict[str, list[CalendarChange]] = {}
    violations: dict[str, list[str]] = {}
    proposed: list[CalendarChange] = []
    summary: str | None = None
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        data = _json(msg)
        if data is None or "changes" not in data:
            continue
        changes = [CalendarChange.model_validate(c) for c in data["changes"]]
        if msg.name == "design_next_week":
            week = str(data.get("week_start"))
            designed[week] = changes
            violations.pop(week, None)
            if data.get("violations"):
                violations[week] = [str(v) for v in data["violations"]]
        elif msg.name == "propose_calendar_changes":
            proposed = changes
            summary = data.get("summary") or None
    designed_weeks = list(designed)
    all_changes = [c for week in designed_weeks for c in designed[week]] + proposed
    if summary is None and designed_weeks:
        summary = (
            "Designed week(s) " + ", ".join(designed_weeks) + " added to the calendar proposal."
        )
    return all_changes, summary, violations


def make_adjust_node(deps: GraphDeps) -> Any:
    query = make_query_tool(deps.db_url)
    change_tool = make_change_tool()
    tp_tools = make_tp_read_tools(deps.tp)

    async def adjust(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        plan_id = state.get("plan_id")
        assert plan_id is not None, "adjust needs an active plan"
        with deps.connect() as conn:
            ctx = load_adjust_context(conn, deps.today(), plan_id, deps.horizon_weeks)
        design_tool = make_design_next_week_tool(deps, lambda: plan_id)
        tools = [query, *deps.garmin_tools, *tp_tools, design_tool, change_tool]
        agent = make_subagent(deps.model, tools, render_adjust_prompt(ctx))
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        new = result["messages"][len(before) :]
        changes, summary, violations = changes_from_messages(new)
        if changes:
            return {
                "messages": new,
                "pending_changes": changes,
                "pending_summary": summary,
                "pending_violations": violations,
                "changes_from": "adjust",
                "review_decision": None,
            }
        # adjust is entered with either no pending changes or its own rejected proposal;
        # a turn that proposes nothing must clear that proposal so it isn't re-reviewed.
        return {
            "messages": new,
            "pending_changes": [],
            "pending_summary": None,
            "pending_violations": {},
            "changes_from": None,
            "review_decision": None,
        }

    return adjust
