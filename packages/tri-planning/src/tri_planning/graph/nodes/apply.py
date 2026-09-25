"""Apply: the only place TrainingPeaks is written. `apply_changes` sends one call per change,
recording each as it goes, and stops at the first failure; the node is state plumbing around it.
The coach calls `apply_changes` directly with `thread_id="coach"`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from tri_core.mcp.client import McpToolError
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning.models import CalendarChange
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import result_workout_id, to_tp_call

OWNED_OPS = ("update", "move", "delete")
SESSION_OPS = ("create", "update", "delete", "move")  # ops that change what the athlete trains
TP_UNAVAILABLE = "TrainingPeaks server unavailable; nothing applied, change set left pending."


def _label(c: CalendarChange) -> str:
    if c.workout is not None:
        return f"{c.op} {c.workout.date} {c.workout.sport} '{c.workout.title}'"
    return f"{c.op} {c.tp_workout_id or c.workout_date or ''}".strip()


@dataclass
class ApplyResult:
    applied: list[CalendarChange]
    skipped: list[str]
    remaining: list[CalendarChange]
    error: str | None
    tp_plan_applied: bool
    sessions_changed: bool  # any create/update/delete/move went through

    def report(self, total: int) -> str:
        lines = [f"TrainingPeaks: applied {len(self.applied)} of {total} changes."]
        lines += [f"  skipped: {s}" for s in self.skipped]
        if self.error:
            lines.append(f"  stopped: {self.error}")
            lines.append(
                f"  {len(self.remaining)} changes still pending; "
                "they will be re-proposed next turn."
            )
        return "\n".join(lines)


async def apply_changes(
    deps: GraphDeps,
    changes: Sequence[CalendarChange],
    thread_id: str,
    *,
    plan_id: int | None,
    goal_id: int | None,
    tp_plan_applied: bool = False,
) -> ApplyResult:
    """Send each change to TrainingPeaks in order, recording every success in `plan_changes`
    under `thread_id`. Ownership: update/move/delete only agent-authored workouts unless
    `athlete_requested`. Stops at the first server error; the rest stay in `remaining`."""
    todo = list(changes)
    if deps.tp is None:
        return ApplyResult(
            applied=[],
            skipped=[],
            remaining=todo,
            error=TP_UNAVAILABLE,
            tp_plan_applied=tp_plan_applied,
            sessions_changed=False,
        )

    owned: set[str] = set()
    if plan_id is not None:
        with deps.connect() as conn:
            owned = repo.owned_workout_ids(conn, plan_id)

    applied: list[CalendarChange] = []
    skipped: list[str] = []
    remaining = list(todo)
    error: str | None = None
    written: set[Any] = set()

    for change in todo:
        if (
            change.op in OWNED_OPS
            and change.tp_workout_id not in owned
            and not change.athlete_requested
        ):
            skipped.append(
                f"{_label(change)}: not agent-authored (id {change.tp_workout_id}); dropped"
            )
            remaining.remove(change)
            continue
        try:
            name, args = to_tp_call(change)
            result = await deps.tp.call_json(name, args)
        except (McpToolError, ValueError) as exc:
            error = f"{_label(change)} failed: {exc}"
            break
        wid = result_workout_id(change, result)
        with deps.connect() as conn:
            repo.insert_change(
                conn,
                plan_id,
                thread_id,
                change,
                tp_workout_id=wid,
                result=result if isinstance(result, dict) else {"result": result},
            )
            if (
                change.op == "create_event"
                and goal_id is not None
                and isinstance(result, dict)
                and result.get("event_id") is not None
            ):
                repo.set_goal_event(conn, goal_id, str(result["event_id"]))
            conn.commit()
        applied.append(change)
        remaining.remove(change)
        if change.op == "create" and change.workout_date is not None:
            # a designed session writes the week it was designed for, not the one it is dated in
            written.add(change.design_week or week_monday(change.workout_date))
        if change.op == "apply_plan":
            tp_plan_applied = True

    if plan_id is not None and written:
        with deps.connect() as conn:
            # Only a designed week is on the calendar as a plan week; a one-off create in an
            # undesigned week must not stop the design node from designing it.
            designed = {w.week_start for w in repo.list_weeks(conn, plan_id) if w.designed}
            repo.mark_weeks_written(conn, plan_id, sorted(written & designed))
            conn.commit()

    return ApplyResult(
        applied=applied,
        skipped=skipped,
        remaining=remaining,
        error=error,
        tp_plan_applied=tp_plan_applied,
        sessions_changed=any(c.op in SESSION_OPS for c in applied),
    )


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        r = await apply_changes(
            deps,
            changes,
            str(config["configurable"]["thread_id"]),
            plan_id=state.get("plan_id"),
            goal_id=state.get("goal_id"),
            tp_plan_applied=bool(state.get("tp_plan_applied")),
        )
        update: dict[str, Any] = {
            "pending_changes": r.remaining,
            "pending_summary": state.get("pending_summary") if r.remaining else None,
            "last_error": r.error,
            "review_decision": None,
            "messages": [AIMessage(r.report(len(changes)))],
            "tp_plan_applied": r.tp_plan_applied,
        }
        if r.error is None and not r.remaining and not r.tp_plan_applied:
            update["phase"] = "active"
        return update

    return apply
