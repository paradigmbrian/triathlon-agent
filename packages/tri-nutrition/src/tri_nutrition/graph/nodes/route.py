"""Route node: the one Store read that routing needs. Edge functions stay pure over state."""

from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore

from tri_nutrition import store as S
from tri_nutrition.graph.state import NutritionState


async def route_node(state: NutritionState, *, store: BaseStore) -> dict[str, Any]:
    update: dict[str, Any] = {"has_profile": await S.get_profile(store) is not None}
    if not state.get("pending_changes"):
        # this turn's refusals only: check-in reads pending_violations after the turn
        update["pending_violations"] = {}
    return update
