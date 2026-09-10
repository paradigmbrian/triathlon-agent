"""One-off spike for the nutrition agent: record the Garmin body-composition and nutrition tool
payloads, and probe whether set_nutrition_daily_settings on a far-future date is per-day.

Run:  uv run python scripts/spike_nutrition.py [--days 14] [--date YYYY-MM-DD] [--probe-write]
Writes packages/tri-nutrition/tests/fixtures/mcp/<tool>.json. Review each file before
committing: scrub anything you consider private. Numbers are fine.

Findings 2026-09-10: Garmin rejects any nutrition date more than 90 days out
("Provided date ... is after 90 days from current date"), so the write probe uses today + 60.
The probe refuses to run when the day carries no goals yet, because there is no tool to clear a
day's goals afterwards; pass --allow-stray to accept leaving the probe target in place.
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

PROBE_DAYS_AHEAD = 60  # inside Garmin's 90-day window
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


async def main(days: int, log_date: str | None, probe_write: bool, allow_stray: bool) -> None:
    settings = get_settings()
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    yesterday = log_date or (today - timedelta(days=1)).isoformat()
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
        far = (today + timedelta(days=PROBE_DAYS_AHEAD)).isoformat()
        before = await record(g, "get_nutrition_daily_settings", {"date": far}, "_far_before")
        goals = before.get("macroGoals") if isinstance(before, dict) else None
        if not goals and not allow_stray:
            print(f"{far} has no goals set; a probe write could not be restored. Skipping.")
            print("Pass --allow-stray to write anyway and leave the probe target in place.")
            return
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
        after = await record(g, "get_nutrition_daily_settings", {"date": far}, "_far_after")
        next_day = (today + timedelta(days=PROBE_DAYS_AHEAD + 1)).isoformat()
        after_next = await record(
            g, "get_nutrition_daily_settings", {"date": next_day}, "_far_next_day"
        )
        ok = all(isinstance(x, dict) and "__error__" not in x for x in (before, after, after_next))
        if not ok:
            print("per-day override? unknown: a call errored; see the _far_*.json files")
        else:
            print("per-day override?", "yes" if after_next == before else "NO: default changed")
        if isinstance(goals, dict) and goals:
            print("previous goals:", goals)
            print("restore by hand with set_nutrition_daily_settings using those values")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--date", help="day to read the food log, meals and settings for")
    ap.add_argument("--probe-write", action="store_true")
    ap.add_argument("--allow-stray", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.days, a.date, a.probe_write, a.allow_stray))
