"""GET /api/progress: the Progress page's charts in one call."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from tri_web.progress import ProgressView, RangeKey, build_progress

router = APIRouter()


@router.get("/progress", response_model=ProgressView)
async def get_progress(
    request: Request, range_: Annotated[RangeKey, Query(alias="range")] = "12m"
) -> ProgressView:
    from tri_web.app import runtime_of

    return await build_progress(runtime_of(request), range_)
