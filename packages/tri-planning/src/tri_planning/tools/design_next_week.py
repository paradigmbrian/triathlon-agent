"""Window extension for the adjust sub-agent: design the next target week with the design prompt."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolArg, StructuredTool

from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.nodes.design import design_week, session_changes
from tri_planning.planning.targets import week_monday


def make_design_next_week_tool(
    deps: GraphDeps, plan_id_getter: Callable[[], int | None]
) -> BaseTool:
    async def design_next_week(config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
        """Design the next undesigned week of the plan (sessions, TSS, structure) so the calendar
        keeps at least two designed weeks ahead. Its sessions join the proposal automatically."""
        plan_id = plan_id_getter()
        if plan_id is None:
            return json.dumps({"error": "no active plan"})
        with deps.connect() as conn:
            plan = repo.get_plan(conn, plan_id)
            assert plan is not None
            stored = repo.get_goal(conn, plan.goal_id)
            assert stored is not None
            weeks = repo.list_weeks(conn, plan_id)
            thresholds = repo.athlete_thresholds(conn)
        monday = week_monday(deps.today())
        horizon_end = monday + timedelta(weeks=deps.horizon_weeks - 1)
        row = next(
            (
                w
                for w in weeks
                if w.week_start >= monday
                and w.designed is None
                and not w.written_to_tp
                and w.week_start <= horizon_end
            ),
            None,
        )
        if row is None:
            undesigned = [
                w
                for w in weeks
                if w.week_start >= monday and w.designed is None and not w.written_to_tp
            ]
            if undesigned:
                return json.dumps({"error": "every week inside the horizon is already designed"})
            return json.dumps({"error": "every remaining week is already designed"})
        target = next(t for t in plan.targets if t.week_start == row.week_start)
        previous = next(
            (w.designed for w in reversed(weeks) if w.designed and w.week_start < row.week_start),
            None,
        )
        week, violations = await design_week(
            deps, stored.goal, target, thresholds, previous, None, config
        )
        with deps.connect() as conn:
            repo.set_week_designed(conn, plan_id, row.week_start, week)
            conn.commit()
        changes = session_changes(week, target.phase)
        return json.dumps(
            {
                "week_start": row.week_start.isoformat(),
                "coach_note": week.coach_note,
                "violations": violations,
                "changes": [c.model_dump(mode="json") for c in changes],
            }
        )

    return StructuredTool.from_function(
        coroutine=design_next_week,
        name="design_next_week",
        description=design_next_week.__doc__ or "",
    )
