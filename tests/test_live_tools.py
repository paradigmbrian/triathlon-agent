import pytest
from langchain_core.tools import tool

from tri_analyze.agent.live_tools import filter_tools, open_live_tools
from tri_analyze.config import Settings
from tri_analyze.mcp.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS


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


def test_allowlists_are_read_only_tools():
    for name in GARMIN_LIVE_TOOLS + TP_LIVE_TOOLS:
        assert name.startswith(("get_", "tp_get_"))


async def test_open_live_tools_survives_a_dead_server(monkeypatch):
    s = Settings(_env_file=None, garmin_mcp_ref="0000000", tp_mcp_ref="0000000")
    logs: list[str] = []
    monkeypatch.setattr("tri_analyze.agent.live_tools.SESSION_TIMEOUT_S", 5)
    async with open_live_tools(s, logs.append) as tools:
        assert tools == []
    assert any("garmin" in m for m in logs) and any("trainingpeaks" in m for m in logs)


@pytest.mark.live
async def test_live_tools_bind_expected_names():
    async with open_live_tools(Settings(), print) as tools:
        names = [t.name for t in tools]
        assert names == GARMIN_LIVE_TOOLS + TP_LIVE_TOOLS
        readiness = next(t for t in tools if t.name == "get_training_readiness")
        text = await readiness.ainvoke({"date": "2026-09-06"})
        assert "score" in str(text)
