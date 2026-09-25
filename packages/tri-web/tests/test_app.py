"""create_app: an unexpected exception is a 500 with a fixed body; the text goes to the log."""

import httpx
import pytest

from tri_web.app import create_app

pytestmark = pytest.mark.db


async def test_an_unexpected_error_logs_the_text_and_returns_a_fixed_body(runtime, monkeypatch):
    rt = runtime()

    async def boom(config):
        raise RuntimeError("psycopg went away")

    monkeypatch.setattr(rt.graph, "aget_state", boom)
    lines: list[str] = []
    transport = httpx.ASGITransport(
        app=create_app(rt, log=lines.append), raise_app_exceptions=False
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
        r = await c.get("/api/coach/thread")
    assert r.status_code == 500 and r.json() == {"detail": "internal error"}
    # `web/dist` may or may not exist locally, which adds a "frontend not built" line at
    # create_app time; only the line the failing request itself logs matters here.
    assert lines[-1] == "internal error on GET /api/coach/thread: RuntimeError: psycopg went away"
