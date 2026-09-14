"""create_app(runtime): the FastAPI app over one Runtime. Error bodies carry a message only."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from tri_web.events import Busy
from tri_web.routes import coach, system
from tri_web.runtime import Runtime
from tri_web.schemas import EditRejected, NoReview


def runtime_of(request: Request) -> Runtime:
    rt: Runtime | None = request.app.state.runtime
    if rt is None:
        raise HTTPException(status_code=503, detail="runtime not open")
    return rt


def create_app(runtime: Runtime | None) -> FastAPI:
    app = FastAPI(title="tri-web", version="0.1.0")
    app.state.runtime = runtime
    app.include_router(coach.router, prefix="/api/coach", tags=["coach"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])

    @app.exception_handler(Busy)
    async def busy(request: Request, exc: Busy) -> JSONResponse:
        return JSONResponse({"running": exc.running}, status_code=409)

    @app.exception_handler(NoReview)
    async def no_review(request: Request, exc: NoReview) -> JSONResponse:
        return JSONResponse({"reason": "no_review"}, status_code=409)

    @app.exception_handler(EditRejected)
    async def edit_rejected(request: Request, exc: EditRejected) -> JSONResponse:
        return JSONResponse(
            {"detail": "edit rejected", "errors": [e.model_dump() for e in exc.errors]},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # uvicorn's error log keeps the traceback; the body never does
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)

    return app
