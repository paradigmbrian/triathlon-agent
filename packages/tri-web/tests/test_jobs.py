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


async def test_a_slow_follower_sees_the_tail_and_done_even_if_the_job_finishes_mid_replay():
    jobs = Jobs()
    gate = asyncio.Event()

    async def run(job: Job) -> dict:
        for i in range(5):
            job.line(f"line{i}")
        await gate.wait()
        job.line("late")
        return {"rows": 1}

    job = jobs.start("sync", run)
    await asyncio.sleep(0)  # let the first 5 lines emit
    assert [e.data["text"] for e in job.events] == [f"line{i}" for i in range(5)]

    async def slow_collect() -> list[JobEvent]:
        result = []
        async for ev in jobs.events(job.id):
            result.append(ev)
            await asyncio.sleep(0.01)  # slow enough that the job finishes during the replay
        return result

    follower = asyncio.create_task(slow_collect())
    await asyncio.sleep(0)  # follower registers its queue and starts replaying `recorded`
    gate.set()  # the job emits "late", `done`, and closes while the follower is still replaying
    events = await follower
    assert [(e.name, e.data) for e in events] == [
        ("line", {"text": "line0"}),
        ("line", {"text": "line1"}),
        ("line", {"text": "line2"}),
        ("line", {"text": "line3"}),
        ("line", {"text": "line4"}),
        ("line", {"text": "late"}),
        ("done", {"result": {"rows": 1}}),
    ]
    assert job.status == "done"


async def test_two_concurrent_followers_see_identical_events():
    jobs = Jobs()
    gate = asyncio.Event()

    async def run(job: Job) -> dict:
        job.line("one")
        await gate.wait()
        job.line("two")
        return {"ok": True}

    job = jobs.start("sync", run)
    await asyncio.sleep(0)
    f1 = asyncio.create_task(collect(jobs, job.id))
    f2 = asyncio.create_task(collect(jobs, job.id))
    await asyncio.sleep(0)
    gate.set()
    e1, e2 = await f1, await f2
    assert [(e.name, e.data) for e in e1] == [(e.name, e.data) for e in e2]
    assert [(e.name, e.data) for e in e1] == [
        ("line", {"text": "one"}),
        ("line", {"text": "two"}),
        ("done", {"result": {"ok": True}}),
    ]


async def test_write_buffers_by_line_and_flushes_the_remainder_before_done():
    jobs = Jobs()

    async def run(job: Job) -> dict:
        job.write("Clean")
        job.write(" week.")
        job.write("\n")
        job.write("a\n\nb")
        return {}

    job = jobs.start("sync", run)
    events = await collect(jobs, job.id)
    assert [(e.name, e.data) for e in events] == [
        ("line", {"text": "Clean week."}),
        ("line", {"text": "a"}),
        ("line", {"text": ""}),
        ("line", {"text": "b"}),
        ("done", {"result": {}}),
    ]


async def test_a_failing_job_flushes_its_remainder_before_error():
    jobs = Jobs()

    async def run(job: Job) -> dict:
        job.write("partial")
        raise RuntimeError("boom")

    job = jobs.start("sync", run)
    events = await collect(jobs, job.id)
    assert [(e.name, e.data) for e in events] == [
        ("line", {"text": "partial"}),
        ("error", {"message": "RuntimeError: boom"}),
    ]
