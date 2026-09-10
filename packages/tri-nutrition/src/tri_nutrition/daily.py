"""The daily Garmin write: regenerate the horizon, then send today's target after a yes.
Used by `tri-nutrition today`; no model call, no graph."""

from __future__ import annotations

from langgraph.store.base import BaseStore

from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.apply import write_change
from tri_nutrition.graph.nodes.targets import Horizon, build_horizon
from tri_nutrition.nutrition.garmin_calls import to_garmin_call

THREAD_ID = "today"


async def propose_today(deps: GraphDeps, store: BaseStore) -> Horizon:
    return await build_horizon(deps, store)


def describe_change(h: Horizon) -> str:
    if not h.changes:
        return "nothing to write"
    _, args = to_garmin_call(h.changes[0])
    return (
        f"{args['date']}: {args['calorie_goal']} kcal, C/P/F "
        f"{args['carbs_grams']}/{args['protein_grams']}/{args['fat_grams']} g"
    )


async def write_today(deps: GraphDeps, h: Horizon) -> str:
    if not h.changes:
        return "nothing to write"
    payload = await write_change(deps, THREAD_ID, h.changes[0])
    return f"written to Garmin: {describe_change(h)} (response: {payload})"
