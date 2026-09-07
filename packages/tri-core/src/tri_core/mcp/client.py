"""Programmatic MCP client: launch a stdio server, call tools, parse JSON results."""

from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from tri_core.mcp.servers import ServerSpec


class McpToolError(Exception):
    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


def parse_tool_text(tool: str, text: str) -> Any | None:
    """Turn a tool's text result into data.

    Conventions observed in the two servers' source:
    - TrainingPeaks: always JSON; failures are {"isError": true, "error_code", "message"}.
    - Garmin: JSON on success; "No ... found ..." plain text when empty; "Error ..." on failure.
    """
    stripped = text.strip()
    if stripped.startswith("No "):
        return None
    if stripped.startswith("Error"):
        raise McpToolError(tool, stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise McpToolError(tool, f"non-JSON result: {stripped[:200]!r}") from exc
    if isinstance(data, dict) and data.get("isError"):
        code = data.get("error_code", "ERROR")
        raise McpToolError(tool, f"{code}: {data.get('message', '')}")
    return data


class McpToolClient:
    """Async context manager owning one server subprocess and one session."""

    def __init__(self, spec: ServerSpec) -> None:
        self.spec = spec
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> McpToolClient:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=self.spec.command,
            args=self.spec.args,
            env={**os.environ, **self.spec.env},
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def list_tool_names(self) -> list[str]:
        assert self._session is not None, "use inside 'async with'"
        result = await self._session.list_tools()
        return [t.name for t in result.tools]

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any | None:
        assert self._session is not None, "use inside 'async with'"
        result = await self._session.call_tool(tool, args or {})
        texts = [c.text for c in result.content if isinstance(c, TextContent)]
        if not texts:
            raise McpToolError(tool, "no text content in result")
        if getattr(result, "isError", False):
            raise McpToolError(tool, texts[0])
        return parse_tool_text(tool, "\n".join(texts))
