"""Garmin reads for the sub-agents, as LangChain tools over the one live server session.

Hand-written schemas keep the model's view small and make the allow-list structural: only these
four read tools exist. Payloads are trimmed to what the nutrition conversation needs.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from tri_core.mcp.client import McpToolError
from tri_core.sync import ToolCaller

UNAVAILABLE = json.dumps({"error": "Garmin server unavailable this session"})


class BodyCompositionArgs(BaseModel):
    days: int = Field(default=28, ge=1, le=365, description="how many days back to read")


class RecentDaysArgs(BaseModel):
    days: int = Field(default=7, ge=1, le=28, description="how many days back, ending yesterday")


class NoArgs(BaseModel):
    pass


def parse_body_composition(payload: Any) -> list[dict[str, Any]]:
    """Index-scale readings, oldest first, masses in kg."""
    if not isinstance(payload, dict):
        return []
    rows = []
    for e in payload.get("dateWeightList", []):
        rows.append(
            {
                "date": e.get("calendarDate"),
                "weight_kg": round(float(e["weight"]) / 1000, 1) if e.get("weight") else None,
                "body_fat_pct": e.get("bodyFat"),
                "muscle_mass_kg": (
                    round(float(e["muscleMass"]) / 1000, 1) if e.get("muscleMass") else None
                ),
            }
        )
    return sorted(rows, key=lambda r: r["date"] or "")


def _age(birth: str | None, today: date) -> int | None:
    if not birth:
        return None
    b = date.fromisoformat(birth[:10])
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def trim_profile(payload: Any, today: date) -> dict[str, Any]:
    data = (payload or {}).get("userData", {}) if isinstance(payload, dict) else {}
    gender = str(data.get("gender") or "").upper()
    system = str(data.get("measurementSystem") or "")
    return {
        "sex": "f" if gender == "FEMALE" else "m" if gender == "MALE" else None,
        "weight_kg": round(float(data["weight"]) / 1000, 1) if data.get("weight") else None,
        "height_cm": round(float(data["height"]), 1) if data.get("height") else None,
        "age": _age(data.get("birthDate"), today),
        "unit_preference": "imperial" if system.startswith("statute") else "metric",
    }


def trim_settings(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    macros = data.get("macroGoals") or {}
    goal = data.get("calorieGoal")
    return {
        "calorie_goal": goal,
        "carbs_g": macros.get("carbs"),
        "protein_g": macros.get("protein"),
        "fat_g": macros.get("fat"),
    }


_EMPTY_LOG: dict[str, Any] = {
    "logged": False,
    "kcal": 0,
    "carbs_g": 0,
    "protein_g": 0,
    "fat_g": 0,
    "meals": {},
    "items": [],
}


def _int(value: Any) -> int:
    return int(round(float(value))) if value is not None else 0


def parse_food_log(payload: Any) -> dict[str, Any]:
    """One day's logged intake: totals (kcal and grams), kcal per meal, item names."""
    if not isinstance(payload, dict):
        return dict(_EMPTY_LOG)
    total = payload.get("dailyNutritionContent") or {}
    meals: dict[str, int] = {}
    items: list[str] = []
    for detail in payload.get("mealDetails") or []:
        name = str((detail.get("meal") or {}).get("mealName") or "meal").lower()
        content = detail.get("mealNutritionContent") or {}
        if content.get("calories") is not None:
            meals[name] = _int(content["calories"])
        for food in detail.get("loggedFoods") or []:
            fname = (food.get("foodMetaData") or {}).get("foodName")
            if not fname:
                continue
            qty = food.get("servingQty")
            label = str(fname)
            if isinstance(qty, int | float) and float(qty) != 1.0:
                label += f" x{float(qty):g}"
            items.append(label)
    return {
        "logged": bool(items),
        "kcal": _int(total.get("calories")),
        "carbs_g": _int(total.get("carbs")),
        "protein_g": _int(total.get("protein")),
        "fat_g": _int(total.get("fat")),
        "meals": meals,
        "items": items,
    }


def parse_hydration(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}

    def ml(key: str) -> int | None:
        value = data.get(key)
        return int(round(float(value))) if value is not None else None

    return {
        "date": data.get("calendarDate"),
        "intake_ml": ml("valueInML"),
        "goal_ml": ml("goalInML"),
        "sweat_loss_ml": ml("sweatLossInML"),
    }


def make_garmin_read_tools(
    garmin: ToolCaller | None,
    today: Callable[[], date],
    only: Collection[str] | None = None,
) -> list[BaseTool]:
    async def _call(tool: str, args: dict[str, Any]) -> Any:
        return await garmin.call_json(tool, args) if garmin is not None else None

    async def read_garmin_profile() -> str:
        """The athlete's Garmin profile: sex, weight_kg, height_cm, age, and unit_preference
        (metric | imperial, from the Garmin display setting). Read this first."""
        if garmin is None:
            return UNAVAILABLE
        try:
            return json.dumps(trim_profile(await _call("get_user_profile", {}), today()))
        except McpToolError as exc:
            return json.dumps({"error": str(exc)})

    async def read_body_composition(days: int = 28) -> str:
        """Index-scale readings for the last `days` days: date, weight_kg, body_fat_pct,
        muscle_mass_kg, oldest first. Empty list when the athlete has not weighed in."""
        if garmin is None:
            return UNAVAILABLE
        end = today()
        args = {
            "start_date": (end - timedelta(days=days)).isoformat(),
            "end_date": end.isoformat(),
        }
        try:
            return json.dumps(parse_body_composition(await _call("get_body_composition", args)))
        except McpToolError as exc:
            return json.dumps({"error": str(exc)})

    async def read_garmin_nutrition_settings() -> str:
        """The calorie and macro goals Garmin currently shows for today (null when none are set)."""
        if garmin is None:
            return UNAVAILABLE
        try:
            payload = await _call("get_nutrition_daily_settings", {"date": today().isoformat()})
            return json.dumps(trim_settings(payload))
        except McpToolError as exc:
            return json.dumps({"error": str(exc)})

    async def read_hydration(days: int = 7) -> str:
        """Garmin hydration for the last `days` days ending yesterday: date, intake_ml, goal_ml,
        sweat_loss_ml per day (null when nothing was logged that day)."""
        if garmin is None:
            return UNAVAILABLE
        end = today() - timedelta(days=1)
        rows = []
        try:
            for i in range(days):
                day = end - timedelta(days=days - 1 - i)
                payload = await _call("get_hydration_data", {"date": day.isoformat()})
                rows.append({**parse_hydration(payload), "date": day.isoformat()})
        except McpToolError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(rows)

    tools = [
        StructuredTool.from_function(
            coroutine=read_garmin_profile,
            name="read_garmin_profile",
            description=read_garmin_profile.__doc__ or "",
            args_schema=NoArgs,
        ),
        StructuredTool.from_function(
            coroutine=read_body_composition,
            name="read_body_composition",
            description=read_body_composition.__doc__ or "",
            args_schema=BodyCompositionArgs,
        ),
        StructuredTool.from_function(
            coroutine=read_garmin_nutrition_settings,
            name="read_garmin_nutrition_settings",
            description=read_garmin_nutrition_settings.__doc__ or "",
            args_schema=NoArgs,
        ),
        StructuredTool.from_function(
            coroutine=read_hydration,
            name="read_hydration",
            description=read_hydration.__doc__ or "",
            args_schema=RecentDaysArgs,
        ),
    ]
    return [t for t in tools if only is None or t.name in only]
