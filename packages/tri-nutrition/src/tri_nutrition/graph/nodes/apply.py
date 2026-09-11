"""Apply node: the only place Garmin and TrainingPeaks are written. One call per change,
recorded as it goes. `write_change` is shared with the `today` command."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_core.mcp.client import McpToolError
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import to_garmin_call
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.nutrition.tp_calls import result_note_id, to_tp_call

GARMIN_OPS = ("set_day_targets",)
TP_OPS = ("set_session_note", "set_race_note")


def _label(c: NutritionChange) -> str:
    return f"{c.op} {c.target_key or c.day}"


async def _check_ownership(deps: GraphDeps, change: NutritionChange) -> None:
    """Raise PermissionError when the change would overwrite something we did not write."""
    assert deps.tp is not None
    if change.op == "set_session_note":
        wid = str(change.payload["workout_id"])
        with deps.connect() as conn:
            if repo.session_note_owned(conn, wid):
                return
        current = await deps.tp.call_json("tp_get_workout_note", {"workout_id": wid})
        existing = current.get("note") if isinstance(current, dict) else None
        if existing and str(existing).strip():
            raise PermissionError(f"workout {wid} has a private note that is not agent-authored")
    elif change.op == "set_race_note" and change.target_key:
        with deps.connect() as conn:
            owned = repo.owned_note_ids(conn)
        if change.target_key not in owned:
            raise PermissionError(f"calendar note {change.target_key} is not agent-authored")


async def write_change(deps: GraphDeps, thread_id: str, change: NutritionChange) -> dict[str, Any]:
    """Send one change to its server, record the audit row, mark the target written.
    Raises McpToolError/ValueError on failure and PermissionError on an ownership refusal."""
    if change.op in GARMIN_OPS:
        if deps.garmin is None:
            raise McpToolError("set_nutrition_daily_settings", "Garmin server unavailable")
        if change.day != deps.today():
            raise ValueError(f"Garmin can only hold today's target; {change.day} is not today")
        name, args = to_garmin_call(change)
        result = await deps.garmin.call_json(name, args)
        payload = result if isinstance(result, dict) else {"result": result}
        with deps.connect() as conn:
            repo.insert_change(conn, thread_id, change, payload)
            repo.mark_targets_written(conn, [change.day])
            conn.commit()
        return payload
    if change.op in TP_OPS:
        if deps.tp is None:
            raise McpToolError(change.op, "TrainingPeaks server unavailable")
        await _check_ownership(deps, change)
        name, args = to_tp_call(change)
        result = await deps.tp.call_json(name, args)
        payload = result if isinstance(result, dict) else {"result": result}
        note_id = result_note_id(change, result)
        recorded = change
        if change.op == "set_race_note" and note_id is not None:
            recorded = change.model_copy(update={"target_key": note_id})
        with deps.connect() as conn:
            repo.insert_change(conn, thread_id, recorded, payload)
            if change.op == "set_session_note":
                wid = str(change.payload["workout_id"])
                repo.mark_fuel_written_for(conn, "session", change.day, wid, None)
            else:
                repo.mark_fuel_written_for(conn, "race", change.day, None, note_id)
            conn.commit()
        return payload
    raise ValueError(f"unknown operation {change.op}")


def _server_down(deps: GraphDeps, change: NutritionChange) -> bool:
    return (change.op in GARMIN_OPS and deps.garmin is None) or (
        change.op in TP_OPS and deps.tp is None
    )


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        thread_id = str(config["configurable"]["thread_id"])
        applied: list[NutritionChange] = []
        skipped: list[str] = []
        held: list[NutritionChange] = []
        remaining = list(changes)
        error: str | None = None
        for change in changes:
            if _server_down(deps, change):
                held.append(change)
                continue
            try:
                await write_change(deps, thread_id, change)
            except PermissionError as exc:
                skipped.append(f"{_label(change)}: {exc}; dropped")
                remaining.remove(change)
                continue
            except (McpToolError, ValueError) as exc:
                error = f"{_label(change)} failed: {exc}"
                break
            applied.append(change)
            remaining.remove(change)
        if error is None:
            remaining = [c for c in remaining if c in held]
        if held:
            servers = sorted({"Garmin" if c.op in GARMIN_OPS else "TrainingPeaks" for c in held})
            held_msg = (
                f"{' and '.join(servers)} server unavailable; {len(held)} change(s) held pending."
            )
            error = held_msg if error is None else f"{error}; {held_msg}"

        overrides = state.get("profile_overrides")
        persisted = False
        if error is None and not remaining and overrides:
            base = await S.get_profile(store)
            if base is not None:
                await S.put_profile(store, apply_overrides(base, overrides))
                persisted = True

        n_garmin = sum(1 for c in applied if c.op in GARMIN_OPS)
        n_tp = sum(1 for c in applied if c.op in TP_OPS)
        lines = [
            f"Applied {len(applied)} of {len(changes)} changes "
            f"(Garmin {n_garmin}, TrainingPeaks {n_tp})."
        ]
        lines += [f"  skipped: {s}" for s in skipped]
        if persisted:
            lines.append(f"  profile updated: {overrides}")
        if error:
            lines.append(f"  stopped: {error}")
            lines.append(
                f"  {len(remaining)} change(s) still pending; they will be re-proposed next turn."
            )
        return {
            "pending_changes": remaining,
            "pending_summary": state.get("pending_summary") if remaining else None,
            "last_error": error,
            "review_decision": None,
            "profile_overrides": None if (error is None and not remaining) else overrides,
            "messages": [AIMessage("\n".join(lines))],
        }

    return apply
