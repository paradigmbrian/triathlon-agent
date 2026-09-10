"""Route node: the one Store read that routing needs. Edge functions stay pure over state."""

from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore

from tri_nutrition import store as S
from tri_nutrition.graph.state import NutritionState


async def route_node(state: NutritionState, *, store: BaseStore) -> dict[str, Any]:
    return {"has_profile": await S.get_profile(store) is not None}
