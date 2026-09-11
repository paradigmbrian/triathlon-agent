"""The function under evaluation: one week of targets (Python) and the fueling plans (model)
for a (profile, training week) input. No database, no Store."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel

from tri_nutrition.graph.nodes.fuel import FuelPlanner, qualifies, race_due
from tri_nutrition.nutrition.bounds import validate_targets
from tri_nutrition.nutrition.models import FuelLogEntry, NutritionProfile, PlanContext, Session
from tri_nutrition.nutrition.targets import build

HORIZON_DAYS = 7


def parse_inputs(
    inputs: dict[str, Any],
) -> tuple[NutritionProfile, list[Session], PlanContext, list[FuelLogEntry], date]:
    return (
        NutritionProfile.model_validate(inputs["profile"]),
        [Session.model_validate(s) for s in inputs["sessions"]],
        PlanContext.model_validate(inputs["ctx"]),
        [FuelLogEntry.model_validate(e) for e in inputs.get("fuel_log", [])],
        date.fromisoformat(inputs["today"]),
    )


async def run_case(
    planner: FuelPlanner, inputs: dict[str, Any], horizon_days: int = HORIZON_DAYS
) -> dict[str, Any]:
    profile, sessions, ctx, fuel_log, today = parse_inputs(inputs)
    targets = build(profile, sessions, ctx, today, horizon_days)
    by_day = {t.day: t for t in targets}
    library = list(profile.tested_products)
    fuels: list[dict[str, Any]] = []
    caffeine: dict[date, int] = {}
    for s in sessions:
        if not qualifies(s):
            continue
        other = caffeine.get(s.day, 0)
        plan, violations = await planner.session(
            profile, library, fuel_log, s, by_day.get(s.day), other
        )
        caffeine[s.day] = other + (plan.caffeine_mg or 0)
        fuels.append(
            {
                "session": s.model_dump(mode="json"),
                "fuel": plan.model_dump(mode="json"),
                "violations": violations,
            }
        )
    race: dict[str, Any] | None = None
    if race_due(ctx, today) and ctx.event_date is not None:
        target = by_day.get(ctx.event_date)
        plan_r, rv = await planner.race(profile, library, fuel_log, ctx, target)
        race = {"plan": plan_r.model_dump(mode="json"), "violations": rv}
    return {
        "targets": [t.model_dump(mode="json") for t in targets],
        "target_violations": validate_targets(targets, profile),
        "fuels": fuels,
        "race": race,
    }


def make_target(model: BaseChatModel) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    planner = FuelPlanner(model)

    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return await run_case(planner, inputs)

    return target
