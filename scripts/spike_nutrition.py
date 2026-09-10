"""One-off spike for the nutrition agent: record the Garmin body-composition and nutrition tool
payloads, and probe whether set_nutrition_daily_settings on a far-future date is per-day.

Run:  uv run python scripts/spike_nutrition.py [--days 14] [--probe-write]
Writes packages/tri-nutrition/tests/fixtures/mcp/<tool>.json. Review each file before
committing: scrub anything you consider private. Numbers are fine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tri_core.config import get_settings
from tri_core.mcp.client import McpToolClient, McpToolError
from tri_core.mcp.servers import garmin_spec

OUT = Path("packages/tri-nutrition/tests/fixtures/mcp")
NUTRITION_TOOLS = [
    "get_body_composition",
    "get_daily_weigh_ins",
    "get_user_profile",
    "get_nutrition_daily_food_log",
    "get_nutrition_daily_meals",
    "get_nutrition_daily_settings",
    "set_nutrition_daily_settings",
    "get_hydration_data",
    "get_stats",
]


async def record(client: McpToolClient, tool: str, args: dict[str, Any], suffix: str = "") -> Any:
    name = f"{tool}{suffix}"
    try:
        result = await client.call_json(tool, args)
        status = "ok" if result is not None else "empty"
    except McpToolError as exc:
        result = {"__error__": str(exc)}
        status = "ERROR"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps({"args": args, "result": result}, indent=2, default=str)
    )
    print(f"{status:5} {name:40} {len(json.dumps(result, default=str)):>8} bytes")
    return result


async def main(days: int, probe_write: bool) -> None:
    settings = get_settings()
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()
    async with McpToolClient(garmin_spec(settings, enabled_tools=NUTRITION_TOOLS)) as g:
        print("tools:", await g.list_tool_names())
        await record(g, "get_user_profile", {})
        await record(g, "get_body_composition", {"start_date": start, "end_date": yesterday})
        await record(g, "get_daily_weigh_ins", {"date": yesterday})
        await record(g, "get_nutrition_daily_food_log", {"date": yesterday})
        await record(g, "get_nutrition_daily_meals", {"date": yesterday})
        await record(g, "get_nutrition_daily_settings", {"date": yesterday})
        await record(g, "get_hydration_data", {"date": yesterday})
        if not probe_write:
            return
        far = (today + timedelta(days=400)).isoformat()
        before = await record(g, "get_nutrition_daily_settings", {"date": far}, "_far_before")
        await record(
            g,
            "set_nutrition_daily_settings",
            {
                "date": far,
                "calorie_goal": 2345,
                "carbs_grams": 300,
                "protein_grams": 150,
                "fat_grams": 61,
            },
        )
        await record(g, "get_nutrition_daily_settings", {"date": far}, "_far_after")
        after_next = await record(
            g,
            "get_nutrition_daily_settings",
            {"date": (today + timedelta(days=401)).isoformat()},
            "_far_next_day",
        )
        print("per-day override?", "yes" if after_next != before else "NO: default changed")
        if isinstance(before, dict):
            restore = {
                "date": far,
                "calorie_goal": before.get("calorie_goal") or before.get("calorieGoal"),
                "carbs_grams": before.get("carbs_grams") or before.get("carbsGoal"),
                "protein_grams": before.get("protein_grams") or before.get("proteinGoal"),
                "fat_grams": before.get("fat_grams") or before.get("fatGoal"),
            }
            await record(g, "set_nutrition_daily_settings", restore, "_restore")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--probe-write", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.days, a.probe_write))
