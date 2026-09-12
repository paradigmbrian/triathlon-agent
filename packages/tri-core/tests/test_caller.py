import json

import pytest
from langchain_core.tools import ToolException, tool

from tri_core.mcp.caller import ToolsCaller, tool_text
from tri_core.mcp.client import McpToolError


@tool
def tp_get_workouts(start_date: str, end_date: str) -> str:
    """Planned workouts; JSON text as the TrainingPeaks server returns it."""
    return json.dumps({"workouts": [{"id": "w1", "date": start_date}], "count": 1})


@tool
def get_stats(date: str) -> list:
    """Daily stats; the adapter's content-block shape, with Garmin's empty convention."""
    return [{"type": "text", "text": "No stats found for " + date}]


@tool
def get_hrv_data(date: str) -> str:
    """HRV; Garmin's error convention."""
    return "Error retrieving HRV data: boom"


@tool
def tp_get_workout(workout_id: str) -> str:
    """One workout; the adapter raises ToolException when the server sets isError."""
    raise ToolException("server said no")


@tool
def tp_get_fitness(days: int) -> list:
    """Two text blocks, joined in order."""
    return [{"type": "text", "text": '{"ctl": 45,'}, {"type": "text", "text": ' "atl": 50}'}]


CALLER = ToolsCaller([tp_get_workouts, get_stats, get_hrv_data, tp_get_workout, tp_get_fitness])


def test_names_are_the_bound_tools():
    assert CALLER.names == [
        "tp_get_workouts",
        "get_stats",
        "get_hrv_data",
        "tp_get_workout",
        "tp_get_fitness",
    ]


async def test_call_json_parses_json_text():
    out = await CALLER.call_json("tp_get_workouts", {"start_date": "2026-09-14", "end_date": "x"})
    assert out == {"workouts": [{"id": "w1", "date": "2026-09-14"}], "count": 1}


async def test_content_blocks_are_joined_and_empty_convention_returns_none():
    assert await CALLER.call_json("get_stats", {"date": "2026-09-14"}) is None
    assert await CALLER.call_json("tp_get_fitness", {"days": 7}) == {"ctl": 45, "atl": 50}


async def test_error_text_raises_mcp_tool_error():
    with pytest.raises(McpToolError) as ei:
        await CALLER.call_json("get_hrv_data", {"date": "2026-09-14"})
    assert ei.value.tool == "get_hrv_data" and "boom" in ei.value.message


async def test_tool_exception_becomes_mcp_tool_error():
    with pytest.raises(McpToolError) as ei:
        await CALLER.call_json("tp_get_workout", {"workout_id": "w1"})
    assert ei.value.tool == "tp_get_workout" and "server said no" in ei.value.message


async def test_unbound_tool_raises():
    with pytest.raises(McpToolError) as ei:
        await CALLER.call_json("tp_create_workout", {})
    assert "not bound" in ei.value.message


async def test_missing_args_default_to_empty():
    caller = ToolsCaller([tp_get_fitness])
    # tp_get_fitness needs `days`; calling with no args surfaces pydantic's error as McpToolError
    with pytest.raises(McpToolError):
        await caller.call_json("tp_get_fitness")


def test_tool_text_shapes():
    assert tool_text("plain") == "plain"
    assert tool_text([{"type": "text", "text": "a"}, {"type": "image", "base64": "zz"}]) == "a"
    assert tool_text(["x", {"type": "text", "text": "y"}]) == "x\ny"
    assert tool_text([]) == ""
    assert tool_text({"k": 1}) == "{'k': 1}"
