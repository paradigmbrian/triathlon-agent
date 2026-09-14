"""web/dist is served from the same port when built; client routes fall back to index.html."""

import httpx
import pytest

from tri_web.app import create_app
from tri_web.config import WebSettings

pytestmark = pytest.mark.db


async def test_built_frontend_is_served_with_spa_fallback(runtime, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>tri</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    rt = runtime()
    rt.settings = WebSettings(_env_file=None, anthropic_api_key="k", tri_web_dist=str(tmp_path))
    logged: list[str] = []
    transport = httpx.ASGITransport(app=create_app(rt, log=logged.append))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
        assert (await c.get("/")).text.startswith("<!doctype html>")
        assert (await c.get("/settings")).text.startswith("<!doctype html>")
        r = await c.get("/assets/app.js")
        assert r.status_code == 200 and r.text == "console.log(1)"
        assert (await c.get("/api/coach/thread")).status_code == 200  # the API still wins
        assert (await c.get("/api/nope")).status_code == 404
    assert logged == []


async def test_missing_frontend_logs_api_only(runtime, tmp_path):
    rt = runtime()
    rt.settings = WebSettings(
        _env_file=None, anthropic_api_key="k", tri_web_dist=str(tmp_path / "none")
    )
    logged: list[str] = []
    transport = httpx.ASGITransport(app=create_app(rt, log=logged.append))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
        assert (await c.get("/")).status_code == 404
    assert logged == ["frontend not built, API only"]
