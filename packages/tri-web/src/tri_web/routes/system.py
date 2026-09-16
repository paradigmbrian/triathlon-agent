"""Readiness as the CLI checks it, the bound live tools, and what is running."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from tri_core.harness.persistence import checkpointer_ready, store_ready
from tri_web.schemas import Readiness, StatusOut

router = APIRouter()


@router.get("/status", response_model=StatusOut)
async def get_status(request: Request) -> StatusOut:
    from tri_web.app import runtime_of

    rt = runtime_of(request)
    url = rt.settings.database_url
    checkpointer, store = await asyncio.gather(
        asyncio.to_thread(checkpointer_ready, url), asyncio.to_thread(store_ready, url)
    )
    return StatusOut(
        live=rt.live,
        tools=[t.name for t in rt.servers.garmin_tools + rt.servers.tp_tools],
        ready=Readiness(
            api_key=bool(rt.settings.anthropic_api_key), checkpointer=checkpointer, store=store
        ),
        thread=rt.thread_id,
        running=rt.running,
    )
