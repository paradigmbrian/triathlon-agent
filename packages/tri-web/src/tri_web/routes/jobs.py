"""Sync and check-in as jobs. Sync never takes the coach lock (the graph reads the tables per
turn). Check-in takes it for its whole duration and runs the CLI's check-in with yes=False, so a
proposed change set pauses on the thread where GET /coach/thread finds it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from tri_coach.checkin import run_checkin
from tri_core.sync.runner import run_sync
from tri_nutrition import store as S
from tri_planning import repo as prepo
from tri_web.events import Busy, format_sse
from tri_web.jobs import Job, Jobs
from tri_web.runtime import Runtime
from tri_web.schemas import CheckinIn, JobOut, JobStarted, SyncIn

router = APIRouter()


def _runtime(request: Request) -> Runtime:
    from tri_web.app import runtime_of

    return runtime_of(request)


async def _sync(rt: Runtime, job: Job, *, since: Any = None, full: bool = False) -> dict[str, Any]:
    report = await run_sync(rt.settings, since=since, full=full, log=job.line)
    return {"ok": report.ok, "results": [asdict(r) for r in report.results]}


@router.post("/sync", response_model=JobStarted)
async def post_sync(body: SyncIn, request: Request) -> JobStarted:
    rt = _runtime(request)

    async def run(job: Job) -> dict[str, Any]:
        return await _sync(rt, job, since=body.since, full=body.full)

    return JobStarted(id=rt.jobs.start("sync", run).id)


@router.post("/checkin", response_model=JobStarted)
async def post_checkin(body: CheckinIn, request: Request) -> JobStarted:
    rt = _runtime(request)
    if rt.lock.locked():
        raise Busy(rt.running or "turn")
    await rt.lock.acquire()
    rt.running = "checkin"

    async def run(job: Job) -> dict[str, Any]:
        try:
            if body.sync:
                report = await _sync(rt, job)
                if not report["ok"]:
                    job.line("check-in: sync had errors; continuing with existing data")
            with rt.connect() as conn:
                phase, _, _ = prepo.derive_phase(conn)
            profile = await S.get_profile(rt.store)
            code = await run_checkin(
                rt.graph,
                has_plan=phase == "active",
                has_profile=profile is not None,
                yes=False,
                out=job.write,  # streamed token fragments, not whole lines; job.write buffers them
                thread_id=rt.thread_id,
            )
            # paused (code 3) covers a new pause, a refusal because a review is already pending,
            # and a stuck thread; the frontend refetches GET /api/coach/thread to tell them apart
            return {"code": code, "paused": code == 3, "no_plan": code == 2}
        finally:
            rt.running = None
            rt.lock.release()

    job = rt.jobs.start("checkin", run)
    rt.turn_task = job.task
    return JobStarted(id=job.id)


def _job(rt: Runtime, job_id: str) -> Job:
    job = rt.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job {job_id}")
    return job


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, request: Request) -> JobOut:
    job = _job(_runtime(request), job_id)
    return JobOut(id=job.id, kind=job.kind, status=job.status, result=job.result, error=job.error)


async def _events(jobs: Jobs, job_id: str) -> AsyncIterator[str]:
    async for ev in jobs.events(job_id):
        yield format_sse(ev.name, ev.data)


@router.get("/{job_id}/events")
async def get_events(job_id: str, request: Request) -> StreamingResponse:
    rt = _runtime(request)
    _job(rt, job_id)
    return StreamingResponse(
        _events(rt.jobs, job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
