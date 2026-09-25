"""Design node: one structured-output call per window week, validated, retried once."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from tri_core.llm import structured
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning import validate
from tri_planning.planning.models import (
    CalendarChange,
    PlannedWeek,
    PlanWeekRow,
    TrainingGoal,
    WeekTarget,
)
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import event_change
from tri_planning.prompts.design import DESIGN_SYSTEM, render_design_prompt

NO_WEEK = "the designer returned no week in two attempts"


def window_weeks(weeks: list[PlanWeekRow], today: date, horizon: int) -> list[PlanWeekRow]:
    """The next `horizon` unwritten plan weeks from this week on. A plan that starts next
    Monday gets its full horizon; a week before the plan is not a plan week."""
    if not weeks:
        return []
    first = max(week_monday(today), weeks[0].week_start)
    last = first + timedelta(weeks=horizon - 1)
    return [w for w in weeks if first <= w.week_start <= last and not w.written_to_tp]


async def design_week(
    deps: GraphDeps,
    goal: TrainingGoal,
    target: WeekTarget,
    thresholds: dict[str, Any] | None,
    previous: PlannedWeek | None,
    note: str | None,
    config: RunnableConfig,
) -> tuple[PlannedWeek, list[str]]:
    designer = structured(deps.design_model or deps.model, PlannedWeek)
    cfg = merge_configs(
        config, {"tags": [f"week_start:{target.week_start}", f"phase:{target.phase}"]}
    )

    async def one(prompt: str) -> PlannedWeek | None:
        out = await designer.ainvoke(
            [SystemMessage(DESIGN_SYSTEM), HumanMessage(prompt)], config=cfg
        )
        return out if isinstance(out, PlannedWeek) else None

    first = render_design_prompt(goal, target, thresholds, previous, note, None, None)
    week = await one(first)
    if week is None:
        week = await one(first)  # a reply without the structured week gets one more try
    if week is None:
        empty = PlannedWeek(week_start=target.week_start, sessions=[], coach_note=NO_WEEK)
        return empty, [NO_WEEK]
    violations = validate.week(week, target, goal)
    if violations:
        retry = await one(
            render_design_prompt(goal, target, thresholds, previous, note, violations, week)
        )
        if retry is not None:
            week, violations = retry, validate.week(retry, target, goal)
    return week, violations


def session_changes(week: PlannedWeek, target: WeekTarget) -> list[CalendarChange]:
    """One create per non-rest session, each carrying the target week it was designed for."""
    return [
        CalendarChange(
            op="create",
            workout_date=s.date,
            workout=s,
            reason=f"{target.phase} week of {week.week_start}: {week.coach_note}",
            design_week=target.week_start,
        )
        for s in week.sessions
        if s.sport != "rest"
    ]


def make_design_node(deps: GraphDeps) -> Any:
    async def design(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        goal_id, plan_id = state.get("goal_id"), state.get("plan_id")
        assert goal_id is not None and plan_id is not None
        with deps.connect() as conn:
            stored = repo.get_goal(conn, goal_id)
            plan = repo.get_plan(conn, plan_id)
            weeks = repo.list_weeks(conn, plan_id)
            thresholds = repo.athlete_thresholds(conn)
        assert stored is not None and plan is not None
        goal = stored.goal
        decision = state.get("review_decision")
        note = decision.note if decision is not None and decision.action == "reject" else None

        todo = window_weeks(weeks, deps.today(), deps.horizon_weeks)
        previous = next(
            (
                w.designed
                for w in reversed(weeks)
                if w.designed and todo and w.week_start < todo[0].week_start
            ),
            None,
        )
        changes: list[CalendarChange] = []
        notes: list[str] = []
        flagged: dict[str, list[str]] = {}
        for row in todo:
            target = next(t for t in plan.targets if t.week_start == row.week_start)
            week, violations = await design_week(
                deps, goal, target, thresholds, previous, note, config
            )
            with deps.connect() as conn:
                repo.set_week_designed(conn, plan_id, row.week_start, week)
                conn.commit()
            changes.extend(session_changes(week, target))
            line = (
                f"{row.week_start} ({target.phase}, target {target.target_tss:.0f} TSS): "
                f"{len(week.sessions)} sessions, {week.total_tss:.0f} TSS, {week.total_hours:.1f} h"
            )
            if violations:
                line += "\n  VIOLATIONS: " + "; ".join(violations)
                flagged[row.week_start.isoformat()] = violations
            notes.append(line)
            previous = week

        if goal.create_tp_event and stored.tp_event_id is None and goal.event_date is not None:
            changes.insert(0, event_change(goal))
        summary = "\n".join(notes) if notes else "No weeks to design inside the horizon."
        return {
            "pending_changes": changes,
            "pending_summary": summary,
            "pending_violations": flagged,
            "changes_from": "design",
            "review_decision": None,
        }

    return design
