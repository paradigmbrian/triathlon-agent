"""The process-wide state behind every route: one graph on thread "coach", one store, one set of
MCP sessions, one lock. open_runtime is tri_coach.cli._open_graph without Typer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.store.base import BaseStore

from tri_coach.servers import Servers
from tri_core.db.repo import Conn
from tri_web.config import WebSettings
from tri_web.jobs import Jobs

Log = Callable[[str], None]


class NotReady(RuntimeError):
    """The API key, checkpointer or store is missing; the message is the CLI's hint."""


@dataclass
class Runtime:
    settings: WebSettings
    graph: Any
    store: BaseStore
    servers: Servers
    connect: Callable[[], AbstractContextManager[Conn]]
    live: bool
    today: Callable[[], date] = date.today
    thread_id: str = "coach"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    running: str | None = None
    turn_task: asyncio.Task[None] | None = None
    jobs: Jobs = field(default_factory=Jobs)


def cfg(rt: Runtime) -> dict[str, Any]:
    return {"configurable": {"thread_id": rt.thread_id}}


@asynccontextmanager
async def open_runtime(
    settings: WebSettings, *, no_live: bool, log: Log, model: BaseChatModel | None = None
) -> AsyncIterator[Runtime]:
    """Readiness, then servers, checkpointer, store, deps, graph; everything closes with the
    exit stack. `model`, when given, replaces every role's model (tests)."""
    from tri_coach.cli import ready
    from tri_coach.graph.deps import make_deps
    from tri_coach.graph.graph import build_graph
    from tri_coach.graph.state import STATE_TYPES
    from tri_coach.servers import open_servers
    from tri_core.harness.persistence import open_checkpointer, open_store
    from tri_core.llm import Role, make_model

    problem = ready(settings)
    if problem is not None:
        raise NotReady(problem)
    async with AsyncExitStack() as stack:
        servers = await open_servers(stack, settings, no_live=no_live, log=log)
        saver = await stack.enter_async_context(
            open_checkpointer(settings.database_url, STATE_TYPES)
        )
        store = await stack.enter_async_context(open_store(settings.database_url))

        def models(role: Role) -> BaseChatModel:
            return model if model is not None else make_model(settings, role)

        deps = make_deps(settings, models, servers)
        yield Runtime(
            settings=settings,
            graph=build_graph(deps, saver, store),
            store=store,
            servers=servers,
            connect=deps.connect,
            live=not no_live,
        )
