"""Targets node: goal + fitness -> week targets in the database. No model call."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning import periodization as P
from tri_planning.planning.models import CalendarChange, StoredGoal, WeekTarget
from tri_planning.planning.targets import build, infer_phases, next_monday, week_monday
from tri_planning.planning.tp_calls import event_change


def weekly_targets_from_workouts(workouts: list[dict[str, Any]], start: date) -> list[WeekTarget]:
    tss: dict[date, float] = defaultdict(float)
    hours: dict[date, float] = defaultdict(float)
    for w in workouts:
        day = date.fromisoformat(str(w["date"])[:10])
        if day < start:
            continue
        monday = week_monday(day)
        tss[monday] += float(w.get("tss_planned") or 0)
        hours[monday] += float(w.get("duration_planned") or 0)  # TP totalTimePlanned is hours
    mondays = sorted(tss)
    phases = infer_phases([tss[m] for m in mondays])
    return [
        WeekTarget(
            week_start=m,
            phase=ph,
            target_tss=round(tss[m]),
            target_hours=round(hours[m], 1),
            sport_hint=P.SPORT_HINTS[ph],
        )
        for m, ph in zip(mondays, phases, strict=True)
    ]


def _summary(targets: list[WeekTarget], source: str) -> str:
    counts: dict[str, int] = defaultdict(int)
    for t in targets:
        counts[t.phase] += 1
    phases = ", ".join(f"{n} {p}" for p, n in counts.items())
    first, last = targets[0], targets[-1]
    flags = sorted({f for t in targets for f in t.flags})
    lines = [
        f"Targets ({source}): {len(targets)} weeks from {first.week_start} to "
        f"{last.week_start + timedelta(days=6)}; phases: {phases}.",
        f"Week 1 target {first.target_tss:.0f} TSS / {first.target_hours:.1f} h; peak "
        f"{max(t.target_tss for t in targets):.0f} TSS.",
    ]
    if flags:
        lines.append(f"Flags: {', '.join(flags)}.")
    return "\n".join(lines)


def make_targets_node(deps: GraphDeps) -> Any:
    async def _adopt_tp_plan(stored: StoredGoal, thread_id: str) -> dict[str, Any]:
        assert deps.tp is not None and stored.goal.event_date is not None
        start = next_monday(deps.today())
        end = stored.goal.event_date + timedelta(days=7)
        result = await deps.tp.call_json(
            "tp_get_workouts",
            {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "workout_filter": "planned",
            },
        )
        workouts = list((result or {}).get("workouts", []))
        targets = weekly_targets_from_workouts(workouts, start)
        if not targets:
            return {
                "last_error": "no planned workouts found after applying the TrainingPeaks plan",
                "tp_plan_applied": False,
            }
        with deps.connect() as conn:
            plan_id = repo.insert_plan(conn, stored.id, "tp_plan", stored.goal.tp_plan_id, targets)
            for w in workouts:
                wid = str(w["id"])
                change = CalendarChange(
                    op="apply_plan",
                    tp_workout_id=wid,
                    workout_date=date.fromisoformat(str(w["date"])[:10]),
                    reason=f"applied TrainingPeaks plan {stored.goal.tp_plan_id}",
                )
                repo.insert_change(conn, plan_id, thread_id, change, tp_workout_id=wid, result=None)
            repo.mark_weeks_written(conn, plan_id, [t.week_start for t in targets])
            conn.commit()
        return {
            "plan_id": plan_id,
            "phase": "active",
            "tp_plan_applied": False,
            "pending_changes": [],
            "pending_summary": None,
            "messages": [AIMessage(_summary(targets, "TrainingPeaks plan"))],
        }

    async def targets_node(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        goal_id = state.get("goal_id")
        assert goal_id is not None, "targets node needs goal_id"
        thread_id = str(config["configurable"]["thread_id"])
        with deps.connect() as conn:
            stored = repo.get_goal(conn, goal_id)
            assert stored is not None
            fitness = repo.fitness_snapshot(conn, deps.today())
        goal = stored.goal

        if goal.tp_plan_id:
            if state.get("tp_plan_applied"):
                return await _adopt_tp_plan(stored, thread_id)
            start = next_monday(deps.today())
            changes: list[CalendarChange] = []
            if goal.create_tp_event and stored.tp_event_id is None:
                changes.append(event_change(goal))
            changes.append(
                CalendarChange(
                    op="apply_plan",
                    payload={"plan_id": goal.tp_plan_id, "start_date": start.isoformat()},
                    reason=f"activate TrainingPeaks plan {goal.tp_plan_id} from {start}",
                )
            )
            return {
                "pending_changes": changes,
                "changes_from": "targets",
                "pending_summary": f"Apply bought plan {goal.tp_plan_id} starting {start}.",
            }

        if state.get("plan_id") is not None:
            return {}
        targets = build(goal, fitness, next_monday(deps.today()))
        with deps.connect() as conn:
            plan_id = repo.insert_plan(conn, stored.id, "generated", None, targets)
            conn.commit()
        return {"plan_id": plan_id, "messages": [AIMessage(_summary(targets, "generated"))]}

    return targets_node
