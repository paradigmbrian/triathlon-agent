"""The coach's athlete memory, and the reset that clears the conversation (never Garmin,
TrainingPeaks, the tables or another agent's Store keys)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from tri_coach import memory as M
from tri_web.events import Busy
from tri_web.runtime import Runtime
from tri_web.schemas import MemoryOut, ResetIn

router = APIRouter()


def _runtime(request: Request) -> Runtime:
    from tri_web.app import runtime_of

    return runtime_of(request)


@router.get("/memory", response_model=MemoryOut)
async def get_memory(request: Request) -> MemoryOut:
    rt = _runtime(request)
    entries = await M.get_entries(rt.store)
    return MemoryOut(entries=entries, active_ids=[e.id for e in M.active(entries, rt.today())])


@router.delete("/memory/{entry_id}", status_code=204)
async def forget(entry_id: str, request: Request) -> Response:
    if not await M.forget_entry(_runtime(request).store, entry_id):
        raise HTTPException(status_code=404, detail=f"no memory entry {entry_id}")
    return Response(status_code=204)


@router.post("/reset", status_code=204)
async def reset(body: ResetIn, request: Request) -> Response:
    rt = _runtime(request)
    if rt.lock.locked():
        raise Busy(rt.running or "turn")
    await rt.lock.acquire()
    rt.running = "reset"
    try:
        await rt.graph.checkpointer.adelete_thread(rt.thread_id)
        if body.forget_memory:
            await M.clear(rt.store)
    finally:
        rt.running = None
        rt.lock.release()
    return Response(status_code=204)
