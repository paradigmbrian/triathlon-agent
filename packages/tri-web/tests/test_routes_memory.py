"""Memory list and forget; reset clears the thread and, when asked, the memory."""

from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage

from tri_coach import memory as M
from tri_planning.testing import MONDAY

pytestmark = pytest.mark.db


async def test_memory_lists_entries_with_the_active_ids(runtime, client, mem_store):
    old = await M.add_entry(
        mem_store, "injury", "knee", MONDAY - timedelta(days=30), until=MONDAY - timedelta(days=1)
    )
    live = await M.add_entry(mem_store, "preference", "long rides on Saturday", MONDAY)
    async with client(runtime()) as c:
        r = await c.get("/api/coach/memory")
        assert r.status_code == 200
        body = r.json()
        assert [e["id"] for e in body["entries"]] == [old.id, live.id]
        assert body["entries"][1] == {
            "id": live.id,
            "kind": "preference",
            "text": "long rides on Saturday",
            "created": "2026-09-14",
            "until": None,
        }
        assert body["active_ids"] == [live.id]
        assert (await c.delete(f"/api/coach/memory/{old.id}")).status_code == 204
        assert (await c.delete(f"/api/coach/memory/{old.id}")).status_code == 404
        assert [e["id"] for e in (await c.get("/api/coach/memory")).json()["entries"]] == [live.id]


async def test_reset_clears_the_thread_and_optionally_the_memory(runtime, client, mem_store):
    await M.add_entry(mem_store, "note", "keep", MONDAY)
    rt = runtime(coach=[AIMessage(content="Hello."), AIMessage(content="Again.")])
    async with client(rt) as c:
        await c.post("/api/coach/turns", json={"text": "hi"})
        assert len((await c.get("/api/coach/thread")).json()["messages"]) == 2
        assert (
            await c.post("/api/coach/reset", json={"confirm": False, "forget_memory": False})
        ).status_code == 422
        r = await c.post("/api/coach/reset", json={"confirm": True, "forget_memory": False})
        assert r.status_code == 204
        assert (await c.get("/api/coach/thread")).json()["messages"] == []
        assert len(await M.get_entries(mem_store)) == 1
        await c.post(
            "/api/coach/turns", json={"text": "hi again"}
        )  # the thread works after a reset
        assert len((await c.get("/api/coach/thread")).json()["messages"]) == 2
        r = await c.post("/api/coach/reset", json={"confirm": True, "forget_memory": True})
        assert r.status_code == 204
        assert await M.get_entries(mem_store) == []
    assert not rt.lock.locked() and rt.running is None


async def test_reset_is_409_while_busy(runtime, client):
    rt = runtime()
    await rt.lock.acquire()
    rt.running = "turn"
    try:
        async with client(rt) as c:
            r = await c.post("/api/coach/reset", json={"confirm": True, "forget_memory": False})
        assert r.status_code == 409 and r.json() == {"running": "turn"}
    finally:
        rt.lock.release()
