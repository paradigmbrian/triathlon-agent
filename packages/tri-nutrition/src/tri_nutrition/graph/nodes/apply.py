"""Apply node: the only place Garmin and TrainingPeaks are written. One call per change,
recorded as it goes. `write_change` is shared with the `today` command; `apply_changes` is the
batch the node and the coach both call."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass
class ApplyResult:
    applied: list[NutritionChange]
    skipped: list[str]
    remaining: list[NutritionChange]
    held: list[NutritionChange]  # a subset of remaining: the server for these was down
    error: str | None
    profile_updated: bool

    def report(self, total: int, overrides: dict[str, Any] | None) -> str:
        n_garmin = sum(1 for c in self.applied if c.op in GARMIN_OPS)
        n_tp = sum(1 for c in self.applied if c.op in TP_OPS)
        lines = [
            f"Applied {len(self.applied)} of {total} changes "
            f"(Garmin {n_garmin}, TrainingPeaks {n_tp})."
        ]
        lines += [f"  skipped: {s}" for s in self.skipped]
        if self.profile_updated:
            lines.append(f"  profile updated: {overrides}")
        if self.error:
            lines.append(f"  stopped: {self.error}")
            lines.append(
                f"  {len(self.remaining)} change(s) still pending; they will be re-proposed next "
                "turn."
            )
        return "\n".join(lines)


async def apply_changes(
    deps: GraphDeps,
    store: BaseStore,
    changes: Sequence[NutritionChange],
    thread_id: str,
    *,
    overrides: dict[str, Any] | None,
) -> ApplyResult:
    """Send each change to its server in order, recording every success in `nutrition_changes`
    under `thread_id`. Changes whose server is down are held (kept in `remaining`); an ownership
    refusal drops the change; a server error stops the batch. `overrides` are written to the
    profile in the Store only when every change went through."""
    todo = list(changes)
    applied: list[NutritionChange] = []
    skipped: list[str] = []
    held: list[NutritionChange] = []
    remaining = list(todo)
    error: str | None = None
    for change in todo:
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

    persisted = False
    if error is None and not remaining and overrides:
        base = await S.get_profile(store)
        if base is not None:
            await S.put_profile(store, apply_overrides(base, overrides))
            persisted = True
    return ApplyResult(
        applied=applied,
        skipped=skipped,
        remaining=remaining,
        held=held,
        error=error,
        profile_updated=persisted,
    )


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        overrides = state.get("profile_overrides")
        r = await apply_changes(
            deps, store, changes, str(config["configurable"]["thread_id"]), overrides=overrides
        )
        clean = r.error is None and not r.remaining
        return {
            "pending_changes": r.remaining,
            "pending_summary": state.get("pending_summary") if r.remaining else None,
            "last_error": r.error,
            "review_decision": None,
            "profile_overrides": None if clean else overrides,
            "messages": [AIMessage(r.report(len(changes), overrides))],
        }

    return apply
