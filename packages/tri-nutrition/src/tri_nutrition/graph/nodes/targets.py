"""Targets node: profile + horizon -> DayTargets in the database and a Garmin change set.
No model call."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_nutrition import plan_loader, repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.bounds import validate_targets
from tri_nutrition.nutrition.garmin_calls import day_target_change, targets_needing_write
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.nutrition.targets import build
from tri_nutrition.repl import render_targets

NO_PROFILE = "no nutrition profile in the store; run intake first"


def apply_overrides(
    profile: NutritionProfile, overrides: dict[str, Any] | None
) -> NutritionProfile:
    if not overrides:
        return profile
    return NutritionProfile.model_validate({**profile.model_dump(mode="json"), **overrides})


def make_targets_node(deps: GraphDeps) -> Any:
    async def targets_node(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        base = await S.get_profile(store)
        if base is None:
            return {
                "pending_changes": [],
                "pending_summary": None,
                "profile_saved": False,
                "last_error": NO_PROFILE,
                "messages": [AIMessage(NO_PROFILE)],
            }
        profile = apply_overrides(base, state.get("profile_overrides"))
        today = deps.today()
        with deps.connect() as conn:
            sessions, ctx = plan_loader.load_horizon(conn, today, deps.horizon_days)
        targets = build(profile, sessions, ctx, today, deps.horizon_days)
        violations = validate_targets(targets, profile)
        if violations:
            text = "Targets not written; bounds violated:\n  " + "\n  ".join(violations)
            return {
                "pending_changes": [],
                "pending_summary": None,
                "profile_saved": False,
                "last_error": "; ".join(violations),
                "messages": [AIMessage(text)],
            }
        end = today + timedelta(days=deps.horizon_days - 1)
        with deps.connect() as conn:
            existing = repo.list_targets(conn, today, end)
            repo.upsert_targets(conn, targets)
            conn.commit()
        changes = [day_target_change(t) for t in targets_needing_write(targets, existing)]
        summary = (
            f"Daily targets for {today} to {end} ({ctx.source}); {len(changes)} of "
            f"{len(targets)} days need a Garmin write.\n" + render_targets(targets)
        )
        return {
            "pending_changes": changes,
            "pending_summary": summary,
            "profile_saved": False,
            "last_error": None,
        }

    return targets_node
