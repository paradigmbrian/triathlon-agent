import asyncio
import json
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tri_web import config
from tri_web.cli import _allowed_hosts, _finish_running_turn, app


@pytest.fixture
def fresh_web_settings():
    config.get_web_settings.cache_clear()
    try:
        yield
    finally:
        config.get_web_settings.cache_clear()


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


def test_serve_exits_2_when_not_ready(monkeypatch, fresh_web_settings):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
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


def test_allowed_hosts_adds_a_named_bind_address_but_not_a_wildcard():
    assert _allowed_hosts("127.0.0.1") == ["127.0.0.1", "localhost"]
    assert _allowed_hosts("localhost") == ["127.0.0.1", "localhost"]
    assert _allowed_hosts("192.168.1.20") == ["127.0.0.1", "localhost", "192.168.1.20"]
    assert _allowed_hosts("0.0.0.0") == ["127.0.0.1", "localhost"]
    assert _allowed_hosts("::") == ["127.0.0.1", "localhost"]


_SIGINT_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import contextlib
    import os
    import signal
    from types import SimpleNamespace

    import uvicorn
    from fastapi import FastAPI

    from tri_web.cli import _finish_running_turn, _Server


    @contextlib.asynccontextmanager
    async def exit_stack():
        try:
            yield
        finally:
            await asyncio.sleep(0.2)
            print("closed", flush=True)


    async def turn() -> None:
        await asyncio.sleep(1.0)
        print("turn finished", flush=True)


    async def main() -> None:
        server = _Server(uvicorn.Config(FastAPI(), host="127.0.0.1", port=0, log_level="warning"))
        loop = asyncio.get_running_loop()

        async def interrupt_when_started() -> None:
            while not server.started:
                await asyncio.sleep(0.01)
            loop.call_later(0.05, os.kill, os.getpid(), signal.SIGINT)

        async with exit_stack():
            task = asyncio.create_task(turn())
            watcher = asyncio.create_task(interrupt_when_started())
            await server.serve()
            await watcher
            await _finish_running_turn(
                SimpleNamespace(turn_task=task), lambda m: print(m, flush=True)
            )


    asyncio.run(main())
    """
)


def test_sigint_lets_the_running_turn_finish_and_the_runtime_close(tmp_path):
    script = tmp_path / "sigint_serve.py"
    script.write_text(_SIGINT_SCRIPT)
    result = subprocess.run(
        [sys.executable, str(script)], timeout=30, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "waiting for the running turn to finish" in result.stdout
    assert "turn finished" in result.stdout
    assert "closed" in result.stdout
