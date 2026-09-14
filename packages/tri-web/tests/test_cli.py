import asyncio
import json
from types import SimpleNamespace

from typer.testing import CliRunner

from tri_web.cli import _finish_running_turn, app


def test_help_lists_the_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("serve", "openapi"):
        assert name in result.output


def test_openapi_prints_the_document_with_the_routes():
    result = CliRunner().invoke(app, ["openapi"])
    assert result.exit_code == 0
    doc = json.loads(result.output)
    assert "/api/coach/turns" in doc["paths"] and "/api/system/status" in doc["paths"]
    assert "ThreadView" in doc["components"]["schemas"]


def test_serve_exits_2_when_not_ready(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from tri_web import config

    config.get_web_settings.cache_clear()
    result = CliRunner().invoke(app, ["serve", "--no-live"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY is not set" in result.output


async def test_finish_running_turn_awaits_an_in_flight_task():
    event = asyncio.Event()
    finished = {"flag": False}

    async def _turn() -> None:
        await event.wait()
        finished["flag"] = True

    task = asyncio.create_task(_turn())
    logged: list[str] = []
    rt = SimpleNamespace(turn_task=task)

    waiter = asyncio.create_task(_finish_running_turn(rt, logged.append))
    await asyncio.sleep(0)  # let the waiter start and log before the task finishes
    assert not waiter.done()
    assert logged == ["tri-web: waiting for the running turn to finish"]

    event.set()
    await waiter
    assert task.done() and finished["flag"] is True


async def test_finish_running_turn_returns_at_once_when_there_is_no_task():
    logged: list[str] = []
    await _finish_running_turn(SimpleNamespace(turn_task=None), logged.append)
    assert logged == []


async def test_finish_running_turn_returns_at_once_when_the_task_is_already_done():
    async def _noop() -> None:
        return None

    task = asyncio.create_task(_noop())
    await task
    logged: list[str] = []
    await _finish_running_turn(SimpleNamespace(turn_task=task), logged.append)
    assert logged == []
