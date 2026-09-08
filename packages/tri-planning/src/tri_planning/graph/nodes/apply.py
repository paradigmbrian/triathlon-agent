"""Apply node: the only place TrainingPeaks is written. One call per change, recorded as it goes."""

from __future__ import annotations

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


def _label(c: CalendarChange) -> str:
    if c.workout is not None:
        return f"{c.op} {c.workout.date} {c.workout.sport} '{c.workout.title}'"
    return f"{c.op} {c.tp_workout_id or c.workout_date or ''}".strip()


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        plan_id, goal_id = state.get("plan_id"), state.get("goal_id")
        thread_id = str(config["configurable"]["thread_id"])
        if deps.tp is None:
            msg = "TrainingPeaks server unavailable; nothing applied, change set left pending."
            return {
                "pending_changes": changes,
                "last_error": msg,
                "review_decision": None,
                "messages": [AIMessage(msg)],
            }

        owned: set[str] = set()
        if plan_id is not None:
            with deps.connect() as conn:
                owned = repo.owned_workout_ids(conn, plan_id)

        applied: list[CalendarChange] = []
        skipped: list[str] = []
        remaining = list(changes)
        error: str | None = None
        written: set[Any] = set()
        tp_plan_applied = bool(state.get("tp_plan_applied"))

        for change in changes:
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
                written.add(week_monday(change.workout_date))
            if change.op == "apply_plan":
                tp_plan_applied = True

        if plan_id is not None and written:
            with deps.connect() as conn:
                repo.mark_weeks_written(conn, plan_id, sorted(written))
                conn.commit()

        lines = [f"TrainingPeaks: applied {len(applied)} of {len(changes)} changes."]
        lines += [f"  skipped: {s}" for s in skipped]
        if error:
            lines.append(f"  stopped: {error}")
            lines.append(
                f"  {len(remaining)} changes still pending; they will be re-proposed next turn."
            )
        update: dict[str, Any] = {
            "pending_changes": remaining,
            "pending_summary": state.get("pending_summary") if remaining else None,
            "last_error": error,
            "review_decision": None,
            "messages": [AIMessage("\n".join(lines))],
            "tp_plan_applied": tp_plan_applied,
        }
        if error is None and not remaining and not tp_plan_applied:
            update["phase"] = "active"
        return update

    return apply
