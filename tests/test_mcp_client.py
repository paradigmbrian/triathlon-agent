import json
from types import SimpleNamespace

import pytest
from mcp.types import TextContent

from tri_analyze.config import Settings
from tri_analyze.mcp.client import McpToolClient, McpToolError, parse_tool_text
from tri_analyze.mcp.servers import garmin_spec, trainingpeaks_spec


def test_parse_json_object():
    assert parse_tool_text("t", json.dumps({"a": 1})) == {"a": 1}


def test_parse_garmin_empty_convention_returns_none():
    assert parse_tool_text("get_stats", "No stats found for 2026-01-01") is None


def test_parse_garmin_error_raises():
    with pytest.raises(McpToolError) as ei:
        parse_tool_text("get_stats", "Error retrieving stats: boom")
    assert ei.value.tool == "get_stats"
    assert "boom" in ei.value.message


def test_parse_tp_iserror_raises():
    payload = {"isError": True, "error_code": "AUTH_INVALID", "message": "Re-authenticate."}
    with pytest.raises(McpToolError) as ei:
        parse_tool_text("tp_get_workouts", json.dumps(payload))
    assert "AUTH_INVALID" in ei.value.message


def test_parse_garbage_raises():
    with pytest.raises(McpToolError):
        parse_tool_text("t", "not json at all")


def test_specs_use_pinned_refs():
    s = Settings(_env_file=None)
    g = garmin_spec(s)
    assert g.command == "uvx"
    assert any(s.garmin_mcp_ref in a for a in g.args)
    assert "GARMIN_ENABLED_TOOLS" in g.env
    t = trainingpeaks_spec(s)
    assert any(s.tp_mcp_ref in a for a in t.args)
    assert t.args[-2:] == ["tp-mcp", "serve"]


def test_tp_cookie_passed_through_env():
    s = Settings(_env_file=None, tp_auth_cookie="abc")
    assert trainingpeaks_spec(s).env["TP_AUTH_COOKIE"] == "abc"


class _FakeSession:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        return SimpleNamespace(content=[TextContent(type="text", text=self.text)], isError=False)


async def test_call_json_uses_session_and_parses():
    client = McpToolClient.__new__(McpToolClient)
    client._session = _FakeSession(json.dumps({"ok": True}))  # type: ignore[attr-defined]
    out = await client.call_json("tp_get_profile", {"x": 1})
    assert out == {"ok": True}
    assert client._session.calls == [("tp_get_profile", {"x": 1})]  # type: ignore[attr-defined]


@pytest.mark.live
async def test_live_servers_expose_expected_tools():
    s = Settings()
    async with McpToolClient(trainingpeaks_spec(s)) as tp:
        names = await tp.list_tool_names()
        assert {
            "tp_get_athlete_settings",
            "tp_get_workouts",
            "tp_get_workout",
            "tp_get_fitness",
        } <= set(names)
    async with McpToolClient(garmin_spec(s)) as g:
        names = await g.list_tool_names()
        assert {
            "get_stats",
            "get_sleep_summary_range",
            "get_training_readiness",
            "get_activities_by_date",
        } <= set(names)
