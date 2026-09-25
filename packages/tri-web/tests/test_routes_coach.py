"""Coach routes over the fake runtime: a turn streams token and done; a proposing coach pauses;
approve resumes and streams the apply report; busy is 409; an edit is validated server-side; a
disconnect lets the run finish."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tri_coach.testing import consult, move_call, propose, seed_active_plan
from tri_planning.testing import FakeTp
from tri_web.events import start_turn
from tri_web.thread import thread_snapshot

pytestmark = pytest.mark.db


def proposing(nocommit):
    """Runtime kwargs for a coach that consults planning and proposes moving w1; the FakeTp is
    returned too so tests can assert on the writes apply made."""
    seed_active_plan(nocommit)
    tp = FakeTp()
    kwargs = {
        "tp": tp,
        "coach": [consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        "planning": [move_call(), AIMessage(content="ok")],
    }
    return tp, kwargs


async def test_empty_thread(runtime, client):
    async with client(runtime()) as c:
        r = await c.get("/api/coach/thread")
    assert r.status_code == 200
    assert r.json() == {
        "messages": [],
        "paused": None,
        "held": None,
        "stuck": False,
        "running": None,
    }


async def test_a_turn_streams_tokens_then_done_and_the_thread_shows_it(runtime, client, parse_sse):
    rt = runtime(coach=[AIMessage(content="Hello athlete.")])
    async with client(rt) as c:
        r = await c.post("/api/coach/turns", json={"text": "hi"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(r.text)
        assert events[0][0] == "token" and events[0][1]["where"] == "coach"
        assert "".join(d["text"] for n, d in events if n == "token") == "Hello athlete."
        assert events[-1] == ("done", {"final_text": "Hello athlete.", "paused": False})
        thread = (await c.get("/api/coach/thread")).json()
    roles = [m["role"] for m in thread["messages"]]
    assert roles == ["user", "assistant"] and thread["messages"][1]["text"] == "Hello athlete."
    assert not rt.lock.locked() and rt.running is None


async def test_a_proposing_coach_streams_the_interrupt_and_pauses(
    nocommit, runtime, client, parse_sse
):
    tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        events = parse_sse((await c.post("/api/coach/turns", json={"text": "my knee hurts"})).text)
        names = [n for n, _ in events]
        assert "tool_call" in names and "consult" in names and "interrupt" in names
        interrupt = next(d for n, d in events if n == "interrupt")
        assert interrupt["narration"] == "Move it." and interrupt["proposals"][0]["id"] == "p1"
        assert events[-1][1]["paused"] is True
        thread = (await c.get("/api/coach/thread")).json()
        assert thread["paused"]["proposals"][0]["domain"] == "planning" and thread["stuck"] is False
        # approve resumes the run and streams the apply report
        r = await c.post("/api/coach/review", json={"action": "approve"})
        events = parse_sse(r.text)
        reports = [d["text"] for n, d in events if n == "report"]
        assert reports and reports[0].startswith("planning: applied 1\n  applied: move w1 -> ")
        assert events[-1][1]["paused"] is False
        assert (await c.get("/api/coach/thread")).json()["paused"] is None
    assert [call[0] for call in tp.calls] == ["tp_update_workout"]


async def test_review_without_a_paused_review_is_409(runtime, client):
    async with client(runtime()) as c:
        r = await c.post("/api/coach/review", json={"action": "approve"})
    assert r.status_code == 409 and r.json() == {"reason": "no_review"}


async def test_busy_is_409_with_the_running_kind(runtime, client):
    rt = runtime()
    await rt.lock.acquire()
    rt.running = "checkin"
    try:
        async with client(rt) as c:
            r = await c.post("/api/coach/turns", json={"text": "hi"})
            assert r.status_code == 409 and r.json() == {"running": "checkin"}
            r = await c.post("/api/coach/review", json={"action": "approve"})
            assert r.status_code == 409 and r.json() == {"running": "checkin"}
            assert (await c.get("/api/coach/thread")).json()["running"] == "checkin"
    finally:
        rt.lock.release()


async def test_edit_is_validated_and_resumes_with_typed_proposals(
    nocommit, runtime, client, parse_sse
):
    tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        await c.post("/api/coach/turns", json={"text": "my knee hurts"})
        paused = (await c.get("/api/coach/thread")).json()["paused"]
        edited = paused["proposals"]
        edited[0]["changes"][0]["op"] = "teleport"
        r = await c.post("/api/coach/review", json={"action": "edit", "proposals": edited})
        assert r.status_code == 422 and r.json()["detail"] == "edit rejected"
        assert any("op" in e["loc"] for e in r.json()["errors"])
        r = await c.post("/api/coach/review", json={"action": "edit", "proposals": []})
        assert r.status_code == 422 and "reject instead" in r.json()["detail"]
        edited[0]["changes"][0]["op"] = "move"
        edited[0]["changes"][0]["new_date"] = "2026-09-19"
        r = await c.post("/api/coach/review", json={"action": "edit", "proposals": edited})
        assert r.status_code == 200
        reports = [d["text"] for n, d in parse_sse(r.text) if n == "report"]
        assert reports[0].startswith("planning: applied 1\n  applied: move w1 -> 2026-09-19")
    assert tp.calls[0][0] == "tp_update_workout"
    assert "2026-09-19" in str(tp.calls[0][1])  # the moved date reached TrainingPeaks


async def test_reject_with_a_note(nocommit, runtime, client, parse_sse):
    _tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        await c.post("/api/coach/turns", json={"text": "my knee hurts"})
        r = await c.post("/api/coach/review", json={"action": "reject", "note": "keep Wednesday"})
        assert r.status_code == 200 and parse_sse(r.text)[-1][0] == "done"
        thread = (await c.get("/api/coach/thread")).json()
    assert thread["paused"] is None
    assert any(m["role"] == "report" and "keep Wednesday" in m["text"] for m in thread["messages"])


async def test_review_helpers(nocommit, runtime, client):
    _tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        assert set((await c.get("/api/coach/review/schema")).json()) == {
            "proposal",
            "planning_change",
            "nutrition_change",
        }
        assert (await c.get("/api/coach/review/yaml")).status_code == 409
        await c.post("/api/coach/turns", json={"text": "my knee hurts"})
        text = (await c.get("/api/coach/review/yaml")).json()["yaml"]
        assert text.startswith("p1:")
        r = await c.post(
            "/api/coach/review/validate", json={"yaml": text.replace("op: move", "op: teleport")}
        )
        assert r.status_code == 200 and r.json()["ok"] is False
        r = await c.post("/api/coach/review/validate", json={"yaml": text})
        assert r.json()["ok"] is True and r.json()["proposals"][0]["id"] == "p1"
        paused = (await c.get("/api/coach/thread")).json()["paused"]
        r = await c.post("/api/coach/review/validate", json={"proposals": paused["proposals"]})
        assert r.json()["ok"] is True
        r = await c.post("/api/coach/review/validate", json={})
        assert r.status_code == 422


async def test_a_disconnect_mid_stream_lets_the_run_finish(runtime):
    rt = runtime(coach=[AIMessage(content="Still here.")])
    run = await start_turn(rt, {"messages": [HumanMessage("hi")]}, kind="turn")
    first = await run.queue.get()  # the browser read one event, then closed the tab
    assert first is not None
    del run.queue  # nobody reads the rest
    await asyncio.wait_for(rt.turn_task, timeout=10)
    view = await thread_snapshot(rt.graph, rt.thread_id, running=rt.running)
    assert [m.role for m in view.messages] == ["user", "assistant"]
    assert view.messages[1].text == "Still here." and not rt.lock.locked()


async def test_route_errors_return_detail_only(runtime, client):
    rt = runtime()

    async def boom(config):
        raise RuntimeError("psycopg went away")

    rt.graph.aget_state = boom  # type: ignore[method-assign]
    async with client(rt) as c:
        r = await c.get("/api/coach/thread")
    assert r.status_code == 500 and r.json() == {"detail": "internal error"}


async def test_a_turn_during_a_paused_review_is_409_and_keeps_the_review(
    nocommit, runtime, client, parse_sse
):
    tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        await c.post("/api/coach/turns", json={"text": "my knee hurts"})
        r = await c.post("/api/coach/turns", json={"text": "never mind"})
        assert r.status_code == 409 and r.json() == {"reason": "paused"}
        thread = (await c.get("/api/coach/thread")).json()
        assert thread["paused"]["proposals"][0]["id"] == "p1"
        assert [m["role"] for m in thread["messages"]].count("user") == 1
        r = await c.post("/api/coach/review", json={"action": "reject"})
        assert r.status_code == 200 and parse_sse(r.text)[-1][0] == "done"
        assert (await c.get("/api/coach/thread")).json()["paused"] is None
    assert tp.calls == []
    assert not rt.lock.locked() and rt.running is None
