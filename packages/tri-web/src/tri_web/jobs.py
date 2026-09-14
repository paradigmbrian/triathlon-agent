"""In-memory jobs (sync, check-in) with a recorded transcript: a follower that connects late, or
reconnects after a reload, replays what was emitted and then follows live. Jobs die with the
process; that is fine for one athlete on one machine."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "failed"]


@dataclass
class JobEvent:
    name: str
    data: dict[str, Any]


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[JobEvent] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    _followers: list[asyncio.Queue[JobEvent | None]] = field(default_factory=list)
    _buf: str = field(default="", repr=False)

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed")

    def emit(self, name: str, data: dict[str, Any]) -> None:
        ev = JobEvent(name, data)
        self.events.append(ev)
        for q in self._followers:
            q.put_nowait(ev)

    def line(self, text: str) -> None:
        self.emit("line", {"text": text.rstrip("\n")})

    def write(self, text: str) -> None:
        """Line-buffered writer for streamed output (per-token chunks): buffer until a `\\n`
        completes a segment, then emit it as a `line` event (blank segments too, so paragraph
        breaks survive); keep any trailing partial segment buffered for `flush`."""
        self._buf += text
        while "\n" in self._buf:
            segment, self._buf = self._buf.split("\n", 1)
            self.emit("line", {"text": segment})

    def flush(self) -> None:
        """Emit any buffered partial segment as a final `line` before `done`/`error`."""
        if self._buf:
            self.emit("line", {"text": self._buf})
            self._buf = ""

    def _close(self) -> None:
        for q in self._followers:
            q.put_nowait(None)


Run = Callable[[Job], Awaitable[dict[str, Any]]]


class Jobs:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def start(self, kind: str, run: Run) -> Job:
        job = Job(id=secrets.token_hex(4), kind=kind)
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job, run))
        return job

    async def _run(self, job: Job, run: Run) -> None:
        job.status = "running"
        try:
            job.result = await run(job)
            job.status = "done"
            job.flush()
            job.emit("done", {"result": job.result})
        except Exception as exc:  # noqa: BLE001 - the job's failure is its result
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "failed"
            job.flush()
            job.emit("error", {"message": job.error})
        finally:
            job._close()

    async def events(self, job_id: str) -> AsyncIterator[JobEvent]:
        job = self._jobs.get(job_id)
        if job is None:
            return
        queue: asyncio.Queue[JobEvent | None] = asyncio.Queue()
        job._followers.append(queue)  # registered before the snapshot: nothing can slip between
        # captured together, with no await between them: `finished` must describe this snapshot,
        # not whatever the job's status has become once the replay below is done yielding
        recorded, finished = list(job.events), job.finished
        try:
            for ev in recorded:
                yield ev
            if finished:
                return
            while True:
                ev_or_none = await queue.get()
                if ev_or_none is None:
                    return
                yield ev_or_none
        finally:
            job._followers.remove(queue)
