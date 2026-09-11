"""Targets node: profile + horizon -> DayTargets in the database and a Garmin change set.
No model call. The horizon builder is shared with the `today` command."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
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
from tri_nutrition.nutrition.models import DayTarget, NutritionChange, NutritionProfile
from tri_nutrition.nutrition.targets import build
from tri_nutrition.repl import render_targets

NO_PROFILE = "no nutrition profile in the store; run intake first"


def apply_overrides(
    profile: NutritionProfile, overrides: dict[str, Any] | None
) -> NutritionProfile:
    if not overrides:
        return profile
    return NutritionProfile.model_validate({**profile.model_dump(mode="json"), **overrides})


@dataclass
class Horizon:
    """What one regeneration produced. `violations` non-empty means nothing was stored."""

    today: date
    targets: list[DayTarget] = field(default_factory=list)
    source: str = ""
    violations: list[str] = field(default_factory=list)
    changes: list[NutritionChange] = field(default_factory=list)  # today's Garmin write, if any
    error: str | None = None

    def summary(self) -> str:
        if self.error:
            return self.error
        if self.violations:
            return "Targets not written; bounds violated:\n  " + "\n  ".join(self.violations)
        end = self.targets[-1].day if self.targets else self.today
        what = (
            f"today's target ({self.today}) needs a Garmin write"
            if self.changes
            else f"today's target ({self.today}) is already on Garmin"
        )
        return (
            f"Daily targets for {self.today} to {end} ({self.source}), stored; {what}. Garmin "
            "holds only the current day; run `tri-nutrition today` each morning.\n"
            + render_targets(self.targets)
        )


async def build_horizon(
    deps: GraphDeps, store: BaseStore, overrides: dict[str, Any] | None = None
) -> Horizon:
    """Regenerate the horizon from the Store profile and the plan; upsert it unless a bound is
    violated; return today's Garmin change when today's row needs a write."""
    today = deps.today()
    base = await S.get_profile(store)
    if base is None:
        return Horizon(today=today, error=NO_PROFILE)
    profile = apply_overrides(base, overrides)
    with deps.connect() as conn:
        sessions, ctx = plan_loader.load_horizon(conn, today, deps.horizon_days)
    targets = build(profile, sessions, ctx, today, deps.horizon_days)
    violations = validate_targets(targets, profile)
    if violations:
        return Horizon(today=today, targets=targets, source=ctx.source, violations=violations)
    end = today + timedelta(days=deps.horizon_days - 1)
    with deps.connect() as conn:
        existing = repo.list_targets(conn, today, end)
        repo.upsert_targets(conn, targets)
        conn.commit()
    needing = [t for t in targets_needing_write(targets, existing) if t.day == today]
    return Horizon(
        today=today,
        targets=targets,
        source=ctx.source,
        changes=[day_target_change(t) for t in needing],
    )


def make_targets_node(deps: GraphDeps) -> Any:
    async def targets_node(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        h = await build_horizon(deps, store, state.get("profile_overrides"))
        if h.error or h.violations:
            # A checkin proposal that breaks a bound is discarded with the violations shown;
            # the athlete adjusts the profile in chat.
            return {
                "pending_changes": [],
                "pending_summary": None,
                "profile_saved": False,
                "targets_requested": False,
                "profile_overrides": None,
                "last_error": h.error or "; ".join(h.violations),
                "messages": [AIMessage(h.summary())],
            }
        return {
            "pending_changes": h.changes,
            "pending_summary": h.summary(),
            "profile_saved": False,
            "targets_requested": False,
            "last_error": None,
        }

    return targets_node
