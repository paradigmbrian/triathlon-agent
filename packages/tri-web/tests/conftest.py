"""A Runtime over the rolled-back test database, scripted models and an in-memory checkpointer;
an httpx client over the ASGI app; an SSE parser for the streamed bodies."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from tri_coach.graph.checkpointer import make_serde
from tri_coach.graph.graph import build_graph
from tri_coach.servers import Servers
from tri_coach.testing import make_test_deps
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel
from tri_planning.testing import MONDAY, NoCommit
from tri_web.app import create_app
from tri_web.config import WebSettings
from tri_web.runtime import Runtime


@pytest.fixture
def nocommit(db):
    return NoCommit(db)


@pytest.fixture
def mem_store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def runtime(nocommit, mem_store) -> Callable[..., Runtime]:
    def _make(
        *,
        coach: list[Any] | None = None,
        planning: list[Any] | None = None,
        nutrition: list[Any] | None = None,
        analyst: list[Any] | None = None,
        tp: Any = None,
        today: date = MONDAY,
    ) -> Runtime:
        deps = make_test_deps(
            nocommit,
            coach=ScriptedChatModel(script=coach or []),
            planning=ScriptedChatModel(script=planning or []),
            nutrition=ScriptedChatModel(script=nutrition or []),
            analyst=ScriptedChatModel(script=analyst or []),
            tp=tp,
            today=today,
        )
        graph = build_graph(deps, InMemorySaver(serde=make_serde()), mem_store)
        settings = WebSettings(
            _env_file=None, anthropic_api_key="test-key", database_url=Settings().test_database_url
        )
        return Runtime(
            settings=settings,
            graph=graph,
            store=mem_store,
            servers=Servers(),
            connect=lambda: contextlib.nullcontext(nocommit),
            live=False,
            today=lambda: today,
        )

    return _make


@pytest.fixture
def client() -> Callable[[Runtime], contextlib.AbstractAsyncContextManager[httpx.AsyncClient]]:
    @contextlib.asynccontextmanager
    async def _open(rt: Runtime) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=create_app(rt), raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
            yield c

    return _open


def _parse_sse(text: str) -> list[tuple[str, Any]]:
    """[(event name, parsed data)] from a text/event-stream body."""
    out: list[tuple[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            out.append((name, json.loads("\n".join(data))))
    return out


@pytest.fixture
def parse_sse() -> Callable[[str], list[tuple[str, Any]]]:
    return _parse_sse
