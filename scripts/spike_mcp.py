"""One-off spike: call every tool the sync depends on and save fixtures.

Run:  uv run python scripts/spike_mcp.py [--days 14]
Writes tests/fixtures/mcp/<tool>.json. Review each file before committing:
scrub anything you consider private (names, emails). Numbers are fine.
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
from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec

OUT = Path("tests/fixtures/mcp")


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
    size = len(json.dumps(result, default=str))
    print(f"{status:5} {name:40} {size:>8} bytes")
    return result


async def main(days: int) -> None:
    settings = get_settings()
    end = date.today()
    start = end - timedelta(days=days)
    s, e = start.isoformat(), end.isoformat()

    print("== TrainingPeaks")
    async with McpToolClient(trainingpeaks_spec(settings)) as tp:
        print("tools:", len(await tp.list_tool_names()))
        await record(tp, "tp_get_athlete_settings", {})
        workouts = await record(
            tp, "tp_get_workouts", {"start_date": s, "end_date": e, "workout_filter": "all"}
        )
        listed = (workouts or {}).get("workouts", [])
        first_completed = next((w for w in listed if w["type"] == "completed"), None)
        first_planned = next((w for w in listed if w["type"] == "planned"), None)
        if first_completed:
            await record(tp, "tp_get_workout", {"workout_id": first_completed["id"]}, "_completed")
        if first_planned:
            await record(tp, "tp_get_workout", {"workout_id": first_planned["id"]}, "_planned")
        await record(tp, "tp_get_fitness", {"start_date": s, "end_date": e})

    print("== Garmin")
    async with McpToolClient(garmin_spec(settings)) as g:
        print("tools:", await g.list_tool_names())
        await record(g, "get_stats", {"date": e})
        await record(
            g,
            "get_sleep_summary_range",
            {"start_date": (end - timedelta(days=3)).isoformat(), "end_date": e},
        )
        await record(g, "get_hrv_data", {"date": e})
        await record(g, "get_training_readiness", {"date": e})
        acts = await record(
            g,
            "get_activities_by_date",
            {"start_date": s, "end_date": e, "page": 0, "page_size": 200},
        )
        first = ((acts or {}).get("activities") or [None])[0]
        if first:
            await record(g, "get_activity", {"activity_id": first["id"]})
            await record(g, "get_activity_splits", {"activity_id": first["id"]})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    asyncio.run(main(ap.parse_args().days))
