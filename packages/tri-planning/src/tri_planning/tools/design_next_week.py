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
    async def design_next_week(
        config: Annotated[RunnableConfig, InjectedToolArg], note: str | None = None
    ) -> str:
        """Design the next plan week that is not yet on the calendar (sessions, durations,
        structure) so at least two weeks ahead stay covered. Its sessions join the proposal
        automatically. Re-designs a week that was designed but never approved. A week whose
        design still breaks a rule after one retry is refused: you get its violations and no
        changes. `note`: what the athlete wants changed, when calling again after a refusal."""
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
                if w.week_start >= monday and not w.written_to_tp and w.week_start <= horizon_end
            ),
            None,
        )
        if row is None:
            unwritten = [w for w in weeks if w.week_start >= monday and not w.written_to_tp]
            if unwritten:
                return json.dumps(
                    {"error": "every week inside the horizon is already on the calendar"}
                )
            return json.dumps({"error": "every remaining week is already on the calendar"})
        target = next(t for t in plan.targets if t.week_start == row.week_start)
        previous = next(
            (w.designed for w in reversed(weeks) if w.designed and w.week_start < row.week_start),
            None,
        )
        week, violations = await design_week(
            deps, stored.goal, target, thresholds, previous, note, config
        )
        with deps.connect() as conn:
            if violations:
                repo.set_week_designed(conn, plan_id, row.week_start, None, violations)
            else:
                repo.set_week_designed(conn, plan_id, row.week_start, week)
            conn.commit()
        if violations:
            return json.dumps(
                {"week_start": row.week_start.isoformat(), "violations": violations, "changes": []}
            )
        changes = session_changes(week, target)
        return json.dumps(
            {
                "week_start": row.week_start.isoformat(),
                "coach_note": week.coach_note,
                "violations": [],
                "changes": [c.model_dump(mode="json") for c in changes],
            }
        )

    return StructuredTool.from_function(
        coroutine=design_next_week,
        name="design_next_week",
        description=design_next_week.__doc__ or "",
    )
