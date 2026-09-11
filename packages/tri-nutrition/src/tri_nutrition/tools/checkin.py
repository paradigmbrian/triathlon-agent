"""Check-in tools: logged intake against targets, the fuel log, and target-change proposals.

record_fuel_feedback writes the Store only (fuel log, and a tested product after an ok outcome).
propose_target_changes writes nothing: it validates the overrides against the saved profile and
returns them; the checkin node carries them into state and the graph regenerates targets for
review, where approve persists them into the profile.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_store
from pydantic import BaseModel, Field, ValidationError

from tri_core.mcp.client import McpToolError
from tri_core.sync import ToolCaller
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import ConnectFactory
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.nutrition.bounds import carbs_evidence
from tri_nutrition.nutrition.models import (
    FuelLogEntry,
    NutritionProfile,
    Outcome,
    Product,
    Sport,
)
from tri_nutrition.tools.garmin import UNAVAILABLE, RecentDaysArgs, parse_food_log

PROFILE_FIELDS = frozenset(NutritionProfile.model_fields)
MAX_ITEMS = 15


class FuelFeedbackArgs(BaseModel):
    day: date
    sport: Sport
    duration_min: int = Field(ge=0)
    carbs_g_per_h: int = Field(ge=0, description="what the athlete actually took per hour")
    outcome: Outcome
    products: list[str] = Field(default_factory=list, description="library product names used")
    note: str = ""
    tp_workout_id: str | None = None
    new_product: Product | None = Field(
        default=None,
        description="a product not yet in the library; added as tested only when outcome is ok",
    )


class ProposeArgs(BaseModel):
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description='profile fields to change, e.g. {"activity_factor": 1.4}; empty to regenerate '
        "the horizon unchanged (extend it)",
    )
    reason: str = Field(description="one sentence the athlete sees at review")


INTAKE_DESCRIPTION = """\
Logged intake (Garmin food log) against the stored daily target for each of the last `days` days
ending yesterday. Per day: day_type, logged (false when nothing was logged), logged_kcal and
logged_carbs_g / protein_g / fat_g, target_kcal and target macros (null when no target was
stored), delta_kcal (logged minus target), and the logged item names. Then by_day_type: averages
over logged days per day type; targets_through: the last day with a stored target;
days_of_targets_remaining: stored target days from today onward. Read this before judging intake."""

FEEDBACK_DESCRIPTION = """\
Record how one session's fueling went: day, sport, duration_min, carbs_g_per_h actually taken,
outcome (ok | gi_upset | bonk | cramps | other), products used, a short note, tp_workout_id when
known. Pass new_product ({name, form, carbs_g, sodium_mg, caffeine_mg} per serving) for a product
not yet in the library; it joins the library only after an ok outcome. Returns the log length and
carbs_evidence_g_per_h, the highest per-hour intake with an ok outcome so far."""

PROPOSE_DESCRIPTION = """\
Propose changes to the profile fields the daily targets are built from (activity_factor 1.2 to
1.5, max_weekly_change_pct up to 1.0, goal, target_weight_kg, target_date, weight_kg, ...) with a
one-sentence reason, or pass empty overrides to regenerate the horizon unchanged. Nothing is
written: the graph rebuilds the targets with the overrides and shows them for approval. Call it
at most once per check-in, after confirming with the athlete when they are present."""


def _error_json(exc: ValidationError) -> str:
    return json.dumps({"error": str(exc)})


def summarize_by_day_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("logged") and r.get("day_type") and r.get("delta_kcal") is not None:
            groups.setdefault(str(r["day_type"]), []).append(r)

    def avg(rs: list[dict[str, Any]], key: str) -> int:
        return round(sum(float(r[key]) for r in rs) / len(rs))

    return {
        day_type: {
            "days": len(rs),
            "avg_logged_kcal": avg(rs, "logged_kcal"),
            "avg_target_kcal": avg(rs, "target_kcal"),
            "avg_delta_kcal": avg(rs, "delta_kcal"),
            "avg_logged_protein_g": avg(rs, "logged_protein_g"),
            "avg_target_protein_g": avg(rs, "target_protein_g"),
        }
        for day_type, rs in groups.items()
    }


def make_checkin_tools(
    garmin: ToolCaller | None, connect: ConnectFactory, today: Callable[[], date]
) -> list[BaseTool]:
    async def read_intake_vs_targets(days: int = 7) -> str:
        if garmin is None:
            return UNAVAILABLE
        now = today()
        end = now - timedelta(days=1)
        start = end - timedelta(days=days - 1)
        with connect() as conn:
            targets = {t.target.day: t.target for t in repo.list_targets(conn, start, end)}
            last = repo.last_target_day(conn)
        rows: list[dict[str, Any]] = []
        for i in range(days):
            day = start + timedelta(days=i)
            try:
                payload = await garmin.call_json(
                    "get_nutrition_daily_food_log", {"date": day.isoformat()}
                )
            except McpToolError as exc:
                return json.dumps({"error": str(exc)})
            logged = parse_food_log(payload)
            t = targets.get(day)
            has_both = t is not None and logged["logged"]
            rows.append(
                {
                    "day": day.isoformat(),
                    "day_type": t.day_type if t else None,
                    "logged": logged["logged"],
                    "logged_kcal": logged["kcal"],
                    "logged_carbs_g": logged["carbs_g"],
                    "logged_protein_g": logged["protein_g"],
                    "logged_fat_g": logged["fat_g"],
                    "target_kcal": t.total_kcal if t else None,
                    "target_carbs_g": t.carbs_g if t else None,
                    "target_protein_g": t.protein_g if t else None,
                    "target_fat_g": t.fat_g if t else None,
                    "delta_kcal": logged["kcal"] - t.total_kcal if has_both and t else None,
                    "items": logged["items"][:MAX_ITEMS],
                }
            )
        remaining = (last - now).days + 1 if last is not None and last >= now else 0
        return json.dumps(
            {
                "days": rows,
                "by_day_type": summarize_by_day_type(rows),
                "targets_through": last.isoformat() if last else None,
                "days_of_targets_remaining": remaining,
            }
        )

    async def record_fuel_feedback(**kwargs: Any) -> str:
        try:
            args = FuelFeedbackArgs(**kwargs)
        except ValidationError as exc:
            return _error_json(exc)
        store = get_store()
        entry = FuelLogEntry(**args.model_dump(exclude={"new_product"}))
        n = await S.append_fuel_entry(store, entry)
        added: bool | None = None
        if args.new_product is not None:
            added = args.outcome == "ok" and await S.add_product(
                store, args.new_product.model_copy(update={"tested": True})
            )
        evidence = carbs_evidence(await S.get_fuel_log(store))
        return json.dumps(
            {
                "recorded": True,
                "entries": n,
                "product_added": added,
                "carbs_evidence_g_per_h": evidence,
            }
        )

    async def propose_target_changes(
        overrides: dict[str, Any] | None = None, reason: str = ""
    ) -> str:
        overrides = dict(overrides or {})
        unknown = sorted(set(overrides) - PROFILE_FIELDS)
        if unknown:
            return json.dumps({"error": f"unknown profile fields: {', '.join(unknown)}"})
        profile = await S.get_profile(get_store())
        if profile is None:
            return json.dumps({"error": "no profile saved; run intake first"})
        try:
            apply_overrides(profile, overrides)
        except ValidationError as exc:
            return _error_json(exc)
        return json.dumps({"proposed": True, "overrides": overrides, "reason": reason})

    return [
        StructuredTool.from_function(
            coroutine=read_intake_vs_targets,
            name="read_intake_vs_targets",
            description=INTAKE_DESCRIPTION,
            args_schema=RecentDaysArgs,
        ),
        StructuredTool.from_function(
            coroutine=record_fuel_feedback,
            name="record_fuel_feedback",
            description=FEEDBACK_DESCRIPTION,
            args_schema=FuelFeedbackArgs,
            handle_validation_error=_error_json,
        ),
        StructuredTool.from_function(
            coroutine=propose_target_changes,
            name="propose_target_changes",
            description=PROPOSE_DESCRIPTION,
            args_schema=ProposeArgs,
            handle_validation_error=_error_json,
        ),
    ]
