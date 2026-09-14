"""Replay then follow; a failing job ends with error; two followers see the same events."""

import asyncio

from tri_web.jobs import Job, JobEvent, Jobs


async def collect(jobs: Jobs, job_id: str) -> list[JobEvent]:
    return [ev async for ev in jobs.events(job_id)]


async def test_a_job_records_lines_and_ends_with_done():
    jobs = Jobs()
    gate = asyncio.Event()

    async def run(job: Job) -> dict:
        job.line("one")
        await gate.wait()
        job.line("two")
        return {"rows": 2}

    job = jobs.start("sync", run)
    assert job.kind == "sync" and jobs.get(job.id) is job and len(job.id) == 8
    await asyncio.sleep(0)  # let the task start
    assert job.status == "running" and [e.data["text"] for e in job.events] == ["one"]
    follower = asyncio.create_task(collect(jobs, job.id))
    gate.set()
    events = await follower
    assert [(e.name, e.data) for e in events] == [
        ("line", {"text": "one"}),
        ("line", {"text": "two"}),
        ("done", {"result": {"rows": 2}}),
    ]
    assert job.status == "done" and job.result == {"rows": 2} and job.finished


async def test_a_late_follower_gets_the_whole_transcript():
    jobs = Jobs()

    async def run(job: Job) -> dict:
        job.line("a")
        return {}

    job = jobs.start("sync", run)
    assert job.task is not None
    await job.task
    events = await collect(jobs, job.id)
    assert [e.name for e in events] == ["line", "done"]


async def test_a_failing_job_ends_with_error():
    jobs = Jobs()

    async def run(job: Job) -> dict:
        job.line("starting")
        raise RuntimeError("garmin down")

    job = jobs.start("sync", run)
    events = await collect(jobs, job.id)
    assert events[-1] == JobEvent("error", {"message": "RuntimeError: garmin down"})
    assert job.status == "failed" and job.error == "RuntimeError: garmin down"


async def test_unknown_job_yields_nothing():
    assert await collect(Jobs(), "nope") == []
