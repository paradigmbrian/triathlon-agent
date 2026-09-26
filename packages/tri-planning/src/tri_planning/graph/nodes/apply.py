"""Apply: the only place TrainingPeaks is written. `apply_changes` sends one call per change,
recording each as it goes, and stops at the first failure; the node is state plumbing around it.
The coach calls `apply_changes` directly with `thread_id="coach"`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.repo import Conn
from tri_core.db.writes import OutcomeUnknown, SentUnrecorded, mark_failed, recorded_write
from tri_core.mcp.client import McpToolError
from tri_core.sync import ToolCaller
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning.models import CalendarChange
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import TP_SPORT, result_workout_id, to_tp_call

OWNED_OPS = ("update", "move", "delete")
SESSION_OPS = ("create", "update", "delete", "move")  # ops that change what the athlete trains
TP_UNAVAILABLE = "TrainingPeaks server unavailable; nothing applied, change set left pending."
PENDING_NOT_FOUND = "not found on TrainingPeaks after a pending write"
PENDING_UNVERIFIABLE = (
    "could not be verified on TrainingPeaks after a pending write; check the calendar"
)
PENDING_AMBIGUOUS = "more than one matching workout on TrainingPeaks; not claimed"


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
    reconciled: list[str] = field(default_factory=list)  # pending rows settled before the batch

    def report(self, total: int) -> str:
        lines = [f"TrainingPeaks: applied {len(self.applied)} of {total} changes."]
        lines += [f"  reconciled: {s}" for s in self.reconciled]
        lines += [f"  skipped: {s}" for s in self.skipped]
        if self.error:
            lines.append(f"  stopped: {self.error}")
            lines.append(
                f"  {len(self.remaining)} changes still pending; "
                "they will be re-proposed next turn."
            )
        return "\n".join(lines)


Verdict = Literal["applied", "missing", "ambiguous", "unverifiable"]


async def _day_listing(tp: ToolCaller, day: str) -> list[dict[str, Any]]:
    result = await tp.call_json(
        "tp_get_workouts", {"start_date": day, "end_date": day, "workout_filter": "all"}
    )
    items = result.get("workouts") if isinstance(result, dict) else None
    return [w for w in items if isinstance(w, dict)] if isinstance(items, list) else []


async def _verify(
    tp: ToolCaller, change: CalendarChange, recorded: set[str]
) -> tuple[Verdict, str | None]:
    """Whether a pending change is on TrainingPeaks, and the workout id it concerns."""
    if change.op == "create" and change.workout is not None:
        w = change.workout
        hits = [
            str(item.get("id"))
            for item in await _day_listing(tp, w.date.isoformat())
            if item.get("title") == w.title
            and item.get("sport") == TP_SPORT[w.sport]
            and str(item.get("id")) not in recorded
        ]
        if len(hits) > 1:
            return "ambiguous", None
        if hits:
            return "applied", hits[0]
        return "missing", None
    wid = change.tp_workout_id
    if change.op == "update" and change.workout is not None and wid:
        items = await _day_listing(tp, change.workout.date.isoformat())
        on_tp = any(
            str(i.get("id")) == wid and i.get("title") == change.workout.title for i in items
        )
    elif change.op == "move" and change.new_date is not None and wid:
        items = await _day_listing(tp, change.new_date.isoformat())
        on_tp = any(str(i.get("id")) == wid for i in items)
    elif change.op == "delete" and change.workout_date is not None and wid:
        items = await _day_listing(tp, change.workout_date.isoformat())
        on_tp = all(str(i.get("id")) != wid for i in items)  # a delete is done when it is gone
    else:
        return "unverifiable", None
    if on_tp:
        return "applied", wid
    return "missing", wid


def _mark_week_written(conn: Conn, plan_id: int | None, change: CalendarChange) -> None:
    if plan_id is None or change.op != "create" or change.workout_date is None:
        return
    week = week_monday(change.workout_date)
    if any(w.week_start == week and w.designed for w in repo.list_weeks(conn, plan_id)):
        repo.mark_weeks_written(conn, plan_id, [week])


def _unchecked(row_id: int, exc: Exception) -> str:
    first = str(exc).splitlines()[0] if str(exc) else ""
    return f"row {row_id}: could not be checked ({type(exc).__name__}: {first}); left pending"


async def reconcile_pending(deps: GraphDeps) -> tuple[list[str], list[CalendarChange]]:
    """Settle `plan_changes` rows an earlier apply left `pending` (the call may have gone
    through while its record did not): `applied` when TrainingPeaks shows the change, else
    `failed`. Returns one report line per row settled or left, and the creates it recorded as
    applied."""
    tp = deps.tp
    assert tp is not None
    with deps.connect() as conn:
        rows = repo.pending_changes(conn)
        recorded = repo.recorded_create_ids(conn)
    lines: list[str] = []
    found: list[CalendarChange] = []
    for i, row in enumerate(rows):
        try:
            change = CalendarChange.model_validate(row["payload"])
            verdict, wid = await _verify(tp, change, recorded)
        except McpToolError as exc:
            lines.append(
                f"TrainingPeaks unreachable ({exc}); {len(rows) - i} pending change(s) left pending"
            )
            break
        except Exception as exc:  # noqa: BLE001 - one bad row stays pending; the apply goes on
            lines.append(_unchecked(row["id"], exc))
            continue
        with deps.connect() as conn:
            if verdict == "applied":
                repo.mark_change_applied(
                    conn, row["id"], tp_workout_id=wid, result={"reconciled": True}
                )
                _mark_week_written(conn, row["plan_id"], change)
                if change.op == "create" and wid is not None:
                    recorded.add(wid)
                    found.append(change)
                lines.append(f"{_label(change)}: found on TrainingPeaks; recorded as applied")
            else:
                err = {
                    "missing": PENDING_NOT_FOUND,
                    "ambiguous": PENDING_AMBIGUOUS,
                    "unverifiable": PENDING_UNVERIFIABLE,
                }[verdict]
                mark_failed(conn, "plan_changes", row["id"], err)
                lines.append(f"{_label(change)}: {err}; marked failed")
            conn.commit()
    return lines, found


async def _record_and_send(
    deps: GraphDeps,
    tp: ToolCaller,
    change: CalendarChange,
    call: tuple[str, dict[str, Any]],
    *,
    plan_id: int | None,
    thread_id: str,
    goal_id: int | None,
) -> Any:
    """One TrainingPeaks call inside its `plan_changes` row: pending before, applied after."""
    name, args = call

    def mark_applied(conn: Conn, row_id: int, result: Any) -> None:
        repo.mark_change_applied(
            conn,
            row_id,
            tp_workout_id=result_workout_id(change, result),
            result=result if isinstance(result, dict) else {"result": result},
        )
        if (
            change.op == "create_event"
            and goal_id is not None
            and isinstance(result, dict)
            and result.get("event_id") is not None
        ):
            repo.set_goal_event(conn, goal_id, str(result["event_id"]))

    sent = False

    async def send() -> Any:
        nonlocal sent
        result = await tp.call_json(name, args)
        sent = True
        return result

    try:
        rec = await recorded_write(
            deps.connect,
            table="plan_changes",
            insert_pending=lambda conn: repo.insert_pending_change(
                conn, plan_id, thread_id, change
            ),
            call=send,
            mark_applied=mark_applied,
        )
    except psycopg.Error as exc:
        if sent:
            raise SentUnrecorded(exc) from exc
        raise
    return rec.result


async def apply_changes(
    deps: GraphDeps,
    changes: Sequence[CalendarChange],
    thread_id: str,
    *,
    plan_id: int | None,
    goal_id: int | None,
    tp_plan_applied: bool = False,
) -> ApplyResult:
    """Send each change to TrainingPeaks in order, recording every attempt in `plan_changes`
    under `thread_id` (pending, then applied or failed); pending rows from earlier applies are
    reconciled first. Ownership: update/move/delete only agent-authored workouts unless
    `athlete_requested`. Stops at the first failure; the rest stay in `remaining`. A definitive
    rejection stays there too; a change whose outcome is unknown (a timeout, a server error, or
    sent but not recorded) leaves `remaining` and is reconciled next apply. Each create
    reconciled as applied in this pass cancels one batch create of the identical workout (every
    field), which is dropped, not sent."""
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

    reconciled, found = await reconcile_pending(deps)
    # each workout reconciled onto TrainingPeaks cancels at most one identical create
    on_tp = [c.workout for c in found if c.workout is not None]
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
        if change.op == "create" and change.workout in on_tp:  # already created: never twice
            on_tp.remove(change.workout)
            skipped.append(
                f"{_label(change)}: already on TrainingPeaks (reconciled); not sent again"
            )
            remaining.remove(change)
            continue
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
            call = to_tp_call(change)  # a malformed change fails here, before any row exists
            await _record_and_send(
                deps,
                deps.tp,
                change,
                call,
                plan_id=plan_id,
                thread_id=thread_id,
                goal_id=goal_id,
            )
        except OutcomeUnknown as exc:  # its row is pending: stop, and never re-send it unchecked
            error = f"{_label(change)}: {exc}"
            remaining.remove(change)
            break
        except (McpToolError, ValueError) as exc:
            error = f"{_label(change)} failed: {exc}"
            break
        applied.append(change)
        remaining.remove(change)
        if change.op == "create" and change.workout_date is not None:
            written.add(week_monday(change.workout_date))
        if change.op == "apply_plan":
            tp_plan_applied = True

    if plan_id is not None and written:
        try:
            with deps.connect() as conn:
                # Only a designed week is on the calendar as a plan week; a one-off create in an
                # undesigned week must not stop the design node from designing it.
                designed = {w.week_start for w in repo.list_weeks(conn, plan_id) if w.designed}
                repo.mark_weeks_written(conn, plan_id, sorted(written & designed))
                conn.commit()
        except psycopg.Error as exc:  # the changes above are on TrainingPeaks; report, never raise
            weeks = ", ".join(d.isoformat() for d in sorted(written))
            note = (
                f"weeks written not recorded ({type(exc).__name__}: {exc}); weeks {weeks} are "
                "on TrainingPeaks but not marked written, check them before designing again"
            )
            error = f"{error}; {note}" if error else note

    return ApplyResult(
        applied=applied,
        skipped=skipped,
        remaining=remaining,
        error=error,
        tp_plan_applied=tp_plan_applied,
        sessions_changed=any(c.op in SESSION_OPS for c in applied),
        reconciled=reconciled,
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
