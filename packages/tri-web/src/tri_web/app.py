"""create_app(runtime): the FastAPI app over one Runtime. Error bodies carry a message only.
Only loopback Host headers are served, so a DNS-rebound page cannot reach the API."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tri_web.events import Busy
from tri_web.routes import coach, jobs, memory, system, today
from tri_web.runtime import Runtime
from tri_web.schemas import EditRejected, NoReview, Paused


def runtime_of(request: Request) -> Runtime:
    rt: Runtime | None = request.app.state.runtime
    if rt is None:
        raise HTTPException(status_code=503, detail="runtime not open")
    return rt


DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost")


def create_app(
    runtime: Runtime | None,
    *,
    allowed_hosts: Sequence[str] | None = None,
    log: Callable[[str], None] = print,
) -> FastAPI:
    app = FastAPI(title="tri-web", version="0.1.0")
    app.state.runtime = runtime
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(allowed_hosts if allowed_hosts is not None else DEFAULT_ALLOWED_HOSTS),
    )
    app.include_router(coach.router, prefix="/api/coach", tags=["coach"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(memory.router, prefix="/api/coach", tags=["memory"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])
    app.include_router(today.router, prefix="/api", tags=["today"])

    @app.exception_handler(Busy)
    async def busy(request: Request, exc: Busy) -> JSONResponse:
        return JSONResponse({"running": exc.running}, status_code=409)

    @app.exception_handler(NoReview)
    async def no_review(request: Request, exc: NoReview) -> JSONResponse:
        return JSONResponse({"reason": "no_review"}, status_code=409)

    @app.exception_handler(Paused)
    async def paused(request: Request, exc: Paused) -> JSONResponse:
        return JSONResponse({"reason": "paused"}, status_code=409)

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

    if runtime is not None:
        _mount_frontend(app, Path(runtime.settings.tri_web_dist), log)
    return app


def _mount_frontend(app: FastAPI, dist: Path, log: Callable[[str], None]) -> None:
    index = dist / "index.html"
    if not index.is_file():
        log("frontend not built, API only")
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        file = dist / path
        if path and file.is_file() and file.resolve().is_relative_to(dist.resolve()):
            return FileResponse(file)  # favicon and other top-level build outputs
        return FileResponse(index)
