"""A coach turn as a stream of typed events. start_turn takes the runtime lock, runs the graph in
a background task through a TurnEmitter, and releases the lock when the run ends, so a closed tab
never leaves a checkpoint half-written. sse_response reads the queue into text/event-stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langgraph.types import Command
from starlette.responses import StreamingResponse

from tri_coach.repl import TurnPrinter, run_turn
from tri_web.runtime import Runtime


@dataclass
class TurnEvent:
    name: str
    data: dict[str, Any]


class TurnEmitter(TurnPrinter):
    """TurnPrinter's classification as queued events (spec §5.3); no terminal output."""

    def __init__(self, queue: asyncio.Queue[TurnEvent | None]) -> None:
        super().__init__(lambda s: None)
        self.queue = queue

    def print_event(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "assistant":
            return
        if kind == "consult":
            payload = {"domain": payload["domain"], "text": payload["text"]}
        elif kind == "report":
            payload = {"text": payload["text"]}
        self.queue.put_nowait(TurnEvent(kind, payload))


class Busy(Exception):
    def __init__(self, running: str) -> None:
        super().__init__(f"a {running} is running")
        self.running = running


@dataclass
class TurnRun:
    queue: asyncio.Queue[TurnEvent | None]
    task: asyncio.Task[None]


def error_message(printer_error: str) -> str:
    return printer_error.strip().removeprefix("[").removesuffix("]")


async def _produce(
    rt: Runtime,
    payload: dict[str, Any] | Command[Any],
    queue: asyncio.Queue[TurnEvent | None],
    tags: list[str] | None,
) -> None:
    emitter = TurnEmitter(queue)
    try:
        printer = await run_turn(
            rt.graph, payload, rt.thread_id, emitter.out, tags=tags, printer=emitter
        )
        if printer.error is not None:
            queue.put_nowait(TurnEvent("error", {"message": error_message(printer.error)}))
        queue.put_nowait(
            TurnEvent(
                "done", {"final_text": printer.final_text, "paused": printer.interrupt is not None}
            )
        )
    finally:
        queue.put_nowait(None)
        rt.running = None
        rt.lock.release()


async def start_turn(
    rt: Runtime,
    payload: dict[str, Any] | Command[Any],
    *,
    kind: str,
    tags: list[str] | None = None,
) -> TurnRun:
    """Refuses with Busy while another run holds the lock. The lock is taken here, in the caller's
    task, and released by the producer when the run ends."""
    if rt.lock.locked():
        raise Busy(rt.running or kind)
    await rt.lock.acquire()
    rt.running = kind
    queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
    task = asyncio.create_task(_produce(rt, payload, queue, tags))
    rt.turn_task = task
    return TurnRun(queue=queue, task=task)


def format_sse(name: str, data: Any) -> str:
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"


async def _body(run: TurnRun) -> AsyncIterator[str]:
    while (ev := await run.queue.get()) is not None:
        yield format_sse(ev.name, ev.data)


def sse_response(run: TurnRun) -> StreamingResponse:
    return StreamingResponse(
        _body(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
