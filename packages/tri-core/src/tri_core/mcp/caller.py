"""A ToolCaller over adapter-bound tools, so one open MCP session serves both the model (as
LangChain tools) and the programmatic `call_json` path the graph deps hold."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool, ToolException
from pydantic import ValidationError

from tri_core.mcp.client import McpToolError, parse_tool_text


def tool_text(out: Any) -> str:
    """The text of a tool result. Adapter tools return a list of content blocks
    (`[{"type": "text", "text": ...}, ...]`); plain tools return a string. Non-text blocks are
    dropped; text blocks are joined with newlines, as `McpToolClient.call_json` joins texts."""
    if isinstance(out, str):
        return out
    if isinstance(out, list):
        parts: list[str] = []
        for block in out:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(out)


class ToolsCaller:
    """`call_json(tool, args)` finds the bound tool by name, awaits it, and parses the text with
    the same conventions as `McpToolClient.call_json`, raising `McpToolError` the same way."""

    def __init__(self, tools: Sequence[BaseTool]) -> None:
        self._tools: dict[str, BaseTool] = {t.name: t for t in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any | None:
        bound = self._tools.get(tool)
        if bound is None:
            raise McpToolError(tool, f"not bound (bound tools: {sorted(self._tools)})")
        try:
            out = await bound.ainvoke(args or {})
        except ToolException as exc:
            raise McpToolError(tool, str(exc)) from exc
        except ValidationError as exc:
            raise McpToolError(tool, f"invalid arguments: {exc}") from exc
        text = tool_text(out)
        if not text.strip():
            raise McpToolError(tool, "no text content in result")
        return parse_tool_text(tool, text)
