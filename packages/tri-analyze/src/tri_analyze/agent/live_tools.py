"""Bind allow-listed MCP server tools as LangChain tools over persistent sessions.

LangChain lesson: MCP tools become ordinary LangChain BaseTools. The adapter converts each
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

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_core.config import Settings
from tri_core.mcp.servers import ServerSpec, garmin_spec, trainingpeaks_spec

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
async def open_live_tools(
    settings: Settings, log: Callable[[str], None]
) -> AsyncIterator[list[BaseTool]]:
    specs = {
        "garmin": (garmin_spec(settings), GARMIN_LIVE_TOOLS),
        "trainingpeaks": (trainingpeaks_spec(settings), TP_LIVE_TOOLS),
    }
    client = MultiServerMCPClient({name: _connection(spec) for name, (spec, _) in specs.items()})
    tools: list[BaseTool] = []
    async with AsyncExitStack() as stack:
        for name, (_, allow) in specs.items():
            try:
                session = await asyncio.wait_for(
                    stack.enter_async_context(client.session(name)), timeout=SESSION_TIMEOUT_S
                )
                loaded = await load_mcp_tools(session)
                picked = filter_tools(loaded, allow)
                tools.extend(picked)
                log(f"{name}: bound {[t.name for t in picked]}")
            except Exception as exc:  # a dead server must not kill the chat
                log(
                    f"warning: {name} MCP server unavailable ({type(exc).__name__}: {exc}); "
                    "its tools are not bound"
                )
        yield tools
