"""GET /api/today: the strip in one call."""

from __future__ import annotations

from fastapi import APIRouter, Request

from tri_web.today import TodayView, build_today

router = APIRouter()


@router.get("/today", response_model=TodayView)
async def get_today(request: Request) -> TodayView:
    from tri_web.app import runtime_of

    return await build_today(runtime_of(request))
