"""Read-only TrainingPeaks access for the adjust sub-agent, over the same session apply uses."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, StructuredTool

from tri_core.sync import ToolCaller


def make_tp_read_tools(tp: ToolCaller | None) -> list[BaseTool]:
    async def tp_get_workouts(start_date: str, end_date: str) -> str:
        """Live TrainingPeaks calendar between two dates (YYYY-MM-DD): planned and completed
        workouts with their ids, dates, titles, planned and actual TSS."""
        if tp is None:
            return json.dumps({"error": "TrainingPeaks server unavailable this session"})
        result = await tp.call_json(
            "tp_get_workouts",
            {"start_date": start_date, "end_date": end_date, "workout_filter": "all"},
        )
        return json.dumps(result, default=str)

    return [
        StructuredTool.from_function(
            coroutine=tp_get_workouts,
            name="tp_get_workouts",
            description=tp_get_workouts.__doc__ or "",
        )
    ]
