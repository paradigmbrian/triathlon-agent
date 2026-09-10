"""Apply node: the only place Garmin (and, from Plan 3, TrainingPeaks) is written.
One call per change, recorded as it goes. `write_change` is shared with the `today` command."""

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

GARMIN_OPS = ("set_day_targets",)


def _label(c: NutritionChange) -> str:
    return f"{c.op} {c.target_key or c.day}"


async def write_change(deps: GraphDeps, thread_id: str, change: NutritionChange) -> dict[str, Any]:
    """Send one Garmin change, record the audit row, mark the day written. Raises on failure.
    A set_day_targets change for any day but today is refused: Garmin holds only the current
    day's goal."""
    if deps.garmin is None:
        raise McpToolError("set_nutrition_daily_settings", "Garmin server unavailable")
    if change.op == "set_day_targets" and change.day != deps.today():
        raise ValueError(f"Garmin can only hold today's target; {change.day} is not today")
    name, args = to_garmin_call(change)
    result = await deps.garmin.call_json(name, args)
    payload = result if isinstance(result, dict) else {"result": result}
    with deps.connect() as conn:
        repo.insert_change(conn, thread_id, change, payload)
        repo.mark_targets_written(conn, [change.day])
        conn.commit()
    return payload


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        thread_id = str(config["configurable"]["thread_id"])
        garmin_changes = [c for c in changes if c.op in GARMIN_OPS]
        skipped = [
            f"{_label(c)}: not applied in this version; dropped"
            for c in changes
            if c.op not in GARMIN_OPS
        ]
        if garmin_changes and deps.garmin is None:
            msg = "Garmin server unavailable; nothing applied, change set left pending."
            return {
                "pending_changes": garmin_changes,
                "last_error": msg,
                "review_decision": None,
                "messages": [AIMessage(msg)],
            }

        applied: list[NutritionChange] = []
        remaining = list(garmin_changes)
        error: str | None = None
        for change in garmin_changes:
            try:
                await write_change(deps, thread_id, change)
            except (McpToolError, ValueError) as exc:
                error = f"{_label(change)} failed: {exc}"
                break
            applied.append(change)
            remaining.remove(change)

        overrides = state.get("profile_overrides")
        persisted = False
        if error is None and not remaining and overrides:
            base = await S.get_profile(store)
            if base is not None:
                await S.put_profile(store, apply_overrides(base, overrides))
                persisted = True

        lines = [f"Garmin: applied {len(applied)} of {len(garmin_changes)} day targets."]
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
