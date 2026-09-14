import pytest

pytestmark = pytest.mark.db


async def test_status_reports_live_tools_readiness_and_thread(runtime, client, monkeypatch):
    monkeypatch.setattr("tri_web.routes.system.checkpointer_ready", lambda url: True)
    monkeypatch.setattr("tri_web.routes.system.store_ready", lambda url: False)
    async with client(runtime()) as c:
        r = await c.get("/api/system/status")
    assert r.status_code == 200
    assert r.json() == {
        "live": False,
        "tools": [],
        "ready": {"api_key": True, "checkpointer": True, "store": False},
        "thread": "coach",
        "running": None,
    }
