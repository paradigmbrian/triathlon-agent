"""Design node: one structured-output call per window week, scaled to its target, validated,
retried once; a week that still fails is stored with its violations and not proposed."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from tri_core.llm import structured
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning import validate
from tri_planning.planning.models import (
    CalendarChange,
    DesignedWeek,
    PlannedWeek,
    PlanWeekRow,
    TrainingGoal,
    WeekTarget,
)
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import event_change
from tri_planning.planning.tss import scale_to_target
from tri_planning.prompts.design import DESIGN_SYSTEM, render_design_prompt

NO_WEEK = "the designer returned no week in two attempts"


def not_designed_line(week_start: date, violations: list[str]) -> str:
    return f"week {week_start}: not designed: " + "; ".join(violations)


def window_weeks(weeks: list[PlanWeekRow], today: date, horizon: int) -> list[PlanWeekRow]:
    """The next `horizon` unwritten plan weeks from this week on. A plan that starts next
    Monday gets its full horizon; a week before the plan is not a plan week."""
    if not weeks:
        return []
    first = max(week_monday(today), weeks[0].week_start)
    last = first + timedelta(weeks=horizon - 1)
    return [w for w in weeks if first <= w.week_start <= last and not w.written_to_tp]


def checked_week(
    designed: DesignedWeek, target: WeekTarget, goal: TrainingGoal
) -> tuple[PlannedWeek, list[str]]:
    """The designed week scaled to its target, and its violations. When scaling cannot reach
    the target, its line (which asks for more or fewer sessions) replaces the validator's sum
    line."""
    week, scaling = scale_to_target(designed, target)
    violations = validate.week(week, target, goal)
    if scaling:
        violations = scaling + [v for v in violations if not v.startswith(validate.TSS_SUM_PREFIX)]
    return week, violations


async def design_week(
    deps: GraphDeps,
    goal: TrainingGoal,
    target: WeekTarget,
    thresholds: dict[str, Any] | None,
    previous: PlannedWeek | None,
    note: str | None,
    config: RunnableConfig,
) -> tuple[PlannedWeek, list[str]]:
    designer = structured(deps.design_model or deps.model, DesignedWeek)
    cfg = merge_configs(
        config, {"tags": [f"week_start:{target.week_start}", f"phase:{target.phase}"]}
    )

    async def one(prompt: str) -> DesignedWeek | None:
        out = await designer.ainvoke(
            [SystemMessage(DESIGN_SYSTEM), HumanMessage(prompt)], config=cfg
        )
        return out if isinstance(out, DesignedWeek) else None

    first = render_design_prompt(goal, target, thresholds, previous, note, None, None)
    designed = await one(first)
    if designed is None:
        designed = await one(first)  # a reply without the structured week gets one more try
    if designed is None:
        empty = PlannedWeek(week_start=target.week_start, sessions=[], coach_note=NO_WEEK)
        return empty, [NO_WEEK]
    week, violations = checked_week(designed, target, goal)
    if violations:
        retry = await one(
            render_design_prompt(goal, target, thresholds, previous, note, violations, week)
        )
        if retry is not None:
            week, violations = checked_week(retry, target, goal)
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
                if violations:
                    repo.set_week_designed(conn, plan_id, row.week_start, None, violations)
                else:
                    repo.set_week_designed(conn, plan_id, row.week_start, week)
                conn.commit()
            if violations:
                # still failing after the retry: stored with its reasons, never proposed
                flagged[row.week_start.isoformat()] = violations
                notes.append(not_designed_line(row.week_start, violations))
                continue
            changes.extend(session_changes(week, target))
            notes.append(
                f"{row.week_start} ({target.phase}, target {target.target_tss:.0f} TSS): "
                f"{len(week.sessions)} sessions, {week.total_tss:.0f} TSS, {week.total_hours:.1f} h"
            )
            previous = week

        if goal.create_tp_event and stored.tp_event_id is None and goal.event_date is not None:
            changes.insert(0, event_change(goal))
        summary = "\n".join(notes) if notes else "No weeks to design inside the horizon."
        update: dict[str, Any] = {
            "pending_changes": changes,
            "pending_summary": summary,
            "pending_violations": flagged,
            "changes_from": "design",
            "review_decision": None,
        }
        if not changes:
            update["messages"] = [AIMessage(summary)]  # nothing to review: the turn ends here
        return update

    return design
