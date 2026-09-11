from langchain_core.tools import tool

from tri_core.config import Settings
from tri_core.mcp.live_tools import filter_tools, open_live_tools
from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec


@tool
def get_activity_splits(activity_id: str) -> str:
    """splits"""
    return ""


@tool
def get_activity(activity_id: str) -> str:
    """activity"""
    return ""


@tool
def delete_activity(activity_id: str) -> str:
    """never"""
    return ""


def test_filter_keeps_allowlisted_in_allowlist_order():
    out = filter_tools(
        [delete_activity, get_activity_splits, get_activity],
        ["get_activity", "get_activity_splits"],
    )
    assert [t.name for t in out] == ["get_activity", "get_activity_splits"]


async def test_open_live_tools_survives_a_dead_server(monkeypatch):
    s = Settings(_env_file=None, garmin_mcp_ref="0000000", tp_mcp_ref="0000000")
    logs: list[str] = []
    monkeypatch.setattr("tri_core.mcp.live_tools.SESSION_TIMEOUT_S", 5)
    specs = {
        "garmin": (garmin_spec(s), ["get_activity"]),
        "trainingpeaks": (trainingpeaks_spec(s), ["tp_get_workout"]),
    }
    async with open_live_tools(specs, logs.append) as tools:
        assert tools == []
    assert any("garmin" in m for m in logs) and any("trainingpeaks" in m for m in logs)
