"""Bind allow-listed MCP server tools as LangChain tools over persistent sessions.

MCP tools become ordinary LangChain BaseTools. The adapter converts each
server tool's JSON schema into a tool the model can call, and the session stays open so
calls are fast. The allow-list keeps the bound tool count small on purpose.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StdioConnection
from langchain_mcp_adapters.tools import load_mcp_tools

from tri_core.mcp.servers import ServerSpec

SESSION_TIMEOUT_S = 120  # uvx cold start + Garmin login can take a while


def filter_tools(tools: Sequence[BaseTool], allow: Sequence[str]) -> list[BaseTool]:
    by_name = {t.name: t for t in tools}
    return [by_name[n] for n in allow if n in by_name]


def _connection(spec: ServerSpec) -> StdioConnection:
    return StdioConnection(
        transport="stdio",
        command=spec.command,
        args=spec.args,
        env={**os.environ, **spec.env},
    )


@asynccontextmanager
async def open_live_servers(
    specs: dict[str, tuple[ServerSpec, Sequence[str]]], log: Callable[[str], None]
) -> AsyncIterator[dict[str, list[BaseTool]]]:
    """Start each server, load its tools, keep the allow-listed ones, and keep every session open
    for as long as the context is. Yields server name -> bound tools, in spec order.

    A server that fails to start is logged and left out, so `name not in servers` means it is
    down; the others still bind.
    """
    client = MultiServerMCPClient({name: _connection(spec) for name, (spec, _) in specs.items()})
    servers: dict[str, list[BaseTool]] = {}
    async with AsyncExitStack() as stack:
        for name, (_, allow) in specs.items():
            try:
                session = await asyncio.wait_for(
                    stack.enter_async_context(client.session(name)), timeout=SESSION_TIMEOUT_S
                )
                loaded = await load_mcp_tools(session)
                picked = filter_tools(loaded, allow)
                servers[name] = picked
                log(f"{name}: bound {[t.name for t in picked]}")
            except Exception as exc:  # a dead server must not kill the chat
                log(
                    f"warning: {name} MCP server unavailable ({type(exc).__name__}: {exc}); "
                    "its tools are not bound"
                )
        yield servers


@asynccontextmanager
async def open_live_tools(
    specs: dict[str, tuple[ServerSpec, Sequence[str]]], log: Callable[[str], None]
) -> AsyncIterator[list[BaseTool]]:
    """The flattened view of `open_live_servers`: every bound tool, servers in spec order."""
    async with open_live_servers(specs, log) as servers:
        yield [t for tools in servers.values() for t in tools]
