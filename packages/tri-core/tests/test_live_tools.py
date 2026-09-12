from contextlib import asynccontextmanager

from langchain_core.tools import tool

from tri_core.config import Settings
from tri_core.mcp.live_tools import filter_tools, open_live_servers, open_live_tools
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


@tool
def tp_get_workout(workout_id: str) -> str:
    """one workout"""
    return ""


class _FakeClient:
    """Stands in for MultiServerMCPClient: session(name) yields the name as the session."""

    def __init__(self, connections):
        self.connections = connections

    @asynccontextmanager
    async def session(self, name):
        yield name


async def _fake_load(session):
    return {
        "garmin": [delete_activity, get_activity_splits, get_activity],
        "trainingpeaks": [tp_get_workout],
    }[session]


async def test_open_live_servers_groups_tools_by_server(monkeypatch):
    monkeypatch.setattr("tri_core.mcp.live_tools.MultiServerMCPClient", _FakeClient)
    monkeypatch.setattr("tri_core.mcp.live_tools.load_mcp_tools", _fake_load)
    s = Settings(_env_file=None)
    specs = {
        "garmin": (garmin_spec(s), ["get_activity_splits", "get_activity"]),
        "trainingpeaks": (trainingpeaks_spec(s), ["tp_get_workout"]),
    }
    logs: list[str] = []
    async with open_live_servers(specs, logs.append) as servers:
        assert {k: [t.name for t in v] for k, v in servers.items()} == {
            "garmin": ["get_activity_splits", "get_activity"],
            "trainingpeaks": ["tp_get_workout"],
        }
    async with open_live_tools(specs, logs.append) as tools:
        assert [t.name for t in tools] == ["get_activity_splits", "get_activity", "tp_get_workout"]
    assert any("garmin: bound" in m for m in logs)


async def test_open_live_servers_omits_a_dead_server(monkeypatch):
    s = Settings(_env_file=None, garmin_mcp_ref="0000000", tp_mcp_ref="0000000")
    monkeypatch.setattr("tri_core.mcp.live_tools.SESSION_TIMEOUT_S", 5)
    specs = {"garmin": (garmin_spec(s), ["get_activity"])}
    logs: list[str] = []
    async with open_live_servers(specs, logs.append) as servers:
        assert servers == {}
    assert any("garmin" in m and "unavailable" in m for m in logs)
