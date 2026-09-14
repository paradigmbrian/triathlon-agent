"""Sync and check-in as jobs: id now, transcript over SSE, result at the end; check-in holds the
coach lock and a paused check-in leaves the review on the thread."""

import pytest
from langchain_core.messages import AIMessage

from tri_coach.testing import consult, move_call, propose, seed_active_plan
from tri_core.sync.runner import SourceResult, SyncReport
from tri_planning.testing import FakeTp

pytestmark = pytest.mark.db


async def fake_sync(settings, *, since=None, full=False, log=print, **kw):
    log(f"== garmin: {'full' if full else 'incremental'} since {since}")
    return SyncReport(
        results=[SourceResult("garmin", "ok", 3), SourceResult("trainingpeaks", "error", 0, "boom")]
    )


async def test_sync_job_streams_its_lines_and_result(runtime, client, monkeypatch, parse_sse):
    monkeypatch.setattr("tri_web.routes.jobs.run_sync", fake_sync)
    rt = runtime()
    async with client(rt) as c:
        r = await c.post("/api/jobs/sync", json={"since": "2026-09-01", "full": True})
        assert r.status_code == 200
        job_id = r.json()["id"]
        assert rt.jobs.get(job_id) is not None
        assert not rt.lock.locked()  # sync never takes the coach lock
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
        assert events[0] == ("line", {"text": "== garmin: full since 2026-09-01"})
        assert events[-1][0] == "done"
        assert events[-1][1]["result"] == {
            "ok": False,
            "results": [
                {"source": "garmin", "status": "ok", "rows": 3, "error": None},
                {"source": "trainingpeaks", "status": "error", "rows": 0, "error": "boom"},
            ],
        }
        status = (await c.get(f"/api/jobs/{job_id}")).json()
        assert (
            status["status"] == "done"
            and status["kind"] == "sync"
            and status["result"]["ok"] is False
        )
        assert (await c.get("/api/jobs/nope")).status_code == 404


async def test_checkin_job_runs_the_coach_and_reports_the_code(
    nocommit, runtime, client, parse_sse
):
    seed_active_plan(nocommit)
    rt = runtime(coach=[AIMessage(content="Clean week.")])
    async with client(rt) as c:
        r = await c.post("/api/jobs/checkin", json={"sync": False})
        job_id = r.json()["id"]
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
    assert any("Clean week." in d.get("text", "") for n, d in events if n == "line")
    assert events[-1] == ("done", {"result": {"code": 0, "paused": False, "no_plan": False}})
    assert not rt.lock.locked() and rt.running is None


async def test_checkin_that_proposes_pauses_on_the_thread(nocommit, runtime, client, parse_sse):
    seed_active_plan(nocommit)
    rt = runtime(
        tp=FakeTp(),
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    async with client(rt) as c:
        job_id = (await c.post("/api/jobs/checkin", json={"sync": False})).json()["id"]
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
        assert events[-1][1]["result"]["paused"] is True
        thread = (await c.get("/api/coach/thread")).json()
    assert thread["paused"] is not None and thread["paused"]["proposals"][0]["id"] == "p1"


async def test_checkin_without_plan_or_profile_is_code_2(runtime, client, parse_sse):
    rt = runtime()
    async with client(rt) as c:
        job_id = (await c.post("/api/jobs/checkin", json={"sync": False})).json()["id"]
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
    assert events[-1][1]["result"] == {"code": 2, "paused": False, "no_plan": True}
    assert any("no active plan" in d.get("text", "") for _, d in events)


async def test_checkin_is_409_while_a_turn_runs_and_holds_the_lock_while_it_runs(
    runtime, client, monkeypatch, parse_sse
):
    rt = runtime()
    await rt.lock.acquire()
    rt.running = "turn"
    try:
        async with client(rt) as c:
            r = await c.post("/api/jobs/checkin", json={"sync": False})
            assert r.status_code == 409 and r.json() == {"running": "turn"}
    finally:
        rt.lock.release()
        rt.running = None
    # and a running check-in refuses a turn
    import asyncio

    gate = asyncio.Event()

    async def slow_checkin(graph, *, has_plan, has_profile, yes, out, thread_id="coach"):
        out("waiting\n")
        await gate.wait()
        return 0

    monkeypatch.setattr("tri_web.routes.jobs.run_checkin", slow_checkin)
    async with client(rt) as c:
        job_id = (await c.post("/api/jobs/checkin", json={"sync": False})).json()["id"]
        await asyncio.sleep(0)
        assert rt.lock.locked() and rt.running == "checkin"
        assert rt.turn_task is rt.jobs.get(job_id).task
        r = await c.post("/api/coach/turns", json={"text": "hi"})
        assert r.status_code == 409 and r.json() == {"running": "checkin"}
        gate.set()
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
    assert events[-1][0] == "done" and not rt.lock.locked()


async def test_checkin_syncs_first_when_asked(runtime, client, monkeypatch, parse_sse):
    calls = []

    async def fake_sync(settings, *, log=print, **kw):
        calls.append(kw)
        log("== synced")
        return SyncReport(results=[SourceResult("garmin", "ok", 1)])

    monkeypatch.setattr("tri_web.routes.jobs.run_sync", fake_sync)
    rt = runtime(coach=[AIMessage(content="Clean week.")])
    async with client(rt) as c:
        job_id = (await c.post("/api/jobs/checkin", json={"sync": True})).json()["id"]
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
    assert calls == [{"since": None, "full": False}] and events[0] == (
        "line",
        {"text": "== synced"},
    )
