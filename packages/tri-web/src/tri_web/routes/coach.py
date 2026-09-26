"""The conversation: thread snapshot, a streamed turn, the review gate and its helpers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from starlette.responses import StreamingResponse

from tri_coach.models import Proposal, ReviewDecision
from tri_coach.repl import paused_review
from tri_web import review as R
from tri_web.events import Busy, sse_response, start_turn
from tri_web.runtime import Runtime, cfg
from tri_web.schemas import (
    EditRejected,
    NoReview,
    Paused,
    ReviewIn,
    SchemaOut,
    TurnIn,
    ValidateIn,
    YamlOut,
)
from tri_web.thread import ThreadView, thread_snapshot

router = APIRouter()


def _runtime(request: Request) -> Runtime:
    from tri_web.app import runtime_of

    return runtime_of(request)


async def _paused_proposals(rt: Runtime) -> list[Proposal]:
    paused = paused_review(await rt.graph.aget_state(cfg(rt)))
    if paused is None:
        raise NoReview()
    return [Proposal.model_validate(p) for p in paused.get("proposals", [])]


@router.get("/thread", response_model=ThreadView)
async def get_thread(request: Request) -> ThreadView:
    rt = _runtime(request)
    return await thread_snapshot(rt.graph, rt.thread_id, running=rt.running)


@router.post("/turns")
async def post_turn(body: TurnIn, request: Request) -> StreamingResponse:
    rt = _runtime(request)
    if rt.lock.locked():
        raise Busy(rt.running or "turn")
    if paused_review(await rt.graph.aget_state(cfg(rt))) is not None:
        raise Paused()  # a new input would restart the graph and drop the waiting review
    run = await start_turn(rt, {"messages": [HumanMessage(body.text)]}, kind="turn")
    return sse_response(run)


@router.post("/review")
async def post_review(body: ReviewIn, request: Request) -> StreamingResponse:
    rt = _runtime(request)
    if rt.lock.locked():
        raise Busy(rt.running or "turn")
    await _paused_proposals(rt)  # 409 no_review when nothing is paused
    decision = ReviewDecision(action=body.action, note=body.note)
    if body.action == "edit":
        checked = R.validate_json(body.proposals or [])
        if not checked.ok:
            raise EditRejected(checked.errors)
        if not checked.proposals:
            raise HTTPException(
                status_code=422, detail="edit needs at least one proposal; reject instead"
            )
        decision = ReviewDecision(action="edit", proposals=R.typed(checked))
    resume: Command[Any] = Command(resume=decision.model_dump(mode="json", exclude_none=True))
    run = await start_turn(rt, resume, kind="review")
    return sse_response(run)


@router.get("/review/schema", response_model=SchemaOut)
async def get_schema() -> SchemaOut:
    return SchemaOut(**R.schema())


@router.post("/review/validate", response_model=R.Validated)
async def post_validate(body: ValidateIn, request: Request) -> R.Validated:
    if body.proposals is not None:
        return R.validate_json(body.proposals)
    originals = await _paused_proposals(_runtime(request))
    return R.validate_yaml(body.yaml or "", originals)


@router.get("/review/yaml", response_model=YamlOut)
async def get_yaml(request: Request) -> YamlOut:
    return YamlOut(yaml=R.to_yaml(await _paused_proposals(_runtime(request))))
