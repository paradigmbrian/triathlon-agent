"""Evaluators over the target's output: two code checks that re-run the bounds, and an LLM
judge for what the bounds cannot see (restrictions and dislikes in the prose)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from tri_core.llm import structured
from tri_nutrition.evals.target import parse_inputs
from tri_nutrition.nutrition.bounds import validate_fuel, validate_race, validate_targets
from tri_nutrition.nutrition.models import DayTarget, RaceFuelPlan, SessionFuel

Evaluator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
AsyncEvaluator = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


def _result(key: str, ok: bool, problems: list[str]) -> dict[str, Any]:
    return {"key": key, "score": int(ok), "comment": "; ".join(problems) or "ok"}


def targets_within_bounds(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    profile, *_ = parse_inputs(inputs)
    targets = [DayTarget.model_validate(t) for t in outputs.get("targets", [])]
    violations = validate_targets(targets, profile)
    return _result("targets_within_bounds", not violations, violations)


def fuel_within_bounds(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    profile, _, _, fuel_log, _ = parse_inputs(inputs)
    library = list(profile.tested_products)
    problems: list[str] = []
    caffeine: dict[date, int] = {}
    for item in outputs.get("fuels", []):
        fuel = SessionFuel.model_validate(item["fuel"])
        other = caffeine.get(fuel.day, 0)
        found = validate_fuel(fuel, profile, library, fuel_log, other)
        problems += [f"{fuel.day} {fuel.tp_workout_id}: {v}" for v in found]
        caffeine[fuel.day] = other + (fuel.caffeine_mg or 0)
    race = outputs.get("race")
    if race:
        plan = RaceFuelPlan.model_validate(race["plan"])
        problems += [f"race: {v}" for v in validate_race(plan, profile, library, fuel_log)]
    return _result("fuel_within_bounds", not problems, problems)


class FuelJudgement(BaseModel):
    respects_restrictions: bool = Field(
        description="every note honours the dietary pattern, restrictions, dislikes and GI history"
    )
    only_library_products: bool = Field(
        description="no named sports product outside the library appears anywhere in the notes; "
        "plain food and water are always fine"
    )
    problems: list[str] = Field(description="one line per problem: the day and the offending text")


JUDGE_SYSTEM = """\
You audit fueling notes written for one athlete. You are given the athlete's dietary pattern,
restrictions, dislikes, GI history and caffeine habit, the product library, and each note (pre,
products, post, note text) plus the race note when there is one. Return a FuelJudgement.
respects_restrictions is true only when every note honours the pattern (a vegan note names no
animal food), every restriction (gluten: no oats unless labelled gluten-free, no bread, no wheat
bars), every dislike, and the GI history (reflux: no large, fatty or acidic pre-session meal;
caffeine_mg_per_day 0: no caffeine anywhere). only_library_products is true only when every
named sports product (gel, chew, drink mix, bar, or brand) is in the library; plain foods and
water never count against it, and neither does an optional pre-race beetroot or nitrate shot,
which the race prompt permits. Be literal: judge the text, not the intent."""


def render_judge_prompt(inputs: dict[str, Any], outputs: dict[str, Any]) -> str:
    profile = inputs["profile"]
    keys = (
        "pattern",
        "restrictions",
        "dislikes",
        "gi_issues",
        "caffeine_mg_per_day",
        "constraints",
    )
    library = [p["name"] for p in profile.get("tested_products", [])]
    parts = [
        "Athlete: " + json.dumps({k: profile.get(k) for k in keys}),
        "Product library: " + (", ".join(library) or "empty"),
    ]
    for item in outputs.get("fuels", []):
        s, f = item["session"], item["fuel"]
        parts.append(
            f"Session {s['day']} {s['sport']} {s['duration_min']} min, {s['intensity']}:\n"
            f"  pre: {f['pre']}\n  products: {', '.join(f['products']) or '-'}\n"
            f"  post: {f['post']}\n  note: {f['note_text']}"
        )
    race = outputs.get("race")
    if race:
        parts.append("Race note:\n" + str(race["plan"]["note_text"]))
    return "\n\n".join(parts)


def make_fuel_judge(model: BaseChatModel) -> AsyncEvaluator:
    judge = structured(model, FuelJudgement)

    async def fuel_respects_profile(
        inputs: dict[str, Any], outputs: dict[str, Any]
    ) -> dict[str, Any]:
        if not outputs.get("fuels") and not outputs.get("race"):
            return _result("fuel_respects_profile", True, [])
        out = await judge.ainvoke(
            [SystemMessage(JUDGE_SYSTEM), HumanMessage(render_judge_prompt(inputs, outputs))]
        )
        assert isinstance(out, FuelJudgement)
        ok = out.respects_restrictions and out.only_library_products
        return _result("fuel_respects_profile", ok, out.problems)

    return fuel_respects_profile
