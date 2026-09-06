"""Sync package: fetch from MCP servers, parse, upsert."""

from typing import Any, Protocol


class ToolCaller(Protocol):
    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any | None: ...
